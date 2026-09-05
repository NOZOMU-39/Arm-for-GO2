from setuptools import find_packages, setup

package_name = "can_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="NOZOMU",
    maintainer_email="nozomu@example.com",
    description="can0 SocketCAN ↔ ROS2 帧桥（原始帧收发，标准库 raw socket）",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "can_bridge = can_bridge.bridge_node:main",
        ],
    },
)
