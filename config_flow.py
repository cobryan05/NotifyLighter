"""Config flow for Notify Light-er integration."""

from __future__ import annotations

import copy
import logging
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_DELAY,
    CONF_DELAY_TIME,
    CONF_ENTITIES,
    CONF_ENTITY_ID,
    CONF_FORCE_UPDATE,
    CONF_NAME,
    CONF_TYPE,
    CONF_UNIQUE_ID,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_DELETE,
    CONF_DYNAMIC_PRIORITY,
    CONF_EXPIRE_ENABLED,
    CONF_NOTIFY_PATTERN,
    CONF_PEEK_ENABLED,
    CONF_PEEK_TIME,
    CONF_PRIORITY,
    CONF_RGB_SELECTOR,
    DEFAULT_PRIORITY,
    DOMAIN,
    MAXIMUM_PRIORITY,
    TYPE_LIGHT,
    TYPE_POOL,
    WARM_WHITE_RGB,
)
from .utils.hass_data import HassData
from .utils.light_sequence import LightSequence

_LOGGER = logging.getLogger(__name__)


ADD_NOTIFY_DEFAULTS = {
    CONF_NAME: "New Notification Name",
    CONF_NOTIFY_PATTERN: [],
    CONF_RGB_SELECTOR: WARM_WHITE_RGB,
    CONF_DELAY_TIME: {"seconds": 0},
    CONF_EXPIRE_ENABLED: False,
    CONF_PRIORITY: DEFAULT_PRIORITY,
    CONF_PEEK_ENABLED: True,
}
ADD_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=ADD_NOTIFY_DEFAULTS[CONF_NAME]): cv.string,
        vol.Required(
            CONF_PRIORITY, default=ADD_NOTIFY_DEFAULTS[CONF_PRIORITY]
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                mode=selector.NumberSelectorMode.BOX, min=1, max=MAXIMUM_PRIORITY
            )
        ),
        vol.Required(
            CONF_PEEK_ENABLED, default=ADD_NOTIFY_DEFAULTS[CONF_PEEK_ENABLED]
        ): cv.boolean,
        vol.Required(
            CONF_EXPIRE_ENABLED, default=ADD_NOTIFY_DEFAULTS[CONF_EXPIRE_ENABLED]
        ): cv.boolean,
        vol.Optional(
            CONF_DELAY_TIME, default=ADD_NOTIFY_DEFAULTS[CONF_DELAY_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
        vol.Optional(
            CONF_RGB_SELECTOR, default=ADD_NOTIFY_DEFAULTS[CONF_RGB_SELECTOR]
        ): selector.ColorRGBSelector(),
        vol.Optional(
            CONF_NOTIFY_PATTERN, default=ADD_NOTIFY_DEFAULTS[CONF_NOTIFY_PATTERN]
        ): selector.TextSelector(
            selector.TextSelectorConfig(
                multiple=True,
            )
        ),
    }
)

ADD_POOL_SCHEMA = vol.Schema({vol.Required(CONF_NAME): cv.string})

ADD_LIGHT_DEFAULTS = {
    CONF_NAME: "New Notification Light",
    CONF_RGB_SELECTOR: WARM_WHITE_RGB,
    CONF_PRIORITY: DEFAULT_PRIORITY,
    CONF_DYNAMIC_PRIORITY: True,
    CONF_DELAY: True,
    CONF_DELAY_TIME: {"seconds": 5},
    CONF_PEEK_TIME: {"seconds": 5},
}
ADD_LIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=ADD_LIGHT_DEFAULTS[CONF_NAME]): cv.string,
        vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=LIGHT_DOMAIN)
        ),
        vol.Optional(
            CONF_RGB_SELECTOR, default=ADD_LIGHT_DEFAULTS[CONF_RGB_SELECTOR]
        ): selector.ColorRGBSelector(),
        vol.Required(
            CONF_DYNAMIC_PRIORITY, default=ADD_LIGHT_DEFAULTS[CONF_DYNAMIC_PRIORITY]
        ): cv.boolean,
        vol.Optional(
            CONF_PRIORITY, default=ADD_LIGHT_DEFAULTS[CONF_PRIORITY]
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                mode=selector.NumberSelectorMode.BOX, min=1, max=MAXIMUM_PRIORITY
            )
        ),
        vol.Required(CONF_DELAY, default=ADD_LIGHT_DEFAULTS[CONF_DELAY]): cv.boolean,
        vol.Optional(
            CONF_DELAY_TIME, default=ADD_LIGHT_DEFAULTS[CONF_DELAY_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
        vol.Optional(
            CONF_PEEK_TIME, default=ADD_LIGHT_DEFAULTS[CONF_PEEK_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
    }
)

SUBSCRIPTION_DEFAULTS = {TYPE_POOL: [], CONF_ENTITIES: []}
SUBSCRIPTION_SCHEMA = vol.Schema(
    {
        vol.Optional(
            TYPE_POOL, default=SUBSCRIPTION_DEFAULTS.get(TYPE_POOL)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                multiple=True, options=SUBSCRIPTION_DEFAULTS.get(TYPE_POOL)
            )
        ),
        vol.Optional(
            CONF_ENTITIES, default=SUBSCRIPTION_DEFAULTS.get(CONF_ENTITIES)
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                multiple=True,
                filter=selector.EntityFilterSelectorConfig(
                    domain=SWITCH_DOMAIN, integration=DOMAIN
                ),
            )
        ),
    }
)


class ConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config or options flow for Notify Light-er."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        return self.async_show_menu(menu_options=["new_pool", "new_light"])

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle integration reconfiguration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if entry.data[CONF_TYPE] == TYPE_LIGHT:
            return await self.async_step_reconfigure_light(user_input)
        elif entry.data[CONF_TYPE] == TYPE_POOL:
            return await self.async_step_reconfigure_pool(user_input)
        else:
            return self.async_abort(
                reason=f"Reconfigure not supported for {str(entry.data[CONF_TYPE])}"
            )

    async def async_step_reconfigure_pool(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguring the light entity."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                title=f"[Pool] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_POOL},
                reason="Changes saved",
            )

        schema = self.add_suggested_values_to_schema(
            ADD_POOL_SCHEMA, suggested_values=entry.data
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    async def async_step_reconfigure_light(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguring the light entity."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                title=f"[Light] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_LIGHT},
                reason="Changes saved",
            )

        schema = self.add_suggested_values_to_schema(
            ADD_LIGHT_SCHEMA, suggested_values=entry.data
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    async def async_step_new_pool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Pool flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"[Pool] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_POOL},
            )
        return self.async_show_form(step_id="new_pool", data_schema=ADD_POOL_SCHEMA)

    async def async_step_new_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Light flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"[Light] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_LIGHT},
            )

        exclude_entities = HassData.get_domain_light_entity_ids(self.hass)
        exclude_entities.extend(HassData.get_wrapped_light_entity_ids(self.hass))
        schema = {k: copy.copy(v) for k, v in ADD_LIGHT_SCHEMA.schema.items()}
        schema[CONF_ENTITY_ID] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=LIGHT_DOMAIN, exclude_entities=exclude_entities
            )
        )

        return self.async_show_form(step_id="new_light", data_schema=vol.Schema(schema))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        item_type = config_entry.data.get(CONF_TYPE, None)
        if item_type == TYPE_LIGHT:
            return LightOptionsFlowHandler(config_entry)
        elif item_type == TYPE_POOL:
            return PoolOptionsFlowHandler(config_entry)
        raise NotImplementedError

    @callback
    def _get_entry_data(self) -> dict[str, dict]:
        return HassData.get_entry_data(self.hass, self.context.get("entry_id", 0))

    @callback
    def _get_ntfctn_entries(self) -> dict[str, dict]:
        return HassData.get_ntfctn_entries(self.hass, self.context.get("entry_id", 0))

    @callback
    def _get_entries_by_uuid(self) -> dict[str, dict]:
        return HassData.get_entries_by_uuid(self.hass, self.context.get("entry_id", 0))

    @callback
    def _get_all_entities(self) -> list[er.RegistryEntry]:
        return HassData.get_all_entities(self.hass, self.context.get("entry_id", 0))


class HassDataOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry):
        self._config_entry = config_entry

    @callback
    def _get_entry_data(self) -> dict[str, dict]:
        return HassData.get_entry_data(self.hass, self._config_entry.entry_id)

    @callback
    def _get_ntfctn_entries(self) -> dict[str, dict]:
        return HassData.get_ntfctn_entries(self.hass, self._config_entry.entry_id)

    @callback
    def _get_entries_by_uuid(self) -> dict[str, dict]:
        return HassData.get_entries_by_uuid(self.hass, self._config_entry.entry_id)

    @callback
    def _get_all_entities(self) -> list[er.RegistryEntry]:
        return HassData.get_all_entities(self.hass, self._config_entry.entry_id)

    async def _async_trigger_conf_update(
        self, title: str | None = None, data: dict | None = None
    ) -> ConfigFlowResult:
        # Trigger a Config Update by setting a unique force_update_cnt
        force_update_cnt: int = self._get_entry_data().get(CONF_FORCE_UPDATE, 0) + 1
        return self.async_create_entry(
            title=title, data=data | {CONF_FORCE_UPDATE: force_update_cnt}
        )


