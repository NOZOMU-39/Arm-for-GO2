import os

from setuptools import setup

package_name = "arm_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=[],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), ["launch/arm_bringup.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="NOZOMU",
    maintainer_email="nozomu@example.com",
    description="Jetson 控制栈一键启动(launch): 界面主/自主任双模式, 总线单主纪律封装",
    license="Apache-2.0",
)
