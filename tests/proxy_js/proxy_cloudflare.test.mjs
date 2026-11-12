import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { ProxyCoordinator } from "./proxy_cloudflare.js";

const NOW = Date.parse("2026-11-12T12:00:00Z");
const SITE = "1111-1111-1111-1111";
const DISCOVERY = { sites: [{ resource_id: SITE, name: "Home", latitude: -33.8 }] };

async function harness(t, envOverrides = {}) {
    t.mock.timers.enable({ apis: ["Date"], now: NOW });
    t.mock.method(console, "log", () => { });
    const stored = new Map();
    const storage = {
        writes: 0,
        alarm: null,
        async get(key) { return stored.get(key); },
        async put(key, value) { this.writes++; stored.set(key, value); },
        async setAlarm(value) { this.alarm = value; },
        async deleteAlarm() { this.alarm = null; },
    };
    const replies = [];
    const upstream = t.mock.method(globalThis, "fetch", async (url) => {
        assert.equal(new URL(url).searchParams.has("force"), false);
        assert.ok(replies.length, "Unexpected upstream request");
        const reply = replies.shift();
        if (reply instanceof Error) throw reply;
        return Response.json(reply.payload, { status: reply.status, headers: reply.headers || {} });
    });
    const env = { SCHEDULE_MODE: "cron", ...envOverrides };
    const state = { storage };
    let coordinator = new ProxyCoordinator(state, env);
    env.PROXY_COORDINATOR = { getByName: () => coordinator };
    await coordinator.rebuildScheduleIfNeeded();
    return {
        storage, replies, upstream,
        get coordinator() { return coordinator; },
        reload() { coordinator = new ProxyCoordinator(state, env); },
        request(path, query = "") {
            return worker.fetch(new Request(`https://proxy.test${path}?api_key=1&format=json${query}`), env);
        },
        async register(payload = DISCOVERY) {
            replies.push({ status: 200, payload });
            assert.equal((await this.request("/rooftop_sites")).status, 200);
        },
    };
}

function payloadFor(kind, power = 2) {
    const period_end = kind === "forecasts" ? "2026-11-12T12:30:00Z" : "2026-11-12T11:30:00Z";
    return { [kind]: [{ period_end, period: "PT30M", pv_estimate: power }] };
}

async function assertReadOnly(h, action, upstreamCalls = 0) {
    const before = structuredClone(await h.coordinator.load());
    const writes = h.storage.writes;
    const alarm = h.storage.alarm;
    const calls = h.upstream.mock.callCount();
    const result = await action();
    assert.deepEqual(await h.coordinator.load(), before);
    assert.equal(h.storage.writes, writes);
    assert.equal(h.storage.alarm, alarm);
    assert.equal(h.upstream.mock.callCount(), calls + upstreamCalls);
    return result;
}

test("retry-after header is honoured over local backoff", async (t) => {
    t.mock.method(Math, "random", () => 0);
    const h = await harness(t, { RETRY_BACKOFF_SECONDS: "1", MAX_ATTEMPTS: "5" });
    await h.register();
    h.replies.push({
        status: 429,
        payload: { error: "Throttled" },
        headers: { "retry-after": "120" },
    });
    await h.coordinator.collectKind("forecasts");

    const data = await h.coordinator.load();
    assert.equal(data.retry.active, true);
    assert.equal(data.retry.attempts, 1);
    assert.ok(h.storage.alarm !== null);
    assert.ok(h.storage.alarm >= NOW + 120000);
});

test("max attempts boundary transitions to give_up and clears alarm", async (t) => {
    t.mock.method(Math, "random", () => 0);
    const h = await harness(t, { RETRY_BACKOFF_SECONDS: "1", MAX_ATTEMPTS: "2" });
    await h.register();

    h.replies.push({ status: 500, payload: { error: "Unavailable" } });
    await h.coordinator.collectKind("forecasts");
    let data = await h.coordinator.load();
    let forecast = data.resources[`1|${SITE}|forecasts`];
    assert.equal(data.retry.active, true);
    assert.equal(data.retry.attempts, 1);
    assert.equal(forecast.retrying, true);
    assert.equal(forecast.give_up, false);
    assert.ok(h.storage.alarm !== null);

    h.replies.push({ status: 500, payload: { error: "Unavailable" } });
    await h.coordinator.collectKind("forecasts");
    data = await h.coordinator.load();
    forecast = data.resources[`1|${SITE}|forecasts`];
    assert.equal(data.retry.active, false);
    assert.equal(data.retry.attempts, 0);
    assert.equal(forecast.attempt_result, "give_up");
    assert.equal(forecast.retrying, false);
    assert.equal(forecast.give_up, true);
    assert.equal(h.storage.alarm, null);
});

