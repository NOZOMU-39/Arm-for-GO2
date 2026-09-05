"""arm_bringup — Jetson 控制栈一键启动(六包收官)

用法(Jetson, 先 source):
  ros2 launch arm_bringup arm_bringup.launch.py                    # 界面主模式(v1): 桥+网关
  ros2 launch arm_bringup arm_bringup.launch.py controller:=true   # 自主任模式: 桥+controller(界面勿连)

模式语义(总线单主纪律):
  - 界面主模式(默认): 总线主 = Windows 界面(经 tcp_gateway), 不起 controller, 不起网关的服务端?
    —— 网关=界面入口, 起; controller 不起。
  - 自主任模式(controller:=true): 总线主 = arm_controller(Jetson); 为防界面误连双主, 网关不起。
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition, IfNotCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    ctrl = LaunchConfiguration("controller")
    return LaunchDescription([
        DeclareLaunchArgument("controller", default_value="false",
                              description="true=自主任模式(起 arm_controller, 网关停, 界面勿连); "
                                          "false=界面主模式(v1, 起网关供界面接入)"),
        DeclareLaunchArgument("poll_interval_ms", default_value="500",
                              description="arm_controller 轮询周期 ms(仅 controller:=true 生效)"),
        LogInfo(condition=IfNotCondition(ctrl),
                msg="界面主模式: can_bridge + tcp_gateway —— Windows 界面连 Jetson IP 即可"),
        LogInfo(condition=IfCondition(ctrl),
                msg="自主任模式: can_bridge + arm_controller —— Windows 界面请勿连接(单主)"),
        Node(package="can_bridge", executable="can_bridge", name="can_bridge", output="screen"),
        Node(package="tcp_gateway", executable="tcp_gateway", name="tcp_gateway",
             output="screen", condition=IfNotCondition(ctrl)),
        Node(package="arm_controller", executable="controller_node", name="arm_controller",
             output="screen", condition=IfCondition(ctrl),
             parameters=[{"poll_interval_ms": LaunchConfiguration("poll_interval_ms")}]),
    ])
