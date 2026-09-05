"""方向/减速比/零点换算 与 设零/键盘限位纯函数（移植自 PROTO_CORE JS）

电机配置 m 为 dict（键名与 JS 注册表对象一致: gear/dir/E4 等）——本库不定义电机类型，
键名对齐 JS 以保移植忠实；与 ROS RegistryEntry 消息的映射由上层转换。
"""

import math

# ---------------------------------------------------------------- 换算


def gear_of(m) -> float:
    """减速比: 输出轴 1 圈 = 转子 gear 圈; 缺失/非法 → 1（对齐 JS parseFloat 语义;
    注: JS parseFloat 会宽松解析数字前缀字符串，实际注册表数据均为数值，无行为差异）"""
    try:
        g = float(m["gear"]) if m and m.get("gear") is not None else float("nan")
    except (TypeError, ValueError):
        g = float("nan")
    return g if g > 0 else 1.0


def dir_of(m) -> int:
    """方向映射: dir === -1 → -1，否则 1"""
    return -1 if (m and m.get("dir") == -1) else 1


def out2rot(v: float, m) -> float:
    """输出轴(显示角) → 协议侧(转子角): v * gear * dir（发帧用）"""
    r = v * gear_of(m) * dir_of(m)
    return r if r != 0 else 0.0  # 归零: 0×dir=-0.0 会致日志显示 "-0.00"(JS toFixed 输出 "0.00")


def rot2out(v: float, m) -> float:
    """协议侧(转子角) → 输出轴(显示角): v / gear * dir"""
    r = v / gear_of(m) * dir_of(m)
    return r if r != 0 else 0.0


def amp2rot(v: float, m) -> float:
    """电流: 乘 dir 映射（V3 电流在协议侧与输出方向同向）"""
    r = v * dir_of(m)
    return r if r != 0 else 0.0


def spd2rot(v: float, m) -> float:
    """速度取绝对值方向映射: |out2rot|"""
    return abs(out2rot(v, m))


def e4_of(m) -> float:
    """V4 显示偏移 E4: 数值且有限 → 原值，否则 0"""
    x = m.get("E4") if m else None
    return x if (isinstance(x, (int, float)) and math.isfinite(x)) else 0.0


# ---------------------------------------------------------------- 设零数学

def v3_e0_for_x(rot_deg_cur: float, x: float, m) -> float:
    """V3 设零: 当前位置标定为 X 时的 E0 档案值 = rotDeg_cur − out2rot(X)（两位小数）"""
    return round((rot_deg_cur - out2rot(x, m)) * 100) / 100


# ---------------------------------------------------------------- 键盘限位停

def kb_limit_blocked(ang, direction: int, lo, hi) -> bool:
    """键盘方向限位停判定: 即将越限(方向继续会出界) → True(停发+停止)；反向键立即恢复。
    ang 非数/NaN → False; lo/hi 为 None 表示该侧未设限。"""
    if not isinstance(ang, (int, float)) or math.isnan(ang):
        return False
    if direction > 0 and hi is not None and ang >= hi:
        return True
    if direction < 0 and lo is not None and ang <= lo:
        return True
    return False
