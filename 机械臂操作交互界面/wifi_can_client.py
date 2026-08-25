#!/usr/bin/env python3
"""
ESP32 WiFi CAN Client v2.0 — Python 双模客户端（TCP + 串口自动降级）

适配 ESP32 WiFi CAN 固件 v2.0 二进制帧协议:
  帧格式: [2B 大端长度] [1B 类型] [N字节载荷]
  类型: 0x01=CMD_REQ  0x02=CMD_RESP  0x03=CAN_FRAME  0x04=CAN_SEND

智能四级自动降级连接（全自动发现 ESP32）:
  0. 本机子网并发扫描 1-254 (64线程, <1秒完成)
  1. 热点网段并发扫描 (192.168.137/0/1/43, 172.20.10)
  2. TCP 直连 AP IP (192.168.4.1)
  3. USB CDC 串口 (自动检测 ESP32-S3)

用法:
  python wifi_can_client.py                          # 全自动连接
  python wifi_can_client.py --host 192.168.4.1       # 指定 TCP IP
  python wifi_can_client.py --serial COM3            # 指定串口
  python wifi_can_client.py --monitor                # 监听模式
  python wifi_can_client.py --list-ports             # 列出可用串口
  python wifi_can_client.py --scan                   # 并发扫描所有通道
"""

import socket
import struct
import time
import argparse
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 串口支持 (可选依赖) ======
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# ====== 帧协议常量 (与 WS_Config.h 保持一致) ======
FRAME_CMD_REQ  = 0x01   # PC → ESP32  命令请求
FRAME_CMD_RESP = 0x02   # ESP32 → PC  命令响应
FRAME_CAN_PUSH = 0x03   # ESP32 → PC  CAN 接收帧推送 (单帧, 兼容模式)
FRAME_CAN_SEND = 0x04   # PC → ESP32  CAN 发送帧
FRAME_CAN_BATCH = 0x05  # ESP32 → PC  CAN 批帧推送 (协商后启用)

CMD_QUERY_IP      = 0x0A0D
CMD_QUERY_CAN     = 0x0A0F
CMD_SET_CAN_RATE  = 0x0A10
CMD_QUERY_RTC     = 0x0A11
CMD_ENABLE_BATCH  = 0x0A13   # 0x0A12 预留给心跳看门狗

# 批帧参数 (与 WS_Config.h 一致)
UDP_PORT = 8889   # UDP 订阅式推送端口

# ====== 可能的热点网段 ======
HOTSPOT_SUBNETS = [
    "192.168.137",   # Windows 默认热点
    "192.168.0",     # 常见路由器/热点
    "192.168.1",     # 常见路由器
    "192.168.43",    # Android 热点
    "172.20.10",     # iOS 热点
]

# ====== ESP32 串口检测关键词 ======
ESP32_SERIAL_KEYWORDS = [
    "USB", "ESP32", "CDC", "JTAG", "Serial",
    "串口", "COM", "UART", "USB-SERIAL", "303A", "1001",
]


@dataclass
class CANFrame:
    """CAN 帧数据结构"""
    id: int              # CAN ID
    extd: bool           # True=扩展帧, False=标准帧
    dlc: int             # 数据长度 (0-8)
    data: bytes          # 帧数据
    timestamp_ms: int    # 接收时间戳 (ms，ESP32 开机计时)

    def __str__(self) -> str:
        hex_data = ' '.join(f'{b:02X}' for b in self.data) if self.data else '(空)'
        frame_type = '扩展帧' if self.extd else '标准帧'
        return f"ID:0x{self.id:X} {frame_type} DLC:{self.dlc} {hex_data} [{self.timestamp_ms}ms]"

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CANFrame':
        """从 CAN_FRAME(0x03) 载荷反序列化"""
        if len(data) < 10:
            raise ValueError(f"CAN帧载荷至少10字节，实际{len(data)}")
        can_id = struct.unpack('>I', data[0:4])[0]
        extd = data[4] != 0
        timestamp_ms = struct.unpack('>I', data[5:9])[0]
        dlc = data[9]
        payload = data[10:10 + dlc] if dlc > 0 else b''
        return cls(id=can_id, extd=extd, dlc=dlc, data=payload, timestamp_ms=timestamp_ms)

    @staticmethod
    def parse_batch(payload: bytes) -> List['CANFrame']:
        """解析 CAN_BATCH(0x05) 批帧载荷: [2B 帧数][N × 帧块]

        帧块格式与 0x03 单帧载荷完全一致，可复用 from_bytes 的解析逻辑。
        """
        if len(payload) < 2:
            return []
        n = struct.unpack('>H', payload[0:2])[0]
        frames = []
        pos = 2
        for _ in range(n):
            if pos + 10 > len(payload):
                break
            can_id = struct.unpack('>I', payload[pos:pos + 4])[0]
            extd = payload[pos + 4] != 0
            timestamp_ms = struct.unpack('>I', payload[pos + 5:pos + 9])[0]
            dlc = payload[pos + 9]
            if pos + 10 + dlc > len(payload):
                break
            data = payload[pos + 10:pos + 10 + dlc]
            frames.append(CANFrame(id=can_id, extd=extd, dlc=dlc,
                                   data=data, timestamp_ms=timestamp_ms))
            pos += 10 + dlc
        return frames


