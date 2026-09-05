"""registry 模块单测: 字段规范化/校验/整表加载(以界面机械臂注册表.json 真数据为样)"""
import json
import pathlib

import pytest

from arm_controller.registry import by_id, load_list, normalize

# 界面注册表 5 台真数据样例(2026-09-05 抄自 机械臂操作交互界面/dist/.../机械臂注册表.json)
REAL = [
    {"id": 1, "name": "基座云台Yaw", "proto": "V3", "note": "X8-Pro 旧拨盘电机",
     "gear": 6, "dir": -1, "E0": -92.97, "E0Date": "2026-08-20",
     "limMinDeg": -91, "limMaxDeg": 91, "E4": 0, "defaultPosDeg": 0},
    {"id": 2, "name": "大臂Pitch", "proto": "V43", "gear": 1, "dir": 1,
     "E0": None, "v9cSemantics": "pulse", "limMaxDeg": 93.5, "limMinDeg": -40,
     "E4": 0, "defaultPosDeg": 80},
    {"id": 3, "name": "小臂Pitch", "proto": "V43", "gear": 1, "dir": 1,
     "limMaxDeg": 90, "limMinDeg": -169.5, "E4": 0, "defaultPosDeg": -159.99},
    {"id": 4, "name": "手腕Pitch", "proto": "V44", "gear": 1, "dir": 1,
     "limMaxDeg": 85, "limMinDeg": -124, "E0": None, "E4": 0, "defaultPosDeg": -10},
    {"id": 5, "name": "末端Yaw", "proto": "V44", "gear": 1, "dir": 1,
     "limMinDeg": -120, "limMaxDeg": 120, "E4": 0, "defaultPosDeg": 0},
]


def test_load_real_registry():
    ms = load_list(REAL)
    assert len(ms) == 5
    m1 = by_id(ms, 1)
    assert m1["proto"] == "V3" and m1["gear"] == 6 and m1["dir"] == -1
    assert m1["E0"] == -92.97 and m1["E0Date"] == "2026-08-20"
    assert m1["limMinDeg"] == -91 and m1["limMaxDeg"] == 91
    assert m1["defaultPosDeg"] == 0
    # V4 电机 E0 保持 None
    assert by_id(ms, 2)["E0"] is None
    assert by_id(ms, 4)["proto"] == "V44"


def test_missing_fields_get_defaults():
    m = normalize({"id": 7, "proto": "V3"})
    assert m["gear"] == 1.0 and m["dir"] == 1
    assert m["E0"] is None and m["limMinDeg"] is None
    assert m["E4"] == 0.0 and m["defaultPosDeg"] is None
    assert m["name"] == "电机7"


def test_bad_gear_dir_fallbacks():
    """JS 语义回落: gear<=0→1, dir≠-1→1"""
    m = normalize({"id": 1, "proto": "V3", "gear": 0, "dir": 3, "dirX": 1})
    assert m["gear"] == 1.0 and m["dir"] == 1


def test_dir_minus_one_kept():
    assert normalize({"id": 1, "proto": "V3", "dir": -1})["dir"] == -1


def test_bad_id_rejected():
    for bad in (0, 33, "a", None):
        with pytest.raises(ValueError):
            normalize({"id": bad, "proto": "V3"})


def test_bad_proto_rejected():
    with pytest.raises(ValueError):
        normalize({"id": 1, "proto": "V5"})


def test_dup_id_rejected():
    with pytest.raises(ValueError):
        load_list([REAL[0], {"id": 1, "proto": "V3"}])


def test_nan_limits_to_none():
    m = normalize({"id": 1, "proto": "V3", "limMaxDeg": float("nan")})
    assert m["limMaxDeg"] is None
