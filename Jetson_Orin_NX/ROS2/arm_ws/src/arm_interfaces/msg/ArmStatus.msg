# 总线级状态（1 Hz 周期发布 /arm/status）：状态机档位 + 全局锁原因 + 诊断
#
# mode 档位（全量安全状态机在 arm_controller 内部实现，此处只报当前档）:
#   0=DISCONNECT 总线未连接/无电机注册
#   1=MANUAL     手动待机（低速可用）
#   2=CALIB      标定中
#   3=READY      就绪（可正常受控）
#   4=RUN        运行中
#   5=SOFT_ESTOP 软急停（停在原地保持）
#   6=LOCKED     全局锁（总线全失联/急停事件；必须 SafetyReset 人工复位）
#
# lock_reason（仅 mode=6 有意义）:
#   0=无  1=总线全失联  2=手动急停输入(可选硬线)  3=其他
#
# 全失联判定: "曾在线集合非空 → 变为 0 台在线" 才算事件; 单台失联只局部处理; 空臂不误报。

std_msgs/Header header
uint8 mode                # 状态机档位（见上）
uint8 lock_reason         # 全局锁原因（见上）
int8[] online_ids         # 当前在线电机 id 列表
uint32 tx_frames          # 累计发送帧数（诊断）
uint32 rx_frames          # 累计接收帧数（诊断）
string last_alarm         # 最近一次报警描述（人读）
