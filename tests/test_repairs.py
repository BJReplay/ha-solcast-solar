"""Test the Solcast Solar repairs flow."""

import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import AUTO_UPDATE, DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.components.solcast_solar.util import SolcastConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

from tests.components.repairs import (
    async_process_repairs_platforms,
    process_repair_fix_flow,
    start_repair_fix_flow,
)
from tests.typing import ClientSessionGenerator

_LOGGER = logging.getLogger(__name__)


async def _reload(hass: HomeAssistant, entry: SolcastConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
    """Reload the integration."""

    _LOGGER.warning("Reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    if hass.data[DOMAIN].get(entry.entry_id):
        try:
            coordinator = entry.runtime_data.coordinator
            return coordinator, coordinator.solcast
        except:  # noqa: E722
            _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
    return None, None


async def test_missing_data_fixable(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
) -> None:
    """Test missing fixable."""

    assert await async_setup_component(hass, "repairs", {})

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[AUTO_UPDATE] = "0"
    entry = await async_init_integration(hass, options)
    config_dir = hass.config.config_dir

    try:

        def remove_future_forecasts():
            data_file = Path(f"{config_dir}/solcast.json")
            data = json.loads(data_file.read_text(encoding="utf-8"))
            # Remove forecasts today up to "now" plus four days
            for site in data["siteinfo"].values():
                site["forecasts"] = [
                    f for f in site["forecasts"] if f["period_start"] < (dt.now(datetime.UTC) + timedelta(days=6)).isoformat()
                ]
            data_file.write_text(json.dumps(data), encoding="utf-8")

        remove_future_forecasts()
        await _reload(hass, entry)

        await async_process_repairs_platforms(hass)

        client = await hass_client()

        # Assert the issue is present, fixable and non-persistent
        issue_reg = ir.async_get(hass)
        assert len(issue_reg.issues) == 1
        issue = list(issue_reg.issues.values())[0]
        issue_id = issue.issue_id
        assert issue.domain == DOMAIN
        assert issue.is_fixable is True
        assert issue.is_persistent is False

        """ TODO: Fix this
        data = await start_repair_fix_flow(client, DOMAIN, issue_id)

        flow_id = data["flow_id"]
        placeholders = data["description_placeholders"]
        assert "https" in placeholders["learn_more"]
        assert data["step_id"] == "offer_auto"

        data = await process_repair_fix_flow(client, flow_id)

        assert data["type"] == "create_entry"  # Wrong, TODO: Fix this
        """

    finally:
        await async_cleanup_integration_tests(hass)