class WiFiCANClient:
    """WiFi CAN 客户端 — TCP/串口双模，支持库调用和交互式终端"""

    SCAN_TIMEOUT = 0.3     # 单IP探测超时 (秒)
    SCAN_WORKERS = 8       # 并发线程数 (Windows 下不宜过高)

    def __init__(self, host: Optional[str] = None, port: int = 8888,
                 serial_port: Optional[str] = None, batch: bool = True):
        self.conn = None
        self.mode: Optional[str] = None    # 'tcp' 或 'serial'
        self.batch_enabled = False         # 批帧模式是否协商成功
        self._lock = threading.Lock()
        self._tx_count = 0
        self._rx_count = 0
        self._stats_time = time.time()

        if serial_port:
            self._connect_serial(serial_port)
        elif host:
            self._connect_tcp(host, port)
        else:
            self._auto_connect(port)

        # TCP 连接成功后自动协商批帧模式 (v2.1)
        # 旧固件/旧版客户端不受影响：协商失败自动回退单帧模式
        if batch and self.mode == 'tcp':
            self._negotiate_batch()

    def _negotiate_batch(self) -> bool:
        """向 ESP32 协商启用批帧模式 (CMD_ENABLE_BATCH = 0x0A12)

        固件 v2.1 响应 "BATCH" → 启用成功，推送改为 0x05 批帧。
        固件 v2.0 无此命令 → 无响应，保持 0x03 单帧，行为不变。
        """
        try:
            self._send_frame(FRAME_CMD_REQ, struct.pack('>H', CMD_ENABLE_BATCH))
            result = self._recv_frame(timeout=0.8)
            if result and result[0] == FRAME_CMD_RESP and result[1] == b'BATCH':
                self.batch_enabled = True
                print("[OK] 批帧模式已启用 (高吞吐)")
                return True
        except Exception:
            pass
        print("[..] 未启用批帧模式 (固件旧版? 继续使用单帧模式)")
        return False

    # ====== 网络发现 ======

    @staticmethod
    def _get_all_local_subnets() -> List[str]:
        """检测本机所有网卡的子网前缀"""
        subnets = []
        seen = set()
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip in seen or ip.startswith('127.'):
                    continue
                seen.add(ip)
                parts = ip.split('.')
                if len(parts) == 4:
                    sub = f"{parts[0]}.{parts[1]}.{parts[2]}"
                    if sub not in subnets:
                        subnets.append(sub)
        except Exception:
            pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(('8.8.8.8', 1))
            ip = s.getsockname()[0]
            s.close()
            parts = ip.split('.')
            if len(parts) == 4:
                sub = f"{parts[0]}.{parts[1]}.{parts[2]}"
                if sub not in subnets:
                    subnets.append(sub)
        except Exception:
            pass
        return subnets

    @staticmethod
    def _tcp_probe(ip: str, port: int, timeout: float = 0.08):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            s.close()
            return (ip, True)
        except Exception:
            return (ip, False)

    @staticmethod
    def _scan_subnet_concurrent(subnet: str, port: int, timeout: float = 0.08,
                                max_workers: int = 64) -> Optional[str]:
        """并发扫描子网 1-254，找到返回 IP。一次扫描可能漏检，调用方应重试。"""
        ips = [f"{subnet}.{i}" for i in range(1, 255)]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(WiFiCANClient._tcp_probe, ip, port, timeout): ip
                       for ip in ips}
            for future in as_completed(futures):
                ip, ok = future.result()
                if ok:
                    for f in futures:
                        f.cancel()
                    return ip
        return None

    @staticmethod
    def _scan_subnet_with_retry(subnet: str, port: int, timeout: float = 0.3,
                                max_workers: int = 8, retries: int = 1) -> Optional[str]:
        """带重试的子网扫描，提高检测可靠性"""
        for attempt in range(retries + 1):
            if attempt > 0:
                time.sleep(0.5)
            found = WiFiCANClient._scan_subnet_concurrent(
                subnet, port, timeout=timeout, max_workers=max_workers)
            if found:
                return found
        return None

    # ====== 连接管理 ======

    def _connect_tcp(self, host: str, port: int):
        try:
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.settimeout(1.0)
            self.conn.connect((host, port))
            self.conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.mode = 'tcp'
            print(f"[OK] TCP 已连接 {host}:{port}")
        except Exception as e:
            raise ConnectionError(f"TCP 连接失败 {host}:{port}: {e}")

    def _connect_serial(self, port: str):
        if not HAS_SERIAL:
            raise ImportError("需要 pyserial: pip install pyserial")
        try:
            self.conn = serial.Serial(port, 115200, timeout=0.1)
            self.mode = 'serial'
            print(f"[OK] 串口已连接 {port}")
        except Exception as e:
            raise ConnectionError(f"串口连接失败 {port}: {e}")

    def _auto_connect(self, port: int):
        """智能多级自动降级: AP直连(秒连) → 本机子网 → 热点网段 → 串口

        v2.1.3: AP 直连提到最前 (0.3s 快速失败) —
        AP 模式下不再先白扫几个网段才轮到 AP, 连接秒开;
        STA 模式只多花 0.3s, 无感知。
        """

        # 第0级: AP 直连 (192.168.4.1) — AP 模式秒连, 失败快速降级
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(("192.168.4.1", port))
            s.close()
            print("[*] 第0级: AP 直连 192.168.4.1...")
            self._connect_tcp("192.168.4.1", port)
            return
        except Exception:
            pass  # AP 不可达, 继续扫描

        # 第1级: 本机所有网卡
        local_subnets = self._get_all_local_subnets()
        if local_subnets:
            print(f"[*] 检测到 {len(local_subnets)} 个网段: " +
                  ', '.join(s + '.0/24' for s in local_subnets))
            for subnet in local_subnets:
                print(f"[*] 第1级: 扫描 {subnet}.1-254 (port {port})...")
                found = self._scan_subnet_with_retry(
                    subnet, port, timeout=self.SCAN_TIMEOUT, max_workers=self.SCAN_WORKERS)
                if found:
                    print(f"    [OK] 发现设备: {found}")
                    self._connect_tcp(found, port)
                    return
                print(f"    [--] {subnet}.0/24 未发现 ESP32")
        else:
            print("[!] 未能检测到本机网段")

        # 第2级: 热点网段 (AP 已在第0级试过)
        print(f"[*] 第2级: 扫描热点网段 (port {port})...")
        scanned = set(local_subnets) if local_subnets else set()
        for subnet in HOTSPOT_SUBNETS:
            if subnet in scanned:
                continue
            scanned.add(subnet)
            print(f"  [*] 扫描 {subnet}.0/24 ...")
            found = self._scan_subnet_with_retry(
                subnet, port, timeout=self.SCAN_TIMEOUT, max_workers=self.SCAN_WORKERS)
            if found:
                print(f"    [OK] 发现设备: {found}")
                self._connect_tcp(found, port)
                return
            print(f"    [--] {subnet}.0/24 无设备")

        # 第3级: 串口
        if HAS_SERIAL:
            print("[*] 第3级: 搜索 USB 串口...")
            ports = list(serial.tools.list_ports.comports())
            if not ports:
                print("[!] 未发现任何串口")
                # 跳过串口尝试
            else:
                for p in ports:
                    desc = (p.description or "") + " " + (p.hwid or "") + " " + (p.name or "")
                    matched = any(kw.lower() in desc.lower() for kw in ESP32_SERIAL_KEYWORDS)
                    if matched:
                        try:
                            print(f"[*] 尝试: {p.device} — {p.description}")
                            self._connect_serial(p.device)
                            return
                        except ConnectionError:
                            continue
                print("[*] 未匹配到 ESP32，尝试所有串口...")
                for p in ports:
                    try:
                        print(f"[*] 尝试: {p.device} — {p.description}")
                        self._connect_serial(p.device)
                        time.sleep(0.5)
                        return
                    except ConnectionError:
                        continue
        else:
            print("[!] pyserial 未安装，跳过串口检测。安装: pip install pyserial")

        raise ConnectionError(
            "\n无法自动连接 ESP32。请检查:\n"
            "  1. ESP32 已上电 (USB 口供电)?\n"
            "  2. 如用 STA 模式: 笔记本热点已开? ESP32 连上了吗?\n"
            "  3. 如用 AP 模式: 电脑已连上 'ESP32-WiFi-CAN' WiFi 了吗?\n"
            "  4. 如用串口: USB 线插好了吗?\n"
            "\n"
            "  手动连接:\n"
            "    python wifi_can_client.py --host 192.168.4.1    (AP模式)\n"
            "    python wifi_can_client.py --host 192.168.137.x  (STA模式)\n"
            "    python wifi_can_client.py --serial COM3          (串口)\n"
            "    python wifi_can_client.py --scan                 (扫描设备)"
        )

    # ====== 帧协议 I/O ======

    def _send_frame(self, frame_type: int, payload: bytes = b''):
        """发送一个完整帧: [2B长度(含类型)] [1B类型] [载荷]"""
        total = 1 + len(payload)  # 类型 + 载荷
        frame = struct.pack('>H', total) + bytes([frame_type]) + payload
        with self._lock:
            if self.mode == 'tcp':
                self.conn.sendall(frame)
            else:
                self.conn.write(frame)

    def _recv_frame(self, timeout: float = 0.5) -> Optional[tuple[int, bytes]]:
        """接收一个完整帧，返回 (类型, 载荷) 或 None"""
        with self._lock:
            if self.mode == 'tcp':
                self.conn.settimeout(timeout)
                try:
                    header = self.conn.recv(2)
                    if len(header) < 2:
                        return None
                    length = struct.unpack('>H', header)[0]
                    if length == 0 or length > 4096:
                        return None
                    data = b''
                    while len(data) < length:
                        chunk = self.conn.recv(length - len(data))
                        if not chunk:
                            break
                        data += chunk
                    if len(data) >= 1:
                        return (data[0], data[1:])
                    return None
                except socket.timeout:
                    return None
            else:
                self.conn.timeout = timeout
                try:
                    header = self.conn.read(2)
                    if len(header) < 2:
                        return None
                    length = struct.unpack('>H', header)[0]
                    if length == 0 or length > 4096:
                        return None
                    data = self.conn.read(length)
                    if len(data) >= 1:
                        return (data[0], data[1:])
                    return None
                except Exception:
                    return None

    # ====== 公开 API ======

    def send_can(self, can_id: int, data: bytes, extended: bool = False,
                 verbose: bool = True):
        """发送 CAN 帧 (FRAME_CAN_SEND 类型，直通模式)

        verbose=False 时静默发送（批量测试用，默认保持日志输出）
        """
        payload = struct.pack('>I', can_id) + bytes([1 if extended else 0]) + data
        self._send_frame(FRAME_CAN_SEND, payload)
        self._tx_count += 1
        if verbose:
            hex_str = ' '.join(f'{b:02X}' for b in data) if data else '(空)'
            frame_type = '扩展帧' if extended else '标准帧'
            print(f"[CAN TX] ID=0x{can_id:X} [{frame_type}] len={len(data)} [{hex_str}]")

    def set_can_rate(self, rate_kbps: int):
        """设置 CAN 波特率"""
        payload = struct.pack('>H', CMD_SET_CAN_RATE) + struct.pack('>I', rate_kbps)
        self._send_frame(FRAME_CMD_REQ, payload)
        print(f"[CFG] CAN 速率设为 {rate_kbps} kbps")

    def query_ip(self) -> str:
        """查询 ESP32 IP 地址"""
        self._send_frame(FRAME_CMD_REQ, struct.pack('>H', CMD_QUERY_IP))
        time.sleep(0.1)
        result = self._recv_frame(timeout=1.0)
        if result:
            return result[1].decode('utf-8', errors='replace').strip()
        return ""

    def read_can_buffer(self) -> List[CANFrame]:
        """读取 CAN 环形缓冲区，返回帧列表"""
        self._send_frame(FRAME_CMD_REQ, struct.pack('>H', CMD_QUERY_CAN))
        time.sleep(0.05)
        frames = []
        # 尝试读取所有推送的帧
        deadline = time.time() + 0.3
        while time.time() < deadline:
            result = self._recv_frame(timeout=0.1)
            if result is None:
                break
            frame_type, payload = result
            if frame_type == FRAME_CAN_PUSH and len(payload) >= 10:
                frames.append(CANFrame.from_bytes(payload))
            elif frame_type == FRAME_CAN_BATCH:
                frames.extend(CANFrame.parse_batch(payload))
            elif frame_type == FRAME_CMD_RESP:
                text = payload.decode('utf-8', errors='replace')
                if 'Empty' in text:
                    break
        return frames

    def query_rtc_time(self) -> str:
        """查询 ESP32 RTC 时间"""
        self._send_frame(FRAME_CMD_REQ, struct.pack('>H', CMD_QUERY_RTC))
        time.sleep(0.1)
        result = self._recv_frame(timeout=1.0)
        if result:
            return result[1].decode('utf-8', errors='replace').strip()
        return ""

    def _update_stats(self):
        """内部: 更新帧率统计"""
        now = time.time()
        elapsed = now - self._stats_time
        if elapsed >= 1.0:
            rx = self._rx_count / elapsed
            tx = self._tx_count / elapsed
            if self._rx_count > 0 or self._tx_count > 0:
                print(f"\n  [STATS] TX: {tx:.1f} fps | RX: {rx:.1f} fps")
            self._rx_count = 0
            self._tx_count = 0
            self._stats_time = now

    def monitor(self, callback: Optional[Callable[[CANFrame], None]] = None,
                stop_event: Optional[threading.Event] = None):
        """持续监听 CAN 数据 (阻塞)

        callback: 每帧回调 (收到 CANFrame 对象)
        stop_event: 可选 threading.Event，置位后自动退出（配合超时监听）
        """
        mode_str = '批帧(高频推荐)' if self.batch_enabled else '单帧(兼容)'
        print(f"[MONITOR] 开始监听 CAN 数据 (推送: {mode_str}, Ctrl+C 停止)...")
        try:
            while True:
                if stop_event and stop_event.is_set():
                    print("[MONITOR] 已结束 (stop_event)")
                    break
                result = self._recv_frame(timeout=0.5)
                if result:
                    frame_type, payload = result
                    if frame_type == FRAME_CAN_PUSH and len(payload) >= 10:
                        frame = CANFrame.from_bytes(payload)
                        self._rx_count += 1
                        self._update_stats()
                        if callback:
                            callback(frame)
                        else:
                            ts = datetime.now().strftime('%H:%M:%S') + \
                                 f'.{int(time.time()*1000)%1000:03d}'
                            print(f"[{ts}] {frame}")
                    elif frame_type == FRAME_CAN_BATCH:
                        # 批帧展开 (v2.1)
                        for frame in CANFrame.parse_batch(payload):
                            self._rx_count += 1
                            if callback:
                                callback(frame)
                            else:
                                ts = datetime.now().strftime('%H:%M:%S') + \
                                     f'.{int(time.time()*1000)%1000:03d}'
                                print(f"[{ts}] {frame}")
                        self._update_stats()
                    elif frame_type == FRAME_CMD_RESP:
                        text = payload.decode('utf-8', errors='replace').strip()
                        if text:
                            print(f"[ESP32] {text}")
        except KeyboardInterrupt:
            print("\n[MONITOR] 已停止")

    def close(self):
        if self.conn:
            self.conn.close()
            print("[INFO] 连接已关闭")


