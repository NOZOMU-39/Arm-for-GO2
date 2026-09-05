import os

from setuptools import find_packages, setup

package_name = "tcp_gateway"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="NOZOMU",
    maintainer_email="nozomu@example.com",
    description="Windows 前端(公用) ↔ Jetson TCP 入口(v1 帧透传, ESP32 v2.1.3 协议兼容)",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "tcp_gateway = tcp_gateway.gateway_node:main",
        ],
    },
)
