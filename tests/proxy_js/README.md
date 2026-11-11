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

## Behavior

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
# Proxy also adds a daily randomized +1..14 minute (and seconds) offset to mirror integration behavior.
ACTUALS_DELAY = "0"

# Poll delay behavior:
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

Once the worker is deployed it will take approxmately five minutes for the per-minute cron schedule to begin firing. With worker observability logs enabled the first every-minute `* * * * *` will eventually show up, and it is at this point that things like schedules are created for all-day and daylight scheduling options. The integration should not be configured to use the proxy until this first cron execution has occurred.

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
- `x-proxy-poll-delay-seconds` behavior:
  - `cron` mode: fixed from `POLL_DELAY_SECONDS`.
  - `daylight`/`all_day`: adaptive from observed tick timing, floored by `POLL_DELAY_MIN_SECONDS`.
- Estimated actuals schedule behavior:
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
