"""arm_protocol — 脉塔电机协议库（纯 Python，零 ROS 运行时依赖）

移植源: 机械臂操作交互界面/index.html 的 PROTO_CORE 段（JS）——逐函数对照翻译。
验证: test/golden_vectors.json 为 JS 侧生成的黄金向量，pytest 逐字节断言一致。
契约: 所有角度为"显示语义角"；本库无状态、无全局，电机配置一律显式传参（键名与 JS 注册表对象一致: gear/dir/E4/v9cSemantics...）。

子模块:
  bytes_ops  字节工具（小端读写/clamp/JS 舍入语义/pad8/hx）
  build      组帧（BUILD_V3 与 BUILD_V44，V4.3 复用 V44）
  errors     错误码表与 errText
  angles     方向/减速比/零点换算与设零数学
  parse      回复解析 parse_reply（V3/V4.3/V4.4 三分支）
"""

from . import angles, build, bytes_ops, errors, parse

__version__ = "0.1.0"

# 对外便捷导出（常用）
from .angles import amp2rot, dir_of, gear_of, out2rot, rot2out, spd2rot  # noqa: E402
from .bytes_ops import hx  # noqa: E402
from .parse import decode79_reply, parse_reply  # noqa: E402

__all__ = [
    "angles", "build", "bytes_ops", "errors", "parse",
    "amp2rot", "dir_of", "gear_of", "out2rot", "rot2out", "spd2rot", "hx",
    "decode79_reply", "parse_reply",
    "__version__",
]
