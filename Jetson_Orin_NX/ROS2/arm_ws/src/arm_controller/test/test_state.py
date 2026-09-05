"""state 模块单测 —— 翻译 index.html updateMotorState 语义(2026-09-05 读码)"""
import pytest

from arm_controller.state import MotorView, SRC_92, SRC_9C, SRC_NONE, update_from_parse
from arm_controller.track import V3Tracks

T0 = 1000.0


def _pr(cmd, **vals):
    return {"cmd": cmd, "values": vals}


def _m(**kw):
    base = {"id": 1, "proto": "V3", "gear": 6, "dir": -1, "E0": -92.97,
            "E4": 0.0, "v9cSemantics": "pulse"}
    base.update(kw)
    return base


# ---------- V3 pulse: 0x92 校准路径(JS: pos→还原固件角→v3PosDual) ----------

def test_v3_92_calibrates_angle_with_e0():
    """parse pos(输出单位未减E0) → rotDeg 还原 → 减 E0 显示角。
    pos=-14.255(固件角-8553/100), gear6 dir-1 → rotDeg=-8553? 例:
    pos = -100 → rotDeg = -100×6×-1 = 600; E0=-92.97 → (600+92.97)/6×(-1) = -115.495"""
    m = _m()
    v = MotorView(1)
    tracks = V3Tracks()
    update_from_parse(m, v, _pr(0x9C, spd=0, iq=0, enc=0), tracks, T0)   # 轮询序 9C→92: 先开张 lastEnc
    first = update_from_parse(m, v, _pr(0x92, pos=-100.0), tracks, T0 + 1)
    assert first is None
    assert v.angle_src == SRC_92
    assert abs(v.last_angle - (-115.495)) < 1e-6
    assert abs(tracks.of(1).rotDeg - 600.0) < 1e-9


def test_v3_92_zero_pos_skipped():
    """pos==0 不更新(JS: if a!==0), 状态保持"""
    m = _m()
    v = MotorView(1)
    v.last_angle = 10.0
    v.angle_src = SRC_92
    update_from_parse(m, v, _pr(0x92, pos=0.0), V3Tracks(), T0)
    assert v.last_angle == 10.0


def test_v3_92_skip_before_any_9c():
    """92 到了但 lastEnc 未开张 → v3PosDual None → 跳过本轮不写(JS 同)"""
    m = _m()
    v = MotorView(1)
    update_from_parse(m, v, _pr(0x92, pos=-100.0), V3Tracks(), T0)
    assert v.last_angle is None and v.angle_src == SRC_NONE


def test_v3_9c_then_92_full_chain():
    """9C 首帧开张相位 → 92 校准覆盖为 SRC_92"""
    m = _m()
    v = MotorView(1)
    tracks = V3Tracks()
    update_from_parse(m, v, _pr(0x9C, spd=0, iq=0, enc=32768), tracks, T0)
    assert v.angle_src == SRC_9C and v.last_angle is not None
    update_from_parse(m, v, _pr(0x92, pos=-100.0), tracks, T0 + 1)
    assert v.angle_src == SRC_92
    assert abs(v.last_angle - (-115.495)) < 1e-6


# ---------- V3 pulse: 9C 相位兜底语义 ----------

def test_v3_9c_phase_not_overwrite_92():
    """0x92 已到位: 9C 相位只喂监控不覆盖角度(快速反转取错圈坑)"""
    m = _m()
    v = MotorView(1)
    tracks = V3Tracks()
    update_from_parse(m, v, _pr(0x9C, spd=0, iq=0, enc=32768), tracks, T0)      # 开张
    update_from_parse(m, v, _pr(0x92, pos=-100.0), tracks, T0 + 1)              # 校准
    ang92 = v.last_angle
    update_from_parse(m, v, _pr(0x9C, spd=50, iq=0, enc=40000), tracks, T0 + 2)  # 相位大幅跳
    assert v.angle_src == SRC_92 and v.last_angle == ang92
    assert v.last_spd is not None  # 速度仍更新


def test_v3_9c_first_frame_sets_angle():
    """V3 pulse 无 92 时: 9C 相位积分出角度"""
    m = _m()
    v = MotorView(1)
    update_from_parse(m, v, _pr(0x9C, spd=0, iq=0, enc=0), V3Tracks(), T0)
    assert v.angle_src == SRC_9C and v.last_angle is not None


# ---------- V4 ----------

def test_v4_92_with_e4():
    m = _m(proto="V44", gear=1, dir=1, E4=30)
    v = MotorView(1)
    update_from_parse(m, v, _pr(0x92, pos=50.0), V3Tracks(), T0)
    assert v.angle_src == SRC_92 and abs(v.last_angle - 80) < 1e-6


def test_v4_9c_fallback_when_no_92():
    m = _m(proto="V44", gear=1, dir=1, E4=0)
    v = MotorView(1)
    update_from_parse(m, v, _pr(0x9C, spd=20, iq=0, ang=-90), V3Tracks(), T0)
    assert v.angle_src == SRC_9C and abs(v.last_angle - (-90)) < 1e-6
    assert abs(v.last_spd - 20) < 1e-6


def test_v4_9c_uses_92_cache():
    """V4 9C: 0x92 已到位 → 角度用 92 缓存(不覆盖), 速度电流仍更新"""
    m = _m(proto="V44", gear=1, dir=1)
    v = MotorView(1)
    update_from_parse(m, v, _pr(0x92, pos=10.0), V3Tracks(), T0)
    update_from_parse(m, v, _pr(0x9C, spd=-5, iq=1, ang=999), V3Tracks(), T0 + 1)
    assert v.angle_src == SRC_92 and v.last_angle == 10.0
    assert v.last_spd == -5.0 and v.last_iq == 1.0


# ---------- 心跳/9A ----------

def test_9a_only_heartbeat():
    m = _m()
    v = MotorView(1)
    v.last_angle = 3.0
    update_from_parse(m, v, _pr(0x9A, temp=27, brake="已锁定", volt=23.7, err=0), V3Tracks(), T0)
    assert v.last_recv_ts == T0
    assert v.last_angle == 3.0 and v.angle_src == SRC_NONE


def test_unknown_cmd_heartbeat_only():
    m = _m()
    v = MotorView(1)
    update_from_parse(m, v, _pr(0xA4, temp=27, iq=1, spd=0, enc=100), V3Tracks(), T0)
    assert v.last_recv_ts == T0
    assert v.last_angle is None


# ---------- 越限触发(经 monitor) ----------

def test_limit_first_trigger_reported():
    m = _m(proto="V44", gear=1, dir=1, limMinDeg=-10, limMaxDeg=10)
    v = MotorView(1)
    update_from_parse(m, v, _pr(0x92, pos=25.0), V3Tracks(), T0)
    assert v.alarm["ang"] is True      # 越限触发由第一帧 92 即报


def test_limit_trigger_on_9c_first():
    """首次越限由 9C 兜底路径触发时返回"角度"给节点发 0x81"""
    m = _m(proto="V44", gear=1, dir=1, limMinDeg=-10, limMaxDeg=10)
    v = MotorView(1)
    first = update_from_parse(m, v, _pr(0x9C, spd=0, iq=0, ang=30), V3Tracks(), T0)
    assert first == "角度" and v.alarm["ang"] is True
