from setuptools import setup

package_name = "imu_hi12s2"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="nvidia",
    maintainer_email="nvidia@todo.todo",
    description="HIPNUC HI12S2 driver over UART 0x91 frames",
    license="MIT",
    tests_require=["pytest"],
    entry_points={"console_scripts": [
        "imu_identify = imu_hi12s2.identify_cli:main",
    ]},
)