# ====== UDP 订阅式监听 (v2.1, 可选) ======

def udp_monitor(host: str, port: int = UDP_PORT,
                callback: Optional[Callable[[CANFrame], None]] = None):
    """UDP 订阅式批帧监听（单向接收，不占用 TCP 连接）

    向 ESP32 的 UDP 8889 端口发一个订阅包即开始接收 0x05 批帧。
    30s 无续订会被 ESP32 移除，故每 20s 自动续订一次。
    """
    if not host:
        raise ValueError("UDP 模式需要指定 ESP32 IP (--host)")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(20.0)
    s.sendto(b'\x01', (host, port))   # 订阅请求
    print(f"[UDP] 已订阅 {host}:{port} 批帧推送 (Ctrl+C 停止)...")

    try:
        while True:
            try:
                data, _ = s.recvfrom(65535)
            except socket.timeout:
                # 20s 无数据 → 续订保活 (ESP32 30s 超时移除)
                try:
                    s.sendto(b'\x01', (host, port))
                except OSError:
                    break
                continue
            if len(data) < 3:
                continue
            frame_type = data[2]
            if frame_type == FRAME_CAN_BATCH and len(data) > 3:
                for frame in CANFrame.parse_batch(data[3:]):
                    if callback:
                        callback(frame)
                    else:
                        ts = datetime.now().strftime('%H:%M:%S') + \
                             f'.{int(time.time()*1000)%1000:03d}'
                        print(f"[{ts}] {frame}")
    except KeyboardInterrupt:
        print("\n[UDP] 已停止")
    finally:
        s.close()


