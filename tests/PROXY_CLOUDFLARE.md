# Solcast Proxy on Cloudflare Workers

This guide is for a standalone Cloudflare Worker deployment of a Solcast proxy
with minimal CPU usage.

## Architecture

- Runtime: Cloudflare Workers.
- Coordinator: one Durable Object named `ProxyCoordinator`.
- State store: Durable Object storage.
- Main schedules: two cron triggers (forecasts + estimated actuals).
- Retry engine: Durable Object alarm with second-level backoff.
- API: Worker `on_fetch` forwards API requests to the coordinator.

`/rooftop_sites` is a live discovery passthrough to upstream Solcast.
Forecast/actual reads are cache-oriented; scheduled runs perform normal
upstream collection.

## Compatibility

The Home Assistant integration depends on these headers and semantics:

- Discovery response headers include:
  - `x-solcast-proxy: true`
  - `x-proxy-forecast-cron`
  - `x-proxy-estimated-actuals-cron`
  - `x-proxy-timezone`
  - `x-proxy-poll-delay-seconds`
- Resource responses include collection status headers.
- `x-proxy-next-attempt-at` is present only while retrying.

## Retry model (lock-step)

- If any resource gets a retryable failure, all resources enter retry mode.
- If any resource gets upstream `429`, all resources are treated as rate-limited.
- Retries are coordinated by one Durable Object alarm.
- If a retry cycle succeeds for all resources, retry mode clears for everyone.

This matches the rule: one out, all out; all succeed, happy days.

## Create a Worker project

```bash
mkdir solcast-proxy-worker
cd solcast-proxy-worker
wrangler init --yes
```

Copy `proxy_cloudflare.py` into this project root.

## Project files

Minimum layout:

- `proxy_cloudflare.py`
- `wrangler.toml`

## wrangler.toml example

Note that the `cron` details are duplicated to allow sharing the proxy
schedule with a HA Solcast integration.

```toml
name = "solcast-proxy"
main = "proxy_cloudflare.py"
compatibility_date = "2026-11-05"

[triggers]
crons = [
  "55 2,7,12,17 * * *",
  "45 22 * * *"
]

[[durable_objects.bindings]]
name = "PROXY_COORDINATOR"
class_name = "ProxyCoordinator"

[[migrations]]
tag = "v1"
new_classes = ["ProxyCoordinator"]

[vars]
SOLCAST_HOST = "api.solcast.com.au"
SOLCAST_PORT = "443"
FORECAST_CRON = "55 2,7,12,17 * * *"
ACTUALS_CRON = "45 22 * * *"
POLL_DELAY_SECONDS = "5"
MAX_ATTEMPTS = "5"
RETRY_BACKOFF_SECONDS = "45"
```

## Deploy

```bash
wrangler deploy
```

Optional route binding:

```bash
wrangler deploy --route "proxy.example.com/*"
```

## Endpoints

- `GET /rooftop_sites?format=json&api_key=...`
- `GET /rooftop_sites/<site_id>/forecasts?format=json&api_key=...&hours=...`
- `GET /rooftop_sites/<site_id>/estimated_actuals?format=json&api_key=...&hours=...`
- `GET /proxy-status` (alias: `/proxy_status`)

## Security

- API keys and resource state are persisted in Durable Object storage.
- Protect endpoint access with Cloudflare Access or network controls.
- Treat persisted state as sensitive.

## Free-tier constraints

- Cron and request invocation limits apply.
- Alarm invocations also count, but only while retries are active.
- Suggested conservative starting point:
  - `MAX_ATTEMPTS = "5"`
  - `RETRY_BACKOFF_SECONDS = "45"`
