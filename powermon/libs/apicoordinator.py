""" apicoordinator.py """
import logging
from time import time

from powermon.commands.command import Command
from powermon.commands.trigger import Trigger
from powermon.device import Device
from powermon.dto.commandDTO import CommandDTO
from powermon.formats.simple import SimpleFormat
from powermon.outputs.api_mqtt import API_MQTT

log = logging.getLogger("APICoordinator")


class ApiCoordinator:
    """ apicoordinator coordinates the api / mqtt interface """
    def __str__(self):
        if not self.enabled:
            return "ApiCoordinator DISABLED"
        return f"ApiCoordinator: adhocTopic: {self.adhoc_topic_format}, announceTopic: {self.announce_topic}"

    @classmethod
    def from_config(cls, config=None):
        log.debug(f"ApiCoordinator config: {config}")
        if not config:
            log.info("No api definition in config")
            refresh_interval = 300
            enabled = False
            announce_topic = "powermon/announce"
            adhoc_topic_format = "powermon/{device_id}/addcommand"
        else:
            refresh_interval = config.get("refresh_interval", 300)
            enabled = config.get("enabled", True)  # default to enabled if not specified
            announce_topic = config.get("announce_topic", "powermon/announce")
            adhoc_topic_format = config.get("adhoc_topic_format", "powermon/{device_id}/addcommand")

        return cls(adhoc_topic_format=adhoc_topic_format, announce_topic=announce_topic, enabled=enabled, refresh_interval=refresh_interval)

    def __init__(self, adhoc_topic_format: str, announce_topic: str, enabled: bool, refresh_interval: int):
        self.device = None
        self.mqtt_broker = None
        self.last_run = None
        self.adhoc_topic_format = adhoc_topic_format
        self.announce_topic = announce_topic
        self.refresh_interval = refresh_interval
        self.enabled = enabled

    def set_device(self, device: Device):
        self.device = device
        self.announce(self.device)

    def set_mqtt_broker(self, mqtt_broker):
        self.mqtt_broker = mqtt_broker

        if self.mqtt_broker is None or self.mqtt_broker.disabled:
            # no use having api running if no mqtt broker
            log.debug(self.mqtt_broker)
            log.debug("No mqttbroker (or it is disabled) so disabling ApiCoordinator")
            self.enabled = False
            return

        mqtt_broker.subscribe(self.get_addcommand_topic(), self.addcommand_callback)
        # mqtt_broker.publish(self.announceTopic, self.schedule.getScheduleConfigAsJSON())

    def get_addcommand_topic(self):
        return self.adhoc_topic_format.format(device_id=self.device.device_id)

    def addcommand_callback(self, client, userdata, msg):
        log.info(f"Received `{msg.payload}` on topic `{msg.topic}`")
        jsonString = msg.payload.decode("utf-8")
        log.debug(f"Yaml string: {jsonString}")

        dto = CommandDTO.parse_raw(jsonString)

        trigger = Trigger.from_DTO(dto.trigger)
        command = Command.from_DTO(dto)
        Command(code=dto.command_code, commandtype="basic", outputs=[], trigger=trigger)
        outputs = []

        output = API_MQTT(formatter=SimpleFormat({}))
        outputs.append(output)

        command.set_outputs(outputs=outputs)
        command.set_mqtt_broker(self.mqtt_broker)

        self.device.add_command(command)

        return command

    def run(self):
        """ regular processing function, ensures that the announce isnt too frequent """
        if not self.enabled:
            return
        if not self.last_run or time() - self.last_run > self.refresh_interval:
            log.info("APICoordinator running")
            self.announce(self.device)
            self.last_run = time()

    def initialize(self):
        """ initialize the apicoordinator """
        if not self.enabled:
            return
        self.announce(self)

    def announce(self, obj):
        """ Announce jsonised obj dto to api """
        obj_dto = obj.to_dto()
        if not self.enabled:
            log.debug("Not announcing obj: %s as api DISABLED", obj_dto)
            return
        log.debug("Announcing obj: %s to api", obj_dto)
        self.mqtt_broker.publish(self.announce_topic, obj_dto.json())
