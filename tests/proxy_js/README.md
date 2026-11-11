# JS Cloudflare Proxy

This folder contains the JavaScript Cloudflare Worker + Durable Object proxy for Solcast scheduling and cached resource serving.

## Architecture

- Runtime: Cloudflare Worker (`proxy_cloudflare.js`).
- Coordinator: one Durable Object (`ProxyCoordinator`).
- State store: SQLite-backed Durable Object storage.
- Scheduler model:
  - Worker cron trigger is a fixed minute tick (`* * * * *`).
  - Coordinator computes due forecast/actual slots from schedule mode.
  - Retries are alarm-driven, not cron-driven.

## Behaviour

- Schedule modes:
  - `cron`
  - `daylight`
  - `all_day`
- Daily schedule rebuild at UTC midnight.
- Discovery-backed site registration and stale-site cleanup.
- Forecast collection is always scheduled; estimated-actuals collection is optional and disabled by default.
- Retry model is lock-step: one retryable failure puts participating resources into coordinated retry.
- While retry is active, scheduled tick collection is suppressed and retries are handled by the Durable Object alarm.

## Runtime controls (`wrangler.toml` `[vars]`)

- `SCHEDULE_MODE`: `cron`, `daylight`, `all_day`.
- `FORECAST_CRONS`, `ACTUALS_CRONS`: semicolon-separated cron list (used in `cron` mode).
- `UPDATE_DIVISIONS`: number of forecast slots for `daylight`/`all_day`.
- `SCHEDULE_EXCEPTIONS_UTC`: JSON array or CSV of UTC exceptions.
- `ENABLE_ESTIMATED_ACTUALS`: `true`/`false` toggle for scheduled estimated-actuals fetching (default: `false`).
- `LATITUDE`, `LONGITUDE`, `TIMEZONE`: required for `daylight`/`all_day`.
- `ACTUALS_DELAY`: minutes after local midnight baseline for actuals in `daylight`/`all_day`.
- `POLL_DELAY_SECONDS`: fixed follow delay in `cron` mode; configured/default reference for adaptive modes.
- `POLL_DELAY_MIN_SECONDS`: adaptive floor for `daylight`/`all_day` polling advice.
- `MAX_ATTEMPTS`: maximum retry failure cycles before `give_up`.
- `RETRY_BACKOFF_SECONDS`: retry backoff base for alarm scheduling.

## Endpoints

- `GET /rooftop_sites?format=json&api_key=...`
- `GET /rooftop_sites/<site_id>/forecasts?format=json&api_key=...&hours=...`
- `GET /rooftop_sites/<site_id>/estimated_actuals?format=json&api_key=...&hours=...`
- `GET /proxy-status` (alias `/proxy_status`)
- `POST /__scheduled` (internal/manual scheduler entrypoint)

## Example `wrangler.toml`

```toml
name = "solcast-proxy"
main = "proxy_cloudflare.js"
compatibility_date = "2026-11-10"

[triggers]
crons = ["* * * * *"]

[[durable_objects.bindings]]
name = "PROXY_COORDINATOR"
class_name = "ProxyCoordinator"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["ProxyCoordinator"]

[vars]
# Schedule modes: cron | daylight | all_day
SCHEDULE_MODE = "all_day"

# cron mode supports one or more cron expressions separated by semicolons (free tier has a number of crons limit)
#FORECAST_CRONS = "30 11,0,1,2,3,4 * * *"
#ACTUALS_CRONS = "05 14 * * *"

# daylight/all_day mode: number of spread updates per day
UPDATE_DIVISIONS = "9"

# Exceptions: JSON array or comma-separated list of HH:MM or full ISO timestamps in UTC
SCHEDULE_EXCEPTIONS_UTC = "[]"

# Required for daylight and all_day modes
LATITUDE = "-33.856784"
LONGITUDE = "151.215297"
TIMEZONE = "Australia/Sydney"

# Enable estimated actuals collection/scheduling.
# Default is off; set true to collect /estimated_actuals on schedule.
ENABLE_ESTIMATED_ACTUALS = "true"

# Minutes after local midnight for estimated actuals collection when using daylight/all_day mode.
# Proxy also adds a daily randomized +1..14 minute (and seconds) offset to mirror integration behaviour.
ACTUALS_DELAY = "0"

# Poll delay behaviour:
# - cron mode: fixed POLL_DELAY_SECONDS used as-is.
# - daylight/all_day: adaptive delay is advertised from observed tick timing; this value is kept as configured/default reference.
#POLL_DELAY_SECONDS = "30"
POLL_DELAY_MIN_SECONDS = "15"
MAX_ATTEMPTS = "5"
RETRY_BACKOFF_SECONDS = "45"

[observability.logs]
enabled = true
invocation_logs = true
```

## Deployment

