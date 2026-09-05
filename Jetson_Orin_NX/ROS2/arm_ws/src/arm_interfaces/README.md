# arm_interfaces — 臂域消息词典

机械臂控制栈的"通信格式"定义包：各节点之间传话的**消息(msg)**与**请求-应答(srv)**标准，全部在这里定稿。改动会同时影响 can_bridge / arm_controller / 未来界面端，属地基包。

## 消息（话题上流动的数据）

| 文件 | 干什么 |
|---|---|
| `msg/CanFrame.msg` | 原始 CAN 帧（can_bridge 与上层的最低层契约，/arm/can/tx、/arm/can/rx） |
| `msg/MotorState.msg` | 单台电机状态（角度/速度/电流/在线/错误/角度来源），10Hz 发布在 /arm/motor_states |
| `msg/ArmStatus.msg` | 总线级状态（状态机档位/全局锁/在线列表/收发计数），1Hz 发布在 /arm/status |
| `msg/JointCmd.msg` | 上层控制意图（五类指令：定位/增量/停/失能/回家），/arm/joint_cmd |
| `msg/RegistryEntry.msg` | 单台电机完整配置（档案，服务读写用；NaN=未设） |

## 服务（请求-应答）

| 文件 | 干什么 |
|---|---|
| `srv/GetRegistry.srv` | 拉注册表全表（带版本号 rev 供前端缓存比对） |
| `srv/SetRegistry.srv` | 写入/更新一台电机配置 |
| `srv/RemoveRegistryEntry.srv` | 删除一台配置（不动电机） |
| `srv/SetLimits.srv` | 写软限幅（全量替换，下限<上限校验） |
| `srv/SetZero.srv` | 设零（V3 记档案 / V4 三步，踩坑要求写在内） |
| `srv/Scan.srv` | 总线扫描（只读探测在线电机） |
| `srv/SafetyReset.srv` | 人工复位全局锁 |

> 字段语义与踩坑要求都写在 .msg/.srv 注释里——改契约前先读注释。
