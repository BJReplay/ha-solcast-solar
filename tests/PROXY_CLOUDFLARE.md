# Solcast Proxy on Cloudflare Workers

This guide is for a Cloudflare Worker deployment of a Solcast proxy.

## Architecture

- Runtime: Cloudflare Workers.
- Coordinator: one Durable Object named `ProxyCoordinator`.
- State store: SQLite-backed Durable Object storage (Workers Free compatible).
- Main schedules: two cron triggers (forecasts + estimated actuals).
- Retry engine: Durable Object alarm with second-level backoff.
- API: Worker `Default.fetch()` forwards API requests to the coordinator.

`/rooftop_sites` is a live discovery passthrough to upstream Solcast. Forecast/actual reads are cache-oriented; scheduled runs perform normal upstream collection.

### Stale rooftop site cleanup

Each successful `/rooftop_sites` discovery reconciles that account's cached resources with the upstream site list. Sites no longer listed have both their forecast and estimated-actuals caches and collection metadata removed from persisted state, so future scheduled collections and retries no longer request them. Existing caches for retained sites and other accounts are preserved. A valid empty site list removes all resources for that account; if no resources remain anywhere, the pending retry alarm and retry state are cleared.

Failed or malformed discovery responses do not remove anything. Cleanup uses the existing discovery request and adds no upstream API calls or separate cleanup schedule. It takes effect when the account next performs discovery, not merely when time passes. Accounts that stop using the proxy are not automatically expired.

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

- If any resource gets a retryable failure, all sites/accounts in that scheduled collection kind enter retry mode.
- If any resource gets upstream `429`, all resources participating in that cycle are treated as rate-limited; unrelated caches and collection metadata are unchanged.
- Retries are coordinated by one Durable Object alarm.
- Retry kinds are persisted and shown in `/proxy-status`.

This matches the rule: one out, all out; all succeed, happy days.

## Create a Worker project

```bash
mkdir -p ~/solcast-proxy-worker
cd ~/solcast-proxy-worker
```

Copy `proxy_cloudflare.py` into this project root and create `wrangler.toml` from the example below.

## Project files

Minimum layout:

- `proxy_cloudflare.py`
- `wrangler.toml`

## wrangler.toml example

Note that the `cron` details are duplicated to allow sharing the proxy schedule with a HA Solcast integration.

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
new_sqlite_classes = ["ProxyCoordinator"]

[vars]
SOLCAST_HOST = "api.solcast.com.au"
SOLCAST_PORT = "443"
FORECAST_CRON = "55 2,7,12,17 * * *"
ACTUALS_CRON = "45 22 * * *"
POLL_DELAY_SECONDS = "30"
MAX_ATTEMPTS = "5"
RETRY_BACKOFF_SECONDS = "45"
```

## Durable Objects and free tier

Durable Objects are available on Workers Free, but only with the SQLite storage backend. This configuration uses `new_sqlite_classes`, not `new_classes`, which selects the legacy key-value backend and is not supported on Workers Free.

- `[[durable_objects.bindings]]` makes the `ProxyCoordinator` namespace available to the Worker as `env.PROXY_COORDINATOR`. The Worker uses one named object, `global`, to coordinate all registered accounts, caches and lock-step retries.
- `[[migrations]]` declares the initial creation of that class and its storage backend. `tag = "v1"` identifies this first creation; it does not imply that the Worker has previously been deployed. Keep this section for the first deployment and subsequent deployments using this migration history.

See Cloudflare's [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) and [class configuration documentation](https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/).

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

- SQLite-backed Durable Objects currently include 100,000 requests/day, 13,000 GB-s of duration/day, 5 million rows read/day, 100,000 rows written/day and 5 GB of total storage on Workers Free. These are account-level allowances.
- Storage `get()`/`put()` calls use a hidden SQLite table and count toward row operations; setting an alarm also counts as a row write.
- Durable Object alarm invocations count as requests. Upstream I/O contributes to active wall-clock duration, even when it consumes little CPU.
- Workers have their own request, CPU and Cron Trigger limits in addition to Durable Object limits. Free-tier eligibility does not guarantee this workload stays within every limit; monitor deployed usage. Exceeding a free Durable Object allowance causes the corresponding operations to fail, with daily allowances resetting at 00:00 UTC.
- Suggested conservative starting point:
  - `MAX_ATTEMPTS = "5"`
  - `RETRY_BACKOFF_SECONDS = "45"`

## Local test with simulator on port 8443

For development, the worker can point at a local simulator using `SOLCAST_HOST` + `SOLCAST_PORT` over HTTPS.

### Local prerequisites in this dev container

This dev container does not include Node.js, npm, or Wrangler by default. Install them before running local Cloudflare Worker tests.

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

There are two separate TLS connections: Home Assistant to Wrangler on port 9443, and the Worker to simulator on port 8443. Home Assistant's advanced `ssl_verify: false` option affects only the first connection. It does not disable the Worker's upstream certificate verification.

The simulator generates a fresh self-signed certificate valid for `localhost` in memory at startup. Neither the certificate nor the private key is written to disk. This uses Linux memory-backed descriptors in the dev container.

Start (or restart) the simulator:

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar
python -u wsgi_sim.py --limit 5000 --port 8443 --use-guidance --bomb429 10-12
```

Use the local launcher in another terminal. It finds the process listening on the configured simulator port, locates its in-memory public certificate, verifies the localhost TLS handshake, and supplies that certificate to Wrangler. It automatically overrides a stale `NODE_EXTRA_CA_CERTS` for the launched process; no manual export or PEM file is needed.

