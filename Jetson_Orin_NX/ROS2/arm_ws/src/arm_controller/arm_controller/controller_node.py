"""arm_controller 主节点（第 2 步: 档案加载 + 只读轮询 + 状态发布, 监督型不运动）

职责(一期逐步扩展, 此步为骨架):
  - 电机档案: 包 share/config/registry.json(交互界面注册表同构) → registry.load_list
  - 轮询: 独立线程, 逐台 9A/9C/92, 帧间隔由周期推导(见 _frame_interval, 不用无线时代固定 60ms)
  - 状态: rx 回复帧 → parse → state.update_from_parse(越限首触发此步只记日志, 发 0x81 归安全链步骤)
  - 发布: /arm/motor_states(10Hz 全表单条流) + /arm/status(1Hz 总线级)
  - 在线: 2s 无回复 = offline(单台失联仅状态置 error=1; 全失联→LOCKED 锁与 SafetyReset 归下一步)

QoS(Humble 兼容): 无 QoSPresetProfile, 显式 QoSProfile(depth, KEEP_LAST, RELIABLE)。
话题命名与 arm_interfaces 契约一致(/arm/can/tx /arm/can/rx 对接 can_bridge)。
"""
import json
import math
import threading
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from ament_index_python.packages import get_package_share_directory

from arm_interfaces.msg import ArmStatus, CanFrame, MotorState
from arm_protocol import parse as arm_parse

from .registry import load_list
from .state import MotorView, SRC_92, SRC_9C, SRC_NONE, update_from_parse
from .track import V3Tracks

Q = lambda: QoSProfile(depth=100, history=HistoryPolicy.KEEP_LAST,
                       reliability=ReliabilityPolicy.RELIABLE)

# 轮询命令(JS pollAll 同款三帧)
POLL_CMDS = (0x9A, 0x9C, 0x92)
# 在线超时窗(秒): 与情报"CAN 反馈超时 2s 自动软急停"看门狗一致
OFFLINE_AFTER = 2.0
# 状态发布周期(Hz)
STATE_HZ = 10.0
STATUS_HZ = 1.0


def _frame_interval(period_ms: float, n_motors: int, n_cmds: int = len(POLL_CMDS)) -> float:
    """帧间隔(ms) = 周期 × 0.8 ÷ 每轮帧数, 下限 5ms。
    推导(2026-09-05): 无线时代固定 60ms 是防 ESP32 TCP 突发, 本地 CAN 实测单机 5ms 全通、
    总线总命令率 ≤200/s 全通(通信档案); 0.8 系数给"命令插队"预留 20% 周期空档;
    5ms 下限 = V4 实测全通边界留双倍余量。默认 500ms/5 电机 → 15 帧 → 间隔 ~26ms(总额 30/s)。"""
    frames = n_motors * n_cmds
    if frames <= 0:
        return 0.0
    return max(period_ms * 0.8 / frames, 5.0)


