from setuptools import find_packages, setup

package_name = "ros2_botnova_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/turtlesim.json"]),
    ],
    install_requires=["setuptools", "paho-mqtt<2.0"],
    zip_safe=True,
    maintainer="Andrew Oshodin",
    maintainer_email="andrewoshodin@gmail.com",
    description="Generic ROS2-to-Botnova bridge, config-driven per robot model, with a turtlesim example.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "bridge_node = botnova_bridge.main:main",
        ],
    },
)
