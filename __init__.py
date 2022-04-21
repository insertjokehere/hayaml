"""The HASSiform integration."""
from __future__ import annotations
import logging
from typing import List

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.data_entry_flow import FlowManager, UnknownHandler
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class FlowError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


def data_for_schema(schema, answers):
    data = {}
    for k in schema.schema.keys():
        if k in answers:
            data[str(k)] = answers[k]
    return data


class ManagedPlatformConfig:
    def __init__(
        self,
        hass: HomeAssistant,
        platform,
        entity_id=None,
        configuration_id=None,
        last_config=None,
        options=None,
    ):
        self.hass = hass
        self.entity_id = entity_id  # The entity ID that HASS knows this config by. None if it hasn't been set up yet
        self.configuration_id = configuration_id  # The ID in the configuration file, so we can track what platforms the user wants us to add/remove/reconfigure
        self.last_config = last_config  # The last configuration we applied
        self.platform = platform  # Name of the platform
        self.desired_config = None  # The config the user wants the platform to have
        self.options = options

    def save(self):
        return {
            "platform": self.platform,
            "entity_id": self.entity_id,
            "configuration_id": self.configuration_id,
            "last_config": self.last_config,
            "options": self.options,
        }

    async def setup_platform(self, flow_manager: FlowManager, flow, answers):
        result = await flow_manager.async_init(flow, context={"source": "user"})
        flow_id = result["flow_id"]
        try:

            while True:
                if "errors" in result and result["errors"]:
                    raise FlowError(
                        f"Flow returned errors while updating component {self.platform} - {result['errors']}"
                    )

                if "result" not in result:
                    try:
                        result = await flow_manager.async_configure(
                            flow_id,
                            data_for_schema(result["data_schema"], answers),
                        )
                    except vol.Error as e:
                        raise FlowError(
                            message=f"Schema error while updating component {self.platform} - {e}",
                        ) from e
                else:
                    break

        except FlowError:
            flow_manager.async_abort(flow_id)
            raise

        return result["result"]

    async def delete_platform(self):
        await self.hass.config_entries.async_remove(self.entity_id)

    async def configure(self):
        config_entries = self.hass.config_entries
        if self.desired_config is None:
            _LOGGER.info("Removing entry %s", self.entity_id)
            await self.delete_platform()
            return

        if config_entries.async_get_entry(self.entity_id) is None:
            self.entity_id = None

        if self.entity_id is None:
            _LOGGER.info("Creating entry %s", self.entity_id)
            result = await self.setup_platform(
                config_entries.flow, self.platform, self.desired_config
            )
            self.entity_id = result.entry_id

        elif self.desired_config != self.last_config:
            _LOGGER.info("Recreating entry %s", self.entity_id)
            await self.delete_platform()
            result = await self.setup_platform(
                config_entries.flow, self.platform, self.desired_config
            )
            self.entity_id = result.entry_id

        self.last_config = self.desired_config
        if self.options:
            try:
                await self.setup_platform(
                    config_entries.options, self.entity_id, self.options
                )
            except UnknownHandler as _:
                _LOGGER.warning("Platform %s does not support options", self.platform)


class LockFile:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store = Store(hass, 1, "hassiform", private=True)
        self.entries = []  # type: List[ManagedPlatformConfig]

    async def async_load(self):
        lock_file_data = await self.store.async_load()
        if lock_file_data is None:
            lock_file_data = []

        for entry in lock_file_data:
            self.entries.append(ManagedPlatformConfig(hass=self.hass, **entry))

    async def async_save(self):
        data = []
        for entry in self.entries:
            if entry.desired_config is not None and entry.entity_id is not None:
                data.append(entry.save())
        await self.store.async_save(data)

    def for_entity_id(self, entity_id):
        for entry in self.entries:
            if entry.entity_id == entity_id:
                return entry

        raise KeyError(entity_id)

    def for_configuration_id(self, configuration_id):
        for entry in self.entries:
            if entry.configuration_id == configuration_id:
                return entry

        raise KeyError(configuration_id)


async def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HASSiform from a config entry."""
    # TODO Store an API object for your platforms to access
    # hass.data[DOMAIN][entry.entry_id] = MyApi(...)

    async def configure(_):

        lock_file = LockFile(hass)
        await lock_file.async_load()

        for platform in entry[DOMAIN].get("platforms", []):
            try:
                managed_platform = lock_file.for_configuration_id(
                    platform["configuration_id"]
                )
            except KeyError:
                managed_platform = ManagedPlatformConfig(
                    hass,
                    platform["platform"],
                    configuration_id=platform["configuration_id"],
                )
                lock_file.entries.append(managed_platform)

            managed_platform.desired_config = platform["data"]
            managed_platform.options = platform.get("options", {})

        _LOGGER.info("Setting up")
        for lock_entry in lock_file.entries:
            try:
                await lock_entry.configure()
            except FlowError as e:
                _LOGGER.error(str(e))

        await lock_file.async_save()
        return True

    if hass.state == CoreState.running:
        await configure(None)
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, configure)