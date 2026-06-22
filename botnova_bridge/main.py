from __future__ import annotations

import rclpy

from botnova_bridge.bridge_node import BridgeNode
from botnova_bridge.mapping import load_config
from botnova_bridge.transport import MqttTransport


def main() -> None:
    rclpy.init()

    param_node = rclpy.create_node("botnova_bridge_params")
    param_node.declare_parameter("config_path", "")
    param_node.declare_parameter("mqtt_host", "localhost")
    param_node.declare_parameter("mqtt_port", 1883)
    config_path = param_node.get_parameter("config_path").value
    mqtt_host = param_node.get_parameter("mqtt_host").value
    mqtt_port = param_node.get_parameter("mqtt_port").value
    param_node.destroy_node()

    if not config_path:
        raise SystemExit(
            "Missing required parameter: --ros-args -p config_path:=<path to robot model json>"
        )

    config = load_config(config_path)

    transport = MqttTransport(
        host=mqtt_host,
        port=mqtt_port,
        robot_id=config.robot.robot_id,
        command_topic=f"botnova/cmd/{config.robot.robot_id}",
        publish_topic=f"botnova/from_robot/{config.robot.robot_id}",
    )
    transport.start()

    bridge = BridgeNode(config, transport)
    bridge.announce()

    try:
        rclpy.spin(bridge)
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
