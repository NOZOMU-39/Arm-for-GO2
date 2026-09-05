# 单台电机完整配置条目（注册表，经服务读写；Jetson 持有权威副本）
# 字段与 Windows 界面注册表 JSON 一一对应:
#   {id,name,proto,gear,dir} + {E0->e0_deg, E0Date->e0_date, E4->e4_deg}
#   + {limMinDeg->lim_min_deg, limMaxDeg->lim_max_deg, limMaxSpd->lim_max_spd,
#      limMaxIq->lim_max_iq, defaultPosDeg->default_pos_deg}
#
# 约定: 所有 float32 零点/限位字段用 NaN = 未设/未标定（对应界面 JSON 的 null）。

int8 id                   # 电机号 1~32
string name               # 显示名（如 "大臂Pitch"）
string proto              # 协议短码: "V3"(X8) / "V43"(V4.3,X6-40) / "V44"(V4.4,X2-7)
float32 gear              # 减速比（输出轴 1 圈 = 转子 gear 圈）
int8 dir                  # 方向: 1=正 -1=反
float32 e0_deg            # V3 零点档案: 凸点标定位置应显示的角（NaN=未标定）
string e0_date            # E0 标定日期/操作者（自由文本，空=无）
float32 e4_deg            # V4 零点偏移 °（0=未设）
float32 lim_min_deg       # 软限位下限 °（NaN=未设）
float32 lim_max_deg       # 软限位上限 °（NaN=未设）
float32 lim_max_spd       # 限速 °/s（NaN=未设）
float32 lim_max_iq        # 限流 A（NaN=未设）
float32 default_pos_deg   # 回默认位置目标角 °（NaN=未设）
