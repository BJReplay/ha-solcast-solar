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
mkdir -p ~/solcast-proxy-worker
cd ~/solcast-proxy-worker
```

Copy `proxy_cloudflare.py` into this project root and create `wrangler.toml`
from the example below.

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
compatibility_flags = ["python_workers", "disable_python_external_sdk"]

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

## Local test with simulator on port 8443

For development, the worker can point at a local simulator using
`SOLCAST_HOST` + `SOLCAST_PORT` over HTTPS.

### Local prerequisites in this dev container

This dev container does not include Node.js, npm, or Wrangler by default.
Install them before running local Cloudflare Worker tests.

Check what is installed:

```bash
for c in node npm wrangler; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "$c: OK"
  else
    echo "$c: MISSING"
  fi
done
```

Install Node.js and npm (user-local via nvm):

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"
nvm install --lts
nvm use --lts
```

Install Wrangler:

```bash
npm install --global wrangler --allow-scripts=esbuild,workerd
```

If your shell cannot find Wrangler after install, add npm global bin to PATH:

```bash
export PATH="$(npm config get prefix)/bin:$PATH"
hash -r
```

Verify toolchain:

```bash
node --version
npm --version
wrangler --version
```

### Simulator certificate and startup

There are two separate TLS connections: Home Assistant → Wrangler on port 9443,
and the Worker → simulator on port 8443. Home Assistant's advanced
`ssl_verify: false` option affects only the first connection. It does not
disable the Worker's upstream certificate verification.

The simulator generates a fresh self-signed certificate valid for `localhost`
in memory at startup. Neither the certificate nor the private key is written
to disk, and existing `cert.pem`/`key.pem` files are ignored. This uses Linux
memory-backed descriptors in the dev container, not Werkzeug's `"adhoc"`
context, which creates temporary PEM files.

Start (or restart) the simulator:

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar
python -u wsgi_sim.py --limit 5000 --port 8443 --use-guidance --bomb429 10-12
```

Use the local launcher in another terminal. It finds the process listening on
the configured simulator port, locates its in-memory public certificate, verifies
the localhost TLS handshake, and supplies that certificate to Wrangler. It
automatically overrides a stale `NODE_EXTRA_CA_CERTS` for the launched process;
no manual export or PEM file is needed. It never stops the simulator or an
existing Wrangler process. Run both as the same user in the same dev container.

Check certificate discovery and TLS without starting Wrangler:

```bash
python /workspaces/homeAssistant-core/tests/components/solcast_solar/run_proxy_cloudflare.py --check-only
```

This must print `Verified simulator HTTPS`. An absent listener, missing
in-memory certificate, or failed verification stops the launcher with a clear
error before Wrangler starts. The check makes no API requests and spends no
simulator quota. Linux `/proc` access and `lsof` are required (both available in
this dev container).

If you already created a Worker project above, open that directory now.
If not, create one first:

```bash
mkdir -p ~/solcast-proxy-worker
cd ~/solcast-proxy-worker
```

For local testing from this repository, keep
`/workspaces/homeAssistant-core/tests/components/solcast_solar/proxy_cloudflare.py`
as the single source of truth and point your local `wrangler.toml` `main`
directly at that file:

```toml
name = "solcast-proxy"
main = "/workspaces/homeAssistant-core/tests/components/solcast_solar/proxy_cloudflare.py"
compatibility_date = "2026-11-05"
compatibility_flags = ["python_workers", "disable_python_external_sdk"]
```

Then set local vars in `wrangler.toml`:

```toml
[vars]
SOLCAST_HOST = "localhost"
SOLCAST_PORT = "8443"
FORECAST_CRON = "55 2,7,12,17 * * *"
ACTUALS_CRON = "45 22 * * *"
POLL_DELAY_SECONDS = "5"
MAX_ATTEMPTS = "5"
RETRY_BACKOFF_SECONDS = "45"
```

Start Wrangler through the launcher, with HTTPS enabled for Home Assistant:

```bash
python /workspaces/homeAssistant-core/tests/components/solcast_solar/run_proxy_cloudflare.py
```

The default configuration is the repository's
`tests/components/solcast_solar/solcast-proxy-worker/wrangler.toml`. If you created
a separate project above, pass `--config /absolute/path/to/wrangler.toml` to
both the check and launch commands. The launcher reads `SOLCAST_HOST` and
`SOLCAST_PORT` from that file; the host must be `localhost`. Wrangler must be
on `PATH`. The local HTTPS port defaults to 9443; override it with `--port`.
The launcher replaces itself with Wrangler, so Ctrl+C stops the Worker normally.
It does not modify the Worker configuration or synchronise source copies.

Important protocol note for local testing:

- `wrangler dev` defaults to HTTP, but `--local-protocol https` enables HTTPS.
- The launcher enables `--local-protocol https`. Use `https://localhost:9443` (or
  `https://127.0.0.1:9443`) in HA proxy settings.
- Wrangler supplies a development certificate. Set the integration's advanced
  `ssl_verify` option to `false` for this local listener unless HA trusts its
  certificate and the hostname matches. HTTPS encryption remains enabled.
- An HTTPS URL against a plain HTTP listener produces `SSL: WRONG_VERSION_NUMBER`;
  disabling certificate verification cannot fix a protocol mismatch.
- A working `/proxy-status` response does not test upstream TLS. Test
  `/rooftop_sites` too: it actually contacts the simulator.

Trigger scheduled runs manually:

```bash
curl -k "https://127.0.0.1:9443/__scheduled?cron=55+2,7,12,17+*+*+*"
curl -k "https://127.0.0.1:9443/__scheduled?cron=45+22+*+*+*"
```

Check status and resource calls:

```bash
curl -k "https://127.0.0.1:9443/proxy-status"
curl -k "https://127.0.0.1:9443/rooftop_sites?format=json&api_key=1"
```

Here `-k` bypasses verification of Wrangler's development certificate only;
it does not disable verification between the Worker and the simulator.

Notes:

- Upstream requests are HTTPS-only in this worker.
- Use `localhost`, not `127.0.0.1`, for `SOLCAST_HOST`: the simulator certificate
  contains a DNS SAN for `localhost`, not an IP SAN.
- Each simulator restart generates a new certificate. Stop Wrangler and run the
  launcher again to pick up the current certificate automatically. The launcher
  does not rotate trust inside an already-running Wrangler process. Flask's
  debug reloader is disabled to keep the certificate stable during a run.
- Both local connections use HTTPS in this setup; no PEM-file setup is needed.
