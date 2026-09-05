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