Once the worker is deployed it will take approximately five minutes for the per-minute cron schedule to begin firing. With worker observability logs enabled the first every-minute `* * * * *` will eventually show up, and it is at this point that things like schedules are created for all-day and daylight scheduling options. The integration should not be configured to use the proxy until this first cron execution has occurred.

## Local simulator workflow

This repo includes a local launcher that wires Wrangler HTTPS to the simulator certificate and emulates cron locally.

### 1) Start the simulator

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar
python -u wsgi_sim.py --limit 5000 --port 8443 --use-guidance --bomb429 10-12
```

### 2) Validate simulator trust (optional)

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar
python run_proxy_js.py --check-only
```

### 3) Launch local JS proxy

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar
python run_proxy_js.py
```

What `run_proxy_js.py` does:

- Verifies simulator TLS using its live in-memory certificate.
- Starts `wrangler dev` with HTTPS on `127.0.0.1:9443`.
- Primes discovery for default accounts (`1`, `2`) unless overridden with `--api-key`.
- Dispatches one immediate `__scheduled` tick.
- Emulates configured cron triggers against `__scheduled`.

Use `--simulator-port` and `--port` to override defaults.

## Cloud deploy workflow (if logged in to Cloudflare...)

From this folder:

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar/proxy_js
wrangler deploy
```

## Verification examples

### Local (`wrangler dev`)

```bash
BASE_URL="https://127.0.0.1:9443"
API_KEY="1"
SITE_ID="1111-1111-1111-1111"

curl -k -sS "$BASE_URL/proxy-status"
curl -k -sS -D - "$BASE_URL/rooftop_sites?format=json&api_key=$API_KEY" -o /dev/null
curl -k -sS -D - "$BASE_URL/rooftop_sites/$SITE_ID/forecasts?format=json&api_key=$API_KEY&hours=336" -o /dev/null
curl -k -sS -D - "$BASE_URL/rooftop_sites/$SITE_ID/estimated_actuals?format=json&api_key=$API_KEY&hours=168" -o /dev/null
```

Manual tick trigger:

```bash
curl -k --get --data-urlencode 'cron=* * * * *' "$BASE_URL/__scheduled"
```

### Cloud (`workers.dev`)

```bash
BASE_URL="https://<worker>.<subdomain>.workers.dev"
API_KEY="<solcast-api-key>"

curl -sS "$BASE_URL/proxy-status"
curl -sS -D - "$BASE_URL/rooftop_sites?format=json&api_key=$API_KEY" -o /dev/null
```

## Home Assistant integration notes

- For local dev (`https://127.0.0.1:9443`), Wrangler uses a development certificate; set integration `ssl_verify` to `false` unless that cert is explicitly trusted, which it won't be.
- `x-proxy-poll-delay-seconds` behaviour:
  - `cron` mode: fixed from `POLL_DELAY_SECONDS`.
  - `daylight`/`all_day`: adaptive from observed tick timing, floored by `POLL_DELAY_MIN_SECONDS`.
- Estimated actuals schedule behaviour:
  - `ENABLE_ESTIMATED_ACTUALS=false` (default): no estimated-actuals slots are scheduled.
  - `ENABLE_ESTIMATED_ACTUALS=true`: estimated-actuals slots are scheduled per mode (`ACTUALS_CRONS` or `ACTUALS_DELAY`).

## Durable Object storage notes

The implementation uses SQLite-backed Durable Object storage. Deploying under a different Worker script/namespace creates a separate storage space.

For storage continuity keep Worker and DO migration lineage consistent.

## Troubleshooting

- `ReferenceError ... is not defined` after edits:
  - Wrangler hot-reload can lag; restart `run_proxy_js.py`.
- `SSL: WRONG_VERSION_NUMBER` from HA:
  - Verify HA URL is `https://...`, not `http://...`.
- `No simulator is listening on port ...`:
  - Start `wsgi_sim.py` first, then `run_proxy_js.py`.
- `not_fetched` responses:
  - Check `/proxy-status` and launcher logs (`[local-cron:info]`) to ensure scheduler is dispatching.

## Prerequisites

- Local launcher needs: Python 3.14+, Node.js 20+, `wrangler`, and `lsof`.
- Quick install (Debian/Ubuntu): `sudo apt install -y lsof nodejs npm && npm install -g wrangler`.
- Quick install (macOS/Homebrew): `brew install lsof node && npm install -g wrangler`.
- Verify tools: `python --version && node --version && npm --version && wrangler --version && lsof -v | head -n 1`.
- Optional for cloud deploy only: `wrangler login`.
- Windows: `run_proxy_js.py` is Linux/dev-container oriented (`/proc` + `lsof`); use WSL/dev-container, or run Wrangler manually.

## Response headers issued

The Home Assistant integration reacts to a small, explicit subset of proxy response headers.