class PoolOptionsFlowHandler(HassDataOptionsFlow):
    """Handle options flow for a Pool"""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        # forward to pool_init to differentiate in strings.json
        return await self.async_step_pool_init(user_input)

    async def async_step_pool_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        return self.async_show_menu(
            step_id="pool_init",
            menu_options=[
                "add_notification",
                "add_notification_sample",
                "modify_notification_select",
                "delete_notification",
            ],
        )

    async def async_step_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form."""
        errors: dict[str, str] = {}
        desc_placeholders: dict[str, str] = {}
        schema = ADD_NOTIFY_SCHEMA
        if user_input is not None:
            # Validate
            try:
                LightSequence.create_from_pattern(user_input.get(CONF_NOTIFY_PATTERN))
            except Exception as e:
                errors["pattern"] = str(e)
                desc_placeholders["error_detail"] = str(e)

            # If no errors continue
            if len(errors) == 0:
                return await self.async_step_finish_add_notification(user_input)

            # If errors then load in the set values and show the form again
            schema = self.add_suggested_values_to_schema(
                schema, suggested_values=user_input
            )

        return self.async_show_form(
            step_id="add_notification",
            data_schema=schema,
            errors=errors,
            description_placeholders=desc_placeholders,
        )

    async def async_step_add_notification_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form with sample."""

        # Insert a sample pattern into the Add Notify schema
        sample_pattern = [
            "[",
            '{"rgb": [255,0,0], "delay": 0.250}',
            '{"rgb": [0,0,255], "delay": 0.250}',
            "],5",
            '{"rgb": [255,255,255]}',
        ]
        defaults = (
            ADD_LIGHT_DEFAULTS
            | self._get_entry_data()
            | {CONF_NOTIFY_PATTERN: sample_pattern}
        )
        schema = self.add_suggested_values_to_schema(
            ADD_NOTIFY_SCHEMA, suggested_values=defaults
        )

        return self.async_show_form(step_id="add_notification", data_schema=schema)

    async def async_step_modify_notification_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Modify Notification Selection form."""
        if user_input is not None:
            return await self.async_step_modify_notification(user_input)

        ntfctn_unique_ids = HassData.get_config_notification_list(
            self.hass, self._config_entry.entry_id
        )
        options_schema = vol.Schema(
            {vol.Required(CONF_UNIQUE_ID): vol.In(ntfctn_unique_ids)}
        )

        return self.async_show_form(
            step_id="modify_notification_select", data_schema=options_schema
        )

    async def async_step_modify_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Modify Notification form."""
        item_data: dict | None = None
        if uuid := user_input.get(CONF_UNIQUE_ID):
            item_data = self._get_entries_by_uuid().get(uuid)

        if item_data is None:
            return self.async_abort(reason="Can't locate notification to modify")

        errors: dict[str, str] = {}
        desc_placeholders: dict[str, str] = {}
        if CONF_FORCE_UPDATE in user_input:
            # Validate
            try:
                LightSequence.create_from_pattern(user_input.get(CONF_NOTIFY_PATTERN))
            except Exception as e:
                errors["pattern"] = str(e)
                desc_placeholders["error_detail"] = str(e)
            # FORCE_UPDATE was just a flag to indicate modification is done
            if len(errors) == 0:
                user_input.pop(CONF_FORCE_UPDATE)
                return await self.async_step_finish_add_notification(user_input)

            # Failed validation, show the form again.
            item_data.update(user_input)

        # Merge in default values
        item_data = ADD_NOTIFY_DEFAULTS | item_data | {CONF_FORCE_UPDATE: 1}

        # Add in the extra 'Force Update' flag and Unique ID
        schema = ADD_NOTIFY_SCHEMA.extend(
            {
                # Flag to indicate modify_notification has been submitted
                vol.Optional(CONF_FORCE_UPDATE): selector.ConstantSelector(
                    selector.ConstantSelectorConfig(label="", value=True)
                ),
                vol.Optional(CONF_UNIQUE_ID): selector.ConstantSelector(
                    selector.ConstantSelectorConfig(label="", value=uuid)
                ),
            }
        )

        schema = self.add_suggested_values_to_schema(schema, suggested_values=item_data)

        return self.async_show_form(
            step_id="modify_notification",
            data_schema=schema,
            errors=errors,
            description_placeholders=desc_placeholders,
        )

    async def async_step_delete_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Delete Notification form."""
        if user_input is not None:
            # Set 'to delete' entries and trigger reload
            entry_data: dict = dict(self._get_entry_data())
            entry_data[CONF_DELETE] = user_input.get(CONF_DELETE, [])
            return await self._async_trigger_conf_update(data=entry_data)

        ntfctn_unique_ids = HassData.get_config_notification_list(
            self.hass, self._config_entry.entry_id
        )

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_DELETE): cv.multi_select(ntfctn_unique_ids),
            }
        )
        return self.async_show_form(
            step_id="delete_notification", data_schema=options_schema
        )

    async def async_step_finish_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize adding the notification."""
        # get hass_data entries
        ntfctn_entries = self._get_ntfctn_entries()

        # ensure defaults are set
        user_input = ADD_NOTIFY_DEFAULTS | user_input
        uuid = user_input.get(CONF_UNIQUE_ID)
        if uuid is None:
            uuid = uuid or uuid4().hex
            user_input[CONF_UNIQUE_ID] = uuid

        # Add to the entry to hass_data
        ntfctn_entries.setdefault(CONF_UNIQUE_ID, {})[uuid] = user_input

        return await self._async_trigger_conf_update(data=self._get_entry_data())


