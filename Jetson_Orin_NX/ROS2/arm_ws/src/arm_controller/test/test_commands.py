"""commands 单测 —— 翻译 index.html moveToAngle/sendToAngle/v3Home/v4Home 语义"""
from arm_protocol.bytes_ops import hx

from arm_controller.commands import plan_command

V4 = {"id": 4, "proto": "V44", "gear": 1, "dir": 1, "E4": 30.0, "limMinDeg": -10,
      "limMaxDeg": 10}
V3 = {"id": 1, "proto": "V3", "gear": 6, "dir": -1, "E0": -92.97,
      "limMinDeg": -91, "limMaxDeg": 91}


# ---------- V4 绝对定位 ----------

def test_v4_abs_target_minus_e4():
    """E4=30: 显示 deg=10 → 协议角 out2rot(10-30) = -20 → 帧角度 -2000"""
    ok, why, frame = plan_command(V4, None, 1, 10, 60, cur_angle=5)
    assert ok, why
    assert hx(frame) == "A4 00 3C 00 30 F8 FF FF"   # spd 60 + i32 -2000(LE)


def test_v4_abs_spd_capped_by_lim():
    """spd 200 但 limMaxSpd=50 → 帧速度 50(0x32); deg=30 与 E4 抵消 → 协议角 0"""
    m = dict(V4, limMaxSpd=50.0, limMinDeg=-100, limMaxDeg=100)
    ok, why, frame = plan_command(m, None, 1, 30, 200, cur_angle=0)
    assert ok, why
    assert hx(frame) == "A4 00 32 00 00 00 00 00"


def test_v4_abs_over_limit_blocked():
    ok, why, frame = plan_command(V4, None, 1, 15, 60, cur_angle=5)
    assert not ok and "上限" in why and frame is None


def test_v4_abs_below_limit_blocked():
    ok, why, _ = plan_command(V4, None, 1, -15, 60, cur_angle=5)
    assert not ok and "下限" in why


# ---------- V3 绝对定位 ----------

def test_v3_abs_requires_phase_ready():
    ok, why, _ = plan_command(V3, None, 1, 0, 60, cur_angle=0, v3_ready=False)
    assert not ok and "相位尚未开张" in why


def test_v3_abs_target_e0_plus_out2rot():
    """E0=-92.97 gear6 dir-1: deg=0 → 固件角 = -92.97 + out2rot(0)=0 → -92.97
    速度 spd2rot(60)=|60×6×-1|=360 → u16 0x168; 角度 -9297=0xFFFFDBAF LE AF DB FF FF"""
    ok, why, frame = plan_command(V3, None, 1, 0, 60, cur_angle=0, v3_ready=True)
    assert ok, why
    assert hx(frame) == "A4 00 68 01 AF DB FF FF", hx(frame)


def test_v3_abs_zero_deg_home_equivalent():
    """deg=0 且 E0 已标 → 目标=E0 固件角(v3Home 同款)"""
    ok, why, frame = plan_command(V3, None, 1, 0, 15, cur_angle=0, v3_ready=True)
    assert ok and frame is not None


# ---------- 相对/回家 ----------

def test_rel_needs_current_angle():
    ok, why, _ = plan_command(V4, None, 2, 5, 60, cur_angle=None)
    assert not ok and "当前角度" in why


def test_rel_abs_path():
    """REL +5 当前 3 → 目标 8(绝对路径); (8-30)=-22 → -2200 LE 68 F7 FF FF"""
    ok, why, frame = plan_command(V4, None, 2, 5, 60, cur_angle=3)
    assert ok, why
    assert hx(frame) == "A4 00 3C 00 68 F7 FF FF", hx(frame)


def test_home_no_default_rejected():
    m = dict(V4, defaultPosDeg=None)
    ok, why, _ = plan_command(m, None, 5, 0, 60, cur_angle=1)
    assert not ok and "默认位置" in why


def test_home_uses_default_pos():
    m = dict(V4, defaultPosDeg=-10)
    ok, why, frame = plan_command(m, None, 5, 0, 60, cur_angle=1)
    assert ok, why
    assert hx(frame) == "A4 00 3C 00 60 F0 FF FF", hx(frame)   # (-10-30)=-40 → -4000


# ---------- 安全指令豁免 ----------

def test_stop_hold_direct():
    ok, _, frame = plan_command(V4, {"ang": True, "spd": False, "iq": False}, 3, 0, 0)
    assert ok and frame[0] == 0x81


def test_disable_direct():
    ok, _, frame = plan_command(V4, {"ang": True, "spd": False, "iq": False}, 4, 0, 0)
    assert ok and frame[0] == 0x80


# ---------- 锁定态方向性 ----------

def test_locked_same_dir_blocked():
    st = {"ang": True, "spd": False, "iq": False}
    ok, why, _ = plan_command(V4, st, 1, 15, 60, cur_angle=9)
    assert not ok


def test_locked_reverse_allowed():
    st = {"ang": True, "spd": False, "iq": False}
    ok, why, frame = plan_command(V4, st, 1, 5, 60, cur_angle=9)
    assert ok and frame is not None


def test_unknown_kind_rejected():
    ok, why, _ = plan_command(V4, None, 99, 0, 60)
    assert not ok and "未知指令类型" in why


# ---------- 无软限防呆(2026-09-05 事故教训) ----------

def test_motion_rejected_when_no_angle_limits():
    """双侧无角度软限 → 运动类拒绝(曾被误清限幅致 200° 放行的事故防呆)"""
    m = dict(V4, limMinDeg=None, limMaxDeg=None)
    for kind in (1, 2, 5):
        ok, why, _ = plan_command(m, None, kind, 0, 60, cur_angle=0)
        assert not ok and "软限" in why, (kind, why)


def test_stop_disable_still_allowed_without_limits():
    """无软限时安全指令(停/失能)仍放行"""
    m = dict(V4, limMinDeg=None, limMaxDeg=None)
    assert plan_command(m, None, 3, 0, 0)[0] is True
    assert plan_command(m, None, 4, 0, 0)[0] is True


def test_single_side_limit_allows_motion():
    """只有单侧软限也允许运动(另一侧由机械/其他约束)"""
    m = dict(V4, limMinDeg=None, limMaxDeg=10.0)
    ok, why, frame = plan_command(m, None, 1, 0, 60, cur_angle=0)
    assert ok, why
