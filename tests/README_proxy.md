@ -0,0 +1,89 @@
# Scheduled Solcast proxy

This is a Solcast proxy. Site discovery is pass-through; forecast and actuals consumer reads never touch the upstream API, including when the cache is empty.

## Running against the WSGI simulator

Install the standalone dependencies using requirements_proxy.txt in this directory. Start the existing WSGI simulator on its usual HTTPS port, then start the proxy from the repository present root, for example:

```sh
python3 tests/components/solcast_solar/proxy.py --solcast-port 8443 --port 9443
```

Or run it against the Solcast API at api.solcast.com.au using real API keys.

Point the integration's `solcast_url` advanced option at `https://127.0.0.1` and `solcast_port` at `9443` for the proxy. No API keys are supplied at startup. They are learned from the caller's `api_key` query parameter, including multiple accounts:

- `/rooftop_sites` forwards the key unchanged to the upstream discovery call and registers the returned sites for scheduled collection.
- If forecasts or actuals are the first request, the key and requested site are registered locally for both collection schedules. Additional sites can be registered this way until live discovery supplies the account's site list.
- A resource-first request with no cached data returns 503 and the next cron timestamp. It does not make an upstream discovery or quota-bearing data call. The upstream validates the key/site during scheduled collection; permanent failures are then reported via the resource headers.
- Subsequent consumers using the same key/site share the cache. Scheduled fetches use exactly that caller-provided key, never a proxy-owned credential.

The upstream defaults to `api.solcast.com.au` on port 443.

Both connections always use HTTPS. Upstream certificate and hostname validation are enabled by default. For local simulator testing with self-signed certificates, use `--solcast-host 127.0.0.1 --solcast-port 8443 --no-verify`.

The proxy always creates an ad-hoc self-signed TLS certificate for its own listener.

The Solcast integration has advanced option `ssl_verify` for its configured Solcast URL. The default is `true` (certificate and hostname verification enabled), with `false` available as an explicit opt-out when users knowingly accept that risk.

Set it in `config/solcast_solar/solcast-advanced.json` (or `config/solcast-advanced.json` when not using a discrete folder), for example:

```json
{
	"solcast_url": "https://127.0.0.1",
	"solcast_port": 9443,
	"ssl_verify": false
}
```

Getting things cranked up initially may require a Solcast integration reload to ask for the sites data.

## Collection and consumer parameters

Defaults are forecasts at `55 2,7,12,17 * * *` and estimated actuals at
`45 22 * * *`, strictly UTC with no DST adjustment. `--forecast-cron` and
`--actuals-cron` accept five-field cron expressions. For quick proxy testing, both may be set to `* * * * *`. The first caller request registers the next scheduled occurrence; startup makes no upstream requests. Registration does not spend forecast or actuals quota to bootstrap immediately. Until collection succeeds, resource reads return 503 with collection headers.

Every scheduled fetch sends the correct account's `api_key`, `format=json`, and `hours`. Forecasts always request `hours=336`, including retries. Requests above 336 hours are invalid and can return HTTP 400. An account may return a shorter available horizon without padding. The proxy does not reconstruct the integration's local midnight, future-day setting, or DST rules. There are no forecast-hours, actuals-hours, or timezone CLI settings. The integration remains responsible for choosing its own requested hours.

Estimated actuals always request `hours=168`, including retries. For the legacy hobbyist API used here, Solcast caps returned history at the account's available limit, never exceeding 168 hours, without padding. Consumer hours do not alter either collection horizon. Each account/site/resource has an independent cache and retry state. Repeated discovery does not reset its schedule or trigger another collection.