class ArmControllerNode(Node):
    def __init__(self):
        super().__init__("arm_controller")
        share = get_package_share_directory("arm_controller")
        self.declare_parameter("registry_file",
                               str(Path(share) / "config" / "registry.json"))
        self.declare_parameter("poll_interval_ms", 500)
        self.declare_parameter("poll_enable", True)

        reg_path = Path(self.get_parameter("registry_file").value).expanduser()
        self.motors = load_list(json.loads(reg_path.read_text(encoding="utf-8")))
        self.get_logger().info(f"档案加载 {len(self.motors)} 台: "
                               + ", ".join(f"#{m['id']}{m['proto']}" for m in self.motors))

        self.views = {m["id"]: MotorView(m["id"]) for m in self.motors}
        self.tracks = V3Tracks()
        self._tx_count = 0
        self._rx_count = 0
        self._last_alarm = ""
        self._stop = threading.Event()

        self.pub_state = self.create_publisher(MotorState, "/arm/motor_states", Q())
        self.pub_status = self.create_publisher(ArmStatus, "/arm/status", Q())
        self.sub_rx = self.create_subscription(CanFrame, "/arm/can/rx", self._on_rx, Q())
        self.pub_tx = self.create_publisher(CanFrame, "/arm/can/tx", Q())

        if self.get_parameter("poll_enable").value:
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
        self.create_timer(1.0 / STATE_HZ, self._publish_states)
        self.create_timer(1.0 / STATUS_HZ, self._publish_status)
        self.get_logger().info(
            f"轮询周期 {self.get_parameter('poll_interval_ms').value}ms, "
            f"帧间隔 {_frame_interval(self.get_parameter('poll_interval_ms').value, len(self.motors)):.0f}ms")

    # ---------------- 轮询线程 ----------------
    def _poll_loop(self):
        period_ms = float(self.get_parameter("poll_interval_ms").value)
        interval = _frame_interval(period_ms, len(self.motors))
        while not self._stop.is_set():
            t0 = time.monotonic()
            for m in self.motors:
                if self._stop.is_set():
                    return
                for cmd in POLL_CMDS:
                    self._send(m["id"], bytes([cmd, 0, 0, 0, 0, 0, 0, 0]), silent=True)
                    time.sleep(interval / 1000.0)
            el = time.monotonic() - t0
            if el < period_ms / 1000.0:
                self._stop.wait((period_ms / 1000.0) - el)

    def _send(self, mid: int, data: bytes, silent: bool = False):
        if not silent:
            self._tx_count += 1
        msg = CanFrame()
        msg.can_id = 0x140 + mid
        msg.dlc = len(data)
        for i, b in enumerate(data):
            msg.data[i] = b
        self.pub_tx.publish(msg)

    # ---------------- rx 回复 ----------------
    def _on_rx(self, msg: rclpy.serialization.Message):
        self._rx_count += 1
        cid = msg.can_id
        n = None
        if 0x140 <= cid <= 0x15F:
            n = cid - 0x140
        elif 0x240 <= cid <= 0x25F:
            n = cid - 0x240
        if not n:
            return
        m = self._motor(n)
        if m is None:
            return
        pr = arm_parse.parse_reply(m["proto"], cid, bytes(msg.data[:msg.dlc]), m)
        if pr is None:
            return
        now = time.time()
        first = update_from_parse(m, self.views[n], pr, self.tracks, now)
        if first:
            # 越限新触发: 安全链步骤起在此"先发 0x81 再报警"; 当前只记日志(监督只读)
            self._last_alarm = f"#{m['name']} 反馈{first}越限(等待安全链接线)"
            self.get_logger().warn(self._last_alarm)

    def _motor(self, mid: int):
        return next((x for x in self.motors if x["id"] == mid), None)

    # ---------------- 发布 ----------------
    def _publish_states(self):
        now = time.time()
        for m in self.motors:
            v = self.views[m["id"]]
            st = MotorState()
            st.motor_id = m["id"]
            st.header.stamp = self.get_clock().now().to_msg()
            st.online = v.last_recv_ts is not None and (now - v.last_recv_ts) < OFFLINE_AFTER
            st.deg = v.last_angle if v.last_angle is not None else float("nan")
            st.vel_dps = v.last_spd if v.last_spd is not None else float("nan")
            st.current_a = v.last_iq if v.last_iq is not None else float("nan")
            st.angle_src = v.angle_src
            if not st.online:
                st.error = 1                      # 本台通信超时
            elif v.alarm["ang"] or v.alarm["spd"] or v.alarm["iq"]:
                st.error = 2                      # 越限报警
            self.pub_state.publish(st)

    def _publish_status(self):
        now = time.time()
        s = ArmStatus()
        s.header.stamp = self.get_clock().now().to_msg()
        s.mode = 1 if self.motors else 0          # MANUAL(只读轮询期) / DISCONNECT
        s.lock_reason = 0
        s.online_ids = [m["id"] for m in self.motors
                        if self.views[m["id"]].last_recv_ts is not None
                        and (now - self.views[m["id"]].last_recv_ts) < OFFLINE_AFTER]
        s.tx_frames = self._tx_count
        s.rx_frames = self._rx_count
        s.last_alarm = self._last_alarm
        self.pub_status.publish(s)

    def destroy_node(self):
        self._stop.set()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ArmControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
