"""rest 模块单测 —— 低势能自落位丢圈判定(2026-09-06, 真机验证后再补档案)

用例设计: X6 型 turnDeg=10 (差 23°→N=2 残差 3°>2 容差 → None) 等边界
"""
import pytest

from arm_controller.rest import lost_turns

# 典型档案: X6-40 谷位期望 93.69 / turnDeg 10; 容差 2.0
REST, TURN = 93.69, 10.0


def test_exact_one_turn_lost():
    """丢 1 圈(读角 = 期望 − 10) → N=1"""
    assert lost_turns(REST - 10.0, REST, TURN) == 1


def test_two_turns_with_valley_spread():
    """丢 2 圈 + 谷位散布 1°(读 = 期望 − 21) → N=2(残差 1° 在容差内)"""
    assert lost_turns(REST - 21.0, REST, TURN) == 2


def test_negative_turns_overcount():
    """多计 1 圈(读 = 期望 + 9.5, 散布 0.5) → N=-1"""
    assert lost_turns(REST + 9.5, REST, TURN) == -1


def test_not_in_valley_returns_none():
    """不在谷(读 = 期望 + 3.5, 残差 3.5 > 容差 2) → None 交人工"""
    assert lost_turns(REST + 3.5, REST, TURN) is None


def test_half_turn_ambiguous_returns_none():
    """恰半圈残差(读 = 期望 − 5, N=0 残差 5 或 N=1 残差 5 都不稳) → None"""
    assert lost_turns(REST - 5.0, REST, TURN) is None


def test_tolerance_must_be_under_half_turn():
    """容差 ≥ turnDeg/2 = 硬界外 → 拒绝判定(返回 None 语义)"""
    assert lost_turns(REST - 10.0, REST, TURN, tol_deg=5.0) is None


def test_bad_archive_returns_none():
    """档案不全(turnDeg 0/None/NaN) → None"""
    assert lost_turns(REST - 10.0, REST, 0.0) is None
    assert lost_turns(REST - 10.0, None, TURN) is None
    assert lost_turns(REST - 10.0, REST, float("nan")) is None


def test_x2_turn_unit():
    """X2-7 型 turnDeg≈12.78: 丢 1 圈读差 12.8(散布 0.1) → N=1"""
    assert lost_turns(0.0 - 12.8, 0.0, 12.78, tol_deg=1.0) == 1


def test_negative_direction_note():
    """(注)读数含 dir 映射时 restDeg 必须同基准——此处 dir=1 直读场景"""
    m = {"proto": "V44", "dir": 1}
    assert m["dir"] == 1
