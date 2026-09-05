"""supervisor 状态机单测: 全失联锁定(2s 窗)/瞬时失联不锁/SafetyReset 校验"""
import pytest

from arm_controller.supervisor import (ArmSupervisor, MODE_LOCKED, MODE_MANUAL,
                                       LOCK_REASON_BUS_LOST, OFFLINE_CONFIRM_SEC)


def test_init_with_motors_manual():
    assert ArmSupervisor(has_motors=True).mode == MODE_MANUAL


def test_init_empty_disconnect():
    assert ArmSupervisor(has_motors=False).mode == 0


def test_online_accrues_ever_ids():
    s = ArmSupervisor(True)
    assert s.on_poll(100.0, [1, 2, 3]) is None
    assert s.ever_ids == {1, 2, 3}


def test_no_lock_before_ever_online():
    """从未在线 → 空在线表不锁(空臂不误报, 契约)"""
    s = ArmSupervisor(True)
    assert s.on_poll(100.0, []) is None
    assert s.mode == MODE_MANUAL


def test_lock_requires_2s_confirm():
    """曾在线后全失联: 未满 2s 不锁; 满 2s 锁"""
    s = ArmSupervisor(True)
    s.on_poll(100.0, [1, 2, 3])
    assert s.on_poll(101.0, []) is None          # 开始计时
    assert s.mode == MODE_MANUAL
    assert s.on_poll(101.5, []) is None          # 0.5s 仍不锁
    ev = s.on_poll(103.0, [])                    # 2s 到
    assert ev == "LOCKED" and s.mode == MODE_LOCKED
    assert s.lock_reason == LOCK_REASON_BUS_LOST


def test_transient_loss_no_lock():
    """瞬时失联(热插拔 <2s)恢复 → 不锁、计时清零"""
    s = ArmSupervisor(True)
    s.on_poll(100.0, [1, 2, 3])
    s.on_poll(101.0, [])          # 失联 1s
    s.on_poll(101.5, [1])         # 恢复 → 计时清
    s.on_poll(102.5, [])          # 再失联: 重新计时
    s.on_poll(103.0, [])
    assert s.mode == MODE_MANUAL
    s.on_poll(104.6, [])
    assert s.mode == MODE_LOCKED  # 102.5 起 2.1s


def test_reset_requires_all_ever_motors_back():
    s = ArmSupervisor(True)
    s.on_poll(100.0, [1, 2, 3])
    s.on_poll(101.0, [])
    s.on_poll(103.0, [])          # LOCKED
    ok, msg = s.reset([1, 2])     # 缺 #3
    assert ok is False and "#3" in msg
    ok, msg = s.reset([1, 2, 3])
    assert ok is True and s.mode == MODE_MANUAL


def test_reset_only_in_locked():
    s = ArmSupervisor(True)
    s.on_poll(100.0, [1])
    ok, msg = s.reset([1])
    assert ok is False and "非 LOCKED" in msg


def test_reset_extra_online_motors_fine():
    """复位时比曾在线更多(新电机)也放行"""
    s = ArmSupervisor(True)
    s.on_poll(100.0, [1, 2])
    s.on_poll(101.0, [])
    s.on_poll(103.0, [])
    ok, _ = s.reset([1, 2, 9])
    assert ok is True
