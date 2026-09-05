"""组帧（移植自 PROTO_CORE JS: BUILD_V3 / BUILD_V44）

协议归属: "V3"(X8) 用 v3_* 族; "V44"(X2-7) 用 v44_* 族; "V43"(X6-40) 复用 v44_* 族
  （JS 注释: V4.3 复用 V44 组帧, 仅解析/面板分叉 —— 与界面/上位机结论一致）。
字节截断: JS 字节数组元素隐式 (b & 255)，Python 侧对裸字节参数显式 & 0xFF。
长度: 所有组帧结果 8 字节（pad8 语义）。
"""

from .bytes_ops import p_i16, p_i32, p_u16, p_u32, p_f32, pad8, js_round

# ===================== V3.9（旧款 X8 / X6-S2） =====================


def v3_q(cmd: int) -> bytes:
    """通用只读命令（0x9A 状态等）"""
    return pad8(bytes([cmd & 0xFF]))


def v3_pos(cmd: int, spd_dps: float, deg: float) -> bytes:
    """位置控制: [cmd, 0] + 速度u16(°/s) + 角度i32(0.01°/LSB)"""
    return pad8(bytes([cmd & 0xFF, 0]) + p_u16(spd_dps) + p_i32(deg * 100))


def v3_pos1(dir_: int, spd_dps: float, deg: float) -> bytes:
    """V3 单圈增量 0xA6: dir + 速度u16 + 角度u16(0~359.99°, 超界截 35999) + 0,0"""
    ang = max(0, min(35999, js_round(deg * 100)))
    return pad8(bytes([0xA6, dir_ & 0xFF]) + p_u16(spd_dps) + p_u16(ang) + b"\x00\x00")


def v3_speed(vel_dps: float) -> bytes:
    """速度控制 0xA2: 速度i32(0.01°/s)"""
    return pad8(bytes([0xA2, 0, 0, 0]) + p_i32(vel_dps * 100))


def v3_torque(amp: float) -> bytes:
    """力矩控制 0xA1: 电流i16(0.01A)"""
    return pad8(bytes([0xA1, 0, 0, 0]) + p_i16(amp * 100) + b"\x00\x00")


def v3_pidw(cmd: int, arr) -> bytes:
    """PID 六参数写入（V3 专有）: [cmd, 0] + 6 字节（逐项 clamp 0~255）"""
    six = bytes(max(0, min(255, js_round(x))) for x in list(arr)[:6])
    return pad8(bytes([cmd & 0xFF, 0]) + six)


def v3_acc(cmd: int, idx: int, val: float) -> bytes:
    """加速度设置 0x42/0x43: idx + i32"""
    return pad8(bytes([cmd & 0xFF, idx & 0xFF, 0, 0]) + p_i32(val))


def v3_zero_off(val: float) -> bytes:
    """零偏写入 0x63（实测对旧款无效——保留以对齐 JS，勿用于真机）"""
    return pad8(bytes([0x63, 0, 0, 0]) + p_i32(val))


def v3_mode(m: int) -> bytes:
    """运行模式 0x70"""
    return pad8(bytes([0x70, 0, 0, 0, 0, 0, 0, m & 0xFF]))


def v3_set_id(id_: int) -> bytes:
    """改 ID 0x79 写: 目标 id 在 D7"""
    return pad8(bytes([0x79, 0, 0, 0, 0, 0, 0, id_ & 0xFF]))


def v3_read_id() -> bytes:
    """读 ID 0x79 只读探测: op=1"""
    return pad8(bytes([0x79, 0, 1, 0, 0, 0, 0, 0]))


def v3_b3(ms: int) -> bytes:
    """通信中断保护时间 0xB3: u32 ms"""
    return pad8(bytes([0xB3, 0, 0, 0]) + p_u32(ms))


def v3_b4(idx: int) -> bytes:
    """波特率索引 0xB4"""
    return pad8(bytes([0xB4, 0, 0, 0, 0, 0, 0, idx & 0xFF]))


def v3_b6(on: bool) -> bytes:
    """0xB6 主动回复开/关（V3 语义按界面实现）"""
    return pad8(bytes([0xB6, 0, 0, 0, 0, 0, 0, 1 if on else 0]))


def v3_func(idx: int, val: float) -> bytes:
    """功能控制 0x20: idx + i32"""
    return pad8(bytes([0x20, idx & 0xFF, 0, 0]) + p_i32(val))


# ===================== V4.4（X2-7；V4.3/X6-40 复用本族组帧） =====================


def v44_q(cmd: int) -> bytes:
    return pad8(bytes([cmd & 0xFF]))


def v44_pos(cmd: int, spd_dps: float, deg: float) -> bytes:
    """位置控制: [cmd, 0] + 速度u16 + 角度i32(0.01°/LSB)"""
    return pad8(bytes([cmd & 0xFF, 0]) + p_u16(spd_dps) + p_i32(deg * 100))


