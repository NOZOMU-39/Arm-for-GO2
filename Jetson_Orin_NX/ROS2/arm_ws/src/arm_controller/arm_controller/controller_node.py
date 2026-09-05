"""arm_controller 主节点（第 2 步: 档案加载 + 只读轮询 + 状态发布, 监督型不运动）

职责(一期逐步扩展, 此步为骨架):
  - 电机档案: ~/ROS2/arm_ws/config/registry.json(部署权威副本, 服务变更落盘于此;
    源码 src/arm_controller/config/registry.json 仅种子, 部署时 scp 到部署路径)
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
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from arm_interfaces.msg import ArmStatus, CanFrame, JointCmd, MotorState, RegistryEntry
from arm_interfaces.srv import (GetRegistry, RemoveRegistryEntry, SafetyReset,
                                Scan, SetLimits, SetRegistry, SetZero)
from arm_protocol import parse as arm_parse

from .commands import plan_command
from .registry import RegistryStore, load_list
from .state import MotorView, SRC_92, SRC_9C, SRC_NONE, update_from_parse
from .supervisor import MODE_LOCKED
from .supervisor import ArmSupervisor
from .track import V3Tracks

# NaN = 未设(RegistryEntry 契约: float32 用 NaN 表示未标定/未设, 对应 JSON null)
NAN = float("nan")

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
        self.declare_parameter("registry_file",
                               "~/ROS2/arm_ws/config/registry.json")
        self.declare_parameter("poll_interval_ms", 500)
        self.declare_parameter("poll_enable", True)

        reg_path = Path(self.get_parameter("registry_file").value).expanduser()
        self._reg_path = reg_path
        self.store = RegistryStore(load_list(json.loads(reg_path.read_text(encoding="utf-8"))))
        self.motors = self.store.motors          # 与 store 同一列表对象(服务变更即时可见)
        self.get_logger().info(f"档案加载 {len(self.motors)} 台: "
                               + ", ".join(f"#{m['id']}{m['proto']}" for m in self.motors))

        self.views = {m["id"]: MotorView(m["id"]) for m in self.motors}
        self.tracks = V3Tracks()
        for m in self.motors:
            if m.get("limMinDeg") is None and m.get("limMaxDeg") is None:
                self.get_logger().warn(
                    f"档案警告: #{m['name']} 无角度软限(limMinDeg/limMaxDeg)——运动指令将被拒绝, 请先设限")
        self._tx_count = 0
        self._rx_count = 0
        self._last_alarm = ""
        self._stop = threading.Event()
        self._poll_paused = False                # 设零等独占流程暂停轮询(173e22b 教训)
        self.supervisor = ArmSupervisor(has_motors=bool(self.motors))
        for name, cb in (("safety_reset", self._on_safety_reset),
                         ("get_registry", self._on_get_registry),
                         ("set_registry", self._on_set_registry),
                         ("remove_registry_entry", self._on_remove_entry),
                         ("set_limits", self._on_set_limits),
                         ("scan", self._on_scan),
                         ("set_zero", self._on_set_zero)):
            self.create_service({"safety_reset": SafetyReset, "get_registry": GetRegistry,
                                 "set_registry": SetRegistry,
                                 "remove_registry_entry": RemoveRegistryEntry,
                                 "set_limits": SetLimits, "scan": Scan,
                                 "set_zero": SetZero}[name], name, cb)

        self.pub_state = self.create_publisher(MotorState, "/arm/motor_states", Q())
        self.pub_status = self.create_publisher(ArmStatus, "/arm/status", Q())
        self.sub_rx = self.create_subscription(CanFrame, "/arm/can/rx", self._on_rx, Q())
        self.sub_cmd = self.create_subscription(JointCmd, "/arm/joint_cmd", self._on_joint_cmd, Q())
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
        while not self._stop.is_set():
            if self._poll_paused:
                self._stop.wait(0.2)
                continue
            interval = _frame_interval(period_ms, len(self.motors))
            t0 = time.monotonic()
            for m in list(self.motors):
                if self._stop.is_set():
                    return
                for cmd in POLL_CMDS:
                    if self._poll_paused:
                        break
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
    def _on_rx(self, msg):
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
            # 越限新触发: 先发 0x81 停止保持, 再报警(先停后报; 持续越限不重复触发)
            self._send(m["id"], bytes([0x81, 0, 0, 0, 0, 0, 0, 0]))
            self._last_alarm = f"#{m['name']} 反馈{first}越限, 已发 0x81 停止保持"
            self.get_logger().warn(self._last_alarm)

    def _motor(self, mid: int):
        return next((x for x in self.motors if x["id"] == mid), None)

    # ---------------- JointCmd 命令通道(第 5 步: 意图→限幅校验→帧) ----------------
    def _on_joint_cmd(self, msg: JointCmd):
        m = self._motor(int(msg.motor_id))
        if m is None:
            self.get_logger().warn(f"JointCmd 拒绝: #{msg.motor_id} 不在注册表")
            return
        v = self.views.get(int(msg.motor_id))
        cur_angle = v.last_angle if v and isinstance(v.last_angle, (int, float)) else None
        cur_spd = v.last_spd if v and isinstance(v.last_spd, (int, float)) else None
        if self.supervisor.mode == MODE_LOCKED and msg.kind in (1, 2, 5):
            self.get_logger().error(f"JointCmd 拒绝: 整臂 LOCKED, #{m['name']} 运动指令不放行(仅可停/失能)")
            return
        v3_ready = self.tracks.of(int(msg.motor_id)).lastEnc is not None if m["proto"] == "V3" else True
        ok, why, frame = plan_command(m, v.alarm if v else None, int(msg.kind),
                                      float(msg.deg), float(msg.spd_dps),
                                      cur_angle, cur_spd, v3_ready)
        if not ok:
            self._last_alarm = f"JointCmd 拦截 #{m['name']}: {why}"
            self.get_logger().warn(self._last_alarm)
            return
        self._send(int(msg.motor_id), frame)
        self.get_logger().info(f"JointCmd #{m['name']} kind={msg.kind}: {why}")

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
        online_ids = [m["id"] for m in self.motors
                      if self.views[m["id"]].last_recv_ts is not None
                      and (now - self.views[m["id"]].last_recv_ts) < OFFLINE_AFTER]
        ev = self.supervisor.on_poll(now, online_ids)
        if ev == "LOCKED":
            self._last_alarm = "全失联 ≥2s → 整臂 LOCKED, 需 SafetyReset 复位"
            self.get_logger().error(self._last_alarm)
        s = ArmStatus()
        s.header.stamp = self.get_clock().now().to_msg()
        s.mode = self.supervisor.mode
        s.lock_reason = self.supervisor.lock_reason
        s.online_ids = online_ids
        s.tx_frames = self._tx_count
        s.rx_frames = self._rx_count
        s.last_alarm = self._last_alarm
        self.pub_status.publish(s)

    # ---------------- 服务(注册表 CRUD / 扫描 / 设零) ----------------

    def _persist(self):
        """内存档案变更落盘(controller 为 Jetson 侧权威; 界面侧经二期 gateway 同步)"""
        try:
            self._reg_path.write_text(
                json.dumps(self.motors, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as e:
            self.get_logger().error(f"档案落盘失败: {e}")

    def _ensure_view(self, mid: int):
        if mid not in self.views:
            self.views[mid] = MotorView(mid)

    @staticmethod
    def _entry_to_dict(e: RegistryEntry) -> dict:
        return {
            "id": int(e.id), "name": e.name, "proto": e.proto,
            "gear": e.gear, "dir": int(e.dir),
            "E0": None if e.e0_deg != e.e0_deg else float(e.e0_deg),
            "E0Date": e.e0_date or None,
            "E4": 0.0 if e.e4_deg != e.e4_deg else float(e.e4_deg),
            "limMinDeg": None if e.lim_min_deg != e.lim_min_deg else float(e.lim_min_deg),
            "limMaxDeg": None if e.lim_max_deg != e.lim_max_deg else float(e.lim_max_deg),
            "limMaxSpd": None if e.lim_max_spd != e.lim_max_spd else float(e.lim_max_spd),
            "limMaxIq": None if e.lim_max_iq != e.lim_max_iq else float(e.lim_max_iq),
            "defaultPosDeg": None if e.default_pos_deg != e.default_pos_deg else float(e.default_pos_deg),
        }

    @staticmethod
    def _dict_to_entry(m: dict) -> RegistryEntry:
        e = RegistryEntry()
        e.id = int(m["id"])
        e.name = m.get("name", "")
        e.proto = m["proto"]
        e.gear = float(m.get("gear", 1))
        e.dir = int(m.get("dir", 1))
        e.e0_deg = NAN if m.get("E0") is None else float(m["E0"])
        e.e0_date = m.get("E0Date") or ""
        e.e4_deg = float(m.get("E4") or 0.0)
        e.lim_min_deg = NAN if m.get("limMinDeg") is None else float(m["limMinDeg"])
        e.lim_max_deg = NAN if m.get("limMaxDeg") is None else float(m["limMaxDeg"])
        e.lim_max_spd = NAN if m.get("limMaxSpd") is None else float(m["limMaxSpd"])
        e.lim_max_iq = NAN if m.get("limMaxIq") is None else float(m["limMaxIq"])
        e.default_pos_deg = NAN if m.get("defaultPosDeg") is None else float(m["defaultPosDeg"])
        return e

    def _on_get_registry(self, request, response):
        response.ok = True
        response.rev = self.store.rev
        response.entries = [self._dict_to_entry(m) for m in self.motors]
        return response

    def _on_set_registry(self, request, response):
        try:
            m = self.store.upsert(self._entry_to_dict(request.entry))
            self._ensure_view(m["id"])
            self._persist()
            response.ok = True
            response.msg = f"#{m['id']} 已写入(rev {self.store.rev})"
        except ValueError as e:
            response.ok = False
            response.msg = str(e)
        return response

    def _on_remove_entry(self, request, response):
        mid = int(request.motor_id)
        if self.store.remove(mid):
            self.views.pop(mid, None)
            self._persist()
            response.ok = True
            response.msg = f"#{mid} 配置已删除(电机本身不受影响)"
        else:
            response.ok = False
            response.msg = f"#{mid} 不在注册表中"
        return response

    def _on_set_limits(self, request, response):
        try:
            self.store.set_limits(int(request.motor_id),
                                  None if request.lim_min_deg != request.lim_min_deg else request.lim_min_deg,
                                  None if request.lim_max_deg != request.lim_max_deg else request.lim_max_deg,
                                  None if request.lim_max_spd != request.lim_max_spd else request.lim_max_spd,
                                  None if request.lim_max_iq != request.lim_max_iq else request.lim_max_iq)
            self._persist()
            response.ok = True
            response.msg = f"#{request.motor_id} 限幅已更新(rev {self.store.rev})"
        except ValueError as e:
            response.ok = False
            response.msg = str(e)
        return response

    def _on_scan(self, request, response):
        """逐个 id 发 0x9A 探测(只读)。间隔 40ms(契约踩坑结论: 总线突发防损坏节奏)。"""
        online, diag = [], []
        start = max(1, int(request.start_id))
        end = min(32, int(request.end_id))
        for mid in range(start, end + 1):
            self._send(mid, bytes([0x9A, 0, 0, 0, 0, 0, 0, 0]), silent=True)
            time.sleep(0.04)
            time.sleep(0.03)   # 回复窗口
            now = time.time()
            v = self.views.get(mid)
            if v is not None and v.last_recv_ts is not None and (now - v.last_recv_ts) < OFFLINE_AFTER:
                online.append(mid)
                diag.append(f"#{mid} 在线")
            else:
                diag.append(f"#{mid} 无应答")
        response.ok = True
        response.online_ids = online
        response.diag = " | ".join(diag)
        return response

    def _on_set_zero(self, request, response):
        """设零(契约注释踩坑全集): V3 记 E0 档案(0x92 到位才记, 防记错圈);
        V4 三步 0x80→500ms→0x64→1000ms→0x76→10s 等复位; 期间暂停轮询独占总线。
        服务在 MultiThreadedExecutor 线程内, sleep 不阻塞状态发布。"""
        mid = int(request.motor_id)
        m = self._motor(mid)
        if m is None:
            response.ok = False
            response.msg = f"#{mid} 不在注册表中"
            return response
        v = self.views.get(mid)
        if v is None or not isinstance(v.last_angle, (int, float)):
            response.ok = False
            response.msg = "尚未收到该电机角度反馈, 请稍候再操作"
            return response
        was_paused = self._poll_paused
        self._poll_paused = True
        try:
            if m["proto"] == "V3":
                if v.angle_src != SRC_92:
                    response.ok = False
                    response.msg = "0x92 绝对角尚未到位, 设零可能记错圈数, 请稍候再试"
                    return response
                st = self.tracks.of(mid, m.get("E0"))
                e0 = round(st.rotDeg * 100) / 100
                m["E0"] = e0
                m["E0Date"] = time.strftime("%Y-%m-%d")
                st.E0 = e0
                self._persist()
                v.last_angle = 0.0
                response.ok = True
                response.msg = f"V3 零点已标定: 当前位置=0°, E0={e0}°(档案)"
                response.new_e0 = e0
                response.new_e4 = NAN
                return response
            # V4 三步(节奏 500/1000/10000ms 为 2026-08-26 实测二次修复值)
            self.get_logger().info(f"设零 #{m['name']} 1/3 失能(0x80)")
            self._send(mid, bytes([0x80, 0, 0, 0, 0, 0, 0, 0]))
            time.sleep(0.5)
            self.get_logger().info("设零 2/3 写零点(0x64)")
            self._send(mid, bytes([0x64, 0, 0, 0, 0, 0, 0, 0]))
            time.sleep(1.0)
            self.get_logger().info("设零 3/3 复位(0x76), 电机约 10 秒不响应属正常")
            self._send(mid, bytes([0x76, 0, 0, 0, 0, 0, 0, 0]))
            time.sleep(10.0)
            m["E4"] = 0.0
            m["E0"] = None
            self._persist()
            v.last_angle = 0.0
            v.angle_src = SRC_92
            response.ok = True
            response.msg = "V4 零点已写入固件: 归零并保持=成功; 回到原值=失败请重试"
            response.new_e0 = NAN
            response.new_e4 = 0.0
            return response
        finally:
            if not was_paused:
                self._poll_paused = False

    # ---- SafetyReset 服务(人工复位全局锁) ----
    def _on_safety_reset(self, request, response):
        ok, msg = self.supervisor.reset(self._online_ids_now())
        response.ok = ok
        response.msg = msg
        if ok:
            self.get_logger().info(f"SafetyReset: {msg}")
        else:
            self.get_logger().warn(f"SafetyReset 拒绝: {msg}")
        return response

    def _online_ids_now(self):
        now = time.time()
        return [m["id"] for m in self.motors
                if self.views[m["id"]].last_recv_ts is not None
                and (now - self.views[m["id"]].last_recv_ts) < OFFLINE_AFTER]

    def destroy_node(self):
        self._stop.set()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ArmControllerNode()
    executor = MultiThreadedExecutor()   # 服务回调(设零等长流程 sleep)与 timer 互不阻塞
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():          # 防重复 shutdown 报错(KeyboardInterrupt 路径怪癖)
            rclpy.shutdown()


if __name__ == "__main__":
    main()