### Discovery and scheduling headers

These are emitted on `/rooftop_sites` discovery responses and tell the integration how to follow the proxy schedule. They are mode-specific, and the useful set depends on whether the proxy is running in cron mode or daylight/all_day mode.

#### Shared discovery headers

These are always relevant regardless of schedule mode.

- `x-solcast-proxy: true` — discovery marker identifying the response as coming from a Solcast-compatible proxy.
- `x-proxy-name` / `x-proxy-version` — human-readable proxy identity and version metadata.
- `x-proxy-status-url` — status endpoint that can be used to inspect runtime health and scheduler state.
- `x-proxy-timezone` — schedule timezone; the integration expects UTC.
- `x-proxy-forecast-mode` — current forecast mode (`cron`, `daylight`, or `all_day`).
- `x-proxy-estimated-actuals-enabled: true|false` — whether scheduled estimated-actuals collection is active.

#### Cron mode headers

These are the headers that matter when the proxy is following a cron-driven forecast schedule.

- `x-proxy-forecast-cron` / `x-proxy-estimated-actuals-cron` — cron expressions the integration should use for scheduled follow-up.
- `x-proxy-poll-delay-seconds` — fixed per-collection follow delay used by the integration while polling a cron schedule.

#### Daylight and all_day mode headers

These are the headers that describe the adaptive schedule used for daylight and all-day collection. The tick statistics are emitted in every mode, but they are only materially used to drive the adaptive delay in daylight/all_day mode.

- `x-proxy-poll-delay-seconds` — adaptive follow delay recommended from observed tick timing.
- `x-proxy-poll-delay-confidence` — optional confidence signal for the adaptive scheduling estimate; not a hard gate, but a useful indicator of schedule stability.
- `x-proxy-observed-tick-second-p90` — observed tick timing percentile used to estimate safe follow delays in adaptive scheduling.
- `x-proxy-schedule-day-utc` — the currently active UTC schedule day in the proxy.
- `x-proxy-forecast-times-utc` — comma-separated forecast collection times in UTC.
- `x-proxy-estimated-actuals-times-utc` — comma-separated estimated-actuals collection times in UTC.

> In other words: `cron` mode is driven by the cron headers and fixed delay, while `daylight` and `all_day` are driven by the time-slot and adaptive polling headers rather than a fixed cron expression.

### Per-resource state and retry headers

These are emitted on individual resource responses, and the integration interprets them to decide whether to keep polling, retry, or wait on a shared upstream failure.

- `x-proxy-upstream-status` — most recent upstream HTTP status for this resource.
- `x-proxy-last-fetch-at` — timestamp of the last completed upstream attempt in ISO 8601 UTC format.
- `x-proxy-last-success-at` — timestamp of the last successful upstream fetch in ISO 8601 UTC format.
- `x-proxy-last-fetch-status` — current resource state, one of `not_fetched`, `clean_success`, `retry_success`, `retrying`, `give_up`, `budget_exhausted`, or `permanent_error`.
- `x-proxy-consecutive-failures` — number of consecutive failed attempts since the last success.
- `x-proxy-retries-used` — number of retry attempts used in the current cycle.
- `x-proxy-next-attempt-at` — ISO 8601 UTC timestamp for the next retry; empty when the resource is not retrying.
- `x-proxy-give-up` — boolean indicating the current retry cycle ended unsuccessfully.
- `x-proxy-halted` — boolean indicating a permanent resource failure that should stop retry scheduling.
- `x-proxy-fetch-in-progress` — boolean indicating a collection is still running and the next poll may be too soon.
- `x-proxy-collection-deferred` — boolean indicating the read was deferred because a shared collection gate is active.

### Cache and truncation headers

These are read when the proxy is serving cached data and when it is responding to truncated requests.

- `x-proxy-requested-hours` — client-requested forecast or actuals horizon.
- `x-proxy-cache-hours` — currently available cache coverage, in hours.
- `x-proxy-hours-truncated` — boolean indicating the cached response was truncated against the number of hours asked for.

### Notes for custom proxy authors

- The integration treats `x-proxy-next-attempt-at` as the authoritative retry schedule while a resource is retrying.
- `x-proxy-halted` is a hard stop: once it is true, the integration should stop queueing retries for that resource.
- `x-proxy-give-up` is not the same as a permanent halt; it tells the integration a retry cycle exhausted but the resource may recover on the next cycle.
- `x-proxy-collection-deferred` tells the integration that a shared upstream failure is blocking other resources even though they may have valid local cache data.
- When a resource is in flight, a short follow delay may still be too aggressive; `x-proxy-fetch-in-progress` is the indicator to honor.

A compatible proxy does not need to emit every header in the wider worker implementation, but these are the ones that matter for timing, retries, and schedule-follow behaviour.
