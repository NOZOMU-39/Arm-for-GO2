# -*- coding: utf-8 -*-
"""
脉塔电机调试上位机 — 主程序(main.py)

功能:
  - pywebview 桌面窗口内嵌 index.html 全中文界面(WebView2 内核)
  - js_api 接口类:界面经 window.pywebview.api.xxx() 直接调用本程序
  - zlgcan 封装:ctypes 直调 zlgcan.dll(32 位),驱动脉塔官方 USBCAN 模块
  - 接收线程:轮询收帧入队,界面定时拉取
  - --mock 模拟模式:无硬件时全链路调试界面

运行:
  开发(需 32 位 Python 3.12,真机模式):  32 位 Python 运行 main.py
  开发(任意 Python,模拟模式):          python main.py --mock
  打包:                                 打包上位机.bat(PyInstaller,--onedir)
"""

import os
import sys
import time
import json
import queue
import struct
import threading
import argparse
import ctypes

# =====================================================================
# 一、pythonnet 运行库路径(必须在 import webview 之前设置)
# =====================================================================


def _setup_pythonnet():
    """设置 PYTHONNET_PYDLL,指向 python312.dll。pythonnet 3.x 找不到会抛异常。"""
    if os.environ.get("PYTHONNET_PYDLL"):
        return
    dll_name = "python312.dll"
    candidates = []
    if getattr(sys, "frozen", False):  # PyInstaller 打包模式
        candidates.append(os.path.join(sys._MEIPASS, dll_name))
        candidates.append(os.path.join(os.path.dirname(sys.executable), dll_name))
    candidates.append(os.path.join(sys.base_prefix, dll_name))
    candidates.append(os.path.join(os.path.dirname(sys.executable), dll_name))
    for cand in candidates:
        if os.path.isfile(cand):
            os.environ["PYTHONNET_PYDLL"] = cand
            return


_setup_pythonnet()

try:
    import webview
except ImportError:
    webview = None

# =====================================================================
# 二、路径工具
# =====================================================================


def exe_dir():
    """程序所在目录(打包后 = exe 同目录,zlgcan.dll 与 kerneldlls 放这里)"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    """资源文件路径(打包后从 _MEIPASS 取)"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def _now_ms():
    return int(time.time() * 1000)


def _fmt_ms(ms):
    """毫秒时间戳 → [HH:MM:SS.mmm] 可读格式(调试日志.txt 用)"""
    s, ms3 = divmod(int(ms), 1000)
    return f"[{time.strftime('%H:%M:%S', time.localtime(s))}.{ms3:03d}]"


# =====================================================================
# 三、zlgcan.dll 封装(32 位,__stdcall,官方头文件 zlgcan.h 布局)
# =====================================================================

# ---- 结构体(自然对齐,无 pack)----


class ZCAN_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dev_type", ctypes.c_uint), ("reserved", ctypes.c_uint)]


class ZCAN_CAN_FRAME(ctypes.Structure):
    """经典 CAN 帧 16 字节。can_id:bit31=扩展帧标志,bit30=远程帧"""

    _fields_ = [
        ("can_id", ctypes.c_uint),
        ("can_dlc", ctypes.c_uint8),
        ("res0", ctypes.c_uint8),
        ("res1", ctypes.c_uint8),
        ("pad", ctypes.c_uint8),
        ("data", ctypes.c_uint8 * 8),
    ]


class ZCAN_Transmit_Data(ctypes.Structure):
    """发送结构 20 字节:帧 + 发送类型(0=正常发送)"""

    _fields_ = [
        ("frame", ZCAN_CAN_FRAME),
        ("transmit_type", ctypes.c_uint8),
        ("pad", ctypes.c_uint8 * 3),
    ]


class ZCAN_Receive_Data(ctypes.Structure):
    """接收结构 24 字节:帧 + 标志 + 时间戳(微秒)"""

    _fields_ = [
        ("frame", ZCAN_CAN_FRAME),
        ("flags", ctypes.c_uint8),
        ("res", ctypes.c_uint8 * 3),
        ("timestamp", ctypes.c_uint64),
    ]


class ZCAN_CAN_INIT_CONFIG(ctypes.Structure):
    """经典 CAN 通道初始化配置 16 字节"""

    _fields_ = [
        ("acc_code", ctypes.c_uint),
        ("acc_mask", ctypes.c_uint),
        ("reserved", ctypes.c_uint),
        ("filter", ctypes.c_uint8),
        ("timing0", ctypes.c_uint8),
        ("timing1", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),  # 0=正常 1=只听
    ]


class ZCAN_CANFD_INIT_CONFIG(ctypes.Structure):
    """CANFD 通道初始化配置 24 字节"""

    _fields_ = [
        ("acc_code", ctypes.c_uint),
        ("acc_mask", ctypes.c_uint),
        ("abit_timing", ctypes.c_uint8 * 8),  # 仲裁域(属性路径设置波特率时此处不生效)
        ("dbit_timing", ctypes.c_uint8 * 8),  # 数据域
        ("brp", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 3),
    ]


