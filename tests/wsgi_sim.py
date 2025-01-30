#!/usr/bin/env python3
"""Solcast hobbyist API simulator.

Install:

* This script runs in a Home Assistant DevContainer
* Modify /etc/hosts (need sudo): 127.0.0.1 localhost api.solcast.com.au
* Script start: python3 -m wsgi_sim.py

Optional run arguments:

* --limit LIMIT      Set the API call limit available, example --limit 100 (There is no limit... 😉)
* --no429            Do not generate 429 response.
* --bomb429 w-x,y,z  The minute(s) of the hour to return API too busy, comma separated, example --bomb429 0-5,15,30-35,45
* --teapot           Infrequently generate 418 response.

Theory of operation:

* Configure integration to use either API key "1", "2", "3", or any combination of multiple. Any other key will return an error.
* API key 1 has two sites, API key 2 has one site, API key 3 has an impossible (for hobbyists) three sites.
* Forecast for every day is the same blissful-clear-day bell curve.
* As time goes on new forecast hour values are calculated based on the current get forecasts call time of day.
* 429 responses are given when minute=0, unless --no429 is set, or other minutes are specified with --bomb429.
* An occasionally generated "I'm a teapot" status can verify that the integration handles unknown status returns.
* The time zone used should be read from the Home Assistant configuration. If this fails then the zone will be Australia/Melbourne.

SSL certificate:

* The integration does not care whether the api.solcast.com.au certificate is valid, so a self-signed certificate is created by this simulator.
* To generate a new self-signed certificate run in this folder: openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 3650,
* or simply delete *.pem files and restart the simulator to generate new ones. The DevContainer will already have openssl installed.

Integration issues raised regarding the simulator will be closed without response.
Raise a pull request instead, suggesting a fix for whatever is wrong, or to add additional functionality.

Experimental support for advanced_pv_power:

* Should Solcast deprecate the legacy hobbyist API, then the advanced_pv_power API calls will probably be preferred, just with capabilities limited by Solcast.
* This simulator, and the integration are prepared should this occur.

"""  # noqa: INP001

import argparse
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
from logging.config import dictConfig
import os
from pathlib import Path
import random
import subprocess
import sys
import traceback
from zoneinfo import ZoneInfo

from simulator import API_KEY_SITES, SimulatedSolcast

simulate = SimulatedSolcast()


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
    import isodate
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
BOMB_429 = [0]
BOMB_KEY = []
ERROR_KEY_REQUIRED = "KeyRequired"
ERROR_INVALID_KEY = "InvalidKey"
ERROR_TOO_MANY_REQUESTS = "TooManyRequests"
ERROR_SITE_NOT_FOUND = "SiteNotFound"
ERROR_MESSAGE = {
    ERROR_KEY_REQUIRED: {"message": "An API key must be specified.", "status": 400},
    ERROR_INVALID_KEY: {"message": "Invalid API key.", "status": 403},
    ERROR_TOO_MANY_REQUESTS: {"message": "You have exceeded your free daily limit.", "status": 429},
    ERROR_SITE_NOT_FOUND: {"message": "The specified site cannot be found.", "status": 404},
}
GENERATE_418 = False
CHANGE_KEY = []
GENERATE_429 = True

