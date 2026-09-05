# 单台电机瞬时状态（轮询回复解析后发布，数组形式挂在 /arm/motor_states）
#
# 角度一律为"显示语义角"（输出轴、已含零点/方向换算）——前端拿来即显示，无需懂电机协议。
# 换算（gear/dir/E0/E4）只存在于 arm_controller，全项目单一换算方。

std_msgs/Header header    # 采样时刻（ROS 时钟）
int8 motor_id             # 电机号 1~32（=注册表 id）
bool online               # 在线（上次收到回复距今 < 超时窗口）
float32 deg               # 输出轴角度 °（显示语义角）
float32 vel_dps           # 输出轴角速度 °/s
float32 current_a         # 电流 A
uint8 angle_src           # 角度来源: 0=无 1=0x92多圈(主) 2=0x9C(相位/兜底) 3=0x94
uint16 error              # 错误: 0=正常 1=本台通信超时 2=越限报警 3=停止保持中
