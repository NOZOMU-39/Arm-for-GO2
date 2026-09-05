"""arm_controller — 机械臂主控（臂脉塔电机域总包）

一期模块（均纯 Python 零 ROS 依赖，Windows 本机可测）：
  registry     电机档案（与界面注册表字段同构）
  track        V3 相位跟踪状态（v3OnPhase/v3PosDual 移植）
  limit        限幅安全链纯函数（limitBlock/monitorLimit 判定数学移植）
节点层（rclpy）在 controller_node.py，二期接线。
"""