Consumer `hours` must be a positive integer. Smaller requests are trimmed using the current UTC time: overlapping forecast intervals, or actual period ends in `(now - hours, now]`. Other Solcast fields are preserved. Larger requests get the available cached data with `x-proxy-hours-truncated: true`, plus `x-proxy-requested-hours` and `x-proxy-cache-hours`. For successful forecast collections, cache hours measure the returned coverage to the latest valid `period_end`, rounded up to whole hours, not the requested 336 hours. An empty forecast response has zero coverage. Truncation uses the exact returned endpoint and current time, so account-specific caps and aging are reflected. Before any successful collection, cache hours are zero. For actuals, cache hours measure the span from the earliest returned interval's start to the latest interval's end, rounded up. Truncation uses the unrounded span minus cache age, not the 168-hour collection request. Cache age reduces available coverage; the proxy never fabricates or pads missing data.

## Retries and resource response headers

Transient upstream failures (including empty-body 429, 5xx, and network errors) are retried with an increasing 15-second backoff plus 0–14 seconds jitter. `Retry-After` is honored. A cycle is bounded to ten total attempts and fifteen minutes, or the next cron occurrence if sooner. Exhaustion ends that cycle; collection resumes at the next cron. A Solcast daily-budget 429 does not trigger immediate retries; it also defers to the next cron. Permanent client errors such as 401/403/404 halt that resource until the proxy is restarted/reconfigured.

Last-good data survives all failures. However, when the latest upstream result is 429, resource reads also return 429, including after that collection cycle gives up. Load-shedding responses use JSON `null`, which the current integration recognises as retryable. Daily-quota responses retain Solcast's `response_status.error_code: TooManyRequests` payload instead, so the integration does not mistake quota exhaustion for temporary load shedding. Successful collection restores normal 200 responses. Other failures can still serve retained data; without any good cache they return 503.

This deliberately avoids hiding upstream load shedding behind a cached 200. The integration's ten attempts (initial request plus nine retries), using `15 * attempt + jitter(0..14)` second delays, total 675–801 seconds of waiting. The proxy uses the same approach, with its fifteen-minute collection deadline starting before the first upstream request. Network time counts. Integration requests do not trigger additional upstream attempts or wait for the proxy; its existing 900-second task limit remains unchanged. Ten consecutive load-shedding responses allow the integration to raise its existing non-fixable API-unavailable warning; later success clears it. Headers and status additionally describe the proxy's collection state:

| Header | Meaning |
| --- | --- |
| `x-proxy-last-fetch-at` | Last completed upstream attempt, UTC ISO timestamp |
| `x-proxy-last-success-at` | Last successful collection, UTC ISO timestamp |
| `x-proxy-last-fetch-status` | `not_fetched`, `clean_success`, `retry_success`, `retrying`, `give_up`, `budget_exhausted`, or `permanent_error` |
| `x-proxy-consecutive-failures` | Failed collection attempts since last success |
| `x-proxy-retries-used` | Retries beyond the initial attempt in the latest cycle |
| `x-proxy-next-attempt-at` | Actual pending retry or next cron, empty when halted |
| `x-proxy-give-up` | Latest cycle ended unsuccessfully; not necessarily a permanent halt |
| `x-proxy-halted` | Permanent resource failure; do not keep scheduling consumer retries |
| `x-proxy-upstream-status` | Latest upstream status, including synthetic 502 for transport/invalid-payload failures |
| `x-proxy-fetch-in-progress` | Collection is still running; the five-second follow offset may be too short |

Consumer reads never move these timestamps or increment failures. Status is available at `/proxy-status` and `/proxy_status`; API keys are not exposed there.

## Discovery for integration support

`/rooftop_sites` advertises `x-solcast-proxy: true`, `x-proxy-name`, and
`x-proxy-version: 2.0`, together with:

- `x-proxy-forecast-cron` and `x-proxy-estimated-actuals-cron`
- `x-proxy-timezone: UTC`
- `x-proxy-poll-delay-seconds: 5`
- `x-proxy-status-url: /proxy-status`

Consumers can follow cron slightly later should they understand the response headers, inspect the resource's next-attempt header during retries, and stop on `x-proxy-halted`. The five-second offset is nominal, not a guarantee that slow upstream collection has finished; consumers must inspect collection state.

All caches are in memory and not persisted at this stage.
