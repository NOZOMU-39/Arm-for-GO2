# -*- coding: utf-8 -*-
"""内存环形缓冲：滚动保留最近 N 秒，供「刚才那一下没录到，倒带捞出来」使用。

容量口径：60 s × 1000 Hz = 60000 条 × 64 B = 3.84 MB/路，双路约 7.7 MB。
按【条数】而不是【字节】限额：1 kHz 下时间与条数一一对应，实现简单且无重分配。
"""
import collections

from .record import RECORD_SIZE


class Ring:
    """单路环形缓冲。存 (t_rx_ns, blob) 二元组，blob 是 64 B 定长记录。"""

    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("capacity 必须为正")
        self.capacity = int(capacity)
        self._buf = collections.deque(maxlen=self.capacity)
        self.total = 0          # 累计写入条数（含已被挤出的）
        self.dropped = 0        # 被挤出的条数（= total - len）

    def append(self, t_rx_ns, blob):
        if len(self._buf) == self.capacity:
            self.dropped += 1
        self._buf.append((int(t_rx_ns), bytes(blob)))
        self.total += 1

    def __len__(self):
        return len(self._buf)

    @property
    def nbytes(self):
        return len(self._buf) * RECORD_SIZE

    def span_s(self):
        """缓冲覆盖的时间跨度（秒）；不足两条返回 0。"""
        if len(self._buf) < 2:
            return 0.0
        return (self._buf[-1][0] - self._buf[0][0]) / 1e9

    def last(self, seconds=None, count=None):
        """取最近 seconds 秒（或 count 条，取先到者）的记录，按时间升序。"""
        if not self._buf:
            return []
        items = list(self._buf)
        if count is not None:
            items = items[-int(count):]
        if seconds is not None:
            cut = items[-1][0] - int(float(seconds) * 1e9)
            items = [it for it in items if it[0] >= cut]
        return items

    def clear(self):
        self._buf.clear()


class MultiRing:
    """按岗位聚合的环形缓冲；容量按【每路】条数算。"""

    def __init__(self, capacity_per_role, roles=()):
        self.capacity = int(capacity_per_role)
        self.roles = {}
        for role in roles:
            self.roles[role] = Ring(self.capacity)

    def ensure(self, role):
        if role not in self.roles:
            self.roles[role] = Ring(self.capacity)
        return self.roles[role]

    def append(self, role, t_rx_ns, blob):
        self.ensure(role).append(t_rx_ns, blob)

    def last(self, role, seconds=None, count=None):
        return self.roles[role].last(seconds=seconds, count=count) if role in self.roles else []

    def stats(self):
        return {
            role: {"n": len(r), "cap": r.capacity, "span_s": round(r.span_s(), 3),
                   "total": r.total, "dropped": r.dropped}
            for role, r in self.roles.items()
        }
