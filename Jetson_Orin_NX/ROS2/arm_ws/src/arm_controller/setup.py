from setuptools import find_packages, setup

package_name = "arm_controller"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="NOZOMU",
    maintainer_email="nozomu@example.com",
    description="机械臂主控: 档案/轮询/相位跟踪/限幅安全链/流程(registry/track/limit 纯逻辑零 ROS 依赖), 节点 controller_node 二期接线",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        # console_scripts: controller_node 待节点层落地后加
    },
)
