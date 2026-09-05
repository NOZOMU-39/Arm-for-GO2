"""pytest 公共配置: 源码树直跑(Windows 本机, 无 ROS 依赖)"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent.parent  # src/
for p in (SRC / "arm_protocol", SRC / "arm_controller"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
