"""黄金向量验收: Python 版组帧必须与 JS 版标准答案逐字节一致（防翻译错误的主防线）

golden_vectors.json 由 tools/gen_golden.js 从 机械臂操作交互界面/index.html 生成。
重新生成流程（JS 侧协议改动后）:
  node tools/gen_golden.js <index.html绝对路径> test/golden_vectors.json
"""
import json
import math

import pytest

import arm_protocol.build as build
import arm_protocol.bytes_ops as bo
from conftest import GOLDEN_PATH


def test_golden_file_exists():
    assert GOLDEN_PATH.exists(), f"缺少黄金向量文件: {GOLDEN_PATH}（先跑 tools/gen_golden.js）"


def test_golden_count_sane():
    doc = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert doc["count"] >= 30, f"黄金向量条数异常少: {doc['count']}"


@pytest.mark.parametrize("case", [
    c for c in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]
], ids=lambda c: f"{c['proto']}_{c['op']}_{c['hex'][:8]}")
def test_frame_matches_js(case):
    """组帧输出与 JS 黄金答案逐字节一致"""
    got = build.build_frame(case["proto"], case["op"], *case["args"])
    assert bo.hx(got) == case["hex"], f"{case['proto']}.{case['op']}{case['args']} → {bo.hx(got)} ≠ {case['hex']}"


# ---- 自含断言（不依赖 JSON，双保险；断言值与 JS 测试文件同源） ----

def test_v3_pos_layout():
    """V3 0xA4: 360°/s 与 90° 布局（360=0x0168→68 01; 9000=0x2328→28 23）"""
    assert bo.hx(build.v3_pos(0xA4, 360, 90)) == "A4 00 68 01 28 23 00 00"


def test_v44_speed_layout():
    """V4 0xA2: D2=50%力矩, 2000=0x07D0→D0 07"""
    assert bo.hx(build.v44_speed(50, 20)) == "A2 00 32 00 D0 07 00 00"


def test_v44_pos_negative():
    """V4 0xA4 负角: -3000 = 0xFFFFF448 → 48 F4 FF FF"""
    assert bo.hx(build.v44_pos(0xA4, 60, -30)) == "A4 00 3C 00 48 F4 FF FF"


def test_u16_overflow_clamp():
    assert bo.hx(bo.p_u16(70000)) == "FF FF"


def test_pack_unpack_roundtrip():
    """i16/i32 边界往返（对齐 JS 测试第 1 节）"""
    assert bo.i32(bo.p_i32(2147483647), 0) == 2147483647
    assert bo.i32(bo.p_i32(-2147483648), 0) == -2147483648
    assert bo.i16(bo.p_i16(-32768), 0) == -32768


def test_js_round_semantics():
    """JS Math.round 向 +∞: round(2.5)=3, round(-2.5)=-2（Python round 是银行家舍入，必须经 js_round）"""
    assert bo.js_round(2.5) == 3
    assert bo.js_round(-2.5) == -2
    assert bo.js_round(-0.6) == -1
    assert math.floor is not None  # noqa: 防 linter 误删 import


def test_pad8_pad_and_truncate():
    assert bo.hx(bo.pad8(b"\xA4")) == "A4 00 00 00 00 00 00 00"
    assert len(bo.pad8(b"\x01" * 12)) == 8


def test_err_text_v44_precision_and_mix():
    """errText: 精确位优先、位与叠加、V3/V44 表不同"""
    assert build is not None  # noqa
    import arm_protocol.errors as er
    assert er.err_text(0, "V44") == "无错误 ✅"
    assert er.err_text(0x0010, "V44") == "相电流过流"          # V44 精确命中（非 V3 的"过流保护"）
    assert er.err_text(0x0010, "V3") == "过流保护"
    assert er.err_text(0x0004 | 0x0100, "V44") == "低压保护 + 超速"
    # 0x0200 不在任何 V44 错误位表中(全位与=0) → 未知分支
    assert er.err_text(0x0200, "V44") == "未知错误位 200"
    # 0x1234 命中 低压(4)+相电流过流(10)+电机过温(1000) → 叠加而非未知(与 JS 同行为)
    assert er.err_text(0x1234, "V44") == "低压保护 + 相电流过流 + 电机过温"