class LightOptionsFlowHandler(HassDataOptionsFlow):
    """Handle an options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        # forward to light_init to differentiate in strings.json
        return await self.async_step_light_init(user_input)

    async def async_step_light_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        return self.async_show_menu(
            step_id="light_init", menu_options=["light_options", "subscriptions"]
        )

    async def async_step_light_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        if user_input is not None:
            self._get_entry_data().update(ADD_LIGHT_DEFAULTS | user_input)
            return await self._async_trigger_conf_update(data=self._get_entry_data())

        # Don't list lights created by this integration or in use
        exclude_entities = HassData.get_domain_light_entity_ids(self.hass)
        exclude_entities.extend(HassData.get_wrapped_light_entity_ids(self.hass))
        # Exclude the current light's wrapped entity
        entry_id: str = self.handler
        keep_entity_ids = [
            x.get(CONF_ENTITY_ID)
            for x in HassData.get_domain_lights(self.hass)
            if x.get(CONF_UNIQUE_ID) == entry_id
        ]
        for entity_id in keep_entity_ids:
            if entity_id in exclude_entities:
                exclude_entities.remove(entity_id)

        # Set up multi-select
        schema = {k: copy.copy(v) for k, v in ADD_LIGHT_SCHEMA.schema.items()}
        schema[CONF_ENTITY_ID] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=LIGHT_DOMAIN, exclude_entities=exclude_entities
            )
        )
        schema = vol.Schema(schema)
        defaults: dict[str, dict] = ADD_LIGHT_DEFAULTS | self._get_entry_data()
        schema = self.add_suggested_values_to_schema(schema, suggested_values=defaults)

        return self.async_show_form(step_id="light_options", data_schema=schema)

    async def async_step_subscriptions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Notification Subscriptions form."""
        if user_input is not None:
            return await self.async_step_finish_subscriptions(user_input)

        pools = HassData.get_all_pools(self.hass)
        pool_items = [
            {"value": pool[CONF_UNIQUE_ID], "label": f"{pool[CONF_NAME]}"}
            for pool in pools
        ]
        # TODO: Set up pool subscriptions
        # TODO: Update light when pool subscriptions change

        # Set up multi-select
        schema = {k: copy.copy(v) for k, v in SUBSCRIPTION_SCHEMA.schema.items()}
        schema[TYPE_POOL] = selector.SelectSelector(
            selector.SelectSelectorConfig(multiple=True, options=pool_items)
        )
        schema = vol.Schema(schema)
        defaults: dict[str, dict] = SUBSCRIPTION_DEFAULTS | self._get_ntfctn_entries()
        schema = self.add_suggested_values_to_schema(schema, suggested_values=defaults)

        return self.async_show_form(step_id="subscriptions", data_schema=schema)

    async def async_step_finish_subscriptions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize adding the notification."""
        # Add to the entry to hass_data ensuring defaults are set
        self._get_ntfctn_entries().update(SUBSCRIPTION_DEFAULTS | user_input)
        return await self._async_trigger_conf_update(data=self._get_entry_data())