dictConfig(  # Logger configuration
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
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

    def default(self, o):
        """Convert datetime to ISO format."""
        if isinstance(o, dt):
            return o.isoformat()

        return super().default(o)


app = Flask(__name__)
app.json = DtJSONProvider(app)
_LOGGER = app.logger
counter_last_reset = dt.now(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)  # Previous UTC midnight

try:
    with Path.open(Path("/etc/hosts")) as file:
        hosts = file.read()
        if "api.solcast.com.au" not in hosts:
            _LOGGER.error("Hosts file contains:\n\n%s", hosts)
            _LOGGER.error("Please add api.solcast.com.au as /etc/hosts localhost alias")
            app = None
            sys.exit()
except Exception as e:  # noqa: BLE001
    _LOGGER.error("%s: %s", e, traceback.format_exc())


def validate_call(api_key, site_id=None, counter=True):
    """Return the state of the API call."""
    global counter_last_reset  # noqa: PLW0603 pylint: disable=global-statement

    revert_key = True

    if counter_last_reset.day != dt.now(datetime.UTC).day:
        _LOGGER.info("Resetting API usage counter")
        for v in API_KEY_SITES.values():
            v["counter"] = 0
        counter_last_reset = dt.now(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    def error(code):
        return (
            ERROR_MESSAGE[code]["status"],
            {"response_status": {"error_code": code, "message": ERROR_MESSAGE[code]["message"]}},
            None,
        )

    if not api_key:
        return error(ERROR_KEY_REQUIRED)
    if api_key not in API_KEY_SITES:
        return error(ERROR_INVALID_KEY)
    if GENERATE_429 and dt.now(datetime.UTC).minute in BOMB_429:
        return 429, "", None
    if dt.now(datetime.UTC).minute in BOMB_KEY:
        if API_KEY_SITES.get("1"):
            API_KEY_SITES["4"] = copy.deepcopy(API_KEY_SITES["1"])
            API_KEY_SITES.pop("1")
        revert_key = False
    if counter and API_KEY_SITES.get(api_key, {}).get("counter", 0) >= API_LIMIT:
        return error(ERROR_TOO_MANY_REQUESTS)
    if GENERATE_418 and random.random() < 0.01:
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
def get_sites():
    """Return sites for an API key."""

    api_key = request.args.get("api_key")

    response_code, issue, _ = validate_call(api_key, counter=False)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    get_sites = simulate.raw_get_sites(api_key)
    if get_sites is not None:
        return jsonify(get_sites), 200
    return {}, 403


@app.route("/rooftop_sites/<site_id>/estimated_actuals", methods=["GET"])
def get_site_estimated_actuals(site_id):
    """Return simulated estimated actials for a site."""

    api_key = request.args.get("api_key")
    response_code, issue, _ = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    return jsonify(simulate.raw_get_site_estimated_actuals(site_id, api_key, int(request.args.get("hours")))), 200


@app.route("/rooftop_sites/<site_id>/forecasts", methods=["GET"])
def get_site_forecasts(site_id):
    """Return simulated forecasts for a site."""

    api_key = request.args.get("api_key")
    response_code, issue, _ = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code
    return jsonify(simulate.raw_get_site_forecasts(site_id, api_key, int(request.args.get("hours")))), 200


@app.route("/data/historic/advanced_pv_power", methods=["GET"])
def get_site_estimated_actuals_advanced():
    """Return simulated advanced pv power history for a site."""

    def missing_parameter():
        _LOGGER.info("Missing parameter")
        return jsonify({"response_status": {"error_code": "MissingParameter", "message": "Missing parameter."}}), 400

    api_key = request.args.get("api_key")
    site_id = request.args.get("resource_id")
    try:
        start = dt.fromisoformat(request.args.get("start"))
    except:  # noqa: E722
        _LOGGER.info("Missing start parameter %s", request.args.get("start"))
        return missing_parameter()
    try:
        end = dt.fromisoformat(request.args.get("end"))
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
    if not duration:
        _hours = int((end - start).total_seconds() / 3600)
    period_end = simulate.get_period(start, timedelta(minutes=30))
    response_code, issue, site = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    return jsonify(simulate.raw_get_site_estimated_actuals(site_id, api_key, _hours, key="pv_power_advanced", period_end=period_end)), 200


@app.route("/data/forecast/advanced_pv_power", methods=["GET"])
def get_site_forecasts_advanced():
    """Return simulated advanced pv power forecasts for a site."""

    api_key = request.args.get("api_key")
    site_id = request.args.get("resource_id")
    _hours = int(request.args.get("hours"))
    period_end = simulate.get_period(dt.now(datetime.UTC), timedelta(minutes=30))
    response_code, issue, site = validate_call(api_key, site_id)
    if response_code != 200:
        return jsonify(issue) if issue != "" else "", response_code

    return jsonify(simulate.raw_get_site_forecasts(site_id, api_key, _hours, key="pv_power_advanced", period_end=period_end)), 200


def get_time_zone():
    """Attempt to read time zone from Home Assistant config."""

    try:
        with Path.open(Path(Path.cwd(), "../../../.storage/core.config")) as f:
            config = json.loads(f.read())
            simulate.set_time_zone(ZoneInfo(config["data"]["time_zone"]))
            _LOGGER.info("Time zone: %s", config["data"]["time_zone"])
    except:  # noqa: E722
        pass


if __name__ == "__main__":
    random.seed()
    _LOGGER.info("Starting Solcast API simulator, will listen on localhost:443")
    _LOGGER.info("Originally written by @autoSteve")
    _LOGGER.info("Integration issues raised regarding this script will be closed without response because it is a development tool")
    get_time_zone()

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", help="Set the API call limit available, example --limit 100", type=int, required=False)
    parser.add_argument("--no429", help="Do not generate 429 response", action="store_true", required=False)
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
    parser.add_argument("--debug", help="Set Flask debug mode on", action="store_true", required=False, default=False)
    args = parser.parse_args()
    if args.limit:
        API_LIMIT = args.limit
        _LOGGER.info("API limit has been set to %s", API_LIMIT)
    if args.no429:
        GENERATE_429 = False
        _LOGGER.info("429 responses will not be generated")
    if args.bomb429:
        if not GENERATE_429:
            _LOGGER.error("Cannot specify --bomb429 with --no429")
            sys.exit()
        BOMB_429 = [int(x) for x in args.bomb429.split(",") if "-" not in x]  # Simple minutes of the hour.
        if "-" in args.bomb429:
            for x_to_y in [x for x in args.bomb429.split(",") if "-" in x]:  # Minute of the hour ranges.
                split = x_to_y.split("-")
                if len(split) != 2:
                    _LOGGER.error("Not two hyphen separated values for --bomb429")
                BOMB_429 += list(range(int(split[0]), int(split[1]) + 1))
        list.sort(BOMB_429)
        _LOGGER.info("API too busy responses will be returned at minute(s) %s", BOMB_429)
    if args.bombkey:
        BOMB_KEY = [int(x) for x in args.bombkey.split(",") if "-" not in x]  # Simple minutes of the hour.
        if "-" in args.bombkey:
            for x_to_y in [x for x in args.bombkey.split(",") if "-" in x]:  # Minute of the hour ranges.
                split = x_to_y.split("-")
                if len(split) != 2:
                    _LOGGER.error("Not two hyphen separated values for --bombkey")
                BOMB_KEY += list(range(int(split[0]), int(split[1]) + 1))
        list.sort(BOMB_KEY)
        _LOGGER.info("API key changes will be happen at minute(s) %s", BOMB_KEY)
    if args.teapot:
        GENERATE_418 = True
        _LOGGER.info("I'm a teapot response will be sometimes generated")

    if API_LIMIT == 50:
        _LOGGER.info("API limit is default %s, usage has been reset", API_LIMIT)

    app.run(debug=args.debug, host="127.0.0.1", port=443, ssl_context=("cert.pem", "key.pem"))
