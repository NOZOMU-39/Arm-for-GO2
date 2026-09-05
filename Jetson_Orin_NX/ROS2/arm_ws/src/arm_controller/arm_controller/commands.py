"""JointCmd 意图 → 帧 纯逻辑（移植 index.html moveToAngle/sendToAngle/v3Home/v4Home 语义）

关键语义(2026-09-05 读码直译, 勿凭直觉改):
  - 目标换算: V3 协议角 = E0 + out2rot(deg)(E0=机械零点固件角档案, 未标 E0 按 0 处理但需相位已开张);
              V4 协议角 = out2rot(deg − E4)(E4=显示偏移);
  - 速度: 传入(默认 60)经 spd2rot = |out2rot| 换算成协议侧; 与 limMaxSpd 取小(契约 JointCmd 注释);
  - 相对增量(REL) = 当前显示角 + deg → 走绝对路径(JS 相对按钮同款);
  - V3 发送前必须相位已开张(lastEnc 就绪)——否则拒绝(发不出正确固件角目标);
  - 发送前 limitBlock(显示语义校验: 目标 deg 与 eff_spd);
  - STOP_HOLD(0x81)/DISABLE(0x80) 为安全指令, 豁免 limitBlock(JS 同: 越限锁定态也能停/失能)。
"""
from __future__ import annotations

from arm_protocol import build as ab
from arm_protocol.angles import e4_of, out2rot, spd2rot
from .limit import limit_block

DEFAULT_SPD = 60.0      # 默认运动速度 °/s(JS sendToAngle/moveToAngle 同款)
HOME_SPD = 60.0         # 回默认位置速度(JS btnMoveDefault 走 moveToAngle 默认 60)


def _eff_spd(spd_dps: float, m: dict) -> float:
    """契约: 请求速度与 limMaxSpd 取小; <=0 用默认"""
    s = spd_dps if spd_dps and spd_dps > 0 else DEFAULT_SPD
    lim = m.get("limMaxSpd")
    if isinstance(lim, (int, float)) and lim > 0:
        s = min(s, float(lim))
    return s


def plan_command(m: dict, alarm: dict | None, kind: int, deg: float, spd_dps: float,
                 cur_angle=None, cur_spd=None, v3_ready: bool = False
                 ) -> tuple[bool, str, bytes | None]:
    """JointCmd 意图 → 帧。返回 (放行?, 原因/说明, 帧或 None)。kind 见 JointCmd.msg 注释。"""
    proto = m["proto"]
    if kind == 3:                                   # STOP_HOLD 停止保持(安全指令豁免)
        return True, "停止保持", bytes([0x81, 0, 0, 0, 0, 0, 0, 0])
    if kind == 4:                                   # DISABLE 失能(安全指令豁免)
        return True, "失能", bytes([0x80, 0, 0, 0, 0, 0, 0, 0])
    if kind == 5:                                   # HOME 回默认位置
        home = m.get("defaultPosDeg")
        if not isinstance(home, (int, float)):
            return False, "未设置默认位置(defaultPosDeg)", None
        deg = float(home)
    elif kind == 1:                                 # ABS_POS
        if not isinstance(deg, (int, float)):
            return False, "ABS_POS 需带目标角度", None
    elif kind == 2:                                 # REL_DELTA
        if not isinstance(deg, (int, float)):
            return False, "REL_DELTA 需带增量角度", None
        if not isinstance(cur_angle, (int, float)):
            return False, "尚无当前角度反馈, 无法计算相对目标", None
        deg = float(cur_angle) + float(deg)
    else:
        return False, f"未知指令类型 {kind}", None

    spd = _eff_spd(spd_dps if kind != 5 else HOME_SPD, m)
    ok, why = limit_block(m, alarm, {"deg": deg, "spd": spd}, cur_angle, cur_spd)
    if not ok:
        return False, why, None

    if proto == "V3":
        if not v3_ready:
            return False, "V3 相位尚未开张(无 9C/0x92 反馈), 拒绝运动", None
        e0 = m.get("E0")
        proto_deg = round(((e0 if isinstance(e0, (int, float)) else 0.0) + out2rot(deg, m)) * 100) / 100
        return True, f"V3 绝对定位 {deg}°(固件角 {proto_deg}°)", \
            ab.v3_pos(0xA4, spd2rot(spd, m), proto_deg)
    proto_deg = round(out2rot(deg - e4_of(m), m) * 100) / 100
    return True, f"V4 绝对定位 {deg}°(协议角 {proto_deg}°)", \
        ab.v44_pos(0xA4, spd2rot(spd, m), proto_deg)
