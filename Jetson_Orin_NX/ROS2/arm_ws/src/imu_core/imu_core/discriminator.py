# -*- coding: utf-8 -*-
"""现场核验：两台都认不出来时，靠“谁在动”判别谁是末端。

原理（2026-11-06 实测依据）：
  机械臂自由站立时，末端（枪口端）随臂微动，基座端（X8 定子侧）几乎不动；
  实测角速度 RMS 相差约 20 倍（0.85 dps vs 0.04 dps）。
  所以“角速度 RMS 大的那台是末端”。

边界（必须写清，别越界使用）：
  - **机械臂完全静止时判别必然失败**（两台都很静），此时必须靠花名册兜底；
  - 只做“建议”，不静默改写花名册——用户原话“绝不瞎猜”，
    要采纳得显式 --auto-discriminate 或人工 bind；
  - 判别用的是角速度模长 RMS，与安装朝向无关。
"""
from dataclasses import dataclass, field

ROLE_MUZZLE = "muzzle"
ROLE_BASE = "base"
ROLE_UNASSIGNED = "unassigned"


@dataclass
class DiscriminatorResult:
    roles: dict = field(default_factory=dict)      # key -> role
    confidence: float = 0.0                        # 0~1
    reason: str = "insufficient-data"
    ratios: dict = field(default_factory=dict)     # key -> rms_dps

    @property
    def ok(self):
        return self.reason == "ok"


def motion_stats(samples, key_of=None):
    """把一段样本流聚合成每个设备的运动统计（角速度模长 RMS）。

    samples: 可迭代的 ImuSample
    key_of:  取设备键的函数，默认用 sample.device
    """
    if key_of is None:
        def key_of(s):
            return s.device
    acc = {}
    for s in samples:
        k = key_of(s)
        rec = acc.setdefault(k, {"n": 0, "sum_sq": 0.0, "t0": s.t_rx_ns, "t1": s.t_rx_ns, "peak": 0.0})
        mag = (s.gx * s.gx + s.gy * s.gy + s.gz * s.gz) ** 0.5
        rec["n"] += 1
        rec["sum_sq"] += mag * mag
        rec["t1"] = s.t_rx_ns
        if mag > rec["peak"]:
            rec["peak"] = mag
    out = {}
    for k, rec in acc.items():
        n = rec["n"]
        out[k] = {
            "frames": n,
            "rms_dps": (rec["sum_sq"] / n) ** 0.5 if n else 0.0,
            "peak_dps": rec["peak"],
            "duration_s": (rec["t1"] - rec["t0"]) / 1e9,
        }
    return out


def discriminate(stats, min_ratio=4.0, min_frames=100, min_rms=0.2, floor=0.02):
    """按运动强弱判末端。返回 DiscriminatorResult（roles 只在 ok 时有意义）。

    stats: motion_stats() 的输出
    """
    ratios = {k: v.get("rms_dps", 0.0) for k, v in stats.items()}
    ready = [k for k, v in stats.items() if v.get("frames", 0) >= min_frames]
    if len(ready) < 2:
        return DiscriminatorResult(ratios=ratios, confidence=0.0, reason="insufficient-data")
    ordered = sorted(ready, key=lambda k: ratios[k], reverse=True)
    top, bottom = ordered[0], ordered[-1]
    if ratios[top] < min_rms:
        return DiscriminatorResult(ratios=ratios, confidence=0.0, reason="both-still")
    ratio = ratios[top] / max(ratios[bottom], floor)
    if ratio < min_ratio:
        return DiscriminatorResult(ratios=ratios, confidence=0.0, reason="ambiguous-%0.1fx" % ratio)
    roles = {k: ROLE_BASE for k in ready}
    roles[top] = ROLE_MUZZLE
    confidence = min(1.0, (ratio - min_ratio) / (4.0 * min_ratio) + 0.6)
    return DiscriminatorResult(roles=roles, confidence=confidence, reason="ok", ratios=ratios)
