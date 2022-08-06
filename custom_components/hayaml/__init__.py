"""The hayaml integration."""
from __future__ import annotations

import logging
from typing import List

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.data_entry_flow import (
    FlowManager,
    UnknownFlow,
    UnknownHandler,
)
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ANSWERS,
    CONF_CONFIG_ID,
    CONF_INTEGRATIONS,
    CONF_OPTIONS,
    CONF_PLATFORM,
    CONF_RECREATE_OPTIONS,
    DOMAIN,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                CONF_INTEGRATIONS: [
                    vol.Schema(
                        {
                            vol.Required(CONF_PLATFORM): str,
                            vol.Required(CONF_CONFIG_ID): str,
                            vol.Required(CONF_ANSWERS): [dict],
                            vol.Required(CONF_RECREATE_OPTIONS, default=False): bool,
                            CONF_OPTIONS: [dict],
                        }
                    )
                ],
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)


class FlowError(Exception):
    pass


class AlreadyConfigured(FlowError):
    pass


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
        entry_id=None,
        configuration_id=None,
        last_config=None,
        last_options=None,
        options_needs_recreate=False,
    ):
        self.hass = hass
        self.entry_id = entry_id  # The entry ID that HASS knows this config by. None if it hasn't been set up yet
        self.configuration_id = configuration_id  # The ID in the configuration file, so we can track what platforms the user wants us to add/remove/reconfigure
        self.last_config = last_config  # The last configuration we applied
        self.last_options = last_options  # The last options we applied
        self.platform = platform  # Name of the platform
        self.options_needs_recreate = (
            options_needs_recreate  # Do we need to recreate the integration if the options change
        )
        self.desired_config = None  # The config the user wants the integration to have
        self.desired_options = None  # The optons the user wants the integration to have

    def save(self):
        return {
            "platform": self.platform,
            "entry_id": self.entry_id,
            "configuration_id": self.configuration_id,
            "last_config": self.last_config,
            "last_options": self.last_options,
        }

    async def run_flow(self, flow_manager: FlowManager, flow: str, answers_list: list[dict]):
        result = await flow_manager.async_init(flow, context={"source": "user", "show_advanced_options": True})
        flow_id = result["flow_id"]
        try:

            for answers in answers_list:
                _LOGGER.debug(f"<- {result}")
                # Android TV integration returns {"errors": {"base": None}} initially, so we need to be careful of the logic here
                if "errors" in result and isinstance(result["errors"], dict) and any(result["errors"].values()):
                    raise FlowError(
                        f"Flow returned errors while updating component {self.platform} - {result['errors']}"
                    )

                if result.get("type") == "abort" and result.get("reason") == "already_configured":
                    raise AlreadyConfigured(
                        f"Integration {self.platform} already configured for given parameters, but not present in lock file"
                    )

                if "result" not in result:
                    last_schema = result["data_schema"]
                    try:
                        step_answers = data_for_schema(result["data_schema"], answers)
                        _LOGGER.debug(f"-> {step_answers}")
                        result = await flow_manager.async_configure(
                            flow_id,
                            step_answers,
                        )
                    except vol.Error as e:
                        raise FlowError(
                            f"Schema error while updating component {self.platform} - {e}. Check that your configuration can match {last_schema}",
                        ) from e
                else:
                    break

        except FlowError:
            try:
                flow_manager.async_abort(flow_id)
            except UnknownFlow:
                pass
            raise

        if "errors" in result and isinstance(result["errors"], dict) and any(result["errors"].values()):
            raise FlowError(f"Flow returned errors while updating component {self.platform} - {result['errors']}")

        return result["result"]

    async def delete_platform(self):
        await self.hass.config_entries.async_remove(self.entry_id)

    async def configure(self):
        config_entries = self.hass.config_entries
        if self.desired_config is None:
            _LOGGER.info("Removing entry %s", self.entry_id)
            await self.delete_platform()
            return

        if config_entries.async_get_entry(self.entry_id) is None:
            self.entry_id = None

        if self.entry_id is None:
            _LOGGER.info("Creating entry for platform %s", self.platform)
            result = await self.run_flow(config_entries.flow, self.platform, self.desired_config)
            self.entry_id = result.entry_id

        elif self.desired_config != self.last_config or (
            self.options_needs_recreate and self.desired_options != self.last_options
        ):
            _LOGGER.info("Recreating entry %s", self.entry_id)
            await self.delete_platform()
            result = await self.run_flow(config_entries.flow, self.platform, self.desired_config)
            self.last_options = None
            self.entry_id = result.entry_id

        self.last_config = self.desired_config
        if self.desired_options != self.last_options:
            _LOGGER.info("Configuring entry %s", self.entry_id)
            try:
                await self.run_flow(config_entries.options, self.entry_id, self.desired_options)
                self.last_options = self.desired_options
            except UnknownHandler as _:
                _LOGGER.warning("Platform %s does not support options", self.platform)


class LockFile:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store = Store(hass, 1, f"{DOMAIN}-lock", private=True)
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
            if entry.desired_config is not None and entry.entry_id is not None:
                data.append(entry.save())
        await self.store.async_save(data)

    def for_entry_id(self, entry_id):
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return entry

        raise KeyError(entry_id)

    def for_configuration_id(self, configuration_id):
        for entry in self.entries:
            if entry.configuration_id == configuration_id:
                return entry

        raise KeyError(configuration_id)


async def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async def configure(_):

        lock_file = LockFile(hass)
        await lock_file.async_load()

        for platform in entry[DOMAIN].get(CONF_INTEGRATIONS, []):
            try:
                managed_platform = lock_file.for_configuration_id(platform[CONF_CONFIG_ID])
            except KeyError:
                managed_platform = ManagedPlatformConfig(
                    hass,
                    platform[CONF_PLATFORM],
                    configuration_id=platform[CONF_CONFIG_ID],
                )
                lock_file.entries.append(managed_platform)

            managed_platform.desired_config = platform[CONF_ANSWERS]
            managed_platform.desired_options = platform.get(CONF_OPTIONS, None)
            managed_platform.options_needs_recreate = platform[CONF_RECREATE_OPTIONS]

        _LOGGER.info("Setting up")
        for lock_entry in lock_file.entries:
            try:
                await lock_entry.configure()
            except FlowError as e:
                _LOGGER.error(str(e))

            await lock_file.async_save()

    if hass.state == CoreState.running:
        await configure(None)
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, configure)

    return True
