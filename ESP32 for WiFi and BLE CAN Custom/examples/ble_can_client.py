"""
ESP32-S3-RS485-CAN 蓝牙 BLE 外部控制示例（不依赖 HTML）

依赖安装: pip install bleak

用法:
    python ble_can_client.py                          # 交互式命令行
    python ble_can_client.py --send "7B:11 22 33"     # 发送一帧后退出
    python ble_can_client.py --monitor                # 只监听 CAN 接收
    python ble_can_client.py --baudrate 1000          # 设置波特率后进入交互模式

BLE 指令格式 (参考本工程 WS_Bluetooth.cpp):
    0A 0C + 4字节CAN_ID + 1字节帧类型(00标准/01扩展) + 数据 = 发送CAN
    0A 0B + 数据 = 发送RS485
    0A 0D = 查询WiFi IP
    0A 0F = 查询CAN接收缓冲区
    0A 10 + 4字节波特率 = 设置CAN波特率(kbps, big-endian)
"""

import asyncio
import sys
import argparse
from bleak import BleakScanner, BleakClient

# === 和 ESP32 代码一致的 UUID ===
SERVICE_UUID   = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
RX_CHAR_UUID   = "beb5483e-36e1-4688-b7f5-ea07361b26a8"  # 写特征值: PC -> ESP32
TX_CHAR_UUID   = "beb5484a-36e1-4688-b7f5-ea07361b26a8"  # 通知特征值: ESP32 -> PC
DEVICE_NAME    = "ESP32-BLE-CAN"


# ==================== BLE 通信核心 ====================

