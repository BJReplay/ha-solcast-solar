const PROXY_NAME = "solcast-proxy";
const PROXY_VERSION = "cloudflare-do-js-1.0";
const DO_ROUTE_PREFIX = "/_do";
const BASE_TICK_CRON = "* * * * *";

const DEFAULT_MODE = "cron"; // cron | daylight | all_day
const MODE_CRON = "cron";
const DEFAULT_FORECAST_CRONS = "30 11,0,1,2,3,4 * * *";
const DEFAULT_ACTUALS_CRONS = "05 14 * * *";
const DEFAULT_DIVISIONS = 9;
const DEFAULT_POLL_DELAY_SECONDS = "30";
const DEFAULT_ACTUALS_DELAY_MINUTES = 0;
const MAX_ACTUALS_DELAY_MINUTES = 120;
const DEFAULT_ACTUALS_RANDOM_MIN_OFFSET_MINUTES = 1;
const DEFAULT_ACTUALS_RANDOM_MAX_OFFSET_MINUTES = 14;
const DEFAULT_TIMEZONE = "UTC";
const MAX_TICK_SECOND_SAMPLES = 180;
const DEFAULT_SOLCAST_HOST = "api.solcast.com.au";
const DEFAULT_SOLCAST_PORT = 443;
const FORECAST_KIND = "forecasts";
const ACTUALS_KIND = "estimated_actuals";
const FORECAST_REQUEST_HOURS = 336;
const ACTUALS_REQUEST_HOURS = 168;
const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_RETRY_BACKOFF_SECONDS = 45;
const DEFAULT_ENABLE_ESTIMATED_ACTUALS = "false";
const RETRY_JITTER_MAX_SECONDS = 14;
const PERIOD_RE = /^PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?$/;

function nowUtc() {
    return new Date();
}

function iso(d) {
    return d.toISOString();
}

function dayUtcString(d) {
    return d.toISOString().slice(0, 10);
}

function resourceId(apiKey, site, kind) {
    return `${apiKey}|${site}|${kind}`;
}

function percentile(values, p) {
    if (!values.length) {
        return 0;
    }
    const sorted = [...values].sort((a, b) => a - b);
    const i = Math.max(0, Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1));
    return sorted[i];
}

function stdDev(values) {
    if (!values.length) {
        return 0;
    }
    const mean = values.reduce((acc, value) => acc + value, 0) / values.length;
    const variance = values.reduce((acc, value) => acc + (value - mean) ** 2, 0) / values.length;
    return Math.sqrt(variance);
}

function parseNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

function parseBool(value, fallback = false) {
    if (value === undefined || value === null) {
        return fallback;
    }
    const normalized = String(value).trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) {
        return true;
    }
    if (["0", "false", "no", "off"].includes(normalized)) {
        return false;
    }
    return fallback;
}

function parseCronList(value, fallback) {
    const raw = String(value || fallback || "");
    return raw
        .split(";")
        .map((item) => item.trim())
        .filter(Boolean);
}

function parseExceptions(value) {
    // Supports JSON array or comma-separated values.
    // Values may be HH:MM (UTC daily) or full ISO timestamps.
    if (!value) {
        return [];
    }

    let items = [];
    let parsedJsonArray = false;
    const str = String(value).trim();
    if (!str) {
        return [];
    }

    if (str.startsWith("[")) {
        try {
            const parsed = JSON.parse(str);
            if (Array.isArray(parsed)) {
                items = parsed.map((v) => String(v));
                parsedJsonArray = true;
            }
        } catch {
            // fall through to CSV parse
        }
    }

    if (!parsedJsonArray && items.length === 0) {
        items = str.split(",").map((v) => v.trim()).filter(Boolean);
    }

    return items;
}

function hhmmToMinuteOfDay(hhmm) {
    const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(hhmm);
    if (!m) {
        return null;
    }
    return Number(m[1]) * 60 + Number(m[2]);
}

