"""臂级状态机（纯逻辑, 节点喂在线表与时钟）—— 全失联→LOCKED 判定 + SafetyReset 校验

契约(ArmStatus.msg)档位: 0=DISCONNECT 1=MANUAL 3=READY ... 6=LOCKED。
锁定判定(契约明文): "曾在线集合非空 → 变为 0 台在线" 才算全失联事件, 且连续 ≥2s
(防 USB-CAN 热插拔瞬时误锁; 时间窗与情报 CAN 反馈超时 2s 看门狗一致)。
SafetyReset(SOP 最后一步): 仅 mode=LOCKED 可复位, 且曾在线电机全部重新在线才成功。
"""
from __future__ import annotations

MODE_DISCONNECT = 0
MODE_MANUAL = 1
MODE_LOCKED = 6

LOCK_REASON_NONE = 0
LOCK_REASON_BUS_LOST = 1

OFFLINE_CONFIRM_SEC = 2.0


class ArmSupervisor:
    def __init__(self, has_motors: bool):
        self.mode = MODE_MANUAL if has_motors else MODE_DISCONNECT
        self.lock_reason = LOCK_REASON_NONE
        self.ever_ids: set[int] = set()   # 曾在线电机集合
        self._lost_since = None           # 全失联连续起点(节点时钟秒)

    # ---- 每轮在线表喂入(节点 1Hz) ----
    def on_poll(self, now: float, online_ids: list[int]) -> str | None:
        """返回事件: "LOCKED" / "RECOVERED"(锁解除回 MANUAL) / None。
        锁中不自动恢复(恢复必须 SafetyReset 显式); 仅在全失联持续够长时锁。"""
        ids = set(online_ids)
        self.ever_ids |= ids
        if self.mode == MODE_LOCKED:
            return None
        if self.ever_ids and not ids:
            if self._lost_since is None:
                self._lost_since = now
            elif now - self._lost_since >= OFFLINE_CONFIRM_SEC:
                self.mode = MODE_LOCKED
                self.lock_reason = LOCK_REASON_BUS_LOST
                self._lost_since = None
                return "LOCKED"
        else:
            self._lost_since = None
        return None

    # ---- SafetyReset 服务校验(SOP 软件最后一步) ----
    def reset(self, online_ids: list[int]) -> tuple[bool, str]:
        ids = set(online_ids)
        if self.mode != MODE_LOCKED:
            return False, f"当前档位 {self.mode} 非 LOCKED, 无需复位"
        missing = sorted(self.ever_ids - ids)
        if missing:
            return False, "电机尚未全部恢复在线, 缺: #" + " #".join(map(str, missing)) \
                          + "——请确认供电与接线(对应 SOP 第②步)"
        self.mode = MODE_MANUAL
        self.lock_reason = LOCK_REASON_NONE
        self._lost_since = None
        return True, "已复位回 MANUAL"
