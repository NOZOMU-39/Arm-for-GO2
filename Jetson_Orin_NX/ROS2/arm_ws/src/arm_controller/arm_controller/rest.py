"""上电参考位校正(纯逻辑) —— 2026-09-06 用户提出, V4 甩动丢圈软件折回

背景(机制定论见情报「十一」09-06 条目):
  - V4 索引 4 掉电保存只保"断电瞬间"圈数; 急停甩动 = 掉电后无电运动的转子整圈,
    固件无从记录(无抱闸物理极限) → 重启后显示角差 N × turnDeg(输出)。
  - turnDeg = 转子 1 圈对应输出角 = 360/减速比: X6-40 36:1 → 10.0°; X2-7 28.17:1 → ≈12.78°。
  - V4 显示角 = 固件 0x92 角(raw) + E4(registry, 界面 JS 与 controller state 同语义)。
  - ⚠️ 判定前提(2026-09-06 用户定规): **规范要求人在上电前把臂人工摆到上电参考位**
    (界面按钮「记录机械臂上电位置」, 建议低势能安全位 + 刻度/凸点辅助)。
    restDeg = **参考位显示角**(人读语义)。
  - 校正(2026-09-06 修正, 曾叠加过补偿): 确认臂在参考位后 **E4 = restDeg − raw(直设)**,
    显示精确回 restDeg; 整圈判定(N)仅用于确认"差 ≈ 整数圈"(在参考位), 不参与 E4 计算。
判定(本模块, 纯函数):
  short = rest_deg − (raw_deg + e4_deg)   # 显示差; 正 = 丢圈(显示不足)
  N = round(short/turnDeg);  残差 = short − N×turnDeg
  |残差| ≤ tol → 判 N(正=丢圈, 负=多计);  否则 → 不在参考位/结构异常 → None(不校, 交人工)
容差 tol 必须 < turnDeg/2(硬界), 默认 2.0°; 自垂挡停重复性实测 ≤0.2°(2026-09-06 测试 B)。
"""
from __future__ import annotations


def lost_turns(raw_deg, e4_deg, rest_deg, turn_deg, tol_deg=2.0):
    """显示差 → 丢圈 N(整数, 正=丢圈显示不足, 负=多计) 或 None(不在参考位/异常)。

    raw_deg: 0x92 固件角 | e4_deg: registry.E4 | rest_deg: registry.restDeg(**显示语义**)
    turn_deg: registry.turnDeg | tol_deg: 散布容差(默认 2.0°, 须 < turnDeg/2)
    """
    vals = (raw_deg, e4_deg, rest_deg, turn_deg)
    if not all(isinstance(x, (int, float)) and x == x for x in vals):
        return None                      # 含 NaN/非数 → 档案不全
    if turn_deg <= 0:
        return None
    if tol_deg <= 0 or tol_deg >= abs(turn_deg) / 2:
        return None                      # 容差超硬界: 判定无意义
    short = rest_deg - (raw_deg + e4_deg)   # 正 = 丢圈(显示不足)
    n = round(short / turn_deg)
    resid = short - n * turn_deg
    if abs(resid) <= tol_deg:
        return n
    return None                          # 残差超容差: 不在参考位/结构漂移 → 交人工
