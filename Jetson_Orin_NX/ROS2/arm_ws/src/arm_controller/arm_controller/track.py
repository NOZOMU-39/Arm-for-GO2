"""V3 相位跟踪（移植自 index.html PROTO_CORE v3TrackOf/v3OnPhase/v3PosDual）

背景: V3 老款(X8/X6-S2) = 转子侧单圈绝对值编码器, 断电丢圈号。
0x9C D6-7 是转子编码器脉冲(16bit 65536/圈), 固件内部多圈角在 0x92(D1-4, 0.01°/LSB)。
策略(界面同源): 0x92 已到位时显示走 0x92; 0x9C 相位仅兜底——最近邻法把相位
连续积分成 rotDeg(固件角), 跳变>180°/采样间 → 取错圈 ±360N(快速反转坑, 0x92 到位即不受影响)。

本模块只放状态容器与纯变换, 谁持有状态(controller 节点)由调用方决定。
"""
from __future__ import annotations

from arm_protocol.angles import dir_of, gear_of
from arm_protocol.bytes_ops import js_round


class V3TrackState:
    """单台 V3 电机的相位跟踪状态(对齐 JS v3Track[id] 对象)"""
    __slots__ = ("E0", "rotDeg", "lastEnc")

    def __init__(self, E0=None):
        self.E0 = E0          # 固件角零点档案(设零时写入); None=未设
        self.rotDeg = 0.0     # 固件角(0x92 校准后=固件读数; 否则由 9C 相位积分维护)
        self.lastEnc = None   # 上一帧编码器原始脉冲(None=首帧)


class V3Tracks:
    """id → V3TrackState 容器(对齐 JS v3Track 全局对象)"""

    def __init__(self):
        self._t: dict[int, V3TrackState] = {}

    def of(self, mid: int, E0=None) -> V3TrackState:
        t = self._t.get(mid)
        if t is None:
            t = self._t[mid] = V3TrackState(E0)
        return t

    def clear(self):
        self._t.clear()


def phase_of(enc: int) -> float:
    """编码器脉冲 → 相位角 0~360°(转子)。JS: ((enc%65536)+65536)%65536/65536*360"""
    return (((enc % 65536) + 65536) % 65536) / 65536 * 360


def v3_on_phase(st: V3TrackState, enc: int) -> float:
    """0x9C 相位帧 → 最近邻积分更新 st.rotDeg(固件角)。
    JS: 首帧 rotDeg=Ep; 之后 rotDeg=round((rotDeg-Ep)/360)*360+Ep
    注: JS Math.round 向 +∞ → js_round。"""
    Ep = phase_of(enc)
    if st.lastEnc is None:
        st.rotDeg = Ep
    else:
        st.rotDeg = js_round((st.rotDeg - Ep) / 360) * 360 + Ep
    st.lastEnc = enc
    return st.rotDeg


def v3_pos_dual(st: V3TrackState, m: dict) -> float | None:
    """显示角(输出轴, 含 E0 零点与方向映射)。lastEnc 未就绪(纯相位没开过张)→ None。
    JS: (rotDeg-(E0===null?0:E0)) / gear * dir"""
    if st.lastEnc is None:
        return None
    e0 = 0.0 if st.E0 is None else st.E0
    return (st.rotDeg - e0) / gear_of(m) * dir_of(m)


def v3_apply_92(st: V3TrackState, m: dict, pos_parse: float) -> float | None:
    """V3 0x92 帧校准(JS updateMotorState 92 分支直译):
    parse 输出的 pos = 固件角/gear×dir(输出轴单位, 未减 E0)——
    先乘回 gear×dir 还原固件角存 st.rotDeg, 再经 v3_pos_dual 减 E0 得真显示角。
    防护: pos==0 不更新(JS: if a!==0); lastEnc 未就绪时 v3_pos_dual=None → 跳过本轮。
    返回显示角, 或 None(跳过——注意 st.rotDeg 已更新, 与 JS 行为一致)。"""
    if pos_parse == 0:
        return None
    st.rotDeg = pos_parse * gear_of(m) * dir_of(m)
    return v3_pos_dual(st, m)
