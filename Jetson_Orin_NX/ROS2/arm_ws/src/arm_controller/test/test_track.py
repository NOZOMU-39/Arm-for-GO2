"""track 模块单测 —— 逐条翻译 proto_core_test.js §5(相位最近邻)/§6(显示公式)"""
import math

from arm_controller.track import V3Tracks, phase_of, v3_on_phase, v3_pos_dual


def _enc_of_deg(deg):
    """相位角 → 编码器脉冲(与 JS 测试同构: round(deg/360*65536))"""
    return round(deg / 360 * 65536)


def test_phase_of_roundtrip():
    """0°→0, 90°→16384, 360° 边界回绕"""
    assert phase_of(0) == 0
    assert abs(phase_of(16384) - 90) < 1e-6
    assert phase_of(65535) < 360


def test_v3_on_phase_first_frame():
    """首帧 rotDeg = 相位角本身(编码器量化误差 ~0.003°, 对齐 JS 用 round 断言)"""
    t = V3Tracks()
    st = t.of(1)
    v3_on_phase(st, _enc_of_deg(350))
    assert round(st.rotDeg) == 350
    assert st.lastEnc == _enc_of_deg(350)


def test_v3_on_phase_nearest_neighbor_350_to_10():
    """JS §5: 350° → 回读 10° 应取 370°(最近邻跨 360, 快速反转取错圈回归)"""
    t = V3Tracks()
    st = t.of(1)
    v3_on_phase(st, _enc_of_deg(350))
    v3_on_phase(st, _enc_of_deg(10))
    assert round(st.rotDeg) == 370, st.rotDeg


def test_v3_on_phase_backward_cross():
    """反向跨零: 10° → 回读 350° 应取 -10°(下取整圈)"""
    t = V3Tracks()
    st = t.of(1)
    v3_on_phase(st, _enc_of_deg(10))
    v3_on_phase(st, _enc_of_deg(350))
    assert round(st.rotDeg) == -10, st.rotDeg


def test_v3_pos_dual_none_before_first_enc():
    """lastEnc 未开张 → None(JS null 语义, 界面曾因 null 写卡死)"""
    t = V3Tracks()
    st = t.of(3)
    assert v3_pos_dual(st, {"gear": 6, "dir": -1}) is None


def test_v3_pos_dual_with_e0_dir_gear():
    """JS §6: E0=90 rotDeg=150 gear6 dir-1 → (150-90)/6×(-1) = -10"""
    t = V3Tracks()
    st = t.of(3)
    st.E0 = 90
    st.rotDeg = 150
    st.lastEnc = 1
    assert abs(v3_pos_dual(st, {"gear": 6, "dir": -1}) - (-10)) < 1e-9


def test_v3_pos_dual_e0_none_means_zero():
    """E0 None → 按 0 减(JS: E0===null ? 0 : E0)"""
    t = V3Tracks()
    st = t.of(1)
    st.rotDeg = 100
    st.lastEnc = 1
    assert abs(v3_pos_dual(st, {"gear": 1, "dir": 1}) - 100) < 1e-9


def test_tracks_per_id_isolation():
    """不同电机状态互不串"""
    t = V3Tracks()
    a, b = t.of(1), t.of(2)
    assert a is not b
    assert t.of(1) is a