test("alarm only runs active retry kinds and preserves other kind state", async (t) => {
    const h = await harness(t);
    await h.register();

    h.replies.push({ status: 200, payload: payloadFor("estimated_actuals", 4) });
    await h.coordinator.collectKind("estimated_actuals");
    const before = structuredClone((await h.coordinator.load()).resources[`1|${SITE}|estimated_actuals`]);

    h.replies.push({ status: 500, payload: { error: "Unavailable" } });
    await h.coordinator.collectKind("forecasts");

    h.replies.push({ status: 200, payload: payloadFor("forecasts", 7) });
    await h.coordinator.alarm();

    const data = await h.coordinator.load();
    const forecast = data.resources[`1|${SITE}|forecasts`];
    const actuals = data.resources[`1|${SITE}|estimated_actuals`];
    assert.equal(data.retry.active, false);
    assert.equal(forecast.attempt_result, "retry_success");
    assert.deepEqual(actuals, before);
});

test("runTick suppresses scheduled collection while retry is active", async (t) => {
    const h = await harness(t);
    await h.register();

    h.replies.push({ status: 500, payload: { error: "Unavailable" } });
    await h.coordinator.collectKind("forecasts");

    const calls = h.upstream.mock.callCount();
    await h.coordinator.runTick(new Date(NOW));
    assert.equal(h.upstream.mock.callCount(), calls);
});

test("forecast and estimated_actuals slicing keeps strict boundary semantics", async (t) => {
    const h = await harness(t);
    await h.register();

    const forecastPayload = {
        forecasts: [
            { id: "boundary-excluded", period_end: "2026-11-12T13:30:00Z", period: "PT30M" },
            { id: "included", period_end: "2026-11-12T12:30:00Z", period: "PT30M" },
        ],
    };
    h.replies.push({ status: 200, payload: forecastPayload });
    await h.coordinator.collectKind("forecasts");
    const forecastResp = await h.request(`/rooftop_sites/${SITE}/forecasts`, "&hours=1");
    const forecastRows = (await forecastResp.json()).forecasts;
    assert.deepEqual(forecastRows.map((row) => row.id), ["included"]);

    const actualsPayload = {
        estimated_actuals: [
            { id: "boundary-excluded", period_end: "2026-11-12T11:00:00Z", period: "PT30M" },
            { id: "included-now", period_end: "2026-11-12T12:00:00Z", period: "PT30M" },
            { id: "included-mid", period_end: "2026-11-12T11:30:00Z", period: "PT30M" },
        ],
    };
    h.replies.push({ status: 200, payload: actualsPayload });
    await h.coordinator.collectKind("estimated_actuals");
    const actualsResp = await h.request(`/rooftop_sites/${SITE}/estimated_actuals`, "&hours=1");
    const actualRows = (await actualsResp.json()).estimated_actuals;
    assert.deepEqual(actualRows.map((row) => row.id), ["included-now", "included-mid"]);
});

test("discovery preserves upstream failures when force is disabled or invalid", async (t) => {
    for (const force of ["", "&force=false", "&force=0", "&force=off", "&force=no", "&force=invalid"]) {
        await t.test(force || "no force", async (tt) => {
            const h = await harness(tt);
            await h.register();
            h.replies.push({ status: 429, payload: { error: "Throttled" } });
            assert.equal((await h.request("/rooftop_sites", force)).status, 429);
        });
    }
});

