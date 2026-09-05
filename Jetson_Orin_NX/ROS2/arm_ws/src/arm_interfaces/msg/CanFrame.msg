# CAN 原始帧（can_bridge 与上层节点的帧级契约；电机总线为标准帧 11bit ID，无扩展帧）
# /arm/can/rx（发布：bridge 收自 can0 的帧，header.stamp = 到达时刻）
# /arm/can/tx（订阅：上层欲发往 can0 的帧，header 忽略）
# 帧内容为电机协议原始字节（不解析）——解析属 arm_protocol/arm_controller 职责。

std_msgs/Header header   # rx: 帧到达时刻; tx: 忽略
uint32 can_id            # 标准帧 ID（0x000~0x7FF，电机总线约定）
uint8 dlc                # 数据长度 0~8（电机协议恒为 8）
uint8[8] data            # 帧数据（有效长度以 dlc 为准）
