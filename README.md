# ros2_botnova_bridge

A generic, config-driven bridge between ROS2 and [Botnova](../botnova_go)'s MQTT
event protocol. The translation engine never imports a robot-specific ROS message
class — message/service types are resolved dynamically from the strings in a JSON
config (`rosidl_runtime_py.utilities.get_message`/`get_service`). Adding a new ROS2
robot model means writing a new JSON config, not new Python.

Ships with a worked example: `config/turtlesim.json` bridges the standard ROS2
`turtlesim` demo.

## Why this exists

Botnova's backend has zero ROS2-specific code, by design: every robot talks to it
through a transport-agnostic event bus (MQTT, Zenoh, or WebSocket), and a robot's
capabilities are just a flat list of named properties/commands declared once at
onboarding. This bridge is the ROS2-side translation layer that makes a ROS2
robot (real or Gazebo-simulated) look like any other MQTT robot to Botnova — no
Botnova backend changes are required.

## Architecture

```
ROS2 topics/services  <-->  bridge_node.py  <-->  transport.py (MQTT)  <-->  Botnova
                                  ^
                                  |
                            mapping.py (loads config/*.json)
```

- `mapping.py` — loads a robot-model JSON config into `BridgeConfig`, and derives
  the `OnboardingPayload`-shaped capability announcement (`Properties`/`Commands`)
  directly from it, so the announced schema can never drift from what the bridge
  actually translates.
- `transport.py` — `Transport` ABC + `MqttTransport`, the only thing that needs to
  change to add a Zenoh transport later.
- `bridge_node.py` — the generic engine: one ROS2 subscription per `state_topics`
  entry (flattens fields into a Botnova property map on every message), one
  publisher or service client per `commands` entry (dispatched by command name
  when a command arrives from Botnova).
- `main.py` — wires it together and spins the node.

## Wire contract with Botnova

Confirmed by reading `botnova_go/internals/infrastructure/transport/mqtt/mqtt_transport.go`
directly (not assumed):

- Botnova subscribes to `#` by default (`MQTTServerConfig.SubscriptionTopic`), so
  it inspects every message's JSON body regardless of topic. This bridge publishes
  state/onboarding/command-results to `botnova/from_robot/<robotId>`.
- Botnova delivers commands to `<PublishBaseTopic>/<RobotID>` — **the MQTTConfig
  used for this bridge must set `PublishBaseTopic` to `"botnova/cmd"`** (an empty
  `PublishBaseTopic` produces an invalid empty publish topic on Botnova's side).
  This bridge subscribes to `botnova/cmd/<robotId>`.
- All JSON bodies use Go's bare struct field names (no json tags): `Type`,
  `RoutingKey`, `RobotID`, `UserID`, `Payload`, `Time`.
- Outbound commands carry the full `models.Command` struct as `Payload`
  (`{"ID", "Name", "Params", ...}`) — see `botnova_go/internals/application/script/api/api.go:127-141`.
- Command results must round-trip into `models.CommandResult` —
  `{"CommandID", "Success", "Message", "Data"}` — see
  `botnova_go/internals/application/services/command_service.go:60-70`.

## Adding a new robot model

Write a new JSON config (see `config/turtlesim.json`) with three sections:

- `robot`: `robot_id`, `robot_name`, `model_name`, `robot_type` (`"physical"` or `"simulated"`).
- `state_topics`: one entry per ROS2 topic to mirror into Botnova state. `fields`
  maps a ROS field path (dotted for nested attributes, e.g. `pose.pose.position.x`)
  to the Botnova property name. Optional `max_rate_hz` caps how often that topic's
  messages are forwarded to Botnova (messages arriving sooner are dropped, not
  buffered); omit it for no limit.
- `commands`: one entry per command Botnova can send. `kind: "publish"` needs
  `topic`/`msg_type`; `kind: "service"` needs `service`/`srv_type`. `params` maps
  a Botnova param name to either a bare ROS field path (defaults to type `float`)
  or `{"path": ..., "type": "int"|"float"}`.

No other code changes are needed — run `bridge_node` with `--ros-args -p
config_path:=<your config>.json`.

## Running the turtlesim demo end-to-end

1. Run a local MQTT broker: `docker run -it -p 1883:1883 eclipse-mosquitto`.
2. In Botnova, create an `MQTTServerConfig` (`POST /mqtt/config`, or the admin UI)
   pointing at it: `Host: localhost`, `Port: 1883`, `PublishBaseTopic: "botnova/cmd"`,
   `SubscriptionTopic: "#"`.
3. Start the Botnova backend (`cmd/server/main.go`) — it connects to the broker on
   startup via `MQTTTransport.Start()`.
4. Start the simulator: `ros2 run turtlesim turtlesim_node`.
5. Build this package into a ROS2 workspace:
   ```
   pip install -r requirements.txt   # into the ROS2 Python env
   ln -s $(pwd) ~/ros2_ws/src/ros2_botnova_bridge
   cd ~/ros2_ws && colcon build --packages-select ros2_botnova_bridge
   source install/setup.bash
   ```
6. Run the bridge:
   ```
   ros2 run ros2_botnova_bridge bridge_node --ros-args \
     -p config_path:=$(pwd)/src/ros2_botnova_bridge/config/turtlesim.json \
     -p mqtt_host:=localhost -p mqtt_port:=1883
   ```
7. Confirm onboarding: a `robot.onboarding.pending` WebSocket notification should
   appear for the user; confirm it (UI, or `POST /robots/onboard`) to create the
   `turtlesim_v1` `RobotModel` + `turtle1` `Robot` + `RobotEndpoint`.
8. Confirm telemetry: `pos_x`/`pos_y`/`theta` should update live in the robot's
   state/UI.
9. Send a `drive` command (script `group.command("drive", {linear_x: 2, angular_z: 1})`,
   or the UI) and watch the turtle move in the turtlesim window.
10. Send `teleport_absolute`/`set_pen` and confirm the corresponding ROS2 service
    gets called (turtle jumps / pen color changes).
