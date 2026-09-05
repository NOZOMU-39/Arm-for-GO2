"""限幅安全链纯函数（移植自 index.html PROTO_CORE limitBlock/monitorLimit 判定数学）

JS 版副作用(发 0x81/横幅/日志)与全局态(limitAlarm/lastAngle/lastSpd)由 controller 节点持有并执行;
本模块只做"判定"——入参全显式, 出参 (ok, why) 与 (alarm', first), 便于单测与黄金对拍。

语义要点(2026-08-26 用户规定 + 踩坑实证, 勿凭直觉改):
  - 发送前 limitBlock: 越限目标拦截; 越限锁定(limitAlarm)期间"反向(回限幅内)放行, 同向继续拦"——
    方向判定需要当前角度; 无当前角度时锁定态一律拦;
  - 电流锁定无方向语义, 锁定期间一律拦;
  - 运行中 monitorLimit: 角度越限带 2° 死区回落解锁(back 需回到 lo+2~hi-2 内); 速度/电流越限回落即解锁;
  - 首次越限返回 first 维度(由调用方"先发 0x81 再报警"), 持续越限不重复触发。
"""
from __future__ import annotations

NUM = (int, float)


def _num(m: dict, k: str):
    v = m.get(k)
    return v if isinstance(v, NUM) and v == v and v is not None else None


def limit_block(m: dict, alarm: dict | None, vals: dict,
                cur_angle: float | None = None, cur_spd: float | None = None) -> tuple[bool, str]:
    """发送前校验。m=电机档案(含 limMinDeg/limMaxDeg/limMaxSpd/limMaxIq);
    alarm={ang,spd,iq} 越限锁定态(无锁 None/全 False 等价); vals 含 deg/spd/iq 之一或组合;
    返回 (放行?, 原因中文)。"""
    st = alarm if alarm and (alarm.get("ang") or alarm.get("spd") or alarm.get("iq")) else None
    if st is not None:
        # ---- 越限锁定中(JS if/else-if 链逐句直译, 勿自作"优化")----
        block = False
        why = ""
        if st.get("ang") and isinstance(vals.get("deg"), NUM):
            hi = _num(m, "limMaxDeg")
            lo = _num(m, "limMinDeg")
            if isinstance(cur_angle, NUM) and cur_angle == cur_angle:
                # 同向 = 目标方向继续越过限幅线; 目标在限幅内一律放行(反向恢复)
                outward = ((hi is not None and vals["deg"] > cur_angle and vals["deg"] > hi)
                           or (lo is not None and vals["deg"] < cur_angle and vals["deg"] < lo))
                if outward:
                    block = True
                    why = "目标越过限幅线"
            else:
                block = True
                why = "角度锁定且无当前位置"
        elif st.get("ang"):
            block = True
            why = "角度锁定"
        if not block and st.get("spd") and isinstance(vals.get("spd"), NUM):
            lim_spd = _num(m, "limMaxSpd")
            if lim_spd is not None and isinstance(cur_spd, NUM) and cur_spd == cur_spd \
                    and abs(cur_spd) > lim_spd and vals["spd"] * cur_spd > 0:
                block = True
                why = "速度同向越限"
        elif st.get("spd"):
            block = True
            why = "速度锁定"
        if st.get("iq"):
            block = True
            why = "电流锁定(无方向,保持拦截)"
        if block:
            return False, why
        return True, ""
    # ---- 常规越限检查(未锁定) ----
    hi = _num(m, "limMaxDeg")
    lo = _num(m, "limMinDeg")
    if "deg" in vals and isinstance(vals.get("deg"), NUM):
        if lo is not None and vals["deg"] < lo:
            return False, f"目标角度 {vals['deg']}° 低于下限 {lo}°"
        if hi is not None and vals["deg"] > hi:
            return False, f"目标角度 {vals['deg']}° 超过上限 {hi}°"
    if "spd" in vals and isinstance(vals.get("spd"), NUM):
        lim_spd = _num(m, "limMaxSpd")
        if lim_spd is not None and abs(vals["spd"]) > lim_spd:
            return False, f"速度 {abs(vals['spd'])}°/s 超过最大速度 {lim_spd}°/s"
    if "iq" in vals and isinstance(vals.get("iq"), NUM):
        lim_iq = _num(m, "limMaxIq")
        if lim_iq is not None and abs(vals["iq"]) > lim_iq:
            return False, f"电流 {abs(vals['iq'])}A 超过最大电流 {lim_iq}A"
    return True, ""


def monitor_limit(alarm: dict, m: dict, ang, spd=None, iq=None) -> tuple[dict, str | None]:
    """运行中监控(每个回复帧驱动)。alarm 就地更新并返回; 新触发返回维度 "角度"/"速度"/"电流",
    持续越限返回 None。角度 2° 死区回落解锁(lo+2 ~ hi-2 内); 速度/电流回落即解锁。
    非数(None/NaN)反馈不参与越限判定(JS 比较恒 False 语义)。"""
    for k in ("ang", "spd", "iq"):
        if not alarm.get(k):
            alarm[k] = False
    lo = _num(m, "limMinDeg")
    hi = _num(m, "limMaxDeg")
    lim_spd = _num(m, "limMaxSpd")
    lim_iq = _num(m, "limMaxIq")
    first = None

    if lo is not None or hi is not None:
        if isinstance(ang, NUM) and ang == ang:
            over = (hi is not None and ang > hi) or (lo is not None and ang < lo)
            back = (lo is None or ang > lo + 2) and (hi is None or ang < hi - 2)
            if over and not alarm.get("ang"):
                alarm["ang"] = True
                first = "角度"
            elif not over and back and alarm.get("ang"):
                alarm["ang"] = False
    if lim_spd is not None and isinstance(spd, NUM) and spd == spd:
        over = abs(spd) > lim_spd
        if over and not alarm.get("spd"):
            alarm["spd"] = True
            if first is None:
                first = "速度"
        elif not over and alarm.get("spd"):
            alarm["spd"] = False
    if lim_iq is not None and isinstance(iq, NUM) and iq == iq:
        over = abs(iq) > lim_iq
        if over and not alarm.get("iq"):
            alarm["iq"] = True
            if first is None:
                first = "电流"
        elif not over and alarm.get("iq"):
            alarm["iq"] = False
    return alarm, first