function minuteOfDayToHhmm(minuteOfDay) {
    const clamped = Math.max(0, Math.min(1439, minuteOfDay));
    const h = Math.floor(clamped / 60);
    const m = clamped % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function secondOfDayToHhmm(secondOfDay) {
    const clamped = Math.max(0, Math.min(86399, secondOfDay));
    const h = Math.floor(clamped / 3600);
    const m = Math.floor((clamped % 3600) / 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function uniqueSortedMinutes(minutes) {
    return [...new Set(minutes)].filter((m) => Number.isInteger(m) && m >= 0 && m < 1440).sort((a, b) => a - b);
}

function uniqueSortedSeconds(seconds) {
    return [...new Set(seconds)].filter((s) => Number.isInteger(s) && s >= 0 && s < 86400).sort((a, b) => a - b);
}

function boolHeader(value) {
    return value ? "true" : "false";
}

function hasKindRetry(retryState, kind) {
    return Boolean(retryState?.active && Array.isArray(retryState.kinds) && retryState.kinds.includes(kind));
}

function cronFieldToSet(field, min, max) {
    const out = new Set();
    for (const part of field.split(",")) {
        const token = part.trim();
        if (!token) {
            continue;
        }

        if (token === "*") {
            for (let i = min; i <= max; i += 1) {
                out.add(i);
            }
            continue;
        }

        if (token.includes("/")) {
            const [base, stepRaw] = token.split("/");
            const step = Number(stepRaw);
            if (!Number.isFinite(step) || step <= 0) {
                continue;
            }
            let start = min;
            let end = max;
            if (base && base !== "*") {
                if (base.includes("-")) {
                    const [s, e] = base.split("-").map(Number);
                    start = Number.isFinite(s) ? s : min;
                    end = Number.isFinite(e) ? e : max;
                } else {
                    const n = Number(base);
                    if (Number.isFinite(n)) {
                        start = n;
                        end = max;
                    }
                }
            }
            for (let i = Math.max(min, start); i <= Math.min(max, end); i += step) {
                out.add(i);
            }
            continue;
        }

        if (token.includes("-")) {
            const [s, e] = token.split("-").map(Number);
            if (!Number.isFinite(s) || !Number.isFinite(e)) {
                continue;
            }
            for (let i = Math.max(min, s); i <= Math.min(max, e); i += 1) {
                out.add(i);
            }
            continue;
        }

        const n = Number(token);
        if (Number.isFinite(n) && n >= min && n <= max) {
            out.add(n);
        }
    }

    return out;
}

function cronTimesUtc(cronExpr) {
    // Limited parser for minute/hour fields. DOM/month/DOW are treated as wildcard.
    const fields = cronExpr.trim().split(/\s+/);
    if (fields.length !== 5) {
        return [];
    }
    const [minField, hourField] = fields;
    const mins = cronFieldToSet(minField, 0, 59);
    const hours = cronFieldToSet(hourField, 0, 23);

    const out = [];
    for (const h of hours) {
        for (const m of mins) {
            out.push(h * 60 + m);
        }
    }
    return uniqueSortedMinutes(out);
}

function spreadTimes(startMinute, endMinute, divisions) {
    const count = Math.max(1, Math.floor(divisions));
    const span = Math.max(0, endMinute - startMinute);
    if (span === 0 || count === 1) {
        return [Math.max(0, Math.min(1439, startMinute))];
    }

    const out = [];
    const step = span / (count - 1);
    for (let i = 0; i < count; i += 1) {
        out.push(Math.round(startMinute + step * i));
    }
    return uniqueSortedMinutes(out);
}

function spreadTimesRaw(startMinute, endMinute, divisions) {
    const count = Math.max(1, Math.floor(divisions));
    const span = Math.max(0, endMinute - startMinute);
    if (span === 0 || count === 1) {
        return [startMinute];
    }

    const out = [];
    const step = span / (count - 1);
    for (let i = 0; i < count; i += 1) {
        out.push(Math.round(startMinute + step * i));
    }
    return out;
}

function spreadSeconds(startSecond, endSecond, divisions) {
    const count = Math.max(1, Math.floor(divisions));
    const span = Math.max(0, endSecond - startSecond);
    if (span === 0 || count === 1) {
        return [Math.max(0, Math.min(86399, startSecond))];
    }

    const out = [];
    const step = span / (count - 1);
    for (let i = 0; i < count; i += 1) {
        out.push(Math.round(startSecond + step * i));
    }
    return uniqueSortedSeconds(out);
}

function spreadSecondsRaw(startSecond, endSecond, divisions) {
    const count = Math.max(1, Math.floor(divisions));
    const span = Math.max(0, endSecond - startSecond);
    if (span === 0 || count === 1) {
        return [startSecond];
    }

    const out = [];
    const step = span / (count - 1);
    for (let i = 0; i < count; i += 1) {
        out.push(Math.round(startSecond + step * i));
    }
    return out;
}

function spreadSecondsForDay(divisions) {
    const count = Math.max(1, Math.floor(divisions));
    const step = 86400 / count;
    const out = [];
    for (let i = 0; i < count; i += 1) {
        out.push(Math.round(i * step) % 86400);
    }
    return uniqueSortedSeconds(out);
}

function utcDateWithMinute(dayUtc, minuteOfDay) {
    const d = new Date(`${dayUtc}T00:00:00.000Z`);
    d.setUTCMinutes(minuteOfDay);
    return d;
}

function utcMinuteOfDay(d) {
    return d.getUTCHours() * 60 + d.getUTCMinutes();
}

function utcSecondOfDay(d) {
    return d.getUTCHours() * 3600 + d.getUTCMinutes() * 60 + d.getUTCSeconds();
}

const TIMEZONE_PARTS_FORMATTER_CACHE = new Map();

function timezonePartsFormatter(timezone) {
    let formatter = TIMEZONE_PARTS_FORMATTER_CACHE.get(timezone);
    if (!formatter) {
        formatter = new Intl.DateTimeFormat("en-CA", {
            timeZone: timezone,
            hourCycle: "h23",
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
        TIMEZONE_PARTS_FORMATTER_CACHE.set(timezone, formatter);
    }
    return formatter;
}

function parseTimezoneParts(d, timezone) {
    const parts = timezonePartsFormatter(timezone).formatToParts(d);

    let year = 0;
    let month = 0;
    let day = 0;
    let hour = 0;
    let minute = 0;
    let second = 0;

    for (const part of parts) {
        switch (part.type) {
            case "year":
                year = Number(part.value);
                break;
            case "month":
                month = Number(part.value);
                break;
            case "day":
                day = Number(part.value);
                break;
            case "hour":
                hour = Number(part.value);
                break;
            case "minute":
                minute = Number(part.value);
                break;
            case "second":
                second = Number(part.value);
                break;
            default:
                break;
        }
    }

    return {
        year,
        month,
        day,
        hour,
        minute,
        second,
    };
}

function validateRequiredTimezone(env, mode) {
    const timezone = String(env.TIMEZONE || "").trim();
    if (!timezone) {
        throw new Error(`TIMEZONE is required when SCHEDULE_MODE=${mode}`);
    }

    // Throws RangeError for unknown time zone identifiers.
    new Intl.DateTimeFormat("en-US", { timeZone: timezone }).format(new Date());
    return timezone;
}

function localMinuteMatchesUtcDay(dayUtc, timezone, targetMinuteOfDay) {
    const startMs = Date.parse(`${dayUtc}T00:00:00.000Z`);
    const instant = new Date(startMs);
    const matches = [];
    for (let minuteOfUtcDay = 0; minuteOfUtcDay < 1440; minuteOfUtcDay += 1) {
        instant.setTime(startMs + minuteOfUtcDay * 60000);
        const local = parseTimezoneParts(instant, timezone);
        const localMinuteOfDay = local.hour * 60 + local.minute;
        if (localMinuteOfDay === targetMinuteOfDay) {
            matches.push(minuteOfUtcDay * 60);
        }
    }
    return uniqueSortedSeconds(matches);
}

function localSecondMatchesUtcDay(dayUtc, timezone, targetSecondOfDay) {
    const targetMinuteOfDay = Math.floor(targetSecondOfDay / 60);
    const targetSecond = targetSecondOfDay % 60;
    const minuteMatches = localMinuteMatchesUtcDay(dayUtc, timezone, targetMinuteOfDay);
    const dayStartMs = Date.parse(`${dayUtc}T00:00:00.000Z`);
    const instant = new Date(dayStartMs);

    const matches = [];
    for (const minuteStart of minuteMatches) {
        const candidate = minuteStart + targetSecond;
        if (candidate < 0 || candidate >= 86400) {
            continue;
        }

        instant.setTime(dayStartMs + candidate * 1000);
        const local = parseTimezoneParts(instant, timezone);
        const localSecond = local.hour * 3600 + local.minute * 60 + local.second;
        if (localSecond === targetSecondOfDay) {
            matches.push(candidate);
        }
    }

    return uniqueSortedSeconds(matches);
}

function hashString(input) {
    let h = 2166136261;
    for (let i = 0; i < input.length; i += 1) {
        h ^= input.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

function dailyActualsRandomOffset(dayUtc, timezone) {
    const seed = hashString(`${dayUtc}|${timezone}|actuals-random-offset`);
    const minuteSpan = DEFAULT_ACTUALS_RANDOM_MAX_OFFSET_MINUTES - DEFAULT_ACTUALS_RANDOM_MIN_OFFSET_MINUTES + 1;
    const minuteOffset = DEFAULT_ACTUALS_RANDOM_MIN_OFFSET_MINUTES + (seed % minuteSpan);
    const secondOffset = (seed >>> 8) % 60;
    return { minuteOffset, secondOffset };
}

function fromIso(value) {
    if (!value) {
        return null;
    }
    const t = Date.parse(value);
    if (Number.isNaN(t)) {
        return null;
    }
    return new Date(t);
}

function parseRetryAfterSeconds(value, now = nowUtc()) {
    if (!value) {
        return null;
    }

    const str = String(value).trim();
    if (!str) {
        return null;
    }

    const asNumber = Number(str);
    if (Number.isFinite(asNumber) && asNumber >= 0) {
        return Math.floor(asNumber);
    }

    const targetMs = Date.parse(str);
    if (Number.isNaN(targetMs)) {
        return null;
    }

    return Math.max(0, Math.ceil((targetMs - now.getTime()) / 1000));
}

function nextRetryAt(now, attempts, backoffSeconds, minRetryAfterSeconds = null) {
    const jitter = Math.floor(Math.random() * (RETRY_JITTER_MAX_SECONDS + 1));
    let delaySeconds = Math.max(1, attempts * backoffSeconds + jitter);
    if (Number.isFinite(minRetryAfterSeconds) && minRetryAfterSeconds !== null) {
        delaySeconds = Math.max(delaySeconds, minRetryAfterSeconds);
    }
    return new Date(now.getTime() + delaySeconds * 1000);
}

function nextMinuteAtOrAfter(minuteList, minuteNow) {
    for (const m of minuteList) {
        if (m >= minuteNow) {
            return m;
        }
    }
    return null;
}

function estimateSunriseSunsetUtc(dayUtc, latitude, longitude) {
    // NOAA-inspired approximation. Good enough for scheduling proof-of-concept.
    const degToRad = Math.PI / 180;
    const radToDeg = 180 / Math.PI;
    const date = new Date(`${dayUtc}T00:00:00.000Z`);

    const dayOfYear = Math.floor((date - new Date(Date.UTC(date.getUTCFullYear(), 0, 0))) / 86400000);
    const lngHour = longitude / 15;

    function calc(isSunrise) {
        const t = dayOfYear + ((isSunrise ? 6 : 18) - lngHour) / 24;
        const M = 0.9856 * t - 3.289;
        let L = M + 1.916 * Math.sin(M * degToRad) + 0.02 * Math.sin(2 * M * degToRad) + 282.634;
        L = ((L % 360) + 360) % 360;

        let RA = radToDeg * Math.atan(0.91764 * Math.tan(L * degToRad));
        RA = ((RA % 360) + 360) % 360;

        const Lquadrant = Math.floor(L / 90) * 90;
        const RAquadrant = Math.floor(RA / 90) * 90;
        RA = (RA + (Lquadrant - RAquadrant)) / 15;

        const sinDec = 0.39782 * Math.sin(L * degToRad);
        const cosDec = Math.cos(Math.asin(sinDec));

        const cosH = (Math.cos(90.833 * degToRad) - sinDec * Math.sin(latitude * degToRad)) / (cosDec * Math.cos(latitude * degToRad));

        if (cosH > 1 || cosH < -1) {
            return null;
        }

        let H = isSunrise ? 360 - radToDeg * Math.acos(cosH) : radToDeg * Math.acos(cosH);
        H /= 15;

        const T = H + RA - 0.06571 * t - 6.622;
        let UT = T - lngHour;
        UT = ((UT % 24) + 24) % 24;

        return Math.round(UT * 60);
    }

    return {
        sunriseMinuteUtc: calc(true),
        sunsetMinuteUtc: calc(false),
    };
}

function rowStart(row, end) {
    if (row.period_start) {
        const parsed = Date.parse(row.period_start);
        if (!Number.isNaN(parsed)) {
            return new Date(parsed);
        }
    }

    const m = PERIOD_RE.exec(String(row.period || ""));
    if (!m) {
        throw new Error("Invalid Solcast period");
    }
    const hours = Number(m[1] || 0);
    const minutes = Number(m[2] || 0);
    const seconds = Number(m[3] || 0);
    const deltaMs = ((hours * 3600) + (minutes * 60) + seconds) * 1000;
    return new Date(end.getTime() - deltaMs);
}

function sliceRows(rows, kind, now, hours) {
    const sliced = [];
    const pastWindowSeconds = -hours * 3600;
    const futureWindowSeconds = hours * 3600;

    for (const row of rows) {
        try {
            const endMs = Date.parse(row.period_end);
            if (Number.isNaN(endMs)) {
                continue;
            }
            const end = new Date(endMs);
            const endDeltaSeconds = (end.getTime() - now.getTime()) / 1000;

            let include = false;
            if (kind === ACTUALS_KIND) {
                include = pastWindowSeconds < endDeltaSeconds && endDeltaSeconds <= 0;
            } else {
                if (endDeltaSeconds <= 0) {
                    continue;
                }
                const start = rowStart(row, end);
                include = ((start.getTime() - now.getTime()) / 1000) < futureWindowSeconds;
            }
            if (include) {
                sliced.push(row);
            }
        } catch {
            // Ignore malformed rows.
        }
    }
    return sliced;
}

function invalidateResourceCache(resource) {
    if (resource.payload) {
        resource.last_success_cache = {
            payload: resource.payload,
            hours: resource.hours,
            forecast_end: resource.forecast_end,
            history_hours: resource.history_hours,
        };
    }
    resource.payload = null;
    resource.hours = 0;
    resource.forecast_end = null;
    resource.history_hours = 0;
}

function newResourceState(apiKey, site, kind) {
    return {
        api_key: apiKey,
        site,
        kind,
        hours: 0,
        forecast_end: null,
        history_hours: 0,
        payload: null,
        last_success_cache: null,
        error_payload: null,
        fetched_at: null,
        last_success_at: null,
        status: 0,
        detail: "",
        rate_limit_headers: {},
        consecutive_failures: 0,
        attempt_result: "not_fetched",
        retries_used: 0,
        retrying: false,
        give_up: false,
        halted: false,
        in_flight: false,
        next_attempt_at: null,
    };
}

function newRetryState() {
    return {
        active: false,
        attempts: 0,
        next_attempt_at: null,
        last_status: 0,
        kinds: [],
    };
}

async function fetchUpstream(env, path, query = "") {
    const host = String(env.SOLCAST_HOST || DEFAULT_SOLCAST_HOST);
    const port = Number(env.SOLCAST_PORT || DEFAULT_SOLCAST_PORT);
    const url = `https://${host}:${port}${path}${query ? `?${query}` : ""}`;

    const response = await fetch(url, {
        method: "GET",
        headers: {
            "User-Agent": `${PROXY_NAME}/${PROXY_VERSION}`,
        },
    });

    const status = Number(response.status);
    const text = await response.text();

    let payload = null;
    if (text && (text.startsWith("{") || text.startsWith("["))) {
        try {
            payload = JSON.parse(text);
        } catch {
            payload = null;
        }
    }

    const detail = status >= 400 ? text : "";
    const guidance = {};
    for (const [key, value] of response.headers.entries()) {
        const k = String(key).toLowerCase();
        if (k === "retry-after" || k.startsWith("x-ratelimit") || k.startsWith("ratelimit")) {
            guidance[key] = value;
        }
    }

    return { status, payload, detail, guidance };
}

function applyExceptions(minutes, dayUtc, exceptionItems) {
    if (!exceptionItems.length) {
        return minutes;
    }

    const blocked = new Set();
    for (const raw of exceptionItems) {
        const hhmmMinute = hhmmToMinuteOfDay(raw);
        if (hhmmMinute !== null) {
            blocked.add(hhmmMinute);
            continue;
        }

        const ts = Date.parse(raw);
        if (!Number.isNaN(ts)) {
            const d = new Date(ts);
            if (dayUtcString(d) === dayUtc) {
                blocked.add(utcMinuteOfDay(d));
            }
        }
    }

    return minutes.filter((m) => !blocked.has(m));
}

function buildForecastTimes(dayUtc, env) {
    const mode = String(env.SCHEDULE_MODE || DEFAULT_MODE).toLowerCase();
    const divisions = parseNumber(env.UPDATE_DIVISIONS, DEFAULT_DIVISIONS);
    const exceptions = parseExceptions(env.SCHEDULE_EXCEPTIONS_UTC);

    if (mode === "daylight" || mode === "all_day") {
        validateRequiredTimezone(env, mode);
    }

    let baseMinutes = [];

    if (mode === "all_day") {
        baseMinutes = spreadTimes(0, 1439, divisions);
    } else if (mode === "daylight") {
        const latitude = parseNumber(env.LATITUDE, 0);
        const longitude = parseNumber(env.LONGITUDE, 0);
        const sun = estimateSunriseSunsetUtc(dayUtc, latitude, longitude);

        if (sun.sunriseMinuteUtc === null || sun.sunsetMinuteUtc === null) {
            // Fallback to all_day spread for polar/invalid conditions.
            baseMinutes = spreadTimes(0, 1439, divisions);
        } else {
            const sunrise = Math.max(0, sun.sunriseMinuteUtc);
            const sunset = Math.min(1439, sun.sunsetMinuteUtc);
            if (sunrise < sunset) {
                baseMinutes = spreadTimes(sunrise, sunset, divisions);
            } else {
                // East-of-UTC locations can have a daylight window that wraps over UTC midnight.
                // Spread across the wrapped interval and fold back into 00:00..23:59.
                const wrapped = spreadTimesRaw(sunrise, sunset + 1440, divisions);
                baseMinutes = uniqueSortedMinutes(wrapped.map((m) => m % 1440));
            }
        }
    } else {
        const cronList = parseCronList(env.FORECAST_CRONS, DEFAULT_FORECAST_CRONS);
        baseMinutes = uniqueSortedMinutes(cronList.flatMap((expr) => cronTimesUtc(expr)));
    }

    baseMinutes = uniqueSortedMinutes(baseMinutes);
    const filteredMinutes = uniqueSortedMinutes(applyExceptions(baseMinutes, dayUtc, exceptions));
    return uniqueSortedSeconds(filteredMinutes.map((m) => m * 60));
}

function buildActualsTimes(dayUtc, env) {
    if (!parseBool(env.ENABLE_ESTIMATED_ACTUALS, parseBool(DEFAULT_ENABLE_ESTIMATED_ACTUALS, false))) {
        return [];
    }

    const mode = String(env.SCHEDULE_MODE || DEFAULT_MODE).toLowerCase();
    const exceptions = parseExceptions(env.SCHEDULE_EXCEPTIONS_UTC);

    let baseSeconds = [];
    if (mode === "daylight" || mode === "all_day") {
        const timezone = validateRequiredTimezone(env, mode);
        const configuredDelay = Math.floor(parseNumber(env.ACTUALS_DELAY, DEFAULT_ACTUALS_DELAY_MINUTES));
        const actualsDelay = Math.max(0, Math.min(MAX_ACTUALS_DELAY_MINUTES, configuredDelay));
        const randomOffset = dailyActualsRandomOffset(dayUtc, timezone);
        const targetSecondOfDay = ((actualsDelay + randomOffset.minuteOffset) * 60) + randomOffset.secondOffset;
        baseSeconds = localSecondMatchesUtcDay(dayUtc, timezone, targetSecondOfDay);
    } else {
        const cronList = parseCronList(env.ACTUALS_CRONS, DEFAULT_ACTUALS_CRONS);
        const baseMinutes = uniqueSortedMinutes(cronList.flatMap((expr) => cronTimesUtc(expr)));
        baseSeconds = uniqueSortedSeconds(baseMinutes.map((m) => m * 60));
    }

    const baseMinutes = uniqueSortedMinutes(baseSeconds.map((s) => Math.floor(s / 60)));
    const filteredMinutes = uniqueSortedMinutes(applyExceptions(baseMinutes, dayUtc, exceptions));
    const allowedMinutes = new Set(filteredMinutes);
    return uniqueSortedSeconds(baseSeconds.filter((s) => allowedMinutes.has(Math.floor(s / 60))));
}

function scheduleConfigKey(env) {
    return JSON.stringify({
        mode: String(env.SCHEDULE_MODE || DEFAULT_MODE).toLowerCase(),
        updateDivisions: String(env.UPDATE_DIVISIONS || DEFAULT_DIVISIONS),
        forecastCrons: String(env.FORECAST_CRONS || DEFAULT_FORECAST_CRONS),
        actualsCrons: String(env.ACTUALS_CRONS || DEFAULT_ACTUALS_CRONS),
        exceptionsUtc: String(env.SCHEDULE_EXCEPTIONS_UTC || "[]"),
        latitude: String(env.LATITUDE || ""),
        longitude: String(env.LONGITUDE || ""),
        timezone: String(env.TIMEZONE || DEFAULT_TIMEZONE),
        actualsDelay: String(env.ACTUALS_DELAY || DEFAULT_ACTUALS_DELAY_MINUTES),
        enableEstimatedActuals: String(env.ENABLE_ESTIMATED_ACTUALS || DEFAULT_ENABLE_ESTIMATED_ACTUALS),
    });
}

function defaultState() {
    return {
        accounts: {},
        discovery_payloads: {},
        resources: {},
        retry: newRetryState(),
        schedule: {
            dayUtc: null,
            builtAt: null,
            mode: DEFAULT_MODE,
            timezone: DEFAULT_TIMEZONE,
            forecastTimesUtc: [],
            actualsTimesUtc: [],
            forecastTimesSecondOfDay: [],
            actualsTimesSecondOfDay: [],
            forecastDone: [],
            actualsDone: [],
            nextForecastAt: null,
            nextActualsAt: null,
            exceptions: [],
            configKey: null,
        },
        telemetry: {
            lastTickSecond: null,
            tickSecondSamples: [],
            observedCount: 0,
        },
    };
}

function jsonResponse(payload, status = 200, headers = {}) {
    return new Response(JSON.stringify(payload), {
        status,
        headers: {
            "content-type": "application/json",
            ...headers,
        },
    });
}

function pollingAdvice(env, telemetry) {
    const samples = telemetry?.tickSecondSamples || [];
    const minimumDelay = Math.max(1, parseNumber(env.POLL_DELAY_MIN_SECONDS, 15));
    if (!samples.length) {
        return {
            recommendedDelaySeconds: minimumDelay,
            confidence: "low",
            observedSecondP10: null,
            observedSecondP50: null,
            observedSecondP90: null,
            observedSecondStdDev: 0,
            observedSecondSpread: 0,
            latestObservedSecond: telemetry?.lastTickSecond ?? null,
            sampleCount: 0,
        };
    }

    const observedSecondP50 = percentile(samples, 50);
    const observedSecondP10 = percentile(samples, 10);
    const observedSecondP90 = percentile(samples, 90);
    const observedSecondStdDev = stdDev(samples);
    const observedSecondSpread = observedSecondP90 - observedSecondP10;

    // Confidence is variance-driven: tight, repeatable second offsets are high confidence.
    // Use the larger of spread and 2*stddev as a conservative dispersion signal.
    const dispersion = Math.max(observedSecondSpread, observedSecondStdDev * 2);
    const confidence = dispersion <= 2 ? "high" : dispersion <= 6 ? "medium" : "low";

    // Delay should trail the observed tick second (plus a floor), not invert it.
    // If ticks are at :00, recommend the minimum floor (e.g. 15s), not 60s.
    const recommendedDelaySeconds = Math.max(minimumDelay, observedSecondP90 + minimumDelay);

    const sampleCount = Number(telemetry?.observedCount || samples.length);

    return {
        recommendedDelaySeconds,
        confidence,
        observedSecondP10,
        observedSecondP50,
        observedSecondP90,
        observedSecondStdDev,
        observedSecondSpread,
        latestObservedSecond: telemetry?.lastTickSecond ?? samples[samples.length - 1],
        sampleCount,
    };
}

function scheduleHeaders(env, schedule, advice) {
    const configuredDelaySeconds = Math.max(1, Math.floor(parseNumber(env.POLL_DELAY_SECONDS, DEFAULT_POLL_DELAY_SECONDS)));
    const effectivePollDelaySeconds = schedule.mode === MODE_CRON ? configuredDelaySeconds : advice.recommendedDelaySeconds;
    return {
        "x-solcast-proxy": "true",
        "x-proxy-name": PROXY_NAME,
        "x-proxy-version": PROXY_VERSION,
        "x-proxy-timezone": "UTC",
        "x-proxy-status-url": "/proxy_status",
        "x-proxy-poll-delay-seconds": String(effectivePollDelaySeconds),
        "x-proxy-poll-delay-confidence": advice.confidence,
        "x-proxy-observed-tick-second-p90": advice.observedSecondP90 === null ? "" : String(advice.observedSecondP90),
        "x-proxy-forecast-cron": BASE_TICK_CRON,
        "x-proxy-estimated-actuals-cron": BASE_TICK_CRON,
        "x-proxy-estimated-actuals-enabled": boolHeader(parseBool(env.ENABLE_ESTIMATED_ACTUALS, parseBool(DEFAULT_ENABLE_ESTIMATED_ACTUALS, false))),
        "x-proxy-forecast-mode": String(schedule.mode || DEFAULT_MODE),
        "x-proxy-schedule-day-utc": String(schedule.dayUtc || ""),
        "x-proxy-forecast-times-utc": (schedule.forecastTimesUtc || []).join(","),
        "x-proxy-estimated-actuals-times-utc": (schedule.actualsTimesUtc || []).join(","),
    };
}

function nextFromDone(dayUtc, slotValues, doneSet, now, useSeconds = false) {
    const nowValue = useSeconds ? utcSecondOfDay(now) : utcMinuteOfDay(now);
    for (const slotValue of slotValues) {
        const slot = `${dayUtc}:${slotValue}`;
        if (slotValue >= nowValue && !doneSet.has(slot)) {
            if (useSeconds) {
                const d = new Date(`${dayUtc}T00:00:00.000Z`);
                d.setUTCSeconds(slotValue);
                return d.toISOString();
            }
            return utcDateWithMinute(dayUtc, slotValue).toISOString();
        }
    }
    return null;
}

export class ProxyCoordinator {
    constructor(state, env) {
        this.state = state;
        this.env = env;
        this.cache = null;
    }

    async load() {
        if (this.cache) {
            return this.cache;
        }

        let raw = await this.state.storage.get("state");
        if (typeof raw === "string") {
            try {
                raw = JSON.parse(raw);
            } catch {
                raw = null;
            }
        }

        const data = raw && typeof raw === "object" ? raw : defaultState();
        if (!data.accounts || typeof data.accounts !== "object") {
            data.accounts = {};
        }
        if (!data.discovery_payloads || typeof data.discovery_payloads !== "object") {
            data.discovery_payloads = {};
        }
        if (!data.resources || typeof data.resources !== "object") {
            data.resources = {};
        }
        if (!data.schedule) {
            data.schedule = defaultState().schedule;
        }
        if (!data.retry || typeof data.retry !== "object") {
            data.retry = newRetryState();
        }
        if (!data.telemetry) {
            data.telemetry = defaultState().telemetry;
        }
        if (!Array.isArray(data.telemetry.tickSecondSamples)) {
            data.telemetry.tickSecondSamples = [];
        }
        if (data.resources && typeof data.resources === "object") {
            for (const raw of Object.values(data.resources)) {
                raw.retries_used = Number(raw.retries_used || 0);
                raw.retrying = Boolean(raw.retrying);
                raw.give_up = Boolean(raw.give_up);
                raw.halted = Boolean(raw.halted);
                raw.in_flight = Boolean(raw.in_flight);
                raw.next_attempt_at = raw.next_attempt_at || null;
            }
        }

        this.cache = data;
        return data;
    }

    async registerSites(data, apiKey, sites) {
        let changed = false;
        const sortedSites = [...sites].sort();
        if (JSON.stringify(data.accounts[apiKey] || []) !== JSON.stringify(sortedSites)) {
            data.accounts[apiKey] = sortedSites;
            changed = true;
        }

        const stale = Object.entries(data.resources)
            .filter(([, raw]) => raw.api_key === apiKey && !sites.has(raw.site))
            .map(([rid]) => rid);

        for (const rid of stale) {
            delete data.resources[rid];
            changed = true;
        }

        for (const site of sites) {
            for (const kind of [FORECAST_KIND, ACTUALS_KIND]) {
                const rid = resourceId(apiKey, site, kind);
                if (!data.resources[rid]) {
                    data.resources[rid] = newResourceState(apiKey, site, kind);
                    changed = true;
                }
            }
        }

        return changed;
    }

    async discover(apiKey) {
        const { status, payload, detail } = await fetchUpstream(
            this.env,
            "/rooftop_sites",
            new URLSearchParams({ format: "json", api_key: apiKey }).toString(),
        );

        if (status !== 200) {
            return { status, payload, detail };
        }

        if (!payload || typeof payload !== "object" || !Array.isArray(payload.sites)) {
            return {
                status: 502,
                payload: { error: "Invalid rooftop sites response from upstream" },
                detail: "Invalid rooftop sites response from upstream",
            };
        }

        const sites = new Set();
        for (const site of payload.sites) {
            if (!site || typeof site !== "object" || typeof site.resource_id !== "string" || !site.resource_id) {
                return {
                    status: 502,
                    payload: { error: "Invalid rooftop sites response from upstream" },
                    detail: "Invalid rooftop sites response from upstream",
                };
            }
            sites.add(site.resource_id);
        }

        const data = await this.load();
        await this.registerSites(data, apiKey, sites);
        data.discovery_payloads[apiKey] = payload;
        await this.save(data);
        return { status, payload, detail };
    }

    async collectOne(resource, hours) {
        const now = nowUtc();
        resource.in_flight = true;
        resource.fetched_at = iso(now);

        const { status, payload, detail, guidance } = await fetchUpstream(
            this.env,
            `/rooftop_sites/${resource.site}/${resource.kind}`,
            new URLSearchParams({ format: "json", api_key: resource.api_key, hours: String(hours) }).toString(),
        );

        resource.status = status;
        resource.detail = detail;
        resource.rate_limit_headers = guidance;
        resource.error_payload = status === 200 ? null : payload;

        if (status === 200 && payload && typeof payload === "object" && Array.isArray(payload[resource.kind])) {
            const rows = payload[resource.kind];
            resource.payload = payload;
            resource.last_success_cache = null;
            resource.last_success_at = iso(now);
            resource.consecutive_failures = 0;
            resource.give_up = false;
            resource.retrying = false;
            resource.attempt_result = "clean_success";
            resource.next_attempt_at = null;

            if (resource.kind === FORECAST_KIND) {
                let latestEnd = null;
                for (const row of rows) {
                    const endMs = Date.parse(row.period_end);
                    if (Number.isNaN(endMs)) {
                        continue;
                    }
                    if (latestEnd === null || endMs > latestEnd) {
                        latestEnd = endMs;
                    }
                }
                if (latestEnd !== null) {
                    resource.forecast_end = iso(new Date(latestEnd));
                    resource.hours = Math.max(0, Math.ceil((latestEnd - now.getTime()) / 3600000));
                } else {
                    resource.forecast_end = null;
                    resource.hours = 0;
                }
            } else {
                let earliestStart = null;
                let latestEnd = null;
                for (const row of rows) {
                    try {
                        const endMs = Date.parse(row.period_end);
                        if (Number.isNaN(endMs)) {
                            continue;
                        }
                        const end = new Date(endMs);
                        const start = rowStart(row, end);
                        const startMs = start.getTime();
                        if (earliestStart === null || startMs < earliestStart) {
                            earliestStart = startMs;
                        }
                        if (latestEnd === null || endMs > latestEnd) {
                            latestEnd = endMs;
                        }
                    } catch {
                        // ignore malformed rows
                    }
                }

                if (earliestStart !== null && latestEnd !== null) {
                    const spanHours = Math.max(0, (latestEnd - earliestStart) / 3600000);
                    resource.history_hours = spanHours;
                    resource.hours = Math.ceil(spanHours);
                } else {
                    resource.history_hours = 0;
                    resource.hours = 0;
                }
            }

            resource.in_flight = false;
            return { resource, success: true, retryable: false, is429: false, retryAfterSeconds: null };
        }

        resource.consecutive_failures = Number(resource.consecutive_failures || 0) + 1;
        resource.attempt_result = "retrying";
        resource.in_flight = false;
        invalidateResourceCache(resource);

        const retryable = !(status >= 400 && status < 500 && status !== 408 && status !== 425 && status !== 429);
        const is429 = status === 429;
        const responseStatus = payload && typeof payload === "object" ? payload.response_status : null;
        const budgetExhausted = is429
            && responseStatus
            && typeof responseStatus === "object"
            && responseStatus.error_code === "TooManyRequests";
        const retryAfterHeader = Object.entries(guidance).find(([key]) => String(key).toLowerCase() === "retry-after")?.[1] || null;
        const retryAfterSeconds = parseRetryAfterSeconds(retryAfterHeader, now);

        if (budgetExhausted) {
            resource.attempt_result = "budget_exhausted";
            resource.give_up = true;
            resource.retrying = false;
            resource.next_attempt_at = null;
            return { resource, success: false, retryable: false, is429: true, retryAfterSeconds: null };
        }

        if (!retryable) {
            resource.attempt_result = "permanent_error";
            resource.halted = true;
            resource.give_up = true;
            resource.retrying = false;
            resource.next_attempt_at = null;
        }

        return { resource, success: false, retryable, is429, retryAfterSeconds };
    }

    async runCollectionCycle(kindFilter = null) {
        const data = await this.load();
        const retry = data.retry && typeof data.retry === "object" ? { ...data.retry } : newRetryState();

        const kinds = new Set(retry.active ? (retry.kinds || []) : []);
        if (kindFilter) {
            kinds.add(kindFilter);
        }

        const resources = Object.entries(data.resources)
            .filter(([, raw]) => kinds.has(raw.kind))
            .map(([rid, raw]) => ({ rid, resource: { ...raw } }));

        if (!resources.length) {
            return { attempted: 0, succeeded: 0 };
        }

        const now = nowUtc();
        let succeeded = 0;
        let anyRetryable = false;
        let any429 = false;
        let allSuccess = true;
        let minRetryAfterSeconds = null;

        for (const entry of resources) {
            if (entry.resource.halted) {
                continue;
            }

            const hours = entry.resource.kind === FORECAST_KIND ? FORECAST_REQUEST_HOURS : ACTUALS_REQUEST_HOURS;
            const result = await this.collectOne(entry.resource, hours);
            entry.resource = result.resource;
            if (result.success) {
                succeeded += 1;
            }

            allSuccess = allSuccess && result.success;
            anyRetryable = anyRetryable || result.retryable;
            any429 = any429 || result.is429;
            if (Number.isFinite(result.retryAfterSeconds) && result.retryAfterSeconds !== null) {
                if (minRetryAfterSeconds === null || result.retryAfterSeconds > minRetryAfterSeconds) {
                    minRetryAfterSeconds = result.retryAfterSeconds;
                }
            }

            data.resources[entry.rid] = entry.resource;
        }

        const maxAttempts = Math.max(1, Math.floor(parseNumber(this.env.MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS)));
        const backoffSeconds = Math.max(1, Math.floor(parseNumber(this.env.RETRY_BACKOFF_SECONDS, DEFAULT_RETRY_BACKOFF_SECONDS)));

        if (allSuccess) {
            const previousAttempts = Number(retry.attempts || 0);
            data.retry = newRetryState();
            for (const [rid, raw] of Object.entries(data.resources)) {
                if (!kinds.has(raw.kind)) {
                    continue;
                }
                raw.retrying = false;
                raw.give_up = false;
                raw.next_attempt_at = null;
                if (raw.attempt_result === "clean_success" && previousAttempts > 0) {
                    raw.attempt_result = "retry_success";
                }
                data.resources[rid] = raw;
            }
            try {
                await this.state.storage.deleteAlarm();
            } catch {
                // ignore
            }
        } else if (anyRetryable) {
            retry.active = true;
            retry.kinds = [...kinds].sort();
            retry.attempts = Number(retry.attempts || 0) + 1;
            retry.last_status = any429 ? 429 : 502;

            if (retry.attempts >= maxAttempts) {
                data.retry = newRetryState();
                for (const [rid, raw] of Object.entries(data.resources)) {
                    if (!kinds.has(raw.kind)) {
                        continue;
                    }
                    raw.retrying = false;
                    raw.give_up = true;
                    raw.attempt_result = "give_up";
                    raw.next_attempt_at = null;
                    invalidateResourceCache(raw);
                    data.resources[rid] = raw;
                }
                try {
                    await this.state.storage.deleteAlarm();
                } catch {
                    // ignore
                }
            } else {
                const nextRetry = nextRetryAt(now, retry.attempts, backoffSeconds, minRetryAfterSeconds);
                retry.next_attempt_at = iso(nextRetry);
                for (const [rid, raw] of Object.entries(data.resources)) {
                    if (!kinds.has(raw.kind) || raw.halted) {
                        continue;
                    }
                    raw.retrying = true;
                    raw.give_up = false;
                    raw.attempt_result = "retrying";
                    raw.next_attempt_at = retry.next_attempt_at;
                    raw.retries_used = retry.attempts;
                    invalidateResourceCache(raw);
                    if (any429) {
                        raw.status = 429;
                    }
                    data.resources[rid] = raw;
                }
                await this.state.storage.setAlarm(nextRetry.getTime());
                data.retry = retry;
            }
        } else {
            data.retry = newRetryState();
            try {
                await this.state.storage.deleteAlarm();
            } catch {
                // ignore
            }
        }

        if (allSuccess || !anyRetryable) {
            data.retry = data.retry || newRetryState();
        }

        await this.save(data);
        return { attempted: resources.length, succeeded };
    }

    async collectKind(kind) {
        return this.runCollectionCycle(kind);
    }

    resourceHeaders(resource, retryState) {
        const retrying = hasKindRetry(retryState, resource.kind);
        const upstreamStatus = retrying ? Number(retryState.last_status || 0) : Number(resource.status || 0);
        return {
            "x-proxy-consecutive-failures": String(resource.consecutive_failures || 0),
            "x-proxy-give-up": boolHeader(Boolean(resource.give_up)),
            "x-proxy-last-fetch-at": resource.fetched_at || "",
            "x-proxy-last-fetch-status": retrying ? "retrying" : (resource.attempt_result || "not_fetched"),
            "x-proxy-last-success-at": resource.last_success_at || "",
            "x-proxy-next-attempt-at": retrying ? (retryState.next_attempt_at || "") : "",
            "x-proxy-upstream-status": String(upstreamStatus),
            "x-proxy-retries-used": String(retrying ? Number(retryState.attempts || 0) : Number(resource.retries_used || 0)),
            "x-proxy-halted": boolHeader(Boolean(resource.halted)),
            "x-proxy-fetch-in-progress": boolHeader(Boolean(resource.in_flight)),
        };
    }

    async resourceResponse(url, siteId, kind) {
        const query = new URL(url).searchParams;
        const apiKey = query.get("api_key") || "";
        const fmt = query.get("format") || "json";
        const hours = Number(query.get("hours") || "0");
        const force = query.has("force") && parseBool(query.get("force") || "true");

        const data = await this.rebuildScheduleIfNeeded(nowUtc());
        const baseHeaders = scheduleHeaders(this.env, data.schedule, pollingAdvice(this.env, data.telemetry));

        if (!apiKey) {
            return jsonResponse({ error: "API key required" }, 400, baseHeaders);
        }
        if (!siteId) {
            return jsonResponse({ error: "Rooftop site required" }, 400, baseHeaders);
        }
        if (fmt !== "json" || !Number.isFinite(hours) || hours <= 0) {
            return jsonResponse({ error: "Positive hours and JSON format required" }, 400, baseHeaders);
        }

        let stateData = await this.load();
        const rid = resourceId(apiKey, siteId, kind);
        let resource = stateData.resources[rid];

        if (!resource) {
            if (force) {
                return jsonResponse({ error: "No successful cached response available" }, 503, {
                    ...baseHeaders,
                    "cache-control": "no-store",
                });
            }
            const discovered = await this.discover(apiKey);
            if (discovered.status !== 200) {
                if (discovered.payload !== null && discovered.payload !== undefined) {
                    return jsonResponse(discovered.payload, discovered.status, baseHeaders);
                }
                return new Response(discovered.detail || "", { status: discovered.status, headers: baseHeaders });
            }
            stateData = await this.load();
            resource = stateData.resources[rid];
            if (!resource) {
                return jsonResponse({ error: "Unknown rooftop site for this account" }, 404, baseHeaders);
            }
        }

        const cached = force && !resource.payload ? resource.last_success_cache : resource;
        const retryState = stateData.retry && typeof stateData.retry === "object" ? stateData.retry : newRetryState();
        const headers = {
            ...baseHeaders,
            ...this.resourceHeaders(resource, retryState),
            "cache-control": "no-store",
            "x-proxy-requested-hours": String(hours),
            "x-proxy-cache-hours": String(cached?.hours || 0),
        };

        if (!force && Number(resource.status) === 429) {
            const responsePayload = resource.attempt_result === "budget_exhausted" ? resource.error_payload : null;
            return jsonResponse(responsePayload, 429, headers);
        }

        if (!cached?.payload) {
            return jsonResponse({ error: force ? "No successful cached response available" : "No scheduled collection has succeeded yet" }, 503, headers);
        }

        const now = nowUtc();
        const rows = Array.isArray(cached.payload[kind]) ? cached.payload[kind] : [];
        const responsePayload = { ...cached.payload, [kind]: sliceRows(rows, kind, now, hours) };

        let availableHours = Number(cached.hours || 0);
        const lastSuccess = fromIso(resource.last_success_at) || now;
        if (kind === FORECAST_KIND && cached.forecast_end) {
            const forecastEnd = fromIso(cached.forecast_end);
            if (forecastEnd) {
                availableHours = Math.max(0, (forecastEnd.getTime() - now.getTime()) / 3600000);
            }
        } else if (kind === ACTUALS_KIND) {
            availableHours = Math.max(0, Number(cached.history_hours || 0) - ((now.getTime() - lastSuccess.getTime()) / 3600000));
        }

        headers["x-proxy-hours-truncated"] = boolHeader(hours > availableHours);
        return jsonResponse(responsePayload, 200, headers);
    }

    async save(data) {
        this.cache = data;
        await this.state.storage.put("state", JSON.stringify(data));
    }

    async rebuildScheduleIfNeeded(now = nowUtc()) {
        const data = await this.load();
        const dayUtc = dayUtcString(now);
        const configKey = scheduleConfigKey(this.env);

        if (data.schedule.dayUtc === dayUtc && data.schedule.configKey === configKey) {
            return data;
        }

        const mode = String(this.env.SCHEDULE_MODE || DEFAULT_MODE).toLowerCase();
        const timezone = String(this.env.TIMEZONE || DEFAULT_TIMEZONE);

        const forecastSeconds = buildForecastTimes(dayUtc, this.env);
        const actualsSeconds = buildActualsTimes(dayUtc, this.env);
        const nowSecond = utcSecondOfDay(now);
        const forecastDone = forecastSeconds.filter((secondOfDay) => secondOfDay < nowSecond).map((secondOfDay) => `${dayUtc}:${secondOfDay}`);
        const actualsDone = actualsSeconds.filter((secondOfDay) => secondOfDay < nowSecond).map((secondOfDay) => `${dayUtc}:${secondOfDay}`);

        data.schedule = {
            dayUtc,
            builtAt: iso(now),
            mode,
            timezone,
            forecastTimesUtc: forecastSeconds.map(secondOfDayToHhmm),
            actualsTimesUtc: actualsSeconds.map(secondOfDayToHhmm),
            forecastTimesSecondOfDay: forecastSeconds,
            actualsTimesSecondOfDay: actualsSeconds,
            forecastDone,
            actualsDone,
            nextForecastAt: null,
            nextActualsAt: null,
            exceptions: parseExceptions(this.env.SCHEDULE_EXCEPTIONS_UTC),
            configKey,
        };

        const doneForecast = new Set(forecastDone);
        const doneActuals = new Set(actualsDone);
        data.schedule.nextForecastAt = nextFromDone(dayUtc, forecastSeconds, doneForecast, now, true);
        data.schedule.nextActualsAt = nextFromDone(dayUtc, actualsSeconds, doneActuals, now, true);

        console.log("[proxy-js] schedule rebuilt", {
            dayUtc,
            mode,
            timezone,
            forecastTimesUtc: data.schedule.forecastTimesUtc,
            actualsTimesUtc: data.schedule.actualsTimesUtc,
            exceptions: data.schedule.exceptions,
        });

        await this.save(data);
        return data;
    }

    async collectForecastAtSlot(slotIso) {
        const result = await this.collectKind(FORECAST_KIND);
        console.log("[proxy-js] collect forecast", { slotIso, ...result });
    }

    async collectEstimatedActualsAtSlot(slotIso) {
        const result = await this.collectKind(ACTUALS_KIND);
        console.log("[proxy-js] collect estimated_actuals", { slotIso, ...result });
    }

    async runTick(now = nowUtc()) {
        const data = await this.rebuildScheduleIfNeeded(now);
        const dayUtc = data.schedule.dayUtc;
        const retryState = data.retry && typeof data.retry === "object" ? data.retry : newRetryState();

        const second = now.getUTCSeconds();
        const samples = [...(data.telemetry.tickSecondSamples || []), second].slice(-MAX_TICK_SECOND_SAMPLES);
        data.telemetry.lastTickSecond = second;
        data.telemetry.tickSecondSamples = samples;
        data.telemetry.observedCount = Number(data.telemetry.observedCount || 0) + 1;

        const forecastSeconds = uniqueSortedSeconds(data.schedule.forecastTimesSecondOfDay || []);
        const actualsSeconds = uniqueSortedSeconds(data.schedule.actualsTimesSecondOfDay || []);

        const forecastDone = new Set(data.schedule.forecastDone || []);
        const actualsDone = new Set(data.schedule.actualsDone || []);

        const nowSecond = utcSecondOfDay(now);

        if (retryState.active) {
            data.schedule.nextForecastAt = nextFromDone(dayUtc, forecastSeconds, forecastDone, now, true);
            data.schedule.nextActualsAt = nextFromDone(dayUtc, actualsSeconds, actualsDone, now, true);
            await this.save(data);
            return data;
        }

        const dueForecastSeconds = forecastSeconds.filter((secondOfDay) => {
            if (secondOfDay > nowSecond) {
                return false;
            }
            const slotKey = `${dayUtc}:${secondOfDay}`;
            return !forecastDone.has(slotKey);
        });
        if (dueForecastSeconds.length) {
            const selectedSecond = dueForecastSeconds[dueForecastSeconds.length - 1];
            const slotAt = new Date(`${dayUtc}T00:00:00.000Z`);
            slotAt.setUTCSeconds(selectedSecond);
            await this.collectForecastAtSlot(slotAt.toISOString());
            for (const secondOfDay of dueForecastSeconds) {
                forecastDone.add(`${dayUtc}:${secondOfDay}`);
            }
        }

        const dueActualsSeconds = actualsSeconds.filter((secondOfDay) => {
            if (secondOfDay > nowSecond) {
                return false;
            }
            const slotKey = `${dayUtc}:${secondOfDay}`;
            return !actualsDone.has(slotKey);
        });
        if (dueActualsSeconds.length) {
            const selectedSecond = dueActualsSeconds[dueActualsSeconds.length - 1];
            const slotAt = new Date(`${dayUtc}T00:00:00.000Z`);
            slotAt.setUTCSeconds(selectedSecond);
            await this.collectEstimatedActualsAtSlot(slotAt.toISOString());
            for (const secondOfDay of dueActualsSeconds) {
                actualsDone.add(`${dayUtc}:${secondOfDay}`);
            }
        }

        data.schedule.forecastDone = [...forecastDone].sort();
        data.schedule.actualsDone = [...actualsDone].sort();

        data.schedule.nextForecastAt = nextFromDone(dayUtc, forecastSeconds, forecastDone, now, true);
        data.schedule.nextActualsAt = nextFromDone(dayUtc, actualsSeconds, actualsDone, now, true);

        await this.save(data);
        return data;
    }

    async statusResponse() {
        const data = await this.rebuildScheduleIfNeeded(nowUtc());
        const advice = pollingAdvice(this.env, data.telemetry);
        const retryState = data.retry && typeof data.retry === "object" ? data.retry : newRetryState();
        const configuredPollDelaySeconds = Math.max(1, Math.floor(parseNumber(this.env.POLL_DELAY_SECONDS, DEFAULT_POLL_DELAY_SECONDS)));
        const pollDelaySeconds = data.schedule.mode === MODE_CRON ? configuredPollDelaySeconds : advice.recommendedDelaySeconds;
        const accountIds = Object.fromEntries(Object.keys(data.accounts || {}).map((apiKey, index) => [apiKey, index + 1]));
        const resources = {};

        for (const raw of Object.values(data.resources || {})) {
            const retrying = hasKindRetry(retryState, raw.kind);
            const label = `account-${accountIds[raw.api_key] || 0}:${raw.site}`;
            if (!resources[label]) {
                resources[label] = {};
            }

            resources[label][raw.kind] = {
                fetched_at: fromIso(raw.fetched_at)?.getTime() || null,
                ok: Number(raw.status || 0) === 200,
                status: retrying ? Number(retryState.last_status || 0) : Number(raw.status || 0),
                detail: raw.detail || "",
                rate_limit_headers: raw.rate_limit_headers || null,
                last_success_at: fromIso(raw.last_success_at)?.getTime() || null,
                consecutive_failures: Number(raw.consecutive_failures || 0),
                attempt_result: retrying ? "retrying" : (raw.attempt_result || "not_fetched"),
                retries_used: retrying ? Number(retryState.attempts || 0) : Number(raw.retries_used || 0),
                next_attempt_at: retrying
                    ? (fromIso(retryState.next_attempt_at)?.getTime() || null)
                    : (fromIso(raw.next_attempt_at)?.getTime() || null),
                give_up: Boolean(raw.give_up),
                halted: Boolean(raw.halted),
                cache_hours: Number(raw.hours || 0),
            };
        }

        const toMinuteDoneKey = (slotKey) => {
            const [day, secondRaw] = String(slotKey).split(":");
            const second = Number(secondRaw);
            if (!Number.isFinite(second)) {
                return String(slotKey);
            }
            const minute = Math.floor(second / 60);
            return `${day}:${minute}`;
        };

        const publicForecastDone = [...new Set((data.schedule.forecastDone || []).map(toMinuteDoneKey))].sort();
        const publicActualsDone = [...new Set((data.schedule.actualsDone || []).map(toMinuteDoneKey))].sort();

        const publicSchedule = {
            dayUtc: data.schedule.dayUtc,
            builtAt: data.schedule.builtAt,
            mode: data.schedule.mode,
            timezone: data.schedule.timezone,
            forecastTimesUtc: data.schedule.forecastTimesUtc,
            actualsTimesUtc: data.schedule.actualsTimesUtc,
            forecastDone: publicForecastDone,
            actualsDone: publicActualsDone,
            nextForecastAt: data.schedule.nextForecastAt,
            nextActualsAt: data.schedule.nextActualsAt,
            exceptions: data.schedule.exceptions,
        };
        return jsonResponse({
            proxy: {
                name: PROXY_NAME,
                version: PROXY_VERSION,
                schedule_mode: data.schedule.mode,
                timezone: "UTC",
                tick_cron: BASE_TICK_CRON,
                rate_limited_by_upstream: Boolean(retryState.active && Number(retryState.last_status || 0) === 429),
                poll_delay_seconds: pollDelaySeconds,
                configured_poll_delay_seconds: configuredPollDelaySeconds,
                estimated_actuals_enabled: parseBool(this.env.ENABLE_ESTIMATED_ACTUALS, parseBool(DEFAULT_ENABLE_ESTIMATED_ACTUALS, false)),
            },
            schedule: publicSchedule,
            polling_advice: {
                recommended_delay_seconds: advice.recommendedDelaySeconds,
                confidence: advice.confidence,
                observed_tick_second_p10: advice.observedSecondP10,
                observed_tick_second_p50: advice.observedSecondP50,
                observed_tick_second_p90: advice.observedSecondP90,
                observed_tick_second_stddev: Number(advice.observedSecondStdDev.toFixed(3)),
                observed_tick_second_spread: advice.observedSecondSpread,
                latest_observed_tick_second: advice.latestObservedSecond,
                observed_samples: advice.sampleCount,
            },
            retry: {
                active: Boolean(retryState.active),
                kinds: Array.isArray(retryState.kinds) ? retryState.kinds : [],
                attempts: Number(retryState.attempts || 0),
                next_attempt_at: retryState.next_attempt_at || null,
                status: Number(retryState.last_status || 0),
            },
            resources,
        });
    }

    async discoveryResponse(url) {
        const query = new URL(url).searchParams;
        const apiKey = query.get("api_key") || "";
        const fmt = query.get("format") || "json";
        const force = query.has("force") && parseBool(query.get("force") || "true");

        const data = await this.rebuildScheduleIfNeeded(nowUtc());
        const headers = {
            ...scheduleHeaders(this.env, data.schedule, pollingAdvice(this.env, data.telemetry)),
            "cache-control": "no-store",
        };

        if (!apiKey || fmt !== "json") {
            return jsonResponse({ error: "API key and JSON format required" }, 400, headers);
        }

        const hasFallback = force && Object.hasOwn(data.discovery_payloads, apiKey);
        let discovered;
        try {
            discovered = await this.discover(apiKey);
        } catch (error) {
            if (!hasFallback) {
                throw error;
            }
            return jsonResponse(data.discovery_payloads[apiKey], 200, headers);
        }
        if (hasFallback && discovered.status !== 200) {
            return jsonResponse(data.discovery_payloads[apiKey], 200, headers);
        }
        if (discovered.payload !== null && discovered.payload !== undefined) {
            return jsonResponse(discovered.payload, discovered.status, headers);
        }
        return new Response(discovered.detail || "", { status: discovered.status, headers });
    }

    async scheduleResponse() {
        const data = await this.rebuildScheduleIfNeeded(nowUtc());
        const headers = {
            ...scheduleHeaders(this.env, data.schedule, pollingAdvice(this.env, data.telemetry)),
            "cache-control": "no-store",
        };
        return new Response(null, { status: 204, headers });
    }

    async resourceResponseForKind(url, kind) {
        const pathRaw = new URL(url).pathname;
        const path = pathRaw.startsWith(`${DO_ROUTE_PREFIX}/`) ? pathRaw.slice(DO_ROUTE_PREFIX.length) : pathRaw;
        const siteId = path.split("/")[2] || "";
        return this.resourceResponse(url, siteId, kind);
    }

    async fetch(request) {
        const url = new URL(request.url);
        let path = url.pathname;

        if (path.startsWith(`${DO_ROUTE_PREFIX}/`)) {
            path = path.slice(DO_ROUTE_PREFIX.length);
        }

        if (path === "/__scheduled") {
            const atMs = Number(url.searchParams.get("at") || "");
            const invokedAt = Number.isFinite(atMs) && atMs > 0 ? new Date(atMs) : nowUtc();
            await this.runTick(invokedAt);
            return new Response(null, { status: 204 });
        }

        if (path === "/proxy_status" || path === "/proxy-status") {
            return this.statusResponse();
        }

        if (path === "/proxy_schedule" || path === "/schedule") {
            return this.scheduleResponse();
        }

        if (path === "/rooftop_sites") {
            return this.discoveryResponse(request.url);
        }

        if (path.startsWith("/rooftop_sites/") && path.endsWith("/forecasts")) {
            return this.resourceResponseForKind(request.url, "forecasts");
        }

        if (path.startsWith("/rooftop_sites/") && path.endsWith("/estimated_actuals")) {
            return this.resourceResponseForKind(request.url, "estimated_actuals");
        }

        return new Response("Not found", { status: 404 });
    }

    async alarm() {
        const data = await this.load();
        const retryState = data.retry && typeof data.retry === "object" ? data.retry : newRetryState();
        if (!retryState.active) {
            return;
        }
        if (!Array.isArray(retryState.kinds) || retryState.kinds.length === 0) {
            data.retry = newRetryState();
            try {
                await this.state.storage.deleteAlarm();
            } catch {
                // ignore
            }
            await this.save(data);
            return;
        }
        await this.runCollectionCycle(null);
    }
}

function coordinatorStub(env) {
    return env.PROXY_COORDINATOR.getByName("global");
}

function edgeRequest(path, url, method) {
    const target = new URL(`https://proxy.internal${DO_ROUTE_PREFIX}${path}`);
    target.search = url.search;
    return new Request(target.toString(), { method });
}

export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        const path = url.pathname;

        if (path === "/") {
            return new Response(null, {
                status: 204,
                headers: {
                    "cache-control": "public, max-age=86400, immutable",
                },
            });
        }

        if (path === "/robots.txt") {
            return new Response("User-agent: *\nDisallow: /\n", {
                status: 200,
                headers: {
                    "content-type": "text/plain; charset=utf-8",
                    "cache-control": "public, max-age=86400, immutable",
                },
            });
        }

        if (path === "/favicon.ico") {
            return new Response(null, {
                status: 204,
                headers: {
                    "cache-control": "public, max-age=86400, immutable",
                },
            });
        }

        if (
            path === "/rooftop_sites" ||
            path === "/proxy-status" ||
            path === "/proxy_status" ||
            path === "/proxy_schedule" ||
            path === "/schedule" ||
            path === "/__scheduled" ||
            (path.startsWith("/rooftop_sites/") && (path.endsWith("/forecasts") || path.endsWith("/estimated_actuals")))
        ) {
            return coordinatorStub(env).fetch(edgeRequest(path, url, request.method));
        }

        return new Response("Not found", { status: 404 });
    },

    async scheduled(controller, env) {
        // Single fixed tick. Coordinator decides whether any update is due.
        const cron = String(controller.cron);
        const now = nowUtc();
        console.log("[proxy-js] scheduled tick", { cron, at: iso(now), second: now.getUTCSeconds() });
        const params = new URLSearchParams({
            cron,
            at: String(now.getTime()),
        });
        const req = new Request(`https://proxy.internal/__scheduled?${params.toString()}`, { method: "POST" });
        await coordinatorStub(env).fetch(req);
    },
};
