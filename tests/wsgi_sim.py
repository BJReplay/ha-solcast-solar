#!/usr/bin/env python3
"""Solcast hobbyist API simulator.

Install:

* This script runs in a Home Assistant DevContainer
* Script start: `python3 -m wsgi_sim.py`, or make the file executable and run `./wsgi_sim.py`

Optional run arguments:

* --limit LIMIT      Set the API call limit available, example --limit 100, default 50 (There is no limit... 😉)
* --bomb429 w-x,y,z  The minute(s) of the hour to return API too busy, comma separated, example --bomb429 0-5,15,30-35,45
* --bombkey w-x,y,z  The minute(s) of the hour to change the API key, comma separated, example --bombkey 0-5,15,30-35,45
* --teapot           Return '418/I'm a teapot' status occasionally.
* --port PORT        Set the listening port, example --port 8443, default 443
* --debug            Enable debug mode.

Theory of operation:

* Configure integration to use either API key "1", "2", "3", or any combination of multiple. Any other key will return an error.
* API key 1 has two sites, API key 2 has one site, API key 3 has an impossible (for hobbyists) three sites.
* Forecast for every day is the same blissful-clear-day bell curve.
* As time goes on new forecast hour values are calculated based on the current get forecasts call time of day.
* 429 responses are only given when --bomb429 is specified.
* An occasionally generated "I'm a teapot" status can verify that the integration handles unknown status returns gracefully.
* The time zone used should be read from the Home Assistant configuration. If this fails then the zone will be Australia/Melbourne.

SSL certificate:

The integration does not care whether the api.solcast.com.au certificate is valid, so a self-signed certificate is created by this simulator.
To generate a new self-signed certificate run in this folder: openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 3650,
or simply delete *.pem files and restart the simulator to generate new ones. The DevContainer will already have openssl installed.

Integration issues raised regarding the simulator will be closed without response.
Raise a pull request instead, suggesting a fix for whatever is wrong, or to add additional functionality.

Experimental support for advanced_pv_power:

Should Solcast deprecate the legacy hobbyist API, then the advanced_pv_power API calls will probably be preferred, just with capabilities limited by Solcast.
This simulator is prepared should this occur.

"""

import argparse
from collections.abc import Callable
import copy
import datetime
from datetime import datetime as dt, timedelta
import functools
import json
from logging.config import dictConfig
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any, cast
from zoneinfo import ZoneInfo

from simulator import API_KEY_SITES, SimulatedSolcast
import werkzeug

simulate = SimulatedSolcast()
DEFAULT_PORT = 443


def restart():
    """Restarts the sim."""

    python = sys.executable
    os.execl(python, python, *sys.argv)
    sys.exit()


need_restart = False

try:
    from flask import Flask, jsonify, request
    from flask.json.provider import DefaultJSONProvider
except (ModuleNotFoundError, ImportError):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    need_restart = True
try:
    import isodate  # pyright: ignore[reportMissingTypeStubs]
except (ModuleNotFoundError, ImportError):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "isodate"])
    need_restart = True

if need_restart:
    restart()

if not (Path("cert.pem").exists() and Path("key.pem").exists()):
    subprocess.check_call(
        [
            "/usr/bin/openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-nodes",
            "-out",
            "cert.pem",
            "-keyout",
            "key.pem",
            "-days",
            "3650",
            "-subj",
            "/C=AU/ST=Victoria/L=Melbourne/O=Solcast/OU=Solcast/CN=api.solcast.com.au",
        ]
    )

API_LIMIT = 50
BOMB_418 = False
BOMB_429 = []
BOMB_KEY = []
ERROR_KEY_REQUIRED = "KeyRequired"
ERROR_INVALID_KEY = "InvalidKey"
ERROR_TOO_MANY_REQUESTS = "TooManyRequests"
ERROR_SITE_NOT_FOUND = "SiteNotFound"
ERROR_MESSAGE: dict[str, Any] = {
    ERROR_KEY_REQUIRED: {"message": "An API key must be specified.", "status": 400},
    ERROR_INVALID_KEY: {"message": "Invalid API key.", "status": 403},
    ERROR_TOO_MANY_REQUESTS: {"message": "You have exceeded your free daily limit.", "status": 429},
    ERROR_SITE_NOT_FOUND: {"message": "The specified site cannot be found.", "status": 404},
}