# ====== 快捷函数（供外部 import 引用） ======

def quick_demo(client: WiFiCANClient):
    """一键演示：发帧 → 查询 → 读缓冲 → 监听（带日志）"""
    print(f"[INFO] 连接模式: {client.mode} | "
          f"推送: {'批帧(高频推荐)' if client.batch_enabled else '单帧(兼容)'}")

    # 发送扩展帧
    try:
        client.send_can(can_id=0x1F6, data=bytes([0xAA, 0xBB]), extended=True)
        print("[OK] 扩展帧已发送")
    except Exception as e:
        print(f"[FAIL] 发送异常: {e}")

    # 查询 IP / RTC
    ip = client.query_ip()
    print(f"[INFO] ESP32 IP: {ip if ip else '(无响应)'}")
    t = client.query_rtc_time()
    print(f"[INFO] RTC 时间: {t if t else '(无响应)'}")

    # 读取缓冲区
    frames = client.read_can_buffer()
    if frames:
        print(f"[OK] 缓冲区 {len(frames)} 帧:")
        for f in frames:
            print(f"    ID=0x{f.id:X} 数据={f.data.hex(' ')} 时间={f.timestamp_ms}ms")
    else:
        print("[FAIL] 缓冲区为空 (总线上没有其他设备在发帧?)")

    # 监听
    print("[INFO] 开始监听 (Ctrl+C 停止)...")
    try:
        client.monitor(callback=lambda f: print(f"    收到: {f}"))
    except KeyboardInterrupt:
        print("[INFO] 监听结束")
    finally:
        client.close()
        print("[INFO] 连接已关闭")


