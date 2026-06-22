"""Generic ROS2 <-> Botnova translation engine.

Message/service types are resolved dynamically from the strings in the mapping
config (e.g. "turtlesim/msg/Pose") via rosidl_runtime_py, so this module never
imports a robot-specific message class. Swapping robot models only requires a
new config file, not new code here.
"""
from __future__ import annotations

from typing import Any, Dict

from rclpy.node import Node
from rosidl_runtime_py.utilities import get_message, get_service

from botnova_bridge.mapping import BridgeConfig, get_nested, set_nested
from botnova_bridge.transport import Transport


def _cast(value: Any, type_: str) -> Any:
    if value is None:
        return 0 if type_ == "int" else 0.0
    return int(value) if type_ == "int" else float(value)


class BridgeNode(Node):
    def __init__(self, config: BridgeConfig, transport: Transport):
        super().__init__("botnova_bridge")
        self._config = config
        self._transport = transport
        self._publishers: Dict[str, tuple] = {}
        self._service_clients: Dict[str, tuple] = {}

        for spec in config.state_topics:
            msg_cls = get_message(spec.msg_type)
            self.create_subscription(msg_cls, spec.topic, self._make_state_callback(spec), 10)

        for cmd in config.commands:
            if cmd.kind == "publish":
                msg_cls = get_message(cmd.msg_type)
                self._publishers[cmd.name] = (msg_cls, self.create_publisher(msg_cls, cmd.topic, 10))
            elif cmd.kind == "service":
                srv_cls = get_service(cmd.srv_type)
                self._service_clients[cmd.name] = (srv_cls, self.create_client(srv_cls, cmd.service))
            else:
                raise ValueError(f"Unknown command kind {cmd.kind!r} for command {cmd.name!r}")

        transport.on_command(self._handle_command)

    def announce(self) -> None:
        self._transport.send_onboarding(self._config.onboarding_payload())

    def _make_state_callback(self, spec):
        def callback(msg):
            payload = {botnova_name: get_nested(msg, ros_path) for ros_path, botnova_name in spec.fields.items()}
            self._transport.send_state(self._config.robot.robot_id, payload)
        return callback

    def _handle_command(self, command_id: str, name: str, params: Dict[str, Any]) -> None:
        robot_id = self._config.robot.robot_id
        cmd = self._config.command_by_name(name)
        if cmd is None:
            self.get_logger().warning(f"Unknown command: {name}")
            self._transport.send_command_result(robot_id, command_id, False, f"unknown command {name}")
            return

        try:
            if cmd.kind == "publish":
                self._dispatch_publish(cmd, params)
                self._transport.send_command_result(robot_id, command_id, True)
            else:
                self._dispatch_service(cmd, params, robot_id, command_id)
        except Exception as exc:  # surfaced to the script/UI via the command result, not swallowed
            self._transport.send_command_result(robot_id, command_id, False, str(exc))

    def _dispatch_publish(self, cmd, params: Dict[str, Any]) -> None:
        msg_cls, publisher = self._publishers[cmd.name]
        msg = msg_cls()
        for botnova_name, spec in cmd.params.items():
            set_nested(msg, spec.path, _cast(params.get(botnova_name), spec.type))
        publisher.publish(msg)

    def _dispatch_service(self, cmd, params: Dict[str, Any], robot_id: str, command_id: str) -> None:
        srv_cls, client = self._service_clients[cmd.name]
        if not client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError(f"service {cmd.service} not available")

        request = srv_cls.Request()
        for botnova_name, spec in cmd.params.items():
            set_nested(request, spec.path, _cast(params.get(botnova_name), spec.type))

        future = client.call_async(request)
        future.add_done_callback(lambda f: self._on_service_done(f, robot_id, command_id))

    def _on_service_done(self, future, robot_id: str, command_id: str) -> None:
        try:
            future.result()
            self._transport.send_command_result(robot_id, command_id, True)
        except Exception as exc:
            self._transport.send_command_result(robot_id, command_id, False, str(exc))
