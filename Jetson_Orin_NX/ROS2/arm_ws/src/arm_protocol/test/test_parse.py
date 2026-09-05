"""回复解析黄金对拍: Python parse_reply 必须与 JS parseReply 输出一致（values 精确相等; summary 字符串相等, 标 values_only 的用例仅比 values——V3 9C angle 分支 JS 有 Number.toString() 裸插值, 字符串跨语言有浮点尾巴差异）"""
import json

import pytest

import arm_protocol.parse as parse
from conftest import GOLDEN_PATH

DOC = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
PARSE_CASES = DOC["parse_cases"]


def test_parse_cases_present():
    assert len(PARSE_CASES) >= 20, f"解析对拍用例异常少: {len(PARSE_CASES)}"


def _norm_js(out: dict) -> dict:
    """JS out → Python 同构（motorId 键名归一）"""
    return {"motor_id": out["motorId"], "broadcast": out["broadcast"],
            "sys300": out["sys300"], "cmd": out["cmd"],
            "summary": out["summary"], "values": out["values"]}


@pytest.mark.parametrize("case", PARSE_CASES, ids=lambda c: f"{c['proto']}_{c['note'][:12]}")
def test_parse_matches_js(case):
    js_out = case["out"]
    if js_out is None:
        # JS 返回 null（cid 不识别等）——Python 必须同样返回 None
        assert parse.parse_reply(case["proto"], case["cid"], bytes(case["bytes"]), case["motor"]) is None
        return
    py = parse.parse_reply(case["proto"], case["cid"], bytes(case["bytes"]), case["motor"])
    assert py is not None, "JS 有输出而 Python 返回 None"
    expected = _norm_js(js_out)
    assert py["motor_id"] == expected["motor_id"]
    assert py["broadcast"] == expected["broadcast"]
    assert py["sys300"] == expected["sys300"]
    assert py["cmd"] == expected["cmd"]
    assert py["values"] == expected["values"], f"values 不一致:\n py={py['values']}\njs={expected['values']}"
    if not case.get("valuesOnly"):
        assert py["summary"] == expected["summary"], (
            f"summary 不一致:\n py={py['summary']!r}\njs={expected['summary']!r}")


# ---- 自含断言（不依赖 JSON，双保险；数值/样例与 JS 测试文件同源） ----

def test_v3_92_d1_d4_264_01():
    """V3 0x92 读 D1-D4: [92 21 67...] = 264.01°（JS 测试同款）"""
    out = parse.parse_reply("V3", 0x241, bytes([0x92, 0x21, 0x67, 0, 0, 0, 0, 0]),
                            {"gear": 1, "dir": 1})
    assert abs(out["values"]["pos"] - 264.01) < 0.01


def test_v3_92_negative():
    out = parse.parse_reply("V3", 0x241, bytes([0x92, 0x82, 0xDA, 0xFF, 0xFF, 0, 0, 0]),
                            {"gear": 1, "dir": 1})
    assert abs(out["values"]["pos"] - (-95.98)) < 0.01


def test_v4_92_d4_d7():
    """V4 0x92 读 D4-D7: DA 82 FF FF 小端 = -9598 → -95.98°"""
    out = parse.parse_reply("V44", 0x242, bytes([0x92, 0, 0, 0, 0x82, 0xDA, 0xFF, 0xFF]),
                            {"gear": 1, "dir": 1})
    assert abs(out["values"]["pos"] - (-95.98)) < 0.01


def test_v43_vs_v44_94_semantics():
    """V4.3 0x94 两字节(0~359.99) vs V4.4 0x94 int32(±180)——同一帧字节两协议解析不同"""
    frame = bytes([0x94, 0, 0, 0, 0x10, 0x27, 0, 0])   # int32 10000
    m = {"gear": 1, "dir": 1}
    out43 = parse.parse_reply("V43", 0x242, frame, m)   # u16(6)=0 → 0.0
    assert out43["values"]["pos"] == 0.0
    out44 = parse.parse_reply("V44", 0x242, frame, m)   # i32(4)=10000 → 100.0
    assert out44["values"]["pos"] == 100.0


def test_v3_9c_pulse_vs_angle():
    """v9cSemantics: 缺失=pulse(enc 脉冲); 'angle'=ang 角度且 enc=None"""
    frame = bytes([0x9C, 30, 0x64, 0, 0xF4, 0x01, 0x34, 0x12])
    m1 = {"gear": 1, "dir": 1}
    out_p = parse.parse_reply("V3", 0x241, frame, m1)
    assert out_p["values"]["enc"] == 0x1234
    assert "ang" not in out_p["values"]
    m2 = {"gear": 1, "dir": 1, "v9cSemantics": "angle"}
    out_a = parse.parse_reply("V3", 0x241, frame, m2)
    assert out_a["values"]["enc"] is None
    assert out_a["values"]["ang"] == 4660


def test_v3_9c_pulse_zero_iq_no_neg_zero():
    """真机 2026-09-05 暴露: V3 9C pulse 分支 dir=-1 零电流曾显示 -0.00A（归零漏网点）"""
    frame = bytes([0x9C, 25, 0, 0, 0, 0, 0xA9, 0xBB])
    out = parse.parse_reply("V3", 0x241, frame, {"gear": 6, "dir": -1})
    assert "0.00A" in out["summary"] and "-0.00A" not in out["summary"], out["summary"]


def test_decode79_reply():
    """0x79 读回复 D6-D7 是回复 CAN 地址 0x240+编号"""
    d = parse.decode79_reply(bytes([0x79, 0, 1, 0, 0, 0, 0x42, 0x02]))
    assert d["mode"] == "read" and d["id"] == 2
    d2 = parse.decode79_reply(bytes([0x79, 0, 0, 0, 0, 0, 0, 5]))
    assert d2["mode"] == "writeEcho" and d2["id"] == 5


def test_cid_unknown_returns_none():
    assert parse.parse_reply("V3", 0x100, bytes(8), None) is None
    assert parse.parse_reply("V3", 0x241, b"", None) is None
    assert parse.parse_reply("V3", 0x241, None, None) is None