# ====== 扫描工具 ======

def scan_esp32():
    """扫描所有可达路径找到 ESP32"""
    print("=" * 50)
    print("  扫描 ESP32-WiFi-CAN ...")
    print("=" * 50)

    found_sta = []
    local_subnets = WiFiCANClient._get_all_local_subnets()

    if local_subnets:
        print(f"\n[0] 本机网段 ({len(local_subnets)} 个)")
        for subnet in local_subnets:
            print(f"    扫描 {subnet}.1-254 ...")
            found = WiFiCANClient._scan_subnet_with_retry(subnet, 8888)
            if found:
                found_sta.append(found)
                print(f"    [OK] 发现: {found}")
            else:
                print(f"    [--] {subnet}.0/24 未发现")

    scanned = set(local_subnets) if local_subnets else set()
    print("\n[1] 热点网段")
    for subnet in HOTSPOT_SUBNETS:
        if subnet in scanned:
            continue
        scanned.add(subnet)
        found = WiFiCANClient._scan_subnet_with_retry(subnet, 8888)
        if found:
            found_sta.append(found)
            print(f"    [OK] {subnet}.0/24 发现: {found}")
        else:
            print(f"    [--] {subnet}.0/24 无设备")

    print("\n[2] AP (192.168.4.1:8888)")
    found_ap = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(("192.168.4.1", 8888))
        s.close()
        found_ap = True
        print("    [OK] AP 可达")
    except Exception:
        print("    [--] AP 不可达")

    print("\n[3] 串口")
    found_serial = []
    if HAS_SERIAL:
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            print("    [--] 无串口")
        for p in ports:
            desc = (p.description or "") + " " + (p.hwid or "")
            matched = any(kw.lower() in desc.lower() for kw in ESP32_SERIAL_KEYWORDS)
            marker = " ← ESP32?" if matched else ""
            print(f"    {p.device} — {p.description}{marker}")
            if matched:
                found_serial.append(p.device)
    else:
        print("    [--] pyserial 未安装")

    print("\n" + "=" * 50)
    print("  连接方式:")
    for ip in found_sta:
        print(f"    python wifi_can_client.py --host {ip}")
    if found_ap:
        print(f"    python wifi_can_client.py --host 192.168.4.1")
    for dev in found_serial:
        print(f"    python wifi_can_client.py --serial {dev}")
    if not found_sta and not found_ap and not found_serial:
        print("    未发现 ESP32")
    print("=" * 50)


