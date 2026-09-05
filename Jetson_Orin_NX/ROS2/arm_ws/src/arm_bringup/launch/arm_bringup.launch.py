"""arm_bringup — Jetson 控制栈一键启动(六包收官)

用法(Jetson, 先 source):
  ros2 launch arm_bringup arm_bringup.launch.py                    # 界面主模式(v1): 桥+网关
  ros2 launch arm_bringup arm_bringup.launch.py controller:=true   # 自主任模式: 桥+controller(界面勿连)

模式语义(总线单主纪律):
  - 界面主模式(默认): 总线主 = Windows 界面(经 tcp_gateway); 起 can_bridge + tcp_gateway。
  - 自主任模式(controller:=true): 总线主 = arm_controller(Jetson); 防界面误连双主, 网关不起。
  - controller 轮询周期用其默认 500ms(需要调时直接改 controller 参数或后续加参数文件)。

⚠️ 用 ExecuteProcess 而非 launch Node: 本栈 console_scripts 由新版 setuptools 装到
   install/*/bin/(launch Node 默认找 libexec 目录会报不存在); 命令名在 source 后的 PATH 可直跑。
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    ctrl = LaunchConfiguration("controller")
    return LaunchDescription([
        DeclareLaunchArgument("controller", default_value="false",
                              description="true=自主任模式(起 arm_controller, 网关停, 界面勿连); "
                                          "false=界面主模式(v1, 起网关供界面接入)"),
        LogInfo(condition=UnlessCondition(ctrl),
                msg="界面主模式: can_bridge + tcp_gateway —— Windows 界面连 Jetson IP 即可"),
        LogInfo(condition=IfCondition(ctrl),
                msg="自主任模式: can_bridge + arm_controller —— Windows 界面请勿连接(单主)"),
        ExecuteProcess(cmd=["can_bridge"], name="can_bridge", output="screen"),
        ExecuteProcess(cmd=["tcp_gateway"], name="tcp_gateway", output="screen",
                       condition=UnlessCondition(ctrl)),
        ExecuteProcess(cmd=["controller_node"], name="arm_controller", output="screen",
                       condition=IfCondition(ctrl)),
    ])
