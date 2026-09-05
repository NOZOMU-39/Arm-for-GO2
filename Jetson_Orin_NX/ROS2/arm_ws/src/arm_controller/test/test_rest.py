"""rest 模块单测 —— 上电参考位丢圈判定(2026-09-06; N 正=丢圈, E4 直设语义见模块 docstring)

lost_turns(raw, e4, rest, turn, tol): short = rest − (raw+e4) ≈ N×turn → N
用例: X6 turn=10, 档案 rest=93.56(显示语义)
"""
import pytest

from arm_controller.rest import lost_turns

REST, TURN = 93.56, 10.0


def test_one_turn_lost_e4_zero():
    """丢1圈 e4=0: raw=83.56 → short=10 → N=+1"""
    assert lost_turns(83.56, 0.0, REST, TURN) == 1


def test_two_turns_lost_e4_partial():
    """丢2圈 e4已补1圈(10): raw=73.63 → short=93.56-83.63=9.93 → N=+1(再丢1圈)"""
    assert lost_turns(73.63, 10.0, REST, TURN) == 1


def test_fully_compensated_no_action():
    """丢圈全补(e4=20): raw=73.63 → short=93.56-93.63=-0.07 → N=0 无需校"""
    assert lost_turns(73.63, 20.0, REST, TURN) == 0


def test_overcount_negative():
    """多计1圈: raw=103.56 → short=-10 → N=-1"""
    assert lost_turns(103.56, 0.0, REST, TURN) == -1


def test_valley_spread_within_tol():
    """丢1圈+散布0.3: raw=83.86 → short=9.7 → N=+1 残差0.3 ≤2 ✓"""
    assert lost_turns(83.86, 0.0, REST, TURN) == 1


def test_not_in_reference_returns_none():
    """不在参考位(显示偏3.5°非整圈): raw=90.06 → short=3.5 → round(0.35)=0 残差3.5>2 → None"""
    assert lost_turns(90.06, 0.0, REST, TURN) is None


def test_tolerance_must_be_under_half_turn():
    assert lost_turns(83.56, 0.0, REST, TURN, tol_deg=5.0) is None


def test_bad_archive_returns_none():
    assert lost_turns(83.56, 0.0, REST, 0.0) is None
    assert lost_turns(83.56, 0.0, None, TURN) is None
    assert lost_turns(83.56, 0.0, REST, float("nan")) is None
    assert lost_turns(83.56, float("nan"), REST, TURN) is None


def test_x2_turn_unit():
    """X2 turn≈12.78: 丢1圈差12.8 散布0.1 → N=+1"""
    assert lost_turns(-12.8, 0.0, 0.0, 12.78, tol_deg=1.0) == 1