dictConfig(  # Logger configuration
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "%(asctime)s.%(msecs)03d %(levelname)s [%(name)s:%(filename)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "wsgi": {"class": "logging.StreamHandler", "stream": "ext://flask.logging.wsgi_errors_stream", "formatter": "default"}
        },
        "root": {"level": "DEBUG", "handlers": ["wsgi"]},
    }
)


class DtJSONProvider(DefaultJSONProvider):
    """Custom JSON provider converting datetime to ISO format."""

    def default(self, o: Any) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Convert datetime to ISO format."""
        if isinstance(o, dt):
            return o.isoformat()

        return super().default(o)


cli = sys.modules["flask.cli"]
cli.show_server_banner = lambda *x: None  # pyright: ignore[reportAttributeAccessIssue]

app = Flask(__name__)
app.json = DtJSONProvider(app)
_LOGGER = app.logger
counter_last_reset = dt.now(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)  # Previous UTC midnight


def _werkzeug_log_suppressor(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: tuple[Any, ...], **kwargs: dict[str, Any]) -> Any:
        if len(args) > 1 and (isinstance(args[1], str)):
            if (
                args[1].startswith("WARNING: This is a development server.")
                or "* Running on http" in args[1]
                or "Press CTRL+C to quit" in args[1]
            ):
                return None
            if " - - [" in args[1] and len(args) >= 5:
                # address = args[1].split(" - - [", 1)[0]
                request_line = str(args[2])
                status = str(args[3])
                # size = str(args[4])
                return func(args[0], 'Request: "%s" -> %s', request_line, status)
        return func(*args, **kwargs)

    return wrapper


def validate_call(api_key: str, site_id: str | None = None, counter: bool = True) -> tuple[int, Any, Any]:
    """Return the state of the API call."""
    global counter_last_reset  # noqa: PLW0603 pylint: disable=global-statement

    revert_key = True

    if counter_last_reset.day != dt.now(datetime.UTC).day:
        _LOGGER.info("Resetting API usage counter")
        for v in API_KEY_SITES.values():
            v["counter"] = 0
        counter_last_reset = dt.now(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    def error(code: str) -> tuple[int, Any, None]:
        return (
            ERROR_MESSAGE[code]["status"],
            {"response_status": {"error_code": code, "message": ERROR_MESSAGE[code]["message"]}},
            None,
        )

    if not api_key:
        return error(ERROR_KEY_REQUIRED)
    if api_key not in API_KEY_SITES:
        return error(ERROR_INVALID_KEY)
    if dt.now(datetime.UTC).minute in BOMB_429:
        return 429, "", None
    if dt.now(datetime.UTC).minute in BOMB_KEY:
        if API_KEY_SITES.get("1"):
            API_KEY_SITES["4"] = copy.deepcopy(API_KEY_SITES["1"])
            API_KEY_SITES.pop("1")
        revert_key = False
    if counter and API_KEY_SITES.get(api_key, {}).get("counter", 0) >= API_LIMIT:
        return error(ERROR_TOO_MANY_REQUESTS)
    if BOMB_418 and random.random() < 0.01:
        return 418, "", None  # An unusual status returned for fun, infrequently
    if site_id is not None:
        # Find the site by site_id
        site = next((site for site in API_KEY_SITES.get(api_key, {}).get("sites", {}) if site["resource_id"] == site_id), None)
        if not site:
            if API_KEY_SITES.get(api_key) is None:
                return error(ERROR_INVALID_KEY)
            return error(ERROR_SITE_NOT_FOUND)  # Technically the Solcast API should not return 404 (as documented), but it might
    else:
        site = None
    if counter:
        if API_KEY_SITES.get(api_key) is None:
            API_KEY_SITES[api_key]["counter"] += 1
            _LOGGER.info("API key %s has been used %s times", api_key, API_KEY_SITES[api_key]["counter"])
    if revert_key and API_KEY_SITES.get("4"):
        API_KEY_SITES["1"] = copy.deepcopy(API_KEY_SITES["4"])
        API_KEY_SITES.pop("4")
    return 200, None, site


@app.route("/rooftop_sites", methods=["GET"])
def get_sites() -> tuple[Any, int]:
    """Return sites for an API key."""

    api_key = request.args.get("api_key")
    if api_key is None:
        return "{}", 500

    response_code, issue, _ = validate_call(api_key, counter=False)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "{}", response_code

    get_sites = simulate.raw_get_sites(api_key)
    if get_sites is not None:
        return jsonify(get_sites), 200
    return "{}", 403


@app.route("/rooftop_sites/<site_id>/estimated_actuals", methods=["GET"])
def get_site_estimated_actuals(site_id: str) -> tuple[Any, int]:
    """Return simulated estimated actuals for a site."""

    api_key = request.args.get("api_key")
    if api_key is None:
        return "{}", 500

    response_code, issue, _ = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    if request.args.get("hours") is None:
        return "{}", 500
    return jsonify(simulate.raw_get_site_estimated_actuals(site_id, api_key, int(request.args["hours"]))), 200


@app.route("/rooftop_sites/<site_id>/forecasts", methods=["GET"])
def get_site_forecasts(site_id: str) -> tuple[Any, int]:
    """Return simulated forecasts for a site."""

    api_key = request.args.get("api_key")
    if api_key is None:
        return "{}", 500

    response_code, issue, _ = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code
    if request.args.get("hours") is None:
        return "{}", 500
    return jsonify(simulate.raw_get_site_forecasts(site_id, api_key, int(request.args["hours"]))), 200


@app.route("/data/historic/advanced_pv_power", methods=["GET"])
def get_site_estimated_actuals_advanced() -> tuple[Any, int]:
    """Return simulated advanced pv power history for a site."""

    def missing_parameter():
        _LOGGER.info("Missing parameter")
        return jsonify({"response_status": {"error_code": "MissingParameter", "message": "Missing parameter."}}), 400

    api_key = request.args.get("api_key")
    site_id = request.args.get("resource_id")
    if api_key is None or site_id is None:
        return "{}", 500

    try:
        start = dt.fromisoformat(request.args.get("start"))  # type:ignore[arg-type]
    except:  # noqa: E722
        _LOGGER.info("Missing start parameter %s", request.args.get("start"))
        return missing_parameter()
    try:
        end = dt.fromisoformat(request.args.get("end"))  # type: ignore[arg-type]
    except:  # noqa: E722
        end = None
    try:
        duration = isodate.parse_duration(request.args.get("duration"))
        end = start + duration
    except:  # noqa: E722
        duration = None
    if not end and not duration:
        _LOGGER.info("Missing end or duration parameter")
        return missing_parameter()
    _hours = int((end - start).total_seconds() / 3600)  # type: ignore[operator]
    period_end = simulate.get_period(start, timedelta(minutes=30))
    response_code, issue, _ = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    return jsonify(simulate.raw_get_site_estimated_actuals(site_id, api_key, _hours, key="pv_power_advanced", period_end=period_end)), 200  # pyright:ignore[reportCallIssue]


@app.route("/data/forecast/advanced_pv_power", methods=["GET"])
def get_site_forecasts_advanced() -> tuple[Any, int]:
    """Return simulated advanced pv power forecasts for a site."""

    api_key = request.args.get("api_key")
    site_id = request.args.get("resource_id")
    _hours = int(request.args.get("hours"))  # type:ignore[arg-type]
    period_end = simulate.get_period(dt.now(datetime.UTC), timedelta(minutes=30))
    response_code, issue, _ = validate_call(api_key, site_id)  # type:ignore[arg-type]
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    return jsonify(simulate.raw_get_site_forecasts(site_id, api_key, _hours, key="pv_power_advanced", period_end=period_end)), 200  # pyright:ignore[reportCallIssue]


def get_time_zone():
    """Attempt to read time zone from Home Assistant config."""

    try:
        with Path.open(Path(Path.cwd(), "../../../.storage/core.config")) as f:
            config = json.loads(f.read())
            simulate.set_time_zone(ZoneInfo(config["data"]["time_zone"]))
            _LOGGER.info("Time zone: %s", config["data"]["time_zone"])
    except:  # noqa: E722
        pass


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", help="Set the API call limit available, example --limit 100", type=int, required=False)
    parser.add_argument("--teapot", help="Infrequently generate 418 response", action="store_true", required=False)
    parser.add_argument(
        "--bomb429",
        help="The minute(s) of the hour to return API too busy, comma separated, example --bomb429 0-5,15,30,45",
        type=str,
        required=False,
    )
    parser.add_argument(
        "--bombkey",
        help="The minute(s) of the hour to use a different API key, comma separated, example --bombkey 0-5,15,30,45",
        type=str,
        required=False,
    )
    parser.add_argument("--port", help="Set the HTTPS listening port, example --port 8443", type=int, default=DEFAULT_PORT, required=False)
    parser.add_argument("--debug", help="Set Flask debug mode on", action="store_true", required=False, default=False)
    return parser


def _apply_args(args: argparse.Namespace) -> dict[str, int | bool | list[int]]:
    """Return simulator runtime values derived from CLI arguments."""

    api_limit = API_LIMIT
    bomb_429 = BOMB_429.copy()
    bomb_key = BOMB_KEY.copy()
    bomb_418 = BOMB_418

    if args.limit is not None:
        api_limit = args.limit
        _LOGGER.info("API limit has been set to %s", api_limit)
    if args.port != DEFAULT_PORT:
        _LOGGER.info("Listening port has been set to %s", args.port)
    if args.bomb429:
        bomb_429 = [int(x.strip()) for x in args.bomb429.split(",") if x.strip() and "-" not in x.strip()]
        if "-" in args.bomb429:
            for x_to_y in [x.strip() for x in args.bomb429.split(",") if "-" in x]:
                split = x_to_y.split("-")
                if len(split) != 2:
                    _LOGGER.error("Not two hyphen separated values for --bomb429")
                    continue
                bomb_429 += list(range(int(split[0].strip()), int(split[1].strip()) + 1))
        list.sort(bomb_429)
        _LOGGER.info("API too busy responses will be returned at minute(s) %s", bomb_429)
    if args.bombkey:
        bomb_key = [int(x.strip()) for x in args.bombkey.split(",") if x.strip() and "-" not in x.strip()]
        if "-" in args.bombkey:
            for x_to_y in [x.strip() for x in args.bombkey.split(",") if "-" in x]:
                split = x_to_y.split("-")
                if len(split) != 2:
                    _LOGGER.error("Not two hyphen separated values for --bombkey")
                    continue
                bomb_key += list(range(int(split[0].strip()), int(split[1].strip()) + 1))
        list.sort(bomb_key)
        _LOGGER.info("API key changes will happen at minute(s) %s", bomb_key)
    if args.teapot:
        bomb_418 = True
        _LOGGER.info("I'm a teapot status will be returned occasionally")

    return {
        "API_LIMIT": api_limit,
        "BOMB_429": bomb_429,
        "BOMB_KEY": bomb_key,
        "BOMB_418": bomb_418,
    }


def main(argv: list[str] | None = None) -> None:
    """Run the simulator."""

    random.seed()
    get_time_zone()
    args = build_parser().parse_args(argv)

    _LOGGER.info("Starting Solcast API simulator")
    _LOGGER.info("Originally written by @autoSteve")
    _LOGGER.info("Integration issues raised regarding this script will be closed without response")

    globals().update(_apply_args(args))
    serving = cast(Any, werkzeug.serving)
    werkzeug_log = serving._log
    serving._log = _werkzeug_log_suppressor(werkzeug_log)
    app.run(debug=args.debug, host="127.0.0.1", port=args.port, ssl_context=("cert.pem", "key.pem"))


if __name__ == "__main__":
    main()
