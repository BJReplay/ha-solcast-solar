"""Solcast advanced options."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

import asyncio
import contextlib
import copy
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

import aiofiles

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE,
    ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT,
    ADVANCED_INVALID_JSON_TASK,
    ADVANCED_OPTION,
    ADVANCED_OPTIONS,
    ADVANCED_TYPE,
    ALIASES,
    CURRENT_NAME,
    DEFAULT,
    DEFAULT_KEYS,
    DEPRECATED,
    DT_DATE_ONLY_FORMAT,
    MAXIMUM,
    MINIMUM,
    NAME,
    OPTION_GREATER_THAN_OR_EQUAL,
    OPTION_LESS_THAN_OR_EQUAL,
    OPTION_NOT_SET_IF,
    OPTION_REQUIRES,
    REQUIRED_KEYS,
    STOPS_WORKING,
)
from .util import (
    clear_cache,
    raise_or_clear_advanced_deprecated,
    raise_or_clear_advanced_problems,
)

if TYPE_CHECKING:
    from .solcastapi import SolcastApi

_LOGGER = logging.getLogger(__name__)


class AdvancedOptions:
    """Manages reading, validation, and storage of advanced options for Solcast."""

    def __init__(self, api: SolcastApi) -> None:
        """Initialise the advanced options manager.

        Arguments:
            api: The parent SolcastApi instance.
        """
        self.api = api
        self.set_default_advanced_options()

    def advanced_options_with_aliases(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Return advanced options including aliases."""

        deprecated: dict[str, str] = {}
        advanced_options_with_aliases = copy.deepcopy(ADVANCED_OPTIONS)
        for option, characteristics in advanced_options_with_aliases.copy().items():
            advanced_options_with_aliases[option][CURRENT_NAME] = option
            for alias in characteristics.get(ALIASES, []):
                if not (
                    not alias[DEPRECATED]
                    and (
                        dt.strptime(
                            alias.get(STOPS_WORKING, dt.strftime(dt.now(self.api.options.tz) - timedelta(days=1), DT_DATE_ONLY_FORMAT)),
                            DT_DATE_ONLY_FORMAT,
                        ).date()
                        > dt.now(self.api.options.tz).date()
                    )
                ):
                    advanced_options_with_aliases[alias[NAME]] = characteristics
                    del advanced_options_with_aliases[alias[NAME]][ALIASES]
                    advanced_options_with_aliases[alias[NAME]][CURRENT_NAME] = option
                    if alias[DEPRECATED]:
                        deprecated[alias[NAME]] = alias.get(STOPS_WORKING)
        return advanced_options_with_aliases, deprecated

    def advanced_with_aliases(self, names: dict[str, Any]) -> list[str]:
        """Return advanced options including aliases."""

        advanced_options_with_aliases, _ = self.advanced_options_with_aliases()
        present_names: list[str] = []
        name: str
        for name in names:
            if advanced_options_with_aliases.get(name) is not None:
                present_names.append(advanced_options_with_aliases[name][CURRENT_NAME])
            else:
                present_names.extend(
                    [
                        characteristics[CURRENT_NAME]
                        for _, characteristics in advanced_options_with_aliases.items()
                        for alias in characteristics.get(ALIASES, [])
                        if name == alias[NAME]
                    ]
                )
        return present_names

    async def read_advanced_options(self) -> bool:  # noqa: C901
        """Read advanced JSON file options, validate and set them."""

        if self.api.suppress_advanced_watchdog_reload:
            self.api.suppress_advanced_watchdog_reload = False  # File has just been written so reset flag but do not reload
            return False

        advanced_options_proposal: dict[str, Any] = copy.deepcopy(self.api.advanced_options)
        change = False
        if Path(self.api.filename_advanced).exists():
            _LOGGER.debug("Advanced options file %s exists", self.api.filename_advanced)
            deprecated_in_use: dict[str, str] = {}
            problems: list[str] = []

            def add_problem(issue_problem: str, *args) -> None:
                """Add an advanced option problem to the issues registry."""
                nonlocal problems
                problem = issue_problem % args if args else issue_problem
                _LOGGER.error(problem)
                problems.append(problem)

            async def add_problem_later(issue_problem: str, *args) -> None:
                """Add an advanced option problem to the issues registry."""
                try:
                    if self.api.hass is not None:
                        problem = issue_problem % args if args else issue_problem
                        _LOGGER.warning("Raise issue in 60 seconds if unresolved: %s", problem)
                        for _ in range(600):
                            await asyncio.sleep(0.1)
                        _LOGGER.error(problem)
                        await raise_or_clear_advanced_problems([problem], self.api.hass)
                except asyncio.CancelledError:
                    self.api.tasks.pop(ADVANCED_INVALID_JSON_TASK, None)

            advanced_options_with_aliases, deprecated = self.advanced_options_with_aliases()

            try:
                async with aiofiles.open(self.api.filename_advanced) as file:
                    _VALIDATION = {
                        ADVANCED_OPTION.INT: r"^\d+$",
                        ADVANCED_OPTION.TIME: r"^([01]?[0-9]|2[0-3]):[03]{1}0$",
                    }

                    content = await file.read()
                    if content.replace("\n", "").replace("\r", "").strip() != "":  # i.e. not empty
                        response_json = ""
                        value: int | float | str | list[str] | None
                        new_value: int | float | str | list[str] | dict[str, Any]
                        if self.api.tasks.get(ADVANCED_INVALID_JSON_TASK) is not None:
                            self.api.tasks[ADVANCED_INVALID_JSON_TASK].cancel()
                            self.api.tasks.pop(ADVANCED_INVALID_JSON_TASK)
                        with contextlib.suppress(json.JSONDecodeError):
                            response_json = json.loads(content)
                        if not isinstance(response_json, dict):
                            self.api.tasks[ADVANCED_INVALID_JSON_TASK] = asyncio.create_task(
                                add_problem_later(
                                    "Advanced options file invalid format, expected JSON `dict`: %s", self.api.filename_advanced
                                )
                            )
                            return change
                        self.api.extant_advanced_options = copy.deepcopy(response_json)
                        options_present = self.advanced_with_aliases(response_json)
                        for option, new_value in response_json.items():
                            if advanced_options_with_aliases.get(option) is None:
                                add_problem("Unknown option: %s, ignored", option)
                                continue
                            if option in deprecated:
                                deprecated_in_use[option] = advanced_options_with_aliases[option][CURRENT_NAME]
                                _LOGGER.warning(
                                    "Advanced option %s is deprecated, please use %s",
                                    option,
                                    advanced_options_with_aliases[option][CURRENT_NAME],
                                )
                            value = self.api.advanced_options.get(advanced_options_with_aliases[option][CURRENT_NAME])
                            valid = True
                            if isinstance(new_value, type(value)):
                                match advanced_options_with_aliases[option][ADVANCED_TYPE]:
                                    case ADVANCED_OPTION.INT | ADVANCED_OPTION.FLOAT:
                                        if (
                                            new_value < advanced_options_with_aliases[option][MINIMUM]
                                            or new_value > advanced_options_with_aliases[option][MAXIMUM]
                                        ):
                                            add_problem(
                                                "Invalid value for advanced option %s: %s (must be %s-%s)",
                                                option,
                                                new_value,
                                                advanced_options_with_aliases[option][MINIMUM],
                                                advanced_options_with_aliases[option][MAXIMUM],
                                            )
                                            valid = False
                                    # case ADVANCED_OPTION.TIME:
                                    #    if re.match(_VALIDATION[ADVANCED_OPTION.TIME], new_value) is None:  # pyright: ignore[reportArgumentType, reportCallIssue]
                                    #        add_problem("Invalid time in advanced option %s: %s", option, new_value)
                                    #        valid = False
                                    case ADVANCED_OPTION.LIST_INT | ADVANCED_OPTION.LIST_TIME:
                                        member_type = advanced_options_with_aliases[option][ADVANCED_TYPE].split("_")[1]
                                        seen_members: list[Any] = []
                                        member: Any
                                        for member in new_value:  # pyright: ignore[reportOptionalIterable, reportGeneralTypeIssues]
                                            if re.match(_VALIDATION[member_type], str(member)) is None:
                                                add_problem("Invalid %s in advanced option %s: %s", member_type, option, member)
                                                valid = False
                                                continue
                                            if member in seen_members:
                                                add_problem("Duplicate %s in advanced option %s: %s", member_type, option, member)
                                                valid = False
                                                continue
                                            seen_members.append(member)
                                    case ADVANCED_OPTION.LIST_DICT:
                                        required_keys = set(advanced_options_with_aliases[option].get(REQUIRED_KEYS, set()))
                                        default_keys = advanced_options_with_aliases[option].get(DEFAULT_KEYS, {})
                                        # Keys that are required but have defaults (can be auto-populated)
                                        required_with_defaults = required_keys & set(default_keys.keys())
                                        # Keys that must be provided by user (no defaults available)
                                        strictly_required_keys = required_keys - required_with_defaults
                                        # All valid keys (required + any with defaults)
                                        valid_keys = required_keys | set(default_keys.keys())

                                        # Track items that need default population
                                        entries_to_add = []
                                        indices_to_remove = []

                                        # Each entry must be a dict
                                        for idx, item in enumerate(new_value):  # pyright: ignore[reportArgumentType]
                                            if not isinstance(item, dict):
                                                add_problem(
                                                    "Invalid entry in %s at index %s: expected dict, got %s",
                                                    option,
                                                    idx,
                                                    type(item).__name__,
                                                )
                                                valid = False
                                                continue

                                            # Check strictly required keys (no defaults) are present
                                            if not strictly_required_keys.issubset(item):
                                                missing_keys = strictly_required_keys - set(item.keys())
                                                add_problem("Missing required keys in %s entry at index %s: %s", option, idx, missing_keys)
                                                valid = False
                                                continue

                                            # Check no unknown keys are present
                                            unknown_keys = set(item.keys()) - valid_keys
                                            if unknown_keys:
                                                add_problem("Unknown keys in %s entry at index %s: %s", option, idx, unknown_keys)
                                                valid = False
                                                continue

                                            if option == ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE:
                                                # Validate that only int values are passed.
                                                item_valid = True
                                                for key, value in item.items():
                                                    if not isinstance(value, int):
                                                        add_problem(
                                                            "Invalid value type in %s entry at index %s: key '%s' must be an integer, got %s",
                                                            option,
                                                            idx,
                                                            key,
                                                            type(value).__name__,
                                                        )
                                                        valid = False
                                                        item_valid = False
                                                        break

                                                # Populate defaults for a valid item
                                                if item_valid and default_keys:
                                                    # Check if any keys with defaults are missing (whether required or not)
                                                    # If missing, then add the missing defaults as new entries, removing the original incomplete item
                                                    missing_defaults = set(default_keys.keys()) - set(item.keys())
                                                    if missing_defaults:
                                                        for key in missing_defaults:
                                                            default_values = default_keys[key]
                                                            for default_value in default_values:
                                                                new_entry = {**item, key: default_value}
                                                                combo_exists = any(
                                                                    all(existing_item.get(k) == v for k, v in new_entry.items())
                                                                    for existing_item in new_value  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable]
                                                                    if isinstance(existing_item, dict)
                                                                )
                                                                if not combo_exists:
                                                                    entries_to_add.append(new_entry)
                                                        indices_to_remove.append(idx)
                                        for idx in reversed(indices_to_remove):
                                            new_value.pop(idx)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue, reportGeneralTypeIssues]
                                        if entries_to_add:
                                            new_value.extend(entries_to_add)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
                                    case _:
                                        pass
                                if (
                                    option == ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT
                                    and new_value
                                    and not self.api.options.get_actuals
                                ):
                                    _LOGGER.warning("Granular dampening delta adjustment requires estimated actuals to be fetched")
                            else:
                                add_problem("Type mismatch for advanced option %s: should be %s", option, type(value).__name__)
                                valid = False
                            if valid:
                                advanced_options_proposal[advanced_options_with_aliases[option][CURRENT_NAME]] = new_value
                                if (
                                    advanced_options_with_aliases[option][ADVANCED_TYPE]
                                    in (
                                        ADVANCED_OPTION.FLOAT,
                                        ADVANCED_OPTION.INT,
                                    )
                                    or advanced_options_with_aliases[option].get(OPTION_NOT_SET_IF) is not None
                                ):
                                    _LOGGER.debug(
                                        "Advanced option proposed %s: %s",
                                        advanced_options_with_aliases[option][CURRENT_NAME],
                                        new_value,
                                    )

                    invalid: list[str] = []
                    for option, value in advanced_options_proposal.items():
                        if advanced_options_with_aliases[option].get(OPTION_GREATER_THAN_OR_EQUAL) is not None:
                            if any(
                                value < advanced_options_proposal[opt]
                                for opt in advanced_options_with_aliases[option][OPTION_GREATER_THAN_OR_EQUAL]
                            ):
                                add_problem(
                                    "Advanced option %s: %s must be greater than or equal to the value of %s",
                                    option,
                                    value,
                                    ", ".join(
                                        [
                                            f"{opt} ({advanced_options_proposal[opt]})"
                                            for opt in advanced_options_with_aliases[option][OPTION_GREATER_THAN_OR_EQUAL]
                                        ]
                                    ),
                                )
                                invalid.append(option)
                        if advanced_options_with_aliases[option].get(OPTION_LESS_THAN_OR_EQUAL) is not None:
                            if any(
                                value > advanced_options_proposal[opt]
                                for opt in advanced_options_with_aliases[option][OPTION_LESS_THAN_OR_EQUAL]
                            ):
                                add_problem(
                                    "Advanced option %s: %s must be less than or equal to the value of %s",
                                    option,
                                    value,
                                    ", ".join(
                                        [
                                            f"{opt} ({advanced_options_proposal[opt]})"
                                            for opt in advanced_options_with_aliases[option][OPTION_LESS_THAN_OR_EQUAL]
                                        ]
                                    ),
                                )
                                invalid.append(option)
                        if advanced_options_with_aliases[option].get(OPTION_NOT_SET_IF) is not None:
                            if any(
                                advanced_options_proposal[opt] and value for opt in advanced_options_with_aliases[option][OPTION_NOT_SET_IF]
                            ):
                                add_problem(
                                    "Advanced option %s: %s can not be set with %s",
                                    option,
                                    value,
                                    ", ".join(
                                        [
                                            f"{opt}: {advanced_options_proposal[opt]}"
                                            for opt in advanced_options_with_aliases[option][OPTION_NOT_SET_IF]
                                        ]
                                    ),
                                )
                                invalid.append(option)
                        if advanced_options_with_aliases[option].get(
                            OPTION_REQUIRES
                        ) is not None and value != advanced_options_with_aliases[option].get(DEFAULT):
                            for req_opt in advanced_options_with_aliases[option][OPTION_REQUIRES]:
                                default_value = advanced_options_with_aliases[req_opt][DEFAULT]
                                proposed_value = advanced_options_proposal.get(req_opt)

                                # If the required option is still at its default, fail
                                if proposed_value == default_value:
                                    add_problem(
                                        "Advanced option %s requires %s to be set (current value is default: %s)",
                                        option,
                                        req_opt,
                                        proposed_value,
                                    )
                                    invalid.append(option)

                    for option, value in advanced_options_proposal.items():
                        default = advanced_options_with_aliases[option][DEFAULT]
                        option = advanced_options_with_aliases[option][CURRENT_NAME]
                        if option in invalid:
                            advanced_options_proposal[advanced_options_with_aliases[option][CURRENT_NAME]] = self.api.advanced_options.get(
                                advanced_options_with_aliases[option][CURRENT_NAME],
                                default,
                            )
                            continue
                        if option not in options_present:
                            if value != default:
                                advanced_options_proposal[option] = default
                                _LOGGER.debug("Advanced option default set %s: %s", option, default)
                                change = True
                        elif value != default:
                            _LOGGER.debug("Advanced option set %s: %s", option, value)
                            change = True
                        elif value != self.api.advanced_options.get(option):
                            advanced_options_proposal[option] = default
                            _LOGGER.debug("Advanced option default set %s: %s", option, default)
                            change = True
                    self.api.advanced_options.update(advanced_options_proposal)
                    if not self.api.advanced_options.get(ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION, False):
                        await clear_cache(self.api.filename_dampening_history, False)  # remove dampening history if necessary
            finally:
                await raise_or_clear_advanced_problems(problems, self.api.hass)
                await raise_or_clear_advanced_deprecated(
                    deprecated_in_use,
                    self.api.hass,
                    stops_working={o: dt.strptime(stops, DT_DATE_ONLY_FORMAT) for o, stops in deprecated.items() if stops is not None},
                )

        return change

    def log_advanced_options(self) -> None:
        """Log the advanced options that are set differently to their defaults."""

        advanced_options_with_aliases, _ = self.advanced_options_with_aliases()
        for key, value in advanced_options_with_aliases.items():
            if key != value[CURRENT_NAME]:
                continue  # Skip aliases, only log canonical names
            if key not in self.api.advanced_options or self.api.advanced_options.get(key) != value[DEFAULT]:
                _LOGGER.debug("Advanced option set %s: %s", key, self.api.advanced_options.get(key))

    def set_default_advanced_options(self) -> None:
        """Set the default advanced options."""

        advanced_options_with_aliases, _ = self.advanced_options_with_aliases()
        initial = not self.api.advanced_options
        for key, value in advanced_options_with_aliases.items():
            if key != value[CURRENT_NAME]:
                continue  # Skip aliases, only set defaults for canonical names
            if key not in self.api.advanced_options or self.api.advanced_options.get(key) != value[DEFAULT]:
                self.api.advanced_options[key] = value[DEFAULT]
                if not initial:
                    _LOGGER.debug("Advanced option default set %s: %s", key, value[DEFAULT])