class _INIT_UNION(ctypes.Union):
    _fields_ = [("can", ZCAN_CAN_INIT_CONFIG), ("canfd", ZCAN_CANFD_INIT_CONFIG)]


class ZCAN_CHANNEL_INIT_CONFIG(ctypes.Structure):
    """通道初始化配置 28 字节:can_type(0=CAN 1=CANFD)+ 联合体"""

    _fields_ = [("can_type", ctypes.c_uint), ("config", _INIT_UNION)]


class ZCAN_CHANNEL_STATUS(ctypes.Structure):
    """通道状态 12 字节"""

    _fields_ = [
        ("err_interrupt", ctypes.c_uint),
        ("reg_mode", ctypes.c_uint8),
        ("reg_status", ctypes.c_uint8),
        ("reg_alcapt", ctypes.c_uint8),
        ("reg_txerr", ctypes.c_uint8),
        ("reg_rxerr", ctypes.c_uint8),
        ("reg_ecc", ctypes.c_uint8),
        ("reg_ewlr", ctypes.c_uint8),
        ("reg_rxerr_cnt", ctypes.c_uint8),
    ]


class ZLGCan:
    """zlgcan.dll 封装:打开设备 → 设置属性 → 初始化通道(CANFD 模式)→ 启动 → 收发"""

    # 常见设备类型号(与 kerneldlls/dll_cfg.ini 的 [KERNELDLL_ZLG_CAN] 段对应)
    DEV_TYPES = {
        41: "USBCANFD-200U(脉塔 USBCAN 标配)",
        42: "USBCANFD-100U",
        43: "USBCANFD-400U",
        76: "USBCANFD-200U(新)",
        59: "USBCANFD-800U",
        44: "CANFDCOM-100IE",
        99: "虚拟设备",
        4: "USBCAN2(老 VCI 体系)",
        3: "USBCAN(老 VCI 体系)",
        20: "USBCAN_E(老 VCI 体系)",
        21: "USBCAN_E(老 VCI 体系)",
        31: "USBCAN_4E_U(老 VCI 体系)",
        34: "USBCAN_8E_U(老 VCI 体系)",
    }
    BAUD_MAP = {  # kbps → 属性字符串(CANFD 体系用)
        1000: "1000000", 500: "500000", 250: "250000", 125: "125000",
        100: "100000", 50: "50000", 20: "20000", 10: "10000",
    }
    VCI_TIMING = {  # kbps → (timing0, timing1),16MHz 晶振 SJA1000 标准值(VCI 老模块用)
        1000: (0x00, 0x14), 800: (0x00, 0x16), 500: (0x00, 0x1C),
        250: (0x01, 0x1C), 125: (0x03, 0x1C), 100: (0x04, 0x1C),
        50: (0x09, 0x1C), 20: (0x18, 0x1C), 10: (0x31, 0x1C),
    }
    # CANFD 内核体系(新 ZCAN 设备)类型号;其余视为老 VCI 体系(经典 CAN)
    FD_TYPES = {41, 42, 43, 44, 46, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58,
                59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74,
                75, 76, 77, 78, 79, 99}

    def __init__(self):
        dll_path = os.path.join(exe_dir(), "zlgcan.dll")
        if not os.path.isfile(dll_path):
            raise OSError(f"未找到 {dll_path}")
        # 允许加载同目录依赖 DLL
        try:
            os.add_dll_directory(exe_dir())
        except (AttributeError, OSError):
            pass
        try:
            self.dll = ctypes.WinDLL(dll_path)  # __stdcall
        except OSError as e:
            if "193" in str(e) or "%1" in str(e):
                raise OSError(
                    "zlgcan.dll 是 32 位动态库,当前 Python 是 64 位,无法加载。\n"
                    "请用打包版 exe,或用 32 位 Python 运行(见 启动上位机.bat)。"
                ) from e
            raise
        self._bind()

    # ---- 函数绑定:显式声明全部参数/返回类型 ----

    def _bind(self):
        d = self.dll
        U, P = ctypes.c_uint, ctypes.c_void_p

        # 官方新版 ZCAN 接口签名(已用虚拟设备实测验证):
        # ZCAN_InitCAN 返回「通道句柄」(不是 1/0!实测 262144/6488064),
        # 之后 Start/Reset/ClearBuffer/Transmit/Receive 全部用通道句柄。
        d.ZCAN_OpenDevice.argtypes = [U, U, U]
        d.ZCAN_OpenDevice.restype = U  # 返回设备句柄(非 0),失败 0

        d.ZCAN_CloseDevice.argtypes = [U]
        d.ZCAN_CloseDevice.restype = U  # 1 成功

        d.ZCAN_GetDeviceInf.argtypes = [U, ctypes.POINTER(ZCAN_DEVICE_INFO)]
        d.ZCAN_GetDeviceInf.restype = U

        d.ZCAN_GetAvailableDevices.argtypes = [ctypes.POINTER(ZCAN_DEVICE_INFO), ctypes.POINTER(U)]
        d.ZCAN_GetAvailableDevices.restype = U

        d.ZCAN_InitCAN.argtypes = [U, U, ctypes.POINTER(ZCAN_CHANNEL_INIT_CONFIG)]
        d.ZCAN_InitCAN.restype = U  # 返回通道句柄,失败 0

        d.ZCAN_StartCAN.argtypes = [U]  # 通道句柄,1 参数
        d.ZCAN_StartCAN.restype = U

        d.ZCAN_ResetCAN.argtypes = [U]  # 通道句柄,1 参数
        d.ZCAN_ResetCAN.restype = U

        d.ZCAN_Transmit.argtypes = [U, ctypes.POINTER(ZCAN_Transmit_Data), U]  # 3 参数
        d.ZCAN_Transmit.restype = U  # 返回发送帧数

        d.ZCAN_Receive.argtypes = [U, ctypes.POINTER(ZCAN_Receive_Data), U, U]  # 4 参数
        d.ZCAN_Receive.restype = U  # 返回接收帧数

        d.ZCAN_ClearBuffer.argtypes = [U]  # 通道句柄,1 参数
        d.ZCAN_ClearBuffer.restype = U

        # 注意:本 DLL 的 ZCAN_GetReceiveNum 经调研为 2 参数版本,直接弃用,
        # 接收一律用 ZCAN_Receive(超时 1ms)轮询,避免 __stdcall 参数错位风险。
        d.ZCAN_SetValue.argtypes = [U, ctypes.c_char_p, P]  # 设备句柄 + 属性路径
        d.ZCAN_SetValue.restype = U

        d.ZCAN_GetValue.argtypes = [U, ctypes.c_char_p, P]
        d.ZCAN_GetValue.restype = U

        d.ZCAN_IsDeviceOnLine.argtypes = [U, ctypes.POINTER(U)]
        d.ZCAN_IsDeviceOnLine.restype = U

        d.ZCAN_ReadChannelStatus.argtypes = [U, ctypes.POINTER(ZCAN_CHANNEL_STATUS)]  # 通道句柄,2 参数
        d.ZCAN_ReadChannelStatus.restype = U

    # ---- 基本操作 ----

    def open(self, dev_type, dev_index):
        """打开设备,返回句柄;失败返回 0"""
        return self.dll.ZCAN_OpenDevice(dev_type, dev_index, 0)

    def set_baud(self, handle, baud_kbps):
        """通道初始化之前设置仲裁域/数据域波特率与终端电阻(属性路径为官方拼写)。
        注意:ZLG 库的成功返回为「非零」而非 1(实测 InitCAN 返回 262144)。"""
        abit = self.BAUD_MAP.get(baud_kbps, "1000000")
        results = []
        results.append(self.dll.ZCAN_SetValue(handle, b"0/canfd_abit_baud_rate",
                                              ctypes.c_char_p(abit.encode())))
        results.append(self.dll.ZCAN_SetValue(handle, b"0/canfd_dbit_baud_rate",
                                              ctypes.c_char_p(abit.encode())))
        results.append(self.dll.ZCAN_SetValue(handle, b"0/initenal_resistance",
                                              ctypes.c_char_p(b"1")))
        return all(r != 0 for r in results)

    def init_channel(self, handle, ch, can_type, baud_kbps):
        """初始化通道,返回通道句柄(0=失败)。
        can_type=1 CANFD 模式(新设备)/ 0 经典 CAN(老 VCI 设备);
        VCI 设备的波特率由 timing0/timing1 定时器设定,CANFD 设备已用属性路径设定。"""
        cfg = ZCAN_CHANNEL_INIT_CONFIG()
        if can_type == 1:
            cfg.can_type = 1  # CANFD 模式
            cfg.config.canfd.acc_code = 0x80000000  # 全收(官方默认)
            cfg.config.canfd.acc_mask = 0xFFFFFFFF
        else:
            cfg.can_type = 0  # 经典 CAN 模式
            cfg.config.can.acc_code = 0x80000000
            cfg.config.can.acc_mask = 0xFFFFFFFF
            t0, t1 = self.VCI_TIMING.get(baud_kbps, self.VCI_TIMING[1000])
            cfg.config.can.timing0 = t0
            cfg.config.can.timing1 = t1
        return self.dll.ZCAN_InitCAN(handle, ch, ctypes.byref(cfg))

    def start(self, ch):
        """启动通道(通道句柄,1 参数)"""
        return self.dll.ZCAN_StartCAN(ch) != 0

    def transmit(self, ch, can_id, extd, data8):
        """发送一帧(通道句柄,3 参数),返回是否成功"""
        frame = ZCAN_CAN_FRAME()
        frame.can_id = can_id | (0x80000000 if extd else 0)
        frame.can_dlc = len(data8)
        for i, b in enumerate(data8[:8]):
            frame.data[i] = b
        td = ZCAN_Transmit_Data()
        td.frame = frame
        td.transmit_type = 0  # 正常发送
        return self.dll.ZCAN_Transmit(ch, ctypes.byref(td), 1) != 0

    def receive(self, ch, max_frames=100):
        """批量接收(通道句柄,等待 1ms),返回 [(can_id, extd, dlc, data_bytes), ...]"""
        buf = (ZCAN_Receive_Data * max_frames)()
        n = self.dll.ZCAN_Receive(ch, buf, max_frames, 1)
        out = []
        for i in range(n):
            f = buf[i].frame
            extd = bool(f.can_id & 0x80000000)
            cid = f.can_id & 0x1FFFFFFF
            data = bytes(f.data[: f.can_dlc])
            out.append((cid, extd, f.can_dlc, data))
        return out

    def is_online(self, handle):
        online = ctypes.c_uint(0)
        if self.dll.ZCAN_IsDeviceOnLine(handle, ctypes.byref(online)) != 0:
            return bool(online.value)
        return False

    def clear_buffer(self, ch):
        return self.dll.ZCAN_ClearBuffer(ch)

    def reset(self, ch):
        return self.dll.ZCAN_ResetCAN(ch)

    def close(self, handle):
        return self.dll.ZCAN_CloseDevice(handle)

    @staticmethod
    def dev_type_name(dev_type):
        return ZLGCan.DEV_TYPES.get(dev_type, f"设备类型 {dev_type}")


