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
- Forecast and estimated-actuals collection cached per site/account.
- Retry model is lock-step: one retryable failure puts participating resources into coordinated retry.
- While retry is active, scheduled tick collection is suppressed and retries are handled by the Durable Object alarm.

## Runtime controls (`wrangler.toml` `[vars]`)

- `SCHEDULE_MODE`: `cron`, `daylight`, `all_day`.
- `FORECAST_CRONS`, `ACTUALS_CRONS`: semicolon-separated cron list (used in `cron` mode).
- `UPDATE_DIVISIONS`: number of forecast slots for `daylight`/`all_day`.
- `SCHEDULE_EXCEPTIONS_UTC`: JSON array or CSV of UTC exceptions.
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
