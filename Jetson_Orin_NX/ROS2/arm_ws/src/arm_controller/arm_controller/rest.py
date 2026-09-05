"""上电参考位校正(纯逻辑) —— 2026-09-06 用户提出, V4 甩动丢圈软件折回

背景(机制定论见情报「十一」09-06 条目):
  - V4 索引 4 掉电保存只保"断电瞬间"圈数; 急停甩动 = 掉电后无电运动的转子整圈,
    固件无从记录(无抱闸物理极限) → 重启后显示角差 N × turnDeg(输出)。
  - turnDeg = 转子 1 圈对应输出角 = 360/减速比: X6-40 36:1 → 10.0°; X2-7 28.17:1 → ≈12.78°。
  - V4 显示角 = 固件 0x92 角 + E4(registry, 界面 JS 与 controller state 同语义) →
    丢圈后用软件把 E4 += N×turnDeg 折回, 零 ROM 写入、零人工移臂。
  - ⚠️ 判定前提(2026-09-06 用户定规): **规范要求人在上电前把臂人工摆到上电参考位**
    (界面按钮文案「记为上电位置」, 建议低势能安全位 + 刻度/凸点辅助)——
    不是依赖掉电自落! 人工摆放让结构异常在摆位时即被发现, 且不依赖重力散布。
    restDeg(参考位期望显示角, 内部档案字段, 界面称"上电位置") 在设零后标定入库。
判定(本模块, 纯函数):
  d = restDeg − 读角;  N = round(d/turnDeg);  残差 = d − N×turnDeg
  |残差| ≤ tol → 判丢圈 N(可负, 负=多计了圈);  否则 → 不在参考位/结构异常 → None(不校, 交人工)
容差 tol 必须 < turnDeg/2(硬界: 超过会把 N 判错一圈), 默认 2.0° 为保守值,
人工摆放重复性实测后收紧/放宽。真机用法见 tools/rest_calib.py。
"""
from __future__ import annotations


def lost_turns(reading_deg, rest_deg, turn_deg, tol_deg=2.0):
    """读角 vs 谷位期望 → 丢圈数 N(整数, 负=多计) 或 None(不在谷/档案不全/异常)。

    reading_deg: 0x92 读数(固件输出角, 未加 E4) | rest_deg: registry.restDeg
    turn_deg: registry.turnDeg | tol_deg: 谷位散布容差(默认 2.0°, 须 < turnDeg/2)
    """
    vals = (reading_deg, rest_deg, turn_deg)
    if not all(isinstance(x, (int, float)) and x == x for x in vals):
        return None                      # 含 NaN/非数 → 档案不全
    if turn_deg <= 0:
        return None
    if tol_deg <= 0 or tol_deg >= abs(turn_deg) / 2:
        return None                      # 容差超硬界: 判定无意义
    d = rest_deg - reading_deg
    n = round(d / turn_deg)
    resid = d - n * turn_deg
    if abs(resid) <= tol_deg:
        return n
    return None                          # 残差超容差: 不在谷/结构漂移 → 交人工