# =====================================================================
# 四、模拟 CAN(无硬件调试界面用)
# =====================================================================

# 模拟在线电机编号(界面扫描时这些编号会应答)
MOCK_ONLINE_IDS = {1, 2, 3, 4}


class MockCan:
    """模拟 USBCAN 设备:对查询指令回假状态帧,让新旧协议面板都有数据可看"""

    def __init__(self):
        self.handle = 1
        self._lock = threading.Lock()
        self._pending = []          # 待发回复帧 [(id, extd, dlc, data), ...]
        self._pos = [0] * 33        # 各电机模拟角度(0.01°)
        self._speed = [0] * 33      # 各电机模拟速度(0.01dps)
        self._run_ms = 0            # 模拟运行时间
        self.tx_count = 0
        self.rx_count = 0
        self._t0 = time.time()

    # ---- 与 ZLGCan 相同的外部接口(通道句柄风格) ----

    def open(self, dev_type, dev_index):
        return self.handle

    def set_baud(self, handle, baud_kbps):
        return True

    def init_channel(self, handle, ch, can_type, baud_kbps):
        return self.handle  # 模拟:通道句柄 = 设备句柄

    def start(self, ch):
        return True

    def transmit(self, ch, can_id, extd, data8):
        self.tx_count += 1
        if not extd:
            if can_id == 0x300 and data8 and data8[0] == 0x79:
                if len(data8) > 2 and data8[2] == 1:
                    # 0x79 读 ID 的 D6-D7 是回复 CAN 地址 0x240+编号。
                    self._enqueue_reply(0x300, [0x79, 0, 1, 0, 0, 0, 2, 0x24])
                return True
            n = can_id - 0x140
            if 1 <= n <= 32:
                self._mock_respond(n, data8)
        return True

    def receive(self, ch, max_frames=100):
        # 直接同步生成回复帧(界面 50ms 拉取一次,时序足够)
        return self._drain()

    def is_online(self, handle):
        return True

    def clear_buffer(self, ch):
        return 1

    def reset(self, ch):
        return 1

    def close(self, handle):
        return 1

    def list_devices(self):
        return [{"type": 41, "name": "模拟 USBCANFD-200U"}, {"type": 4, "name": "模拟 USBCAN2"}]

    # ---- 模拟回复逻辑 ----

    def _drain(self):
        """生成待发回复帧列表(存于内部队列由 Device 线程拉取,这里直接返回)"""
        with self._lock:
            out = list(self._pending)
            self._pending.clear()
        return out

    def _enqueue_reply(self, can_id, data):
        """回复帧(0x240+编号,与 V4.4 回复编号一致;界面两协议均兼容解析)"""
        with self._lock:
            self._pending.append((can_id, False, 8, bytes(data)))
            self.rx_count += 1

    def _mock_respond(self, n, req):
        """按指令码生成假回复。查询指令回语义帧,控制指令回 0x9A 状态帧。"""
        if n not in MOCK_ONLINE_IDS:
            return
        cmd = req[0]
        rid = 0x240 + n
        if cmd == 0x9A:  # 状态:温度/抱闸/电压/错误码
            self._enqueue_reply(rid, [0x9A, 40, 35, 1, 240, 0, 0, 0])
        elif cmd == 0x9C:  # 状态:温度/力矩电流/速度/角度
            ang = int(self._pos[n] / 100) % 360  # 输出轴角度(°)
            spd = self._speed[n]
            iq = 200 + int(spd / 10)  # 假装随速度变化的电流
            self._enqueue_reply(rid, list(struct.pack("<B b h h h", 0x9C, 40,
                                                      max(-2048, min(2047, iq)),
                                                      max(-32767, min(32767, spd)),
                                                      ang)))
        elif cmd in (0x92, 0x94):  # 角度
            self._enqueue_reply(rid, [cmd] + [0] * 3 + list(struct.pack("<i", self._pos[n])))
        elif cmd in (0x60, 0x61, 0x62):  # 编码器
            enc = int(self._pos[n] * 16384 / 360)
            self._enqueue_reply(rid, [cmd] + [0] * 3 + list(struct.pack("<i", enc)))
        elif cmd == 0x70:  # 模式(D7=0x02 位置环,两代协议通用值)
            self._enqueue_reply(rid, [0x70, 0, 0, 0, 0, 0, 0, 0x02])
        elif cmd == 0x71:  # V2.4 功率
            self._enqueue_reply(rid, [0x71, 0, 0, 0, 500, 0, 0, 0])
        elif cmd == 0x79:  # 旧协议 ID 查询固定走 0x300,此处保留兼容模拟
            if req[2] == 1:
                self._enqueue_reply(0x300, [0x79, 0, 1, 0, 0, 0, (0x240 + n) & 255, (0x240 + n) >> 8])
        elif cmd in (0x30, 0x31, 0x32):  # V4.4 PID 读(单索引,回 float32=1.0)
            self._enqueue_reply(rid, [cmd, req[1], 0, 0] + list(struct.pack("<f", 1.0)))
        elif cmd in (0x42, 0x43):  # 加速度读
            self._enqueue_reply(rid, [cmd, req[1], 0, 0] + list(struct.pack("<i", 500)))
        elif cmd == 0xB1:  # 运行时间
            self._run_ms = int((time.time() - self._t0) * 1000)
            self._enqueue_reply(rid, [0xB1] + [0] * 3 + list(struct.pack("<I", self._run_ms)))
        elif cmd == 0xB2:  # 固件日期
            self._enqueue_reply(rid, [0xB2] + [0] * 3 + list(struct.pack("<I", 20250815)))
        elif cmd == 0xB3:  # 通信中断保护
            self._enqueue_reply(rid, [0xB3] + [0] * 3 + list(struct.pack("<I", 5000)))
        elif cmd in (0xA1, 0xA2, 0xA4, 0xA6, 0xA8, 0xA9, 0x72, 0x73, 0x80, 0x81, 0x77, 0x78, 0x88):
            # 控制/系统指令:更新模拟状态并回 0x9A 状态帧(0x88 使能按手册无回复)
            if cmd == 0xA4:  # 绝对位置:目标 = D4~7 int32
                target = struct.unpack("<i", bytes(req[4:8]))[0]
                self._pos[n] = target
                self._speed[n] = 300
            elif cmd == 0xA8:  # 增量位置
                delta = struct.unpack("<i", bytes(req[4:8]))[0]
                self._pos[n] += delta
                self._speed[n] = 300
            elif cmd == 0xA2:  # 速度:目标 = D4~7 int32
                self._speed[n] = struct.unpack("<i", bytes(req[4:8]))[0]
            elif cmd == 0xA1:  # 力矩电流
                iq = struct.unpack("<h", bytes(req[2:4]))[0]
                self._speed[n] = iq // 20
            elif cmd == 0x80:  # 关闭
                self._speed[n] = 0
            elif cmd == 0x88:  # V2.4 使能:无回复,速度清零
                self._speed[n] = 0
            if cmd != 0x88:
                self._enqueue_reply(rid, [0x9A, 40, 35, 1, 240, 0, 0, 0])


