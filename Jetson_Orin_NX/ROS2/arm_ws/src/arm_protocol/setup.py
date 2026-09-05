from setuptools import find_packages, setup

package_name = "arm_protocol"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*", "tools"]),
    data_files=[],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="NOZOMU",
    maintainer_email="nozomu@example.com",
    description="脉塔电机协议库（PROTO_CORE JS 版移植）: 组帧/解析/角度模型/错误表, 纯 Python 零 ROS 依赖",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={},
)
