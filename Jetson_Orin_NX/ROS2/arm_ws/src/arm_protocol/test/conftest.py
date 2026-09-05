"""pytest 公共配置：把包根加入 sys.path（源码树直接跑，无需 colcon install）"""
import pathlib
import sys

PKG_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

GOLDEN_PATH = pathlib.Path(__file__).resolve().parent / "golden_vectors.json"