# =====================================================================
# 五、设备管理(接收线程 + 事件队列)
# =====================================================================


class Device:
    """统一管理真机(ZLGCan)/模拟(MockCan),接收线程轮询收帧,事件统一入队"""

    def __init__(self, mock=False):
        self.mock = mock
        self._impl = None  # ZLGCan 或 MockCan 实例
        self._handle = 0
        self._ch = 0
        self._ch_handle = 0  # ZCAN_InitCAN 返回的通道句柄(收发都用它)
        self._running = False
        self._rx_thread = None
        self._events = queue.Queue(maxsize=100000)
        self._lock = threading.Lock()
        self.opened = False
        self._bus_off = False  # 总线无应答(发送持续失败)标记:快速失败,不再逐帧复位重试
        self.status = {
            "opened": False, "mock": mock, "dev_type": 0, "dev_index": 0,
            "ch": 0, "baud": 1000, "online": False, "tx": 0, "rx": 0, "err": "",
        }
        # 调试日志:单次运行一个文件,统一放 exe 同目录「日志\」子文件夹
        # (旧版持续追加同一个 调试日志.txt,多次运行后文本量过大不利于读取;
        #  2026-08-19 改为每次启动新建 调试日志_YYYYMMDD_HHMMSS.txt)
        self._log_fh = None
        try:
            log_dir = os.path.join(exe_dir(), "日志")
            os.makedirs(log_dir, exist_ok=True)
            fname = "调试日志_" + time.strftime("%Y%m%d_%H%M%S") + ".txt"
            self._log_fh = open(os.path.join(log_dir, fname), "a", encoding="utf-8")
            self._log_fh.write("=" * 60 + "\n")
            self._log_fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 上位机启动"
                               f"({'模拟模式' if mock else '真机模式'})\n")
            self._log_fh.flush()
        except OSError:
            pass

    # ---- 事件与日志 ----

    def _event(self, kind, **kw):
        kw["kind"] = kind
        try:
            self._events.put_nowait(kw)
        except queue.Full:
            pass

    def _file_log(self, text):
        """写调试日志.txt(每次写立即落盘,界面崩溃也不丢)"""
        if self._log_fh is None:
            return
        try:
            self._log_fh.write(text + "\n")
            self._log_fh.flush()
        except OSError:
            pass

    def add_log(self, level, msg):
        ts = _now_ms()
        self._event("log", ts=ts, level=level, msg=msg)
        self._file_log(f"{_fmt_ms(ts)} [{level}] {msg}")

    def log_line(self, text):
        """界面摘要同步落盘(2026-08-20):JS addLog 转发,文件日志含帧+摘要便于分析"""
        try:
            self._file_log(text)
        except Exception:
            pass

    def _frame_event(self, dir_, can_id, extd, dlc, data):
        ts = _now_ms()
        hexs = " ".join(f"{b:02X}" for b in data)
        self._event("frame", ts=ts, dir=dir_, id=can_id, extd=extd, dlc=dlc, data=hexs)
        arrow = "→ 发" if dir_ == "tx" else "← 收"
        self._file_log(f"{_fmt_ms(ts)} {arrow} 0x{can_id:03X}  {hexs}")

    # ---- 设备操作 ----

    def list_devices(self):
        """列出可用设备(真机枚举;模拟返回虚拟列表)"""
        if self.mock:
            return [{"type": 41, "name": "模拟 USBCANFD-200U"}, {"type": 4, "name": "模拟 USBCAN2"}]
        try:
            impl = ZLGCan()
        except OSError as e:
            return {"err": str(e)}
        buf = (ZCAN_DEVICE_INFO * 64)()
        count = ctypes.c_uint(64)
        try:
            ret = impl.dll.ZCAN_GetAvailableDevices(buf, ctypes.byref(count))
        except OSError as e:
            return {"err": str(e)}
        if ret != 1:
            return {"err": "枚举设备失败"}
        devices = []
        for i in range(count.value):
            devices.append({"type": buf[i].dev_type,
                            "name": ZLGCan.dev_type_name(buf[i].dev_type)})
        # 没有任何设备/枚举失败时仍给出候选下拉,便于用户手动选择
        # (枚举失败的常见原因:模块为老 VCI 体系,新接口枚举不到)
        if not devices:
            devices = [{"type": 41, "name": ZLGCan.dev_type_name(41)},
                       {"type": 76, "name": ZLGCan.dev_type_name(76)},
                       {"type": 4, "name": ZLGCan.dev_type_name(4)},
                       {"type": 3, "name": ZLGCan.dev_type_name(3)}]
        return devices

    def open_device(self, dev_type, dev_index, ch, baud_kbps):
        """打开设备 + 初始化通道 + 启动接收线程。返回 {ok, msg}(永不抛异常)"""
        with self._lock:
            if self.opened:
                return {"ok": False, "msg": "设备已打开,请先关闭"}
            try:
                return self._open_locked(dev_type, dev_index, ch, baud_kbps)
            except Exception as e:
                self.add_log("err", f"打开设备异常:{type(e).__name__}:{e}")
                return {"ok": False, "msg": f"打开设备异常:{e}"}

    def _open_locked(self, dev_type, dev_index, ch, baud_kbps):
        """open_device 的锁内实现(失败路径全部落盘日志)。
        打开失败时自动回退尝试其他类型(新 CANFD 系 41/76 → 老 VCI 系 4/3),
        兼容脉塔新老两种 USBCAN 模块;初始化按实际打开的体系选 CANFD/经典模式。"""
        try:
            impl = ZLGCan() if not self.mock else MockCan()
        except OSError as e:
            self.add_log("err", f"驱动库加载失败:{e}")
            return {"ok": False, "msg": f"驱动库加载失败:{e}"}
        handle = impl.open(dev_type, dev_index)
        actual = dev_type
        if not handle and not self.mock:
            # 自动回退:先试新 CANFD 系,再试老 VCI 系(USBCAN2/USBCAN)
            for fb in (41, 76, 4, 3):
                if fb == dev_type:
                    continue
                handle = impl.open(fb, dev_index)
                if handle:
                    actual = fb
                    self.add_log("warn", f"设备类型 {dev_type} 打开失败,"
                                         f"已自动回退为类型 {actual} 打开成功")
                    break
                self.add_log("warn", f"设备类型 {fb} 打开失败,继续尝试…")
        if not handle:
            self.add_log("err", "打开设备失败:请检查 USBCAN 模块是否插入、"
                                "是否被官方调试软件占用(请先关闭 MYACTUATOR 调试软件)")
            return {"ok": False, "msg": "打开设备失败:请检查 USBCAN 模块是否插入、"
                                        "是否被官方调试软件占用(请先关闭 MYACTUATOR 调试软件)"}
        can_type = 1 if actual in ZLGCan.FD_TYPES else 0
        ch_handle = 0
        if not self.mock:
            if can_type == 1:
                impl.set_baud(handle, baud_kbps)
            ch_handle = impl.init_channel(handle, ch, can_type, baud_kbps)
            if not ch_handle:
                impl.close(handle)
                self.add_log("err", "通道初始化失败(波特率或通道参数错误)")
                return {"ok": False, "msg": "通道初始化失败(波特率或通道参数错误)"}
            if not impl.start(ch_handle):
                impl.close(handle)
                self.add_log("err", "启动通道失败")
                return {"ok": False, "msg": "启动通道失败"}
        else:
            ch_handle = impl.init_channel(handle, ch, can_type, baud_kbps)
        self._impl = impl
        self._handle = handle
        self._ch = ch
        self._ch_handle = ch_handle
        self.opened = True
        self.status.update(opened=True, mock=self.mock, dev_type=actual,
                           dev_index=dev_index, ch=ch, baud=baud_kbps, err="")
        self._running = True
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()
        mode = "CANFD" if can_type == 1 else "经典CAN"
        name = "模拟设备" if self.mock else f"{ZLGCan.dev_type_name(actual)}(类型 {actual})"
        self.add_log("info", f"已打开 {name},通道 {ch},波特率 {baud_kbps} kbps,{mode} 模式")
        return {"ok": True, "msg": f"已打开 {name}({mode} 模式)"}

    def close_device(self):
        with self._lock:
            if not self.opened:
                return {"ok": True, "msg": "设备未打开"}
            self._running = False
            if self._rx_thread:
                self._rx_thread.join(timeout=2)
                self._rx_thread = None
            try:
                if self._impl is not None:
                    if not self.mock:
                        self._impl.reset(self._ch_handle)
                        self._impl.clear_buffer(self._ch_handle)
                    self._impl.close(self._handle)
            except Exception as e:
                self.add_log("err", f"关闭设备异常:{e}")
            self._impl = None
            self._handle = 0
            self._ch_handle = 0
            self.opened = False
            self.status.update(opened=False, online=False, err="")
            self.add_log("info", "设备已关闭")
            return {"ok": True, "msg": "设备已关闭"}

    def send_frame(self, can_id, extd, data_hex):
        """发帧:解析十六进制串,补 0 到 8 字节。返回 {ok, msg}"""
        if not self.opened:
            self.add_log("warn", f"发送被拒绝(0x{can_id:03X}):设备未打开")
            return {"ok": False, "msg": "设备未打开"}
        try:
            data8 = bytes(int(b, 16) for b in data_hex.replace(",", " ").split())[:8]
        except ValueError:
            return {"ok": False, "msg": "数据格式错误:请输入十六进制字节(空格分隔)"}
        data8 = data8.ljust(8, b"\x00")
        try:
            ok = self._impl.transmit(self._ch_handle, can_id, bool(extd), data8)
        except Exception as e:
            self.add_log("err", f"发送异常:{e}")
            return {"ok": False, "msg": f"发送异常:{e}"}
        if not ok and not self.mock:
            if not self.opened or self._impl is None:
                return {"ok": False, "msg": "设备已关闭"}
            if not self._bus_off:
                # 首次失败常见于控制器 bus-off(总线曾无应答):复位通道后重新启动再重试一次
                self._impl.reset(self._ch_handle)
                self._impl.start(self._ch_handle)
                self._impl.clear_buffer(self._ch_handle)
                self.add_log("warn", f"发送 0x{can_id:03X} 失败,已复位通道并重试…")
                time.sleep(0.05)
                try:
                    ok = self._impl.transmit(self._ch_handle, can_id, bool(extd), data8)
                except Exception as e:
                    self.add_log("err", f"重试发送异常:{e}")
                    return {"ok": False, "msg": f"发送异常:{e}"}
            if not ok:
                self._bus_off = True  # 后续发送直接快速失败,不逐帧复位(总线恢复后自动解除)
                self.add_log("err", "发送失败:总线上无设备应答——请检查电机 24V 是否上电、CAN 线是否接好、波特率是否一致")
                return {"ok": False, "msg": "发送失败:总线上无设备应答——请检查电机 24V 是否上电、CAN 线是否接好、波特率是否一致"}
        else:
            self._bus_off = False  # 发送成功即总线恢复
        self._frame_event("tx", can_id, bool(extd), len(data8), data8)
        self.status["tx"] += 1
        return {"ok": True, "msg": "已发送"}

    # ---- 接收线程 ----

    def _rx_loop(self):
        """轮询收帧(Receive 超时 1ms),帧入事件队列"""
        while self._running:
            try:
                frames = self._impl.receive(self._ch_handle, 100)
                for (cid, extd, dlc, data) in frames:
                    self._frame_event("rx", cid, extd, dlc, data)
                    self.status["rx"] += 1
            except Exception as e:
                self.add_log("err", f"接收异常:{e}")
                time.sleep(0.05)
            time.sleep(0.001)
            # 设备在线状态(每秒检查一次,粗略)
        self._running = False

    # ---- 界面拉取 ----

    def get_pending(self, max_frames=800):
        """界面定时调用:拉取事件(帧 + 日志)+ 状态"""
        frames, logs = [], []
        n = 0
        while n < max_frames:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                break
            if ev["kind"] == "frame":
                frames.append(ev)
            else:
                logs.append(ev)
            n += 1
        online = False
        if self.opened:
            try:
                online = self._impl.is_online(self._handle)
            except Exception:
                online = False
        self.status["online"] = online
        return {"frames": frames, "logs": logs, "status": dict(self.status)}

    def shutdown(self):
        """程序退出清理"""
        self._running = False
        if self._rx_thread:
            self._rx_thread.join(timeout=2)
        if self.opened:
            try:
                if self._impl is not None:
                    self._impl.close(self._handle)
            except Exception:
                pass


