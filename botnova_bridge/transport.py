"""Speaks Botnova's exact MQTT wire contract.

Confirmed by reading botnova_go/internals/infrastructure/transport/mqtt/mqtt_transport.go:
- Botnova's MQTTServerConfig.SubscriptionTopic defaults to "#", so it inspects every
  message's JSON body regardless of topic -- this transport may publish anywhere.
- Botnova delivers commands to "<PublishBaseTopic>/<RobotID>" -- this transport must
  subscribe there.
- The JSON body has no field tags on the Go side, so keys are the bare Go struct
  field names: Type, RoutingKey, RobotID, UserID, Payload, Time.
"""
from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt

# (command_id, command_name, params)
CommandHandler = Callable[[str, str, Dict[str, Any]], None]


class Transport(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def send_state(self, robot_id: str, payload: Dict[str, Any]) -> None: ...

    @abstractmethod
    def send_onboarding(self, payload: Dict[str, Any]) -> None: ...

    @abstractmethod
    def send_status(self, robot_id: str, status: str) -> None: ...

    @abstractmethod
    def send_command_result(self, robot_id: str, command_id: str, success: bool, message: str = "") -> None: ...

    @abstractmethod
    def on_command(self, handler: CommandHandler) -> None: ...


class MqttTransport(Transport):
    def __init__(self, host: str, port: int, robot_id: str, command_topic: str, publish_topic: str, user_id: str):
        self._publish_topic = publish_topic
        self._command_topic = command_topic
        self._userId = user_id
        self._command_handler: Optional[CommandHandler] = None

        self._client = mqtt.Client(client_id=f"botnova-bridge-{robot_id}-{uuid.uuid4()}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(host, port)

    def start(self) -> None:
        self._client.loop_start()

    def on_command(self, handler: CommandHandler) -> None:
        self._command_handler = handler

    def send_state(self, robot_id: str, payload: Dict[str, Any]) -> None:
        self._publish({"Type": "state", "RobotID": robot_id, "Payload": payload, "Time": int(time.time())})

    def send_onboarding(self, payload: Dict[str, Any]) -> None:
        print("Sending onboarding...\n")
        self._publish({
            "Type": "default",
            "RoutingKey": "robot.onboarding",
            "RobotID": payload["RobotId"],
            "Payload": payload,
            "Time": int(time.time()),
            "UserID": self._userId
        })

    def send_status(self, robot_id: str, status: str) -> None:
        self._publish({
            "Type": "default",
            "RoutingKey": "robot.status",
            "RobotID": robot_id,
            "Payload": {"Status": status},
            "Time": int(time.time()),
            "UserID": self._userId
        })

    def send_command_result(self, robot_id: str, command_id: str, success: bool, message: str = "") -> None:
        self._publish({
            "Type": "command",
            "RoutingKey": "command.result",
            "RobotID": robot_id,
            "Payload": {"CommandID": command_id, "Success": success, "Message": message, "Data": {}},
            "Time": int(time.time()),
            "UserID": self._userId
        })

    def _publish(self, envelope: Dict[str, Any]) -> None:
        self._client.publish(self._publish_topic, json.dumps(envelope))

    def _on_connect(self, client, userdata, flags, rc):
        print("connected.\n")
        client.subscribe(self._command_topic)

    def _on_message(self, client, userdata, msg):
        print("message received \n")
        try:
            envelope = json.loads(msg.payload)
        except json.JSONDecodeError:
            return

        if envelope.get("RoutingKey") == "robot.probe":
            self.send_status(envelope.get("RobotID", ""), "online")
            return

        if self._command_handler is None:
            return
        if envelope.get("Type") != "command":
            return

        # Outbound commands carry the full models.Command struct as Payload
        # (see botnova_go internals/application/script/api/api.go:127-141).
        command = envelope.get("Payload") or {}
        self._command_handler(command.get("ID", ""), command.get("Name", ""), command.get("Params") or {})
