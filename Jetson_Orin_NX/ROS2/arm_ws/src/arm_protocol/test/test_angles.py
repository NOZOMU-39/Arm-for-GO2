"""angles 模块单测 —— 翻译 proto_core_test.js §7(设零点数学)/§10(键盘限位停)"""
from arm_protocol.angles import (amp2rot, dir_of, e4_of, gear_of, kb_limit_blocked,
                                 out2rot, rot2out, v3_e0_for_x)


# ---------- §7 设零点数学 ----------

def test_v3_e0_for_x_zero():
    """JS: X=0 时 E0 = 当前固件角本身"""
    assert abs(v3_e0_for_x(264.01, 0, {"gear": 6, "dir": -1}) - 264.01) < 0.01


def test_v3_e0_for_x_30_gear6_dir_neg():
    """JS: X=30(dir=-1 gear6) → out2rot(30)=-180 → E0=264.01+180=444.01"""
    assert abs(v3_e0_for_x(264.01, 30, {"gear": 6, "dir": -1}) - 444.01) < 0.01


def test_v4_display_offset_e4():
    """JS: V4 显示 = rot2out(0x92)+E4"""
    m = {"gear": 1, "dir": 1, "E4": 30}
    assert abs(rot2out(50, m) + e4_of(m) - 80) < 1e-9


def test_v4_send_target_minus_e4():
    """JS: V4 发送目标 = out2rot(deg−E4)"""
    m = {"gear": 1, "dir": 1, "E4": 30}
    assert abs(out2rot(10 - 30, m) - (-20)) < 1e-9


def test_e4_of_defaults():
    assert e4_of({}) == 0.0
    assert e4_of({"E4": "x"}) == 0.0
    assert e4_of(None) == 0.0


def test_gear_dir_defaults():
    assert gear_of({}) == 1.0
    assert gear_of({"gear": 0}) == 1.0
    assert dir_of({}) == 1
    assert dir_of({"dir": -1}) == -1
    assert dir_of({"dir": 1}) == 1


def test_amp2rot_only_dir():
    """电流只乘 dir 不乘 gear"""
    assert amp2rot(1.5, {"gear": 6, "dir": -1}) == -1.5


# ---------- §10 键盘限位停 ----------

def test_kb_up_at_hi_stops():
    assert kb_limit_blocked(10, 1, -10, 10) is True


def test_kb_up_below_hi_ok():
    assert kb_limit_blocked(9.9, 1, -10, 10) is False


def test_kb_down_at_lo_stops():
    assert kb_limit_blocked(-10, -1, -10, 10) is True


def test_kb_down_above_lo_ok():
    assert kb_limit_blocked(-9.9, -1, -10, 10) is False


def test_kb_no_angle_ok():
    assert kb_limit_blocked(float("nan"), 1, -10, 10) is False


def test_kb_no_limits_ok():
    assert kb_limit_blocked(100, 1, None, None) is False