def list_serial_ports():
    if not HAS_SERIAL:
        print("pyserial 未安装: pip install pyserial")
        return
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("未发现任何串口")
        return
    print("可用串口:")
    for p in ports:
        desc = (p.description or "") + " " + (p.hwid or "")
        matched = any(kw.lower() in desc.lower() for kw in ESP32_SERIAL_KEYWORDS)
        marker = " ← ESP32?" if matched else ""
        print(f"  {p.device} — {p.description}{marker}")


# ====== 命令行入口 ======

def main():
    parser = argparse.ArgumentParser(
        description='ESP32 WiFi CAN Client v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python wifi_can_client.py                              # 全自动连接
  python wifi_can_client.py --host 192.168.4.1           # TCP 直连
  python wifi_can_client.py --serial COM3                # 串口直连
  python wifi_can_client.py --can-id 0x141 --can-data "A4 00 F4 01"  # 发送一帧
  python wifi_can_client.py --monitor                    # 监听模式
  python wifi_can_client.py --udp 192.168.4.1            # UDP 批帧监听 (v2.1)
  python wifi_can_client.py --scan                       # 扫描设备
  python wifi_can_client.py --list-ports                 # 列串口
        """)
    parser.add_argument('--host', help='ESP32 IP 地址 (TCP/UDP)')
    parser.add_argument('--port', type=int, default=8888, help='TCP 端口 (默认8888)')
    parser.add_argument('--serial', dest='serial_port', help='串口 (如 COM3)')
    parser.add_argument('--udp', action='store_true', help='UDP 订阅式批帧监听 (需 --host)')
    parser.add_argument('--can-id', type=str, default='0x123', help='CAN ID (hex)')
    parser.add_argument('--can-data', type=str, help='CAN 数据 hex 空格分隔')
    parser.add_argument('--can-extd', action='store_true', help='CAN 扩展帧')
    parser.add_argument('--can-rate', type=int, help='设置 CAN 速率 (kbps)')
    parser.add_argument('--monitor', action='store_true', help='监听模式')
    parser.add_argument('--query-ip', action='store_true', help='查询 ESP32 IP')
    parser.add_argument('--read-can', action='store_true', help='读取 CAN 缓冲区')
    parser.add_argument('--query-rtc', action='store_true', help='查询 RTC 时间')
    parser.add_argument('--scan', action='store_true', help='扫描设备')
    parser.add_argument('--list-ports', action='store_true', help='列出串口')

    args = parser.parse_args()

    if args.list_ports:
        list_serial_ports()
        return
    if args.scan:
        scan_esp32()
        return

    # UDP 模式：独立于 TCP 的单向批帧监听
    if args.udp:
        host = args.host or "192.168.4.1"
        udp_monitor(host)
        return

    client = WiFiCANClient(host=args.host, port=args.port, serial_port=args.serial_port)
    mode_str = '批帧(高频推荐)' if client.batch_enabled else '单帧(兼容)'
    print(f"[INFO] 连接模式: {client.mode} | 推送模式: {mode_str}")
    if not client.batch_enabled:
        print("[INFO] 提示: 未启用批帧 → 固件可能是 v2.0 旧版或协商超时, "
              "已自动回退单帧模式。高频通信建议烧录 v2.1 固件")

    try:
        if args.query_ip:
            ip = client.query_ip()
            print(f"ESP32 IP: {ip}")

        if args.query_rtc:
            t = client.query_rtc_time()
            print(f"ESP32 RTC: {t}")

        if args.can_rate:
            client.set_can_rate(args.can_rate)

        if args.can_data:
            can_id = int(args.can_id, 16)
            data = bytes.fromhex(args.can_data.replace(' ', ''))
            client.send_can(can_id, data, args.can_extd)

        if args.read_can:
            frames = client.read_can_buffer()
            if frames:
                for f in frames:
                    print(f"  {f}")
            else:
                print("  [CAN 缓冲区为空]")

        if args.monitor:
            client.monitor()

        # 无操作 → 交互模式
        if not any([args.query_ip, args.query_rtc, args.can_rate,
                    args.can_data, args.read_can, args.monitor]):
            print("")
            print("  \033[1;36m连接成功!\033[0m 输入 \033[1mhelp\033[0m 查看命令")
            print("  \033[90m先用 stat 看看设备状态\033[0m")
            print("")
            while True:
                try:
                    cmd = input("\033[1;32m>\033[0m ").strip()
                    if not cmd:
                        continue
                    parts = cmd.split()
                    c = parts[0].lower()

                    if c == 'help':
                        print("""
  \033[1m发送 CAN\033[0m
    send  <ID>:<hex数据>    标准帧  例: send 7B:11 22 33
    sendex <ID>:<hex数据>   扩展帧  例: sendex 1F6:AA BB
    短别名: s=send  se=sendex

  \033[1m设置\033[0m
    baud <kbps>             CAN波特率  例: baud 1000
    短别名: b=baud

  \033[1m查询\033[0m
    query                   查询 CAN 缓冲区   (q)
    wifi / ip               查询 ESP32 IP
    rtc                     查询 RTC 时间
    stat                    设备状态概览

  \033[1m监听\033[0m
    mon                     监听模式 (Ctrl+C 退出)

  \033[1m其他\033[0m
    help                    帮助
    quit / exit             退出
""")
                    # ---- send / s ----
                    elif c in ('send', 's') and len(parts) >= 2:
                        rest = cmd.split(None, 1)[1]
                        id_str, data_str = rest.split(':', 1) if ':' in rest else (rest, '')
                        cid = int(id_str, 16)
                        cdata = bytes.fromhex(data_str.replace(' ', '')) if data_str.strip() else b''
                        client.send_can(cid, cdata, extended=False)

                    # ---- sendex / se ----
                    elif c in ('sendex', 'se') and len(parts) >= 2:
                        rest = cmd.split(None, 1)[1]
                        id_str, data_str = rest.split(':', 1) if ':' in rest else (rest, '')
                        cid = int(id_str, 16)
                        cdata = bytes.fromhex(data_str.replace(' ', '')) if data_str.strip() else b''
                        client.send_can(cid, cdata, extended=True)

                    # ---- baud / b ----
                    elif c in ('baud', 'b') and len(parts) >= 2:
                        client.set_can_rate(int(parts[1]))

                    # ---- query / q ----
                    elif c in ('query', 'q'):
                        frames = client.read_can_buffer()
                        if frames:
                            for f in frames:
                                print(f"  {f}")
                        else:
                            print("  [CAN 缓冲区为空]")

                    # ---- wifi / ip ----
                    elif c in ('wifi', 'ip'):
                        print(client.query_ip())

                    # ---- rtc ----
                    elif c == 'rtc':
                        print(client.query_rtc_time())

                    # ---- stat ----
                    elif c == 'stat':
                        ip = client.query_ip()
                        print(f"ESP32 IP: {ip if ip else '(无响应)'}")
                        mode_str = '批帧(高频推荐)' if client.batch_enabled else '单帧(兼容)'
                        print(f"推送模式: {mode_str}")
                        frames = client.read_can_buffer()
                        print(f"CAN 缓冲区: {len(frames)} 帧" if frames else "CAN 缓冲区: 空")

                    # ---- mon ----
                    elif c == 'mon':
                        client.monitor()

                    # ---- quit / exit ----
                    elif c in ('quit', 'exit'):
                        break

                    else:
                        print(f"未知命令: {c}，输入 help 查看帮助")

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"错误: {e}")
    finally:
        client.close()


if __name__ == '__main__':
    main()
