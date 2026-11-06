# -*- coding: utf-8 -*-
"""数据质量位：把设备状态字翻译成“这条数据能不能用”。

用法分两层：
  Quality         单帧质量（这条有没有饱和/是否静止）
  WindowQuality   滚动窗口统计（最近 N 秒里饱和帧占比），用于质量门与录制标记
"""
from dataclasses import dataclass

from .types import decode_status


@dataclass(frozen=True)
class Quality:
    """单帧质量。未识别的状态位一律视为未知，不猜。"""

    acc_sat: bool = False
    gyr_sat: bool = False
    static: bool = False
    utc_unsync: bool = False
    sout_pulse: bool = False
    raw: int = 0

    @classmethod
    def from_status(cls, status):
        flags = set(decode_status(status))
        return cls(
            acc_sat="acc_sat" in flags,
            gyr_sat="gyr_sat" in flags,
            static="static" in flags,
            utc_unsync="utc_unsync" in flags,
            sout_pulse="sout_pulse" in flags,
            raw=status,
        )

    @property
    def saturated(self):
        return self.acc_sat or self.gyr_sat

    @property
    def usable_for_transient(self):
        """瞬态（后坐）分析可用性：饱和了就不能用；静止只是提示，不代表坏。"""
        return not self.saturated


class WindowQuality:
    """最近 window_s 秒的质量统计（滑动，按接收时间裁剪）。"""

    def __init__(self, window_s=10.0):
        self.window_ns = int(window_s * 1e9)
        self._samples = []  # [(t_ns, Quality)]

    def update(self, t_ns, status):
        self._samples.append((t_ns, Quality.from_status(status)))
        cutoff = t_ns - self.window_ns
        if self._samples and self._samples[0][0] < cutoff:
            self._samples = [it for it in self._samples if it[0] >= cutoff]
        return self._samples[-1][1]

    def snapshot(self):
        total = len(self._samples)
        if not total:
            return {"frames": 0, "acc_sat": 0.0, "gyr_sat": 0.0, "static": 0.0}
        acc = sum(1 for _t, q in self._samples if q.acc_sat)
        gyr = sum(1 for _t, q in self._samples if q.gyr_sat)
        sta = sum(1 for _t, q in self._samples if q.static)
        return {
            "frames": total,
            "acc_sat": acc / total,
            "gyr_sat": gyr / total,
            "static": sta / total,
        }