def v44_force_pos(tq_pct: int, spd_dps: float, deg: float) -> bytes:
    """带力矩限幅位置 0xA9: 力矩% + 速度u16 + 角度i32"""
    return pad8(bytes([0xA9, tq_pct & 0xFF]) + p_u16(spd_dps) + p_i32(deg * 100))


def v44_speed(tq_max_pct: int, vel_dps: float) -> bytes:
    """速度控制 0xA2（V4）: 力矩上限% + 速度i32"""
    return pad8(bytes([0xA2, 0, tq_max_pct & 0xFF, 0]) + p_i32(vel_dps * 100))


def v44_torque(amp: float) -> bytes:
    """力矩控制 0xA1（V4）: 电流i16 在 D2-D3（与 V3 D4-D5 不同）"""
    return pad8(bytes([0xA1, 0]) + p_i16(amp * 100) + b"\x00\x00\x00\x00")


def v44_ff_spd(spd_dps: float, deg: float) -> bytes:
    """前馈速度位控 0x72: 速度i16 + 角度i32"""
    return pad8(bytes([0x72, 0]) + p_i16(spd_dps) + p_i32(deg * 100))


def v44_ff_tq(tq_pct: int, spd_dps: float, deg: float) -> bytes:
    """前馈力矩位控 0x73: 力矩% + 速度i16 + 角度i32"""
    return pad8(bytes([0x73, tq_pct & 0xFF]) + p_i16(spd_dps) + p_i32(deg * 100))


def v44_pid(cmd: int, idx: int, val: float) -> bytes:
    """PID 写入 0x31 等（V4 用 f32，与 V3 六参数直写不同）"""
    return pad8(bytes([cmd & 0xFF, idx & 0xFF, 0, 0]) + p_f32(val))


def v44_acc(cmd: int, idx: int, val: float) -> bytes:
    """加速度 0x42/0x43: idx + i32"""
    return pad8(bytes([cmd & 0xFF, idx & 0xFF, 0, 0]) + p_i32(val))


def v44_zero_off(val: float) -> bytes:
    """零偏写入 0x63（V4 设零三步中无此步——保留对齐 JS）"""
    return pad8(bytes([0x63, 0, 0, 0]) + p_i32(val))


def v44_mode(m: int) -> bytes:
    """运行模式 0x70"""
    return pad8(bytes([0x70, 0, 0, 0, 0, 0, 0, m & 0xFF]))


def v44_func(idx: int, val: float) -> bytes:
    """功能控制 0x20: idx + i32（V4 索引语义见 errors.V44_FUNC_NAME）"""
    return pad8(bytes([0x20, idx & 0xFF, 0, 0]) + p_i32(val))


def v44_b3(ms: int) -> bytes:
    return pad8(bytes([0xB3, 0, 0, 0]) + p_u32(ms))


def v44_b4(idx: int) -> bytes:
    return pad8(bytes([0xB4, 0, 0, 0, 0, 0, 0, idx & 0xFF]))


def v44_b6(on: bool) -> bytes:
    return pad8(bytes([0xB6, 0, 0, 0, 0, 0, 0, 1 if on else 0]))


# ===================== 协议分发表（对齐 JS BUILD_* 结构） =====================

#: V4.3（X6-40）组帧复用 V44（仅解析/面板分叉）
PROTO_V43_BUILD = "V44"

BUILD_V3 = {
    "Q": v3_q, "POS": v3_pos, "POS1": v3_pos1, "SPEED": v3_speed, "TORQUE": v3_torque,
    "PIDW": v3_pidw, "ACC": v3_acc, "ZERO_OFF": v3_zero_off, "MODE": v3_mode,
    "SETID": v3_set_id, "READID": v3_read_id,
    "B3": v3_b3, "B4": v3_b4, "B6": v3_b6, "FUNC": v3_func,
}

BUILD_V44 = {
    "Q": v44_q, "POS": v44_pos, "FORCE_POS": v44_force_pos, "SPEED": v44_speed,
    "TORQUE": v44_torque, "FF_SPD": v44_ff_spd, "FF_TQ": v44_ff_tq, "PID": v44_pid,
    "ACC": v44_acc, "ZERO_OFF": v44_zero_off, "MODE": v44_mode,
    "FUNC": v44_func, "B3": v44_b3, "B4": v44_b4, "B6": v44_b6,
}


def build_frame(proto: str, op: str, *args) -> bytes:
    """按协议号取表组帧（"V3"→BUILD_V3；"V43"/"V44"→BUILD_V44）"""
    table = BUILD_V3 if proto == "V3" else BUILD_V44
    try:
        fn = table[op]
    except KeyError:
        raise ValueError(f"协议 {proto} 无组帧操作 {op}") from None
    return fn(*args)