Check certificate discovery and TLS without starting Wrangler:

```bash
python /workspaces/homeAssistant-core/tests/components/solcast_solar/run_proxy_cloudflare.py --check-only
```

This must print `Verified simulator HTTPS`. An absent listener, missing in-memory certificate, or failed verification stops the launcher with a clear error before Wrangler starts. Linux `/proc` access and `lsof` are required (both generally available in a dev container).

For local testing from this repository, point a local `wrangler.toml` `main` at `/workspaces/homeAssistant-core/tests/components/solcast_solar/proxy_cloudflare.py`.

```toml
name = "solcast-proxy"
main = "/workspaces/homeAssistant-core/tests/components/solcast_solar/proxy_cloudflare.py"
compatibility_date = "2026-11-05"
compatibility_flags = ["python_workers", "disable_python_external_sdk"]
```

Then set local vars in the same `toml` file:

```toml
[vars]
SOLCAST_HOST = "localhost"
SOLCAST_PORT = "8443"
FORECAST_CRON = "*/5 * * * *"
ACTUALS_CRON = "05 14 * * *"
POLL_DELAY_SECONDS = "5"
MAX_ATTEMPTS = "5"
RETRY_BACKOFF_SECONDS = "45"
```

Start Wrangler through the launcher, with HTTPS enabled for Home Assistant:

```bash
cd /workspaces/homeAssistant-core/tests/components/solcast_solar
python ./run_proxy_cloudflare.py
```

The default configuration is `wrangler.toml` in the current directory. Run from `tests/components/solcast_solar` to use the repository's local configuration. The launcher can also accept a path to the wrangler configuration.

`--config /absolute/path/to/wrangler.toml`

The launcher reads `SOLCAST_HOST` and `SOLCAST_PORT` from that file; the host must be `localhost`. Wrangler must be on `PATH`. The local HTTPS port defaults to 9443; override it with `--port`. The launcher streams Wrangler's output, hiding only the attached-module table. After Wrangler reports that it is ready, the launcher discovers simulator accounts `1` and `2` and immediately seeds both forecast and estimated-actuals caches. It then dispatches the configured cron events locally. To seed different accounts, pass `--api-key` for each account, for example `--api-key 1 --api-key 3`; this replaces the default account list. Both `[triggers].crons` and the advertised `FORECAST_CRON` and `ACTUALS_CRON` must match; startup rejects a mismatch. All schedules use UTC. `[local-cron:info]` messages report dispatch and completion; failures are logged as `[local-cron:error]`.

Important protocol note for local testing:

- The launcher enables `--local-protocol https`. Use `https://localhost:9443` (or `https://127.0.0.1:9443`) in HA proxy settings.
- Wrangler supplies a development certificate. Set the integration's advanced `ssl_verify` option to `false` for this local listener unless HA trusts its certificate and the hostname matches. HTTPS encryption remains enabled.
- An HTTPS URL against a plain HTTP listener produces `SSL: WRONG_VERSION_NUMBER`; disabling certificate verification cannot fix a protocol mismatch.
- A working `/proxy-status` response does not test upstream TLS. Test `/rooftop_sites`, which contacts the simulator.

### Collection timing and an empty cache

Cloudflare executes Cron Triggers when deployed, but `wrangler dev` does not execute them automatically. `--test-scheduled` only exposes an endpoint for invoking scheduled handlers. The launcher supplies the missing local scheduler; starting raw Wrangler does not.

Startup seeding registers the selected accounts with `/rooftop_sites`, invokes both collection handlers regardless of their next scheduled times, and checks `/proxy-status` before logging `Startup cache seeding complete`. After seeding, the launcher follows future cron occurrences.

Wait for `Startup cache seeding complete` before starting or reloading HA. No manual discovery or scheduled trigger is required for the selected accounts. If the simulator rejects a request (for example during `--bomb429` minutes), startup logs a seeding error and normal scheduling continues. Until collection succeeds, resource reads can still return HTTP 503 with `x-proxy-last-fetch-status: not_fetched`. Those reads do not contact the simulator, so there will be no corresponding forecast/actuals request in its log.

To register an additional account after startup or invoke a collection manually, use the exact cron strings from the active configuration. These examples match the repository's local configuration:

```bash
curl -k "https://127.0.0.1:9443/rooftop_sites?format=json&api_key=1"
curl -k "https://127.0.0.1:9443/rooftop_sites?format=json&api_key=2"
curl -k --get --data-urlencode 'cron=*/5 * * * *' "https://127.0.0.1:9443/__scheduled"
curl -k --get --data-urlencode 'cron=05 14 * * *' "https://127.0.0.1:9443/__scheduled"
```

Check status and resource calls:

```bash
curl -k "https://127.0.0.1:9443/proxy-status"
curl -k "https://127.0.0.1:9443/rooftop_sites?format=json&api_key=1"
```

Here `-k` bypasses verification of Wrangler's development certificate.

Notes:

- Use `localhost`, not `127.0.0.1`, for `SOLCAST_HOST`: the simulator certificate contains a DNS SAN for `localhost`, not an IP SAN.
- Each simulator restart generates a new certificate. Stop Wrangler and run the launcher again to pick up the current certificate automatically. The launcher does not rotate trust inside an already-running Wrangler process. Flask's debug reloader is disabled to keep the certificate stable during a run.
- Both local connections use HTTPS in this setup; no PEM-file setup is needed.
