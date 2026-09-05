"""电机档案（registry）: 规范化/校验/加载，字段与交互界面注册表 JSON 同构

界面注册表字段（机械臂注册表.json 实证 2026-09-05）:
  id 1~32 | name str | proto V3/V43/V44 | note str(可选)
  gear 减速比(缺省/非法→1) | dir -1 反转否则 1
  E0 V3 零点档案(固件角,数值或 None) | E0Date str|None | v9cSemantics "pulse"/"angle"|None
  limMinDeg/limMaxDeg 软件限位(°|None=未设) | limMaxSpd/limMaxIq 可选(°|A,None=未设)
  E4 V4 显示偏移(缺省 0) | defaultPosDeg 默认位置(°|None)
规范化失败抛 ValueError(中文); 不存在的键保持原样由调用方承载。
"""
from __future__ import annotations

PROTOS = ("V3", "V43", "V44")

_FLOAT_FIELDS = ("gear", "dir", "E0", "E4", "limMinDeg", "limMaxDeg",
                 "limMaxSpd", "limMaxIq", "defaultPosDeg")


def _opt_num(m: dict, k: str):
    v = m.get(k)
    return v if isinstance(v, (int, float)) and v == v else None  # NaN → None


def normalize(raw: dict) -> dict:
    """单台电机规范化 → dict(键同构界面注册表对象)。非法值按 JS 语义回落默认。"""
    if not isinstance(raw, dict):
        raise ValueError("档案条目必须为对象")
    mid = raw.get("id")
    if not isinstance(mid, int) or not (1 <= mid <= 32):
        raise ValueError(f"电机 id 非法: {mid!r}(须 1~32 整数)")
    proto = raw.get("proto")
    if proto not in PROTOS:
        raise ValueError(f"电机#{mid} proto 非法: {proto!r}(须 V3/V43/V44)")
    out = {
        "id": mid,
        "name": str(raw.get("name") or f"电机{mid}"),
        "proto": proto,
        "gear": 1.0,
        "dir": 1,
        "E0": None,
        "E0Date": None,
        "limMinDeg": None,
        "limMaxDeg": None,
        "limMaxSpd": None,
        "limMaxIq": None,
        "E4": 0.0,
        "defaultPosDeg": None,
    }
    for k, v in raw.items():
        if k in ("id", "name", "proto"):
            continue
        if k == "note":
            out["note"] = str(v)
            continue
        if k == "v9cSemantics":
            out["v9cSemantics"] = v if v in ("pulse", "angle") else None
            continue
        if k == "E0Date":
            out["E0Date"] = str(v) if v else None
            continue
        if k in _FLOAT_FIELDS:
            x = _opt_num(raw, k)
            if x is None:
                continue  # 保持默认
            if k == "gear":
                out["gear"] = float(x) if x > 0 else 1.0   # JS gearOf: >0 否则 1
            elif k == "dir":
                out["dir"] = -1 if x == -1 else 1          # JS dirOf: ===-1 → -1 否则 1
            elif k == "E4":
                out["E4"] = float(x)                        # JS e4Of: 数值有限 → 原值
            elif k == "E0":
                out["E0"] = float(x) if x == x else None
            else:
                out[k] = float(x)
    return out


def load_list(items: list) -> list:
    """整表加载: 逐台 normalize, id 重复报错。"""
    seen = set()
    out = []
    for it in items:
        m = normalize(it)
        if m["id"] in seen:
            raise ValueError(f"电机 id {m['id']} 重复")
        seen.add(m["id"])
        out.append(m)
    return out


def by_id(motors: list, mid: int) -> dict | None:
    return next((m for m in motors if m["id"] == mid), None)


class RegistryStore:
    """注册表运行时容器(节点持有权威副本; 变更带 rev 版本号, 供前端缓存比对)。

    upsert 校验与 SetRegistry.srv 契约一致: id 1~32 / proto 白名单 / gear>0 / dir±1 /
    limMin<limMax(NaN=未设放行)。remove 仅删配置不动电机。set_limits 全量替换(清理=置 NaN)。
    """

    def __init__(self, motors: list | None = None):
        self.motors = load_list(motors) if motors else []
        self.rev = 0

    def get_all(self) -> list:
        return list(self.motors)

    def get(self, mid: int) -> dict | None:
        return by_id(self.motors, mid)

    def upsert(self, entry: dict) -> dict:
        """写入/更新一台(全量覆盖)。先经 normalize(非法字段回落默认), 再查 limMin<limMax。"""
        m = normalize(entry)
        self._check_limits(m)
        old = by_id(self.motors, m["id"])
        if old is None:
            self.motors.append(m)
        else:
            self.motors[self.motors.index(old)] = m
        self.rev += 1
        return m

    def remove(self, mid: int) -> bool:
        old = by_id(self.motors, mid)
        if old is None:
            return False
        self.motors.remove(old)
        self.rev += 1
        return True

    def set_limits(self, mid: int, lim_min_deg=None, lim_max_deg=None,
                   lim_max_spd=None, lim_max_iq=None) -> dict:
        """全量替换某台限幅(None=未设即清除该项)。校验 limMin<limMax 才生效。"""
        m = by_id(self.motors, mid)
        if m is None:
            raise ValueError(f"电机 #{mid} 不在注册表中")
        for k, v in (("limMinDeg", lim_min_deg), ("limMaxDeg", lim_max_deg),
                     ("limMaxSpd", lim_max_spd), ("limMaxIq", lim_max_iq)):
            m[k] = float(v) if v is not None and v == v else None   # NaN → None
        self._check_limits(m)
        self.rev += 1
        return m

    @staticmethod
    def _check_limits(m: dict):
        lo, hi = m.get("limMinDeg"), m.get("limMaxDeg")
        if lo is not None and hi is not None and lo >= hi:
            raise ValueError(f"电机 #{m['id']} 限幅下限 {lo}° 需小于上限 {hi}°")
