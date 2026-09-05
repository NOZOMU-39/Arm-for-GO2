"""limit 模块单测 —— 逐条翻译 proto_core_test.js §8(limitBlock 判定矩阵)/§9(monitorLimit 状态机)"""
import pytest

from arm_controller.limit import limit_block, monitor_limit

# JS §8 同款电机: lim ±10 / limMaxSpd 50 / limMaxIq 5
M = {"id": 4, "proto": "V44", "gear": 1, "dir": 1,
     "limMinDeg": -10, "limMaxDeg": 10, "limMaxSpd": 50, "limMaxIq": 5}


def _alarm(**kw):
    return {"ang": kw.get("ang", False), "spd": kw.get("spd", False), "iq": kw.get("iq", False)}


# ---------- §8 常规越限检查 ----------

def test_in_limit_ok():
    assert limit_block(M, None, {"deg": 5, "spd": 20}) == (True, "")


def test_deg_over_hi_blocked():
    assert limit_block(M, None, {"deg": 15})[0] is False


def test_deg_below_lo_blocked():
    assert limit_block(M, None, {"deg": -15})[0] is False


def test_spd_over_blocked():
    assert limit_block(M, None, {"spd": 80})[0] is False


def test_iq_over_blocked():
    assert limit_block(M, None, {"iq": 8})[0] is False


def test_unset_limits_no_block():
    m = {"id": 9, "proto": "V3"}
    assert limit_block(m, None, {"deg": 9999, "spd": 9999, "iq": 99}) == (True, "")


# ---------- §8 越限锁定态 ----------

def test_locked_same_direction_blocked():
    """锁定(角度)+ 当前位置 9.9 + 同向目标 15 → 拦截"""
    st = _alarm(ang=True)
    ok, why = limit_block(M, st, {"deg": 15}, cur_angle=9.9)
    assert ok is False and "限幅线" in why


def test_locked_reverse_direction_ok():
    """锁定 + 目标回限幅内 5 → 放行(反向恢复)"""
    st = _alarm(ang=True)
    assert limit_block(M, st, {"deg": 5}, cur_angle=9.9) == (True, "")


def test_locked_no_current_angle_blocked():
    """锁定 + 无当前位置 → 拦截(JS §8 删 lastAngle 后拦)"""
    st = _alarm(ang=True)
    assert limit_block(M, st, {"deg": 0}, cur_angle=None)[0] is False


def test_locked_spd_same_dir_blocked():
    """速度锁 + 当前速度同向越限 → 拦; 反向放行"""
    st = _alarm(spd=True)
    m = dict(M, limMaxSpd=50)
    assert limit_block(m, st, {"spd": 30}, cur_spd=60)[0] is False   # cur 60>50 同向
    assert limit_block(m, st, {"spd": -30}, cur_spd=60)[0] is True   # 反向
    assert limit_block(m, st, {"spd": 30}, cur_spd=10)[0] is True    # cur 未越限 → 放行


def test_locked_iq_always_blocked():
    """电流锁无方向: 一律拦"""
    st = _alarm(iq=True)
    assert limit_block(M, st, {"deg": 0}, cur_angle=0)[0] is False


def test_locked_ang_release_but_iq_still_blocks():
    """JS 链语义: 角度方向放行(反向)但电流仍锁 → 仍拦(独立 if, 非 else-if)"""
    st = _alarm(ang=True, iq=True)
    assert limit_block(M, st, {"deg": 5}, cur_angle=9.9)[0] is False


def test_locked_non_deg_cmd_blocked_by_angle_lock():
    """JS else-if: 角度锁 + 指令无 deg 字段(速度/力矩) → 一律拦(why=角度锁定)"""
    st = _alarm(ang=True)
    ok, why = limit_block(M, st, {"spd": 10})
    assert ok is False and "角度锁定" in why


# ---------- §9 monitorLimit 状态机(先 0x81 后报警语义 = first 返回值) ----------

def test_first_violation_returns_first():
    st = _alarm()
    st2, first = monitor_limit(st, M, 25, 0, 0)
    assert first == "角度" and st2["ang"] is True


def test_persist_violation_no_retrigger():
    st = _alarm()
    monitor_limit(st, M, 25, 0, 0)
    _, first = monitor_limit(st, M, 25, 0, 0)
    assert first is None


def test_deadzone_no_unlock():
    """回落到 9(死区 2° 内: lo+2=-8 ~ hi-2=8 之外) → 不解锁"""
    st = _alarm()
    monitor_limit(st, M, 25, 0, 0)
    monitor_limit(st, M, 9, 0, 0)
    assert st["ang"] is True


def test_back_outside_deadzone_unlock():
    monitor_limit(_alarm(), M, 25, 0, 0)
    st = _alarm()
    monitor_limit(st, M, 25, 0, 0)
    monitor_limit(st, M, 7, 0, 0)
    assert st["ang"] is False


def test_speed_iq_trigger_and_release():
    st = _alarm()
    m = dict(M, limMaxSpd=50, limMaxIq=5)
    _, f1 = monitor_limit(st, m, 0, 80, 0)
    assert f1 == "速度" and st["spd"] is True
    # 速度持续越限不重触发; 但电流 10A 首次越限 → 报"电流"(JS: 每维度独立首触发)
    _, f2 = monitor_limit(st, m, 0, 80, 10)
    assert f2 == "电流" and st["iq"] is True
    _, f3 = monitor_limit(st, m, 0, 80, 10)
    assert f3 is None  # 双维度都已锁 → 无新触发
    # 回落解锁: 速度/电流回落即解锁(无死区)
    _, f4 = monitor_limit(st, m, 0, 10, 1)
    assert f4 is None and st["spd"] is False and st["iq"] is False


def test_multi_dimension_first_wins_ang():
    st = _alarm()
    _, first = monitor_limit(st, M, 25, 80, 10)  # 全越
    assert first == "角度"


def test_nan_feedback_ignored():
    """非数反馈不触发(JS NaN 比较恒 False)"""
    st = _alarm()
    _, first = monitor_limit(st, M, float("nan"), 0, 0)
    assert first is None and st["ang"] is False


def test_no_limits_noop():
    st = _alarm()
    _, first = monitor_limit(st, {"id": 9}, 999, 999, 999)
    assert first is None and st == {"ang": False, "spd": False, "iq": False}
