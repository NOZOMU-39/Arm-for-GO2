# -*- coding: utf-8 -*-
"""HI12 串口链路层：裸 os + termios（Jetson 上没有 pyserial，也不该为它加依赖）。

关键实测约束（2026-11-06 于 Jetson Orin NX 复测，别凭手册想当然）：
  - **lflag 必须全清**。Linux tty 默认 lflag 含 ECHO/ECHOE/ECHOK，漏清一个，
    n_tty 就把收到的字节回显到 TX；921600 已占 USB 全速带宽约 89%，
    回显直接吃满 -> 掉到 933 fps、每 ~15 ms 缺整帧。设 at[3]=0 即满速。
  - **满速收流期间或之后 close() 会让 CH340 有概率 wedged**（后续 open 报 EIO）。
    静音后再关**不能可靠规避**，必须配合 imu_hi12s2/recover.py。
  - 查询 ASCII 配置前必须先静音 0x91 输出，否则回包被 1 kHz 流淹掉。

本模块只做 I/O；切帧与解析在 protocol.py（纯逻辑、可单测）。
"""
import os
import re
import select
import termios
import time

from .protocol import CMD_END, FrameSplitter

BAUD_TABLE = {
    9600: termios.B9600,
    115200: termios.B115200,
    230400: termios.B230400,
    460800: termios.B460800,
    921600: termios.B921600,
}


class Hi12Link(object):
    """一台 HI12 的串口链路。"""

    def __init__(self, dev, baud=921600):
        if baud not in BAUD_TABLE:
            raise ValueError("unsupported baud %r" % (baud,))
        self.dev = dev
        self.baud = baud
        self.fd = -1

    # ---- 生命周期

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
        """在已打开的 fd 上切波特率（tcsetattr），不需要 close/reopen。"""
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

    # ---- 读写

    def read(self, timeout=0.2, maxbytes=262144):
        if self.fd < 0:
            return b""
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
        except (OSError, ValueError):
            return b""
        if not ready:
            return b""
        try:
            return os.read(self.fd, maxbytes)
        except OSError:
            return b""

    def flush(self):
        """丢弃输入队列里已到的字节。

        固定用 TCIFLUSH：TCIOFLUSH 会连输出队列一起丢，
        刚写出去的命令可能还没进驱动就被抹掉。
        """
        if self.fd >= 0:
            try:
                termios.tcflush(self.fd, termios.TCIFLUSH)
            except (OSError, termios.error):
                pass

    def command(self, text, wait=0.20, read_for=0.40, max_total=None):
        """发一条 ASCII 命令（自动补 CRLF），返回读到的原始字节。

        【必须有硬截止】只按“有数据就再等 0.08 s”滚动延长时，
        设备一旦开始连续出 0x91 流（92 KB/s），deadline 永远被推后，循环永不退出
        —— unmute() 一发、流一起来就整条脚本卡死在 select 里（已踩）。
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
            ready, _, _ = select.select([self.fd], [], [], 0.05)
            if not ready:
                if chunks:
                    break
                continue
            try:
                data = os.read(self.fd, 8192)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
            deadline = min(now + 0.08, hard_deadline)   # 有数据就再等一小会，但封顶
        return b"".join(chunks)

    def send(self, text):
        """只写不读。用于静音/恢复输出这类“回包无所谓、在流里必然读不干净”的命令。"""
        if self.fd < 0:
            raise IOError("port not open")
        os.write(self.fd, text.encode("ascii") + CMD_END)

    # ---- 流控：查询前必须先静音

    def mute(self, settle=0.25):
        """静音 0x91 输出：盲发 -> 等一拍让命令生效 -> 清掉残留输入。"""
        self.send("LOG HI91 ONTIME 0")
        time.sleep(settle)
        self.flush()

    def unmute(self, period_s=0.001, settle=0.05):
        """恢复 0x91 输出。period_s 是输出周期（0.001 s = 1000 Hz）。

        【绝不读回包】：一恢复输出，连续流立刻灌进来，去读它等于自找卡死。
        """
        self.send("LOG HI91 ONTIME %s" % _fmt_period(period_s))
        time.sleep(settle)
        self.flush()

    # ---- 身份与配置查询

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
        这是“任意插拔也能分清两台”的唯一可靠依据（SN 可能为空串）。
        """
        self.mute()
        self.flush()
        raw = self.command("LOG VERSION", wait=0.25, read_for=0.50)
        text = raw.decode("utf-8", "replace")
        return parse_kv(text), text

    # ---- 收尾

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

# 值必须限制在同一行内：SN 可能为空串，写成 \s* 会吃掉换行，
# 把下一行的 "APP_VER=172" 当成 SN 的值（已踩：SN=APP_VER=172）。
_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*[:=][ \t]*([^\r\n]*)")


def parse_kv(text):
    """容错解析 LOG 命令回包。手册没给严格格式，所以两种分隔符都认。"""
    kv = {}
    for key, value in _KV_RE.findall(text):
        kv[key.upper()] = value.strip().strip(",;")
    return kv


def _fmt_period(period_s):
    """1000 Hz -> "0.001"；保持小数写法，设备只认这种。"""
    return ("%.6f" % float(period_s)).rstrip("0").rstrip(".") or "0"


# ---------------------------------------------------------------- 探测工具

class _ProbeTimeout(Exception):
    pass


def probe_open(dev, timeout=3.0):
    """带超时的可打开性探测。wedged 时 os.open 会永久阻塞，必须加 alarm。

    返回值 (ok, message)。注意：**open+close 本身就是触发 wedged 的动作**，
    不要拿它当“跑业务前先确认设备好的”的例行检查（2026-11-06 踩过：
    用它验证健康口，反而把刚救回来的口又打死）。
    """
    import signal

    def _handler(_signum, _frame):
        raise _ProbeTimeout()

    old = signal.signal(signal.SIGALRM, _handler)
    fd = -1
    try:
        # 计时器必须在 os.open 的 finally 里取消；留到外层 finally 会与
        # except 处理期重叠，二次抛异常把整条脚本掀翻（已踩）。
        try:
            signal.setitimer(signal.ITIMER_REAL, timeout)
            fd = os.open(dev, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        return True, ""
    except _ProbeTimeout:
        return False, "open 超时 %.1fs（设备可能已 wedged）" % timeout
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


def detect_baud_on_link(link, candidates=(921600, 460800, 230400, 115200), read_for=0.55):
    """在【已经打开的】链路上逐个波特率试 "LOG VERSION"，返回 (baud, detail)。

    为什么要这一步：波特率不是设备的“标准状态”，而是为达到 1000 Hz 派生出来的量。
    出厂默认 115200/100 Hz；换件、恢复出厂、别人用 CHCenter 改过都会变。
    全程只开一次口（切波特率用 tcsetattr），因为 open/close 会触发 CH340 wedged。
    """
    detail = []
    for baud in candidates:
        if baud not in BAUD_TABLE:
            continue
        link.set_baud(baud)
        try:
            link.send("LOG HI91 ONTIME 0")   # 先静音，否则回包被 1 kHz 流淹掉
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
