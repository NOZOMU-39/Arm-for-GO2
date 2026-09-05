"""单台电机运行时状态 + 回复帧→状态更新（移植 index.html updateMotorState 语义, 2026-09-05 读码直译）

关键语义(勿凭直觉改):
  - 角度=显示语义角(输出轴, 含零点/方向)——V3 经 E0(v3_pos_dual), V4 经 +E4;
  - **只有 0x9C/0x92 帧驱动角度/监控**(JS 如此; 0xA4 等控制回复不更新 lastAngle, 仅日志);
    轮询(9C/92)是唯一角度源——监控粒度=轮询粒度, "控制回复帧喂监控"为二期增强(TODO);
  - V3 pulse: 0x92 已到位时 9C 相位仅兜底(曲线/监控用 92 角, 相位不覆盖——快速反转取错圈坑);
  - V3 0x92: pos==0 跳过; 还原固件角→v3_pos_dual; lastEnc 未就绪(None)跳过本轮;
  - V4 0x92/9C: 显示角 = rot2out(协议角)+E4;
  - 越限新触发返回维度("角度"/"速度"/"电流")——由节点"先发 0x81 再报警"; 持续越限 None;
  - 任何回复帧刷新 last_recv(在线心跳), 在线超时判定归节点(需时钟)。
"""
from __future__ import annotations

from arm_protocol.angles import dir_of, e4_of, rot2out
from .limit import monitor_limit
from .track import V3Tracks, v3_apply_92, v3_on_phase, v3_pos_dual

# 角度来源(MotorState.angle_src 契约): 0=无 1=0x92多圈(主) 2=0x9C(相位/兜底) 3=0x94
SRC_NONE = 0
SRC_92 = 1
SRC_9C = 2


class MotorView:
    """单台电机运行时状态(节点按 id 持有一份; alarm 即 JS limitAlarm[id])"""
    __slots__ = ("mid", "last_angle", "angle_src", "last_spd", "last_iq",
                 "last_recv_ts", "alarm")

    def __init__(self, mid: int):
        self.mid = mid
        self.last_angle = None          # float|None 显示语义角
        self.angle_src = SRC_NONE       # 角度来源
        self.last_spd = None
        self.last_iq = None
        self.last_recv_ts = None        # 节点时钟(epoch 秒), 任何回复帧刷新
        self.alarm = {"ang": False, "spd": False, "iq": False}


def update_from_parse(m: dict, v: MotorView, pr: dict, tracks: V3Tracks,
                      now: float) -> str | None:
    """单帧回复更新状态。pr=parse_reply 输出。返回越限新触发维度(供节点先发 0x81), 无=None。
    9A 帧只心跳不更新角度(JS 同); 其它 cmd(控制回复等)仅心跳。"""
    v.last_recv_ts = now
    cmd = pr["cmd"]
    vals = pr["values"]
    if cmd == 0x9C:
        v.last_spd = rot2out(vals["spd"], m)
        v.last_iq = vals["iq"] * dir_of(m)
        if m["proto"] != "V3":
            a92 = v.last_angle if v.angle_src == SRC_92 and isinstance(v.last_angle, (int, float)) else None
            if a92 is not None:
                return monitor_limit(v.alarm, m, v.last_angle, v.last_spd, v.last_iq)[1]
            a = rot2out(vals["ang"], m) + e4_of(m)
            v.last_angle = a
            v.angle_src = SRC_9C
            return monitor_limit(v.alarm, m, a, v.last_spd, v.last_iq)[1]
        if m.get("v9cSemantics") == "angle":
            a92 = v.last_angle if v.angle_src == SRC_92 and isinstance(v.last_angle, (int, float)) else None
            if a92 is not None:
                return monitor_limit(v.alarm, m, v.last_angle, v.last_spd, v.last_iq)[1]
            a = rot2out(vals["ang"], m)
            v.last_angle = a
            v.angle_src = SRC_9C
            return monitor_limit(v.alarm, m, a, v.last_spd, v.last_iq)[1]
        # V3 pulse: 0x92 已到位 → 相位仅兜底(不覆盖 92 角, 仅监控)
        if v.angle_src == SRC_92 and isinstance(v.last_angle, (int, float)):
            return monitor_limit(v.alarm, m, v.last_angle, v.last_spd, v.last_iq)[1]
        st = tracks.of(m["id"], m.get("E0"))
        v3_on_phase(st, vals["enc"])
        a = v3_pos_dual(st, m)
        if a is None:            # lastEnc 未开张 → 跳过本轮不污染(null 防护)
            return None
        v.last_angle = a
        v.angle_src = SRC_9C
        return monitor_limit(v.alarm, m, a, v.last_spd, v.last_iq)[1]
    if cmd == 0x92:
        if m["proto"] == "V3":
            st = tracks.of(m["id"], m.get("E0"))
            rel = v3_apply_92(st, m, vals["pos"])
            if rel is None:
                return None
            v.last_angle = rel
            v.angle_src = SRC_92
            return monitor_limit(v.alarm, m, rel)[1]
        v.last_angle = rot2out(vals["pos"], m) + e4_of(m)
        v.angle_src = SRC_92
        return monitor_limit(v.alarm, m, v.last_angle)[1]
    return None  # 9A 等: 心跳已刷新, 不驱动角度/监控
