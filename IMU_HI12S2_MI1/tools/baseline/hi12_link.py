#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HI12S2-MI1 串口链路层（P0 基线脚本与 P1 驱动共用）。

职责边界（刻意划窄）：
  - 只管"和一台 HI12 说话"：打开串口、读字节、切帧、校验、解析 0x91、
    发 ASCII 命令、静音/恢复、关闭。
  - 不做统计聚合，不落盘，不依赖 rospy/rclpy，也不依赖 pyserial
    （Jetson 上 python3.10 没有 pyserial，全部走裸 os + termios）。

关键实测约束（2026-11-06 于 Jetson Orin NX 复测确认，勿凭手册想当然）：
  - lflag 必须【全清】。Linux tty 默认 lflag 含 ECHO/ECHOE/ECHOK，只要漏清一个，
    n_tty 就会把收到的字节回显到 TX；921600 已占 USB 全速带宽约 89%，
    回显直接吃满带宽 -> 掉到 933fps、每 ~15ms 缺整帧、dt 空洞 2ms、CRC 0。
  - 1 kHz 满速收流期间或之后 close() 会让 CH340 芯片 wedged（后续 open 报
    EIO / dmesg -110）。静音后再关【不能可靠规避】，必须配合 ch340_recover.py。
  - 帧内 system_time 是 u32 毫秒，会回绕，只能做丢帧判据，绝不能当时间基准。