test("forced discovery semantics are consolidated", async (t) => {
    await t.test("falls back to latest cached payload across upstream failures and reload", async (tt) => {
        const h = await harness(tt);
        await h.register();
        const latest = { sites: [{ ...DISCOVERY.sites[0], name: "Renamed home" }] };
        await h.register(latest);
        for (const reply of [
            { status: 429, payload: { error: "Throttled" } },
            { status: 403, payload: { error: "Forbidden" } },
            { status: 500, payload: { error: "Unavailable" } },
            { status: 200, payload: { sites: [{}] } },
            { status: 200, payload: {} },
        ]) {
            h.replies.push(reply);
            assert.notEqual((await h.request("/rooftop_sites")).status, 200);
            h.reload();
            await h.coordinator.load();
            h.replies.push(reply);
            const response = await assertReadOnly(h, () => h.request("/rooftop_sites", "&force=true"), 1);
            assert.equal(response.status, 200);
            assert.equal(response.headers.get("cache-control"), "no-store");
            assert.deepEqual(await response.json(), latest);
        }
        h.replies.push(new Error("Connection failed"));
        await assert.rejects(h.request("/rooftop_sites"), /Connection failed/);
        h.replies.push(new Error("Connection failed"));
        const response = await assertReadOnly(h, () => h.request("/rooftop_sites", "&force=true"), 1);
        assert.deepEqual(await response.json(), latest);
    });

    await t.test("returns live updates, persists them, and then falls back", async (tt) => {
        const h = await harness(tt);
        const peer = "2222-2222-2222-2222";
        for (const payload of [DISCOVERY, { sites: [{ resource_id: peer, name: "New site" }] }, { sites: [] }]) {
            h.replies.push({ status: 200, payload });
            const calls = h.upstream.mock.callCount();
            const response = await h.request("/rooftop_sites", "&force=true");
            assert.equal(response.status, 200);
            assert.equal(h.upstream.mock.callCount(), calls + 1);
            assert.deepEqual(await response.json(), payload);
            const data = await h.coordinator.load();
            assert.deepEqual(data.discovery_payloads["1"], payload);
            assert.deepEqual(data.accounts["1"], payload.sites.map((site) => site.resource_id));
            assert.deepEqual(Object.values(data.resources).map((resource) => resource.site), payload.sites.flatMap((site) => [site.resource_id, site.resource_id]));
            h.reload();
            await h.coordinator.load();
            h.replies.push({ status: 502, payload: {} });
            const fallback = await assertReadOnly(h, () => h.request("/rooftop_sites", "&force=true"), 1);
            assert.equal(fallback.status, 200);
            assert.deepEqual(await fallback.json(), payload);
        }
    });

    await t.test("is account-isolated and supports empty successful site list", async (tt) => {
        const h = await harness(tt);
        await h.register({ sites: [] });
        h.replies.push({ status: 429, payload: { error: "Throttled" } });
        const response = await assertReadOnly(h, () => h.request("/rooftop_sites", "&force"), 1);
        assert.equal(response.status, 200);
        assert.deepEqual(await response.json(), { sites: [] });
        h.replies.push({ status: 403, payload: { error: "Forbidden" } });
        const missing = await assertReadOnly(h, () => h.coordinator.discoveryResponse(
            "https://proxy.test/rooftop_sites?api_key=2&force=true",
        ), 1);
        assert.equal(missing.status, 403);
        assert.deepEqual(await missing.json(), { error: "Forbidden" });
    });

    await t.test("without cache preserves connection errors", async (tt) => {
        const h = await harness(tt);
        h.replies.push(new Error("Connection failed"));
        await assert.rejects(h.request("/rooftop_sites", "&force=true"), /Connection failed/);
        assert.equal(h.upstream.mock.callCount(), 1);
    });
});