class CAN_BLE_Client:
    """ESP32 CAN BLE 客户端，封装所有 BLE 通信细节"""

    def __init__(self):
        self.client = None
        self._on_can_data = None  # 回调: func(text)
        # 帧率统计
        self._rx_count = 0
        self._tx_count = 0
        self._stats_time = 0
        self.rx_rate = 0.0
        self.tx_rate = 0.0
        # 自收回显过滤
        self._sent_ids = []

    # ---------- 连接管理 ----------

    @staticmethod
    async def scan_all(timeout=10):
        """扫描附近所有 BLE 设备，返回列表。用于诊断。"""
        print(f"🔍 正在扫描附近所有 BLE 设备 ({timeout}秒)...")
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        if not devices:
            print("❌ 未发现任何 BLE 设备。")
            return []
        print(f"✅ 发现 {len(devices)} 个设备:")
        for i, (addr, (dev, adv)) in enumerate(devices.items()):
            name = dev.name or "(无名称)"
            rssi = adv.rssi if adv else "?"
            print(f"  {i+1}. {name}  [{addr}]  RSSI={rssi} dBm")
        return list(devices.keys())

    async def connect(self, address=None):
        """连接 ESP32 设备。不传 address 则自动扫描。"""
        if address:
            device_addr = address
        else:
            print(f"🔍 正在扫描 {DEVICE_NAME} ...")
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
            if device is None:
                print(f"❌ 未找到 '{DEVICE_NAME}'")
                print("💡 尝试扫描所有设备看看附近有什么:")
                await CAN_BLE_Client.scan_all(timeout=5)
                raise RuntimeError(
                    f"未找到设备 '{DEVICE_NAME}'。\n"
                    "  排查步骤:\n"
                    "  1. ESP32 重新上电（释放旧的 BLE 连接）\n"
                    "  2. 关闭手机/nRF Connect/网页端的蓝牙连接\n"
                    "  3. 确认 Windows 蓝牙已开启\n"
                    "  4. BLE 信号弱时把 ESP32 靠近电脑"
                )
            device_addr = device.address
            print(f"✅ 找到设备: {device.name} ({device_addr})")

        self.client = BleakClient(device_addr)
        await self.client.connect()
        print(f"🔗 已连接到 {DEVICE_NAME}")

        # Windows BLE 需要时间完成服务发现
        print("📋 等待服务发现...")
        await asyncio.sleep(2.0)

        # 直接尝试启用通知（bleak 内部会完成服务发现）
        try:
            await self.client.start_notify(TX_CHAR_UUID, self._on_notification)
            print("📡 通知接收已启用 (服务+特征值自动匹配成功)")
        except Exception as e:
            # 如果失败，打印诊断信息
            services = self.client.services
            available = []
            if services is not None:
                for s in services:
                    available.append(s.uuid)
                    chars = [c.uuid for c in s.characteristics]
                    print(f"  服务 {s.uuid}: 特征值 {chars}")
            print(f"❌ 启用通知失败: {e}")
            print(f"   可用服务: {available}")
            raise

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("🔌 已断开")

    def on_can_data(self, callback):
        """注册 CAN 数据接收回调: callback(text: str)"""
        self._on_can_data = callback

    def _on_notification(self, sender, data):
        """内部: BLE 通知回调"""
        text = data.decode("utf-8", errors="replace").strip()
        if text:
            import time
            now_ms = int(time.time() * 1000)

            # 检查是否为刚发送的帧的回显 (CAN 总线自收)
            is_self_echo = False
            for sent in self._sent_ids[:]:
                if sent['id_str'] in text and sent['data_str'] in text:
                    if now_ms - sent['time'] < 500:
                        is_self_echo = True
                        self._sent_ids.remove(sent)
                        break
                elif now_ms - sent['time'] > 500:
                    self._sent_ids.remove(sent)

            # 统计实际收发帧率 (自收回显不计入)
            if not is_self_echo:
                self._rx_count += 1
            self._update_stats()

            marker = "🔁" if is_self_echo else "📩"
            print(f"\n{marker} {text}")
            if self._on_can_data:
                self._on_can_data(text)

    def _update_stats(self):
        """每秒输出一次帧率统计"""
        import time
        now_ms = int(time.time() * 1000)
        if self._stats_time == 0:
            self._stats_time = now_ms
        elapsed = (now_ms - self._stats_time) / 1000.0
        if elapsed >= 1.0:
            self.rx_rate = self._rx_count / elapsed
            self.tx_rate = self._tx_count / elapsed
            if self._rx_count > 0 or self._tx_count > 0:
                print(f"\n  ⚡ 速率: 发送 {self.tx_rate:.1f} fps | 接收 {self.rx_rate:.1f} fps")
            self._rx_count = 0
            self._tx_count = 0
            self._stats_time = now_ms

    # ---------- CAN 操作 ----------

    async def send_can(self, can_id: int, data: bytes, is_extended: bool = False):
        """
        发送 CAN 帧
        can_id: CAN ID (0x000 ~ 0x7FF 标准帧, 0x00000000 ~ 0x1FFFFFFF 扩展帧)
        data: 数据字节 (1~8 字节, 超过 8 字节 ESP32 自动分帧)
        is_extended: True=扩展帧, False=标准帧
        """
        if can_id > 0x1FFFFFFF:
            raise ValueError(f"CAN ID 超出范围: 0x{can_id:X}")
        if len(data) == 0:
            raise ValueError("数据不能为空")

        frame_type = 1 if is_extended else 0
        cmd = bytes([
            0x0A, 0x0C,
            (can_id >> 24) & 0xFF,
            (can_id >> 16) & 0xFF,
            (can_id >> 8) & 0xFF,
            can_id & 0xFF,
            frame_type,
            *data
        ])
        await self.client.write_gatt_char(RX_CHAR_UUID, cmd, response=False)
        frame_str = "扩展帧" if is_extended else "标准帧"
        hex_data = " ".join(f"0x{b:02X}" for b in data)

        # 记录发送签名用于标记自收回显，并统计发送帧率
        import time
        self._sent_ids.append({
            'id_str': f"0x{can_id:x}",
            'data_str': hex_data,
            'time': int(time.time() * 1000)
        })
        self._tx_count += 1
        self._update_stats()

        print(f"📤 CAN 发送: ID=0x{can_id:X} [{frame_str}] 数据={hex_data}")

    async def set_baudrate(self, rate_kbps: int):
        """设置 CAN 波特率 (25/50/100/125/250/500/800/1000 kbps)"""
        cmd = bytes([0x0A, 0x10, (rate_kbps >> 24) & 0xFF, (rate_kbps >> 16) & 0xFF,
                     (rate_kbps >> 8) & 0xFF, rate_kbps & 0xFF])
        await self.client.write_gatt_char(RX_CHAR_UUID, cmd, response=False)
        print(f"⚙️ CAN 波特率已设置为 {rate_kbps} kbps")

    async def query_can_buffer(self):
        """查询 CAN 接收缓冲区 (0A 0F)"""
        await self.client.write_gatt_char(RX_CHAR_UUID, bytes([0x0A, 0x0F]), response=False)
        print("📤 查询 CAN 缓冲区")

    async def query_wifi_ip(self):
        """查询 WiFi IP (0A 0D)"""
        await self.client.write_gatt_char(RX_CHAR_UUID, bytes([0x0A, 0x0D]), response=False)
        print("📤 查询 WiFi IP")