"""

import glob
import os
import re
import select
import struct
import termios
import time

# ---------------------------------------------------------------- 帧格式常量

HEAD = b"\x5a\xa5"
CMD_END = b"\r\n"

# 0x91 数据域 76 字节，全小端。注意 temperature 是 i8（int8），不是 int32；
# 这里曾经写成 "<BHBifI..." 多了一个 i，struct.error: unpack requires a buffer of 80 bytes。
PAYLOAD_091 = struct.Struct("<BHbfI3f3f3f3f4f")  # 2026-11-06 修正：temperature 是 i8，原来用的 B 在 0℃ 以下会读成 253
PAYLOAD_091_LEN = PAYLOAD_091.size          # 76

P091_FIELDS = (
    "tag", "main_status", "temperature", "air_pressure", "system_time",
    "ax", "ay", "az", "gx", "gy", "gz",
    "mx", "my", "mz",
    "roll", "pitch", "yaw",
    "qw", "qx", "qy", "qz",
)

BAUD_TABLE = {
    9600: termios.B9600,
    115200: termios.B115200,
    230400: termios.B230400,
    460800: termios.B460800,
    921600: termios.B921600,
}

# MAIN_STATUS 位定义（bit5/bit6 的 ACC_SAT/GYR_SAT 来自手册 p10，其余位待与手册核对）
STATUS_BITS = {
    5: "ACC_SAT",
    6: "GYR_SAT",
    9: "STATIC",
    11: "UTC_UNSYNC",
    12: "SOUT_PULSE",
}

# ---------------------------------------------------------------- CRC-16/XMODEM


def _build_crc_table():
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()


def crc16_xmodem(data):
    """CRC-16/XMODEM：多项式 0x1021、初值 0x0000、不反转、无终值异或。

    自检：crc16_xmodem(b"123456789") == 0x31C3
    """
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def crc_selftest():
    return crc16_xmodem(b"123456789") == 0x31C3


# ---------------------------------------------------------------- 切帧


class FrameSplitter:
    """字节流 -> 0x91 数据域。跨 read() 边界自行拼接，坏帧计数据、不抛异常。"""

    __slots__ = ("buf", "crc_bad", "len_bad", "resync_bytes", "unknown_tag")

    def __init__(self):
        self.buf = bytearray()
        self.crc_bad = 0
        self.len_bad = 0
        self.resync_bytes = 0
        self.unknown_tag = 0

    def reset_stats(self):
        self.crc_bad = 0
        self.len_bad = 0
        self.resync_bytes = 0
        self.unknown_tag = 0

    def feed(self, data):
        """喂入原始字节，返回本次切出的 payload 列表。"""
        buf = self.buf
        buf += data
        n = len(buf)
        i = 0
        out = []
        while True:
            j = buf.find(HEAD, i)
            if j < 0:
                self.resync_bytes += n - i
                i = n
                break
            if j > i:
                self.resync_bytes += j - i
            if n - j < 6:
                i = j
                break
            ln = buf[j + 2] | (buf[j + 3] << 8)
            if ln > 128:
                # 2026-11-06 补：payload 里撞上伪帧头 5A A5 时，把后两字节当长度会得到
                # 几万，原实现要等 4 万字节才 CRC 失败 —— 1 kHz 下等于丢 0.5 s 数据
                self.resync_bytes += 1
                i = j + 1
                continue
            total = 6 + ln
            if n - j < total:
                i = j
                break
            payload = bytes(buf[j + 6:j + 6 + ln])
            crc_rx = buf[j + 4] | (buf[j + 5] << 8)
            if crc16_xmodem(bytes(buf[j:j + 4]) + payload) != crc_rx:
                self.crc_bad += 1
                i = j + 1          # 丢掉这个帧头，往后重新找同步
                continue
            if ln != PAYLOAD_091_LEN:
                self.len_bad += 1  # 合法 CRC 但不是 0x91 全量帧（0x81/0x83 等）
            else:
                out.append(payload)
            i = j + total
        if i:
            del buf[:i]
        return out


def parse_091(payload):
    """76 字节数据域 -> 具名 tuple，21 个字段。"""
    return dict(zip(P091_FIELDS, PAYLOAD_091.unpack(payload)))


# ---------------------------------------------------------------- 设备发现


def list_tty_usb():
    """按自然序返回 /dev/ttyUSB*。编号会漂，禁止拿它当身份。"""
    def key(p):
        digits = "".join(ch for ch in os.path.basename(p) if ch.isdigit())
        return int(digits) if digits else 0
    return sorted(glob.glob("/dev/ttyUSB*"), key=key)


def usb_port_of(dev):
    """返回该 tty 所在的 USB 物理端口名，如 "1-3.3.2"。失败返回 None。"""
    name = os.path.basename(dev)
    try:
        real = os.path.realpath("/sys/class/tty/%s/device" % name)
    except OSError:
        return None
    parts = [p for p in real.split("/") if p]
    for k, p in enumerate(parts):
        if ":" in p and p[0].isdigit():
            return parts[k - 1] if k else None
    return None


def decode_status(value):
    return [name for bit, name in sorted(STATUS_BITS.items()) if value & (1 << bit)]


# ---------------------------------------------------------------- 链路


class Hi12Link(object):
    """一台 HI12 的串口链路。"""

    def __init__(self, dev, baud=921600):
        if baud not in BAUD_TABLE:
            raise ValueError("unsupported baud %r" % (baud,))
        self.dev = dev
        self.baud = baud
        self.fd = -1

    # -- 生命周期

    def open(self):
        # 必须 O_RDWR：要发 LOG 命令。O_RDONLY 的 fd 上 os.write() 直接 EBADF（已踩）。
        fd = os.open(self.dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self._configure(fd)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        self.fd = fd
        return self

    def _configure(self, fd):
        iflag, oflag, cflag, lflag, _ispeed, _ospeed, cc = termios.tcgetattr(fd)
        iflag = 0
        oflag = 0
        lflag = 0                                    # 【必须全清，见模块 docstring】
        cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
        cc = list(cc)
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        baud = BAUD_TABLE[self.baud]
        termios.tcsetattr(fd, termios.TCSANOW,
                          [iflag, oflag, cflag, lflag, baud, baud, cc])
        termios.tcflush(fd, termios.TCIOFLUSH)

    def set_baud(self, baud):
        """在已打开的 fd 上切波特率（tcsetattr）。不需要 close/reopen。"""
        if baud not in BAUD_TABLE:
            raise ValueError("unsupported baud %r" % (baud,))
        self.baud = baud
        if self.fd >= 0:
            self._configure(self.fd)
        return self

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.quiet_close()
        return False

    # -- 读写

    def read(self, timeout=0.2, maxbytes=262144):
        if self.fd < 0:
            return b""
        try:
            r, _, _ = select.select([self.fd], [], [], timeout)
        except (OSError, ValueError):
            return b""
        if not r:
            return b""
        try:
            return os.read(self.fd, maxbytes)
        except OSError:
            return b""

    def flush(self):
        """丢弃输入队列里已到的字节。

        【只清输入】：TCIOFLUSH 会连输出队列一起丢，刚写出去的命令可能还没进驱动
        就被抹掉。所以这里固定用 TCIFLUSH。
        """
        if self.fd >= 0:
            try:
                termios.tcflush(self.fd, termios.TCIFLUSH)
            except (OSError, termios.error):
                pass

    def command(self, text, wait=0.20, read_for=0.40, max_total=None):
        """发一条 ASCII 命令（自动补 CRLF），返回读到的原始字节。

        【必须有硬截止，这是踩出来的】原来只按"有数据就再等 0.08 s"滚动延长，
        一旦设备开始连续出 0x91 流（92 KB/s、每 1 ms 一帧），deadline 永远被推后，
        循环永不退出 —— unmute() 一发出、流一起来就整条脚本卡死在 select 里，
        没有异常、没有输出，只能靠 faulthandler 抓到。所以再加一个不可延长的硬截止。
        """
        if self.fd < 0:
            raise IOError("port not open")
        os.write(self.fd, text.encode("ascii") + CMD_END)
        time.sleep(wait)
        if read_for <= 0:
            return b""
        start = time.monotonic()
        hard_deadline = start + (max_total if max_total is not None else read_for * 2.0)
        deadline = min(start + read_for, hard_deadline)
        chunks = []
        while True:
            now = time.monotonic()
            if now >= deadline or now >= hard_deadline:
                break
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if not r:
                if chunks:
                    break
                continue
            try:
                d = os.read(self.fd, 8192)
            except OSError:
                break
            if not d:
                break
            chunks.append(d)
            deadline = min(now + 0.08, hard_deadline)   # 有数据就再等一小会，但封顶
        return b"".join(chunks)

    def send(self, text):
        """只写不读。用于静音/恢复输出这类"回包无所谓、而在流里必然读不干净"的命令。"""
        if self.fd < 0:
            raise IOError("port not open")
        os.write(self.fd, text.encode("ascii") + CMD_END)

    # -- 流控：查询前必须先静音，否则 1 kHz 二进制流会把 ASCII 回包冲掉

    def mute(self, settle=0.25):
        """静音 0x91 输出：盲发 -> 等一拍让命令生效 -> 清掉残留输入。"""
        self.send("LOG HI91 ONTIME 0")
        time.sleep(settle)
        self.flush()

    def unmute(self, ontime="0.001", settle=0.05):
        """恢复 0x91 输出。ontime 单位是秒，"0.001" = 1000 Hz。

        【绝不读回包】：一恢复输出，连续流立刻灌进来，去读它等于自找卡死。
        """
        self.send("LOG HI91 ONTIME %s" % ontime)
        time.sleep(settle)
        self.flush()

    # -- 身份与配置查询

    def query(self, key, mute=False):
        """发 "LOG <key>" 并返回 (解析出的 dict, 原始文本)。"""
        if mute:
            self.mute()
            self.flush()
        raw = self.command("LOG %s" % key, wait=0.25, read_for=0.45)
        text = raw.decode("utf-8", "replace")
        return parse_kv(text), text

    def query_version(self):
        """LOG VERSION -> PNAME / BUILD / UUID / SN / APP_VER / BL_VER。

        UUID 是模块固件里的只读出厂编号，跟着模块走、不跟 USB 口走，
        这是"任意插拔也能分清两台"的唯一可靠依据（SN 可能为空串）。
        """
        self.mute()
        self.flush()
        raw = self.command("LOG VERSION", wait=0.25, read_for=0.50)
        text = raw.decode("utf-8", "replace")
        kv = parse_kv(text)
        return kv, text

    # -- 收尾

    def quiet_close(self, drain=0.25):
        """静音 -> 排空 -> close。不能可靠规避 wedged，只是尽量降低概率。"""
        if self.fd < 0:
            return
        try:
            self.mute()
        except (OSError, IOError):
            pass
        try:
            deadline = time.monotonic() + drain
            while time.monotonic() < deadline:
                self.read(timeout=0.02)
        except (OSError, IOError):
            pass
        fd, self.fd = self.fd, -1
        try:
            os.close(fd)
        except OSError:
            pass


# ---------------------------------------------------------------- ASCII 回包解析

# 值必须限制在同一行内：SN 可能为空串，写成 \s* 会把换行吃掉、把下一行的
# "APP_VER=172" 当成 SN 的值（已踩：SN=APP_VER=172）。
_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*[:=][ \t]*([^\r\n]*)")


def parse_kv(text):
    """容错解析 LOG 命令回包。手册没给严格格式，所以两种分隔符都认。"""
    kv = {}
    for key, value in _KV_RE.findall(text):
        kv[key.upper()] = value.strip().strip(",;")
    return kv


# ---------------------------------------------------------------- 端口探测


class _ProbeTimeout(Exception):
    pass


def probe_open(dev, timeout=3.0):
    """带超时的可打开性探测。wedge 时 os.open 会永久阻塞，必须加 alarm。"""
    import signal

    def _handler(_signum, _frame):
        raise _ProbeTimeout()

    old = signal.signal(signal.SIGALRM, _handler)
    fd = -1
    try:
        # 计时器必须在 os.open 的 finally 里就取消。
        # 若留到外层 finally 才取消，os.open 抛 EIO 进入 except 处理器的这段时间里
        # 定时器仍会到点，_ProbeTimeout 就会从 except 块里逃出去把整条脚本掀翻（已踩）。
        try:
            signal.setitimer(signal.ITIMER_REAL, timeout)
            fd = os.open(dev, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        return True, ""
    except _ProbeTimeout:
        return False, "open 超时 %.1fs（设备已 wedged）" % timeout
    except OSError as exc:
        return False, "open 失败（大概率已 wedged）: %s" % (exc,)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


# ---------------------------------------------------------------- 波特率探测


def detect_baud_on_link(link, candidates=(921600, 460800, 230400, 115200), read_for=0.55):
    """在【已经打开的】链路上逐个波特率试 "LOG VERSION"，返回可用波特率与明细。

    为什么要这一步：波特率不是"设备的标准状态"，它是为了达到 1000 Hz 派生出来的量。
    出厂默认 115200/100 Hz；换件、恢复出厂、或别人用 CHCenter 改过都会变。
    用错波特率打开拿到的只是位噪声，表现为 0 帧 + 大量 resync 字节。

    为什么不在同一循环里反复 open/close：CH340 在满速收流后 close 有概率 wedged，
    切波特率用 tcsetattr 就够了，不必动 fd。这里全程只开一次口。

    为什么用 ASCII 回包而不是"数帧"来判断：设备可能被别人留在静音状态
    （HI91 ONTIME 0，本次会话开始前就是这样），静音时根本不会出帧，
    数帧法会误判成"波特率不对"。而 LOG VERSION 的 ASCII 回包与流无关。
    """
    detail = []
    for baud in candidates:
        if baud not in BAUD_TABLE:
            continue
        link.set_baud(baud)
        # 先盲发静音再问：设备若正在满速出流，LOG VERSION 的回包会被二进制帧淹掉。
        # 波特率不对时这条命令只是被当成噪声丢掉，不影响后续候选。
        try:
            link.send("LOG HI91 ONTIME 0")
            time.sleep(0.25)
        except OSError:
            pass
        link.flush()
        raw = link.command("LOG VERSION", wait=0.25, read_for=read_for)
        text = raw.decode("utf-8", "replace")
        upper = text.upper()
        if "PNAME" in upper or "UUID" in upper:
            detail.append((baud, "ASCII 回包可读"))
            return baud, detail
        # 退一步：有的固件只在流里回，看能不能切出连续 0x91 帧
        split = FrameSplitter()
        frames = 0
        t_end = time.monotonic() + 0.5
        while time.monotonic() < t_end:
            data = link.read(timeout=0.1)
            if data:
                frames += len(split.feed(data))
        if frames > 5:
            detail.append((baud, "%d 帧/0.5s" % frames))
            return baud, detail
        detail.append((baud, "无有效回包（%d 帧）" % frames))
    return None, detail


if __name__ == "__main__":
    print("crc16_xmodem selftest:", "PASS" if crc_selftest() else "FAIL")
    print("ttyUSB ports:", list_tty_usb())
    for d in list_tty_usb():
        print(" ", d, "-> usb port", usb_port_of(d))