for (const kind of ["forecasts", "estimated_actuals"]) {
    test(`forced ${kind} semantics are consolidated`, async (t) => {
        const failures = [
            { name: "retrying", status: 502, payload: { error: "Unavailable" } },
            { name: "throttled", status: 429, payload: { error: "Throttled" } },
            { name: "budget_exhausted", status: 429, payload: { response_status: { error_code: "TooManyRequests" } } },
            { name: "permanent_error", status: 403, payload: { error: "Forbidden" } },
            { name: "give_up", status: 500, payload: { error: "Unavailable" }, maxAttempts: "1" },
            { name: "invalid_success", status: 200, payload: {} },
        ];

        await t.test("retains cached success across collection failure states", async (tt) => {
            for (const failure of failures) {
                await tt.test(failure.name, async (ttt) => {
                    const h = await harness(ttt, { MAX_ATTEMPTS: failure.maxAttempts || "5" });
                    await h.register();
                    const payload = payloadFor(kind);
                    h.replies.push({ status: 200, payload });
                    await h.coordinator.collectKind(kind);
                    h.replies.push(failure);
                    await h.coordinator.collectKind(kind);
                    const path = `/rooftop_sites/${SITE}/${kind}`;
                    assert.notEqual((await h.request(path, "&hours=24")).status, 200);
                    h.reload();
                    await h.coordinator.load();
                    const response = await assertReadOnly(h, () => h.request(path, "&hours=24&force=true"));
                    assert.equal(response.status, 200);
                    assert.deepEqual(await response.json(), payload);
                    assert.equal(response.headers.get("x-proxy-upstream-status"), String(failure.status === 200 ? 502 : failure.status));
                    assert.equal(response.headers.get("x-proxy-last-success-at"), new Date(NOW).toISOString());
                    assert.equal(response.headers.get("x-proxy-hours-truncated"), "true");
                    assert.notEqual(response.headers.get("x-proxy-cache-hours"), "0");
                });
            }
        });

        await t.test("uses latest success and preserves hours slicing", async (tt) => {
            const h = await harness(tt);
            await h.register();
            for (const power of [1, 3]) {
                h.replies.push({ status: 200, payload: payloadFor(kind, power) });
                await h.coordinator.collectKind(kind);
                h.replies.push({ status: 502, payload: {} });
                await h.coordinator.collectKind(kind);
            }
            const path = `/rooftop_sites/${SITE}/${kind}`;
            const response = await assertReadOnly(h, () => h.request(path, "&hours=24&force=1"));
            assert.deepEqual(await response.json(), payloadFor(kind, 3));
            const narrow = await h.request(path, "&hours=0.1&force=yes");
            const expected = kind === "forecasts" ? payloadFor(kind, 3) : { [kind]: [] };
            assert.deepEqual(await narrow.json(), expected);
        });

        await t.test("without prior success returns 503 and keeps account isolation", async (tt) => {
            const h = await harness(tt);
            const path = `/rooftop_sites/${SITE}/${kind}`;
            assert.equal((await assertReadOnly(h, () => h.request(path, "&hours=24&force=true"))).status, 503);
            await h.register();
            h.replies.push({ status: 429, payload: {} });
            await h.coordinator.collectKind(kind);
            assert.equal((await assertReadOnly(h, () => h.request(path, "&hours=24&force=true"))).status, 503);
            assert.equal((await h.request(path, "&hours=24")).status, 429);
            const other = await assertReadOnly(h, () => h.coordinator.resourceResponse(
                `https://proxy.test${path}?api_key=2&hours=24&force=true`, SITE, kind,
            ));
            assert.equal(other.status, 503);
        });

        await t.test("supports in-flight and pre-upgrade success fallback", async (tt) => {
            const h = await harness(tt);
            await h.register();
            h.replies.push({ status: 200, payload: payloadFor(kind) });
            await h.coordinator.collectKind(kind);
            const data = await h.coordinator.load();
            const resource = data.resources[`1|${SITE}|${kind}`];
            delete resource.last_success_cache;
            resource.in_flight = true;
            const path = `/rooftop_sites/${SITE}/${kind}`;
            const response = await assertReadOnly(h, () => h.request(path, "&hours=24&force=on"));
            assert.equal(response.headers.get("x-proxy-fetch-in-progress"), "true");
            assert.deepEqual(await response.json(), payloadFor(kind));
            h.replies.push({ status: 502, payload: {} });
            await h.coordinator.collectKind(kind);
            assert.deepEqual(await (await h.request(path, "&hours=24&force=true")).json(), payloadFor(kind));
        });
    });
}

test("forced reads preserve query validation and old discovery-state compatibility", async (t) => {
    const h = await harness(t);
    const data = await h.coordinator.load();
    delete data.discovery_payloads;
    await h.coordinator.save(data);
    h.reload();
    h.replies.push({ status: 503, payload: { error: "Unavailable" } });
    assert.equal((await h.request("/rooftop_sites", "&force=true")).status, 503);
    assert.equal((await h.coordinator.discoveryResponse("https://proxy.test/rooftop_sites?force=true")).status, 400);
    assert.equal((await h.coordinator.discoveryResponse("https://proxy.test/rooftop_sites?api_key=1&format=csv&force=true")).status, 400);
    const path = `/rooftop_sites/${SITE}/forecasts`;
    assert.equal((await h.request(path, "&hours=0&force=true")).status, 400);
    assert.equal((await h.request(path, "&hours=abc&force=true")).status, 400);
});

test("coordinated failure retains successful peer responses", async (t) => {
    const h = await harness(t);
    const peer = "2222-2222-2222-2222";
    await h.register({ sites: [...DISCOVERY.sites, { resource_id: peer }] });
    h.replies.push({ status: 200, payload: payloadFor("forecasts") }, { status: 429, payload: {} });
    await h.coordinator.collectKind("forecasts");
    const response = await assertReadOnly(h, () => h.request(`/rooftop_sites/${SITE}/forecasts`, "&hours=24&force=true"));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-proxy-last-fetch-status"), "retrying");
    assert.equal(response.headers.get("x-proxy-upstream-status"), "429");
    assert.deepEqual(await response.json(), payloadFor("forecasts"));
});
