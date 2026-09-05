"""随机对拍验收: Python 版对随机输入重算，与 JS 老翻译标准答案逐值一致

只比 values 不比 summary（随机值会撞 JS toFixed 与 Python 浮点格式化的舍入边界差异）。
跨语言 JSON 表示差异统一规则（非协议语义差异，比较前归一）:
  - JS JSON.stringify(NaN/Inf) = null → Python 非有限 float 归一 None
  - JS 大 double 定点输出被 Python json 读成 int；Python 科学计数读成 float
    —— 数值比较统一经 float()（float32→double 往返精度内无损）
重新生成（JS 侧协议改动后）:
  node tools/gen_rand_vectors.js <index.html绝对路径> test/rand_vectors.json
"""
import json
import math

import pytest

import arm_protocol.build as build
import arm_protocol.bytes_ops as bo
import arm_protocol.parse as parse
from conftest import GOLDEN_PATH

RAND_PATH = GOLDEN_PATH.parent / "rand_vectors.json"
DOC = json.loads(RAND_PATH.read_text(encoding="utf-8"))


def _eq(a, b) -> bool:
    """跨语言数值/JSON 表示统一比较"""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and not math.isfinite(a):
        a = None          # Python nan/inf ↔ JS JSON null
    if isinstance(b, float) and not math.isfinite(b):
        b = None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)   # JS 定点 int vs Python 科学计数 float，统一数值比较
    return a == b


def test_rand_counts_sane():
    assert DOC["frame_count"] >= 400, f"组帧随机题过少: {DOC['frame_count']}"
    assert DOC["parse_count"] >= 1000, f"解析随机题过少: {DOC['parse_count']}"


def _motor_for(mid):
    """与生成器 ROUTES 一致的最小电机配置（生成器只存了 mid，此处按解析所需重建）"""
    return {
        1: {"gear": 6, "dir": -1},
        2: {"gear": 1, "dir": 1},
        3: {"gear": 1, "dir": 1},
        5: {"gear": 1, "dir": -1},
        6: {"gear": 1, "dir": 1, "v9cSemantics": "angle"},
    }.get(mid, {"gear": 1, "dir": 1})


@pytest.mark.parametrize("case", DOC["rand_frames"],
                         ids=lambda c: f"{c['proto']}_{c['op']}")
def test_rand_frame_matches_js(case):
    got = build.build_frame(case["proto"], case["op"], *case["args"])
    assert bo.hx(got) == case["hex"], f"{case['proto']}.{case['op']}{case['args']} → {bo.hx(got)} ≠ {case['hex']}"


@pytest.mark.parametrize("case", DOC["rand_parse"],
                         ids=lambda c: f"{c['proto']}m{c['mid']}_{c['bytes'][0]:02X}")
def test_rand_parse_matches_js_values(case):
    js_out = case["out"]
    py = parse.parse_reply(case["proto"], 0x240 + case["mid"], bytes(case["bytes"]),
                           _motor_for(case["mid"]))
    if js_out is None:
        assert py is None
        return
    assert py is not None
    assert py["cmd"] == js_out["cmd"]
    assert _eq(py["values"], js_out["values"]), (
        f"{case['proto']} m{case['mid']} cmd=0x{case['bytes'][0]:02X} 帧 {bo.hx(bytes(case['bytes']))}\n"
        f"  py={py['values']}\n  js={js_out['values']}")
