# 前端控制指令（/arm/joint_cmd 话题流式发布）
# 流式原因: 键盘按住连发/松手停、手柄摇杆天然是流; 安全性由状态回馈(MotorState.error)兜底。
#
# kind 指令类型:
#   1=ABS_POS   绝对定位（deg=目标显示角°）
#   2=REL_DELTA 相对增量（deg=带符号增量°）
#   3=STOP_HOLD 停止保持（0x81，松手即停；deg/spd 忽略）
#   4=DISABLE   失能（0x80；deg/spd 忽略）
#   5=HOME      回默认位置（用注册表 default_pos_deg；deg/spd 忽略）
# 速度/力矩模式后续按需扩 kind（枚举可扩展）。

std_msgs/Header header
int8 motor_id             # 电机号 1~32
uint8 kind                # 指令类型（见上）
float32 deg               # kind=1 目标角 / kind=2 增量角（显示语义）；其余忽略
float32 spd_dps           # 本次允许最大速度 °/s（与注册表 limMaxSpd 取小）；<=0=用注册表默认