# =====================================================================
# 六、js_api 接口类(界面经 window.pywebview.api.xxx() 调用)
# =====================================================================


class Api:
    """js_api:界面经 window.pywebview.api 调用的入口。每个方法打 [桥接] 诊断日志,
    便于从 调试日志.txt 判断桥接是否真正建立(桥不通则日志无 [桥接] 记录)。"""

    def __init__(self, device):
        self.device = device
        self._logged = set()

    def _trace(self, name):
        """每个方法只记一次,避免轮询刷屏"""
        if name not in self._logged:
            self._logged.add(name)
            self.device.add_log("info", f"[桥接] 界面已成功调用 {name}()——桥接正常")

    def list_devices(self):
        self._trace("list_devices")
        return {"ok": True, "data": self.device.list_devices()}

    def open_device(self, dev_type, dev_index, ch, baud_kbps):
        self._trace("open_device")
        return self.device.open_device(int(dev_type), int(dev_index), int(ch), int(baud_kbps))

    def close_device(self):
        self._trace("close_device")
        return self.device.close_device()

    def send_frame(self, can_id, extd, data_hex):
        self._trace("send_frame")
        return self.device.send_frame(int(can_id), int(extd), str(data_hex))

    def get_pending(self):
        self._trace("get_pending")
        return self.device.get_pending()

    def get_status(self):
        self._trace("get_status")
        return {"ok": True, "data": self.device.status}

    # ---- 电机注册表持久化(存 exe 同目录 JSON 文件;WebView2 的 localStorage 在打包版会随用户数据目录丢失)----

    def _registry_path(self):
        """注册表文件路径:打包版 = exe 同目录;开发版 = main.py 同目录"""
        if getattr(sys, "frozen", False):
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "电机注册表.json")

    def get_registry(self):
        self._trace("get_registry")
        path = self._registry_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except (OSError, ValueError):
            data = []   # 首次运行无文件,返回空注册表
        return {"ok": True, "data": data}

    def save_registry(self, data):
        self._trace("save_registry")
        path = self._registry_path()
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data if isinstance(data, list) else [], f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)   # 原子替换,防止写一半断电损坏
            return {"ok": True, "msg": "注册表已保存"}
        except OSError as e:
            return {"ok": False, "msg": f"注册表保存失败:{e}"}


