"""Loads a robot-model mapping config and derives Botnova's onboarding vocabulary from it.

The mapping is intentionally the single source of truth: the Properties/Commands
announced to Botnova on connect (see BridgeConfig.onboarding_payload) are derived
from the same fields/params this module uses to actually translate messages, so
the announced capability schema can never drift from what the bridge can do.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParamSpec:
    path: str
    type: str = "float"


@dataclass
class StateTopicSpec:
    topic: str
    msg_type: str
    fields: Dict[str, str]  # ROS field path -> Botnova property name


@dataclass
class CommandSpec:
    name: str
    kind: str  # "publish" | "service"
    params: Dict[str, ParamSpec]  # Botnova param name -> ParamSpec
    topic: Optional[str] = None
    msg_type: Optional[str] = None
    service: Optional[str] = None
    srv_type: Optional[str] = None


@dataclass
class RobotSpec:
    robot_id: str
    robot_name: str
    model_name: str
    robot_type: str = "simulated"


@dataclass
class BridgeConfig:
    robot: RobotSpec
    state_topics: List[StateTopicSpec] = field(default_factory=list)
    commands: List[CommandSpec] = field(default_factory=list)

    def command_by_name(self, name: str) -> Optional[CommandSpec]:
        return next((c for c in self.commands if c.name == name), None)

    def onboarding_payload(self) -> Dict[str, Any]:
        properties = [
            {"Name": botnova_name, "Type": "float", "ReadOnly": True}
            for spec in self.state_topics
            for botnova_name in spec.fields.values()
        ]

        commands = [
            {
                "Name": cmd.name,
                "Parameters": [{"Name": pname, "Type": pspec.type} for pname, pspec in cmd.params.items()],
                "Presetable": False,
            }
            for cmd in self.commands
        ]

        return {
            "RobotId": self.robot.robot_id,
            "RobotName": self.robot.robot_name,
            "RobotType": self.robot.robot_type,
            "ModelName": self.robot.model_name,
            "Commands": commands,
            "Properties": properties,
            "Teachables": [],
        }


def _parse_param(value: Any) -> ParamSpec:
    if isinstance(value, str):
        return ParamSpec(path=value)
    return ParamSpec(path=value["path"], type=value.get("type", "float"))


def load_config(path: str) -> BridgeConfig:
    with open(path) as f:
        raw = json.load(f)

    robot = RobotSpec(**raw["robot"])

    state_topics = [
        StateTopicSpec(topic=t["topic"], msg_type=t["msg_type"], fields=t["fields"])
        for t in raw.get("state_topics", [])
    ]

    commands = [
        CommandSpec(
            name=c["name"],
            kind=c["kind"],
            params={pname: _parse_param(pval) for pname, pval in c.get("params", {}).items()},
            topic=c.get("topic"),
            msg_type=c.get("msg_type"),
            service=c.get("service"),
            srv_type=c.get("srv_type"),
        )
        for c in raw.get("commands", [])
    ]

    return BridgeConfig(robot=robot, state_topics=state_topics, commands=commands)


def get_nested(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_nested(obj: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)