# ==================== 命令行交互 ====================

def parse_can_send_arg(arg_str):
    """解析 'ID:HEXDATA' 或 'ID:HH HH HH' 格式, 如 '7B:11 22 33' 或 '1F6:AA BB' """
    parts = arg_str.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"格式错误: {arg_str}，应为 'CAN_ID:数据' 如 '7B:11 22 33'")
    can_id = int(parts[0], 16)
    data_hex = parts[1].strip().replace(" ", "")
    if len(data_hex) % 2 != 0:
        raise ValueError(f"数据长度不是偶数: {parts[1]}")
    data = bytes.fromhex(data_hex)
    return can_id, data


async def interactive_mode(client: CAN_BLE_Client):
    """交互式命令行模式"""
    print("\n" + "=" * 60)
    print("  ESP32 CAN BLE 交互式控制台")
    print("  命令:")
    print("    send  <ID>:<数据>      发送 CAN 标准帧 (如: send 7B:11 22 33)")
    print("    sendex <ID>:<数据>     发送 CAN 扩展帧")
    print("    baud  <波特率>         设置 CAN 波特率 (如: baud 1000)")
    print("    query                  查询 CAN 接收缓冲区")
    print("    wifi                   查询 WiFi IP")
    print("    quit / exit            退出")
    print("    短别名: s/se/b/q/ip 与全称等价")
    print("=" * 60 + "\n")

    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("CAN-BLE> ").strip())
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        try:
            if cmd in ("quit", "exit", "q!"):
                break
            elif cmd in ("send", "s"):
                can_id, data = parse_can_send_arg(arg)
                await client.send_can(can_id, data, is_extended=False)
            elif cmd in ("sendex", "se"):
                can_id, data = parse_can_send_arg(arg)
                await client.send_can(can_id, data, is_extended=True)
            elif cmd in ("baud", "b"):
                await client.set_baudrate(int(arg))
            elif cmd in ("query", "q"):
                await client.query_can_buffer()
            elif cmd in ("wifi", "ip"):
                await client.query_wifi_ip()
            else:
                print(f"  ❓ 未知命令: {cmd}")
        except Exception as e:
            print(f"  ❌ 错误: {e}")


# ==================== 主入口 ====================

async def main():
    parser = argparse.ArgumentParser(description="ESP32 CAN BLE 外部控制客户端")
    parser.add_argument("--address", "-a", help="ESP32 BLE MAC 地址 (省略则自动扫描)")
    parser.add_argument("--send", "-s", help="发送 CAN 帧后退出, 格式: 'ID:数据', 如 '7B:11 22 33'")
    parser.add_argument("--extended", "-e", action="store_true", help="结合 --send 使用, 发扩展帧")
    parser.add_argument("--baudrate", "-b", type=int, help="设置 CAN 波特率 (kbps)")
    parser.add_argument("--monitor", "-m", action="store_true", help="仅监听模式, 只接收不发送")
    parser.add_argument("--scan", action="store_true", help="扫描附近所有 BLE 设备后退出 (诊断用)")
    args = parser.parse_args()

    client = CAN_BLE_Client()

    try:
        # 诊断模式: 只扫描
        if args.scan:
            await CAN_BLE_Client.scan_all(timeout=10)
            return

        await client.connect(args.address)

        # 设置波特率 (如果指定)
        if args.baudrate:
            await client.set_baudrate(args.baudrate)
            await asyncio.sleep(0.5)  # 等待生效

        # 单次发送模式
        if args.send:
            can_id, data = parse_can_send_arg(args.send)
            await client.send_can(can_id, data, is_extended=args.extended)
            await asyncio.sleep(1)  # 等待接收可能的回复
            return

        # 仅监听模式
        if args.monitor:
            print("📡 监听模式下按 Ctrl+C 退出...")
            while True:
                await asyncio.sleep(1)

        # 默认: 交互式模式
        await interactive_mode(client)

    except KeyboardInterrupt:
        print("\n👋 用户中断")
    except Exception as e:
        print(f"❌ 错误: {e}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