# =====================================================================
# 七、WebView2 运行库检测
# =====================================================================


def check_webview2():
    """检测 WebView2 Runtime(32 位进程自动重定向 WOW6432Node,即 x86 版)"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        )
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def _msgbox(text, title="脉塔电机调试上位机"):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x30)  # 警告图标
    except Exception:
        print(text)


def prompt_install_webview2():
    """缺 WebView2 运行库时中文提示并打开官方下载页"""
    _msgbox(
        "检测到本机未安装 WebView2 运行库(与程序位数一致的 x86 版),"
        "界面无法显示。\n\n点击「确定」后将打开微软官方下载页,"
        "请下载「Evergreen Bootstrapper」并安装,"
        "完成后重新双击运行本程序。"
    )
    try:
        os.startfile("https://developer.microsoft.com/microsoft-edge/webview2/")
    except OSError:
        pass


# =====================================================================
# 八、入口
# =====================================================================


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="脉塔电机调试上位机(新旧双协议)")
    ap.add_argument("--mock", action="store_true", help="模拟模式:不加载硬件,供无硬件调试界面")
    ap.add_argument("--debug", action="store_true", help="开启 WebView2 开发者工具(开发调试用)")
    args = ap.parse_args()

    if webview is None:
        _msgbox("未安装 pywebview 组件,请先运行:\n\npip install pywebview\n\n"
                "(打包版 exe 不受影响)")
        sys.exit(1)

    if not check_webview2():
        prompt_install_webview2()
        sys.exit(1)

    device = Device(mock=args.mock)
    api = Api(device)
    html = resource_path("index.html")
    if not os.path.isfile(html):
        _msgbox(f"未找到界面文件 index.html:\n{html}")
        sys.exit(1)

    webview.create_window(
        "脉塔电机调试上位机",
        html,
        js_api=api,
        width=1460,
        height=920,
        min_size=(1180, 740),
        background_color="#1a1a2e",
    )
    try:
        webview.start(gui="edgechromium", debug=args.debug)
    except Exception as e:
        _msgbox(f"界面启动失败:{e}\n\n"
                "请确认已安装与程序位数一致的 WebView2 运行库,"
                "或改用 --mock 模拟模式排查。")
        sys.exit(1)
    finally:
        device.shutdown()


if __name__ == "__main__":
    main()
