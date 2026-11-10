#!/usr/bin/env python3
"""Launch local Wrangler for the JS Solcast proxy against the simulator TLS cert."""

# ruff: noqa: T201

import argparse
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
from threading import Event, Thread
import tomllib
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, OpenerDirector, ProxyHandler, build_opener

from cronsim import CronSim, CronSimError

PROC_ROOT = Path("/proc")
DEFAULT_CONFIG = Path(__file__).resolve().parent / "proxy_js" / "wrangler.toml"
DEFAULT_API_KEYS = ("1", "2")
NOISY_WRANGLER_LOG_PREFIX = "Attaching additional modules:"


def _simulator_certificate(port: int) -> Path:
    """Find the public certificate belonging to the process listening on the port."""
    result = subprocess.run(
        ["lsof", "-t", "-a", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Cannot inspect port {port}: {result.stderr.strip()}")
    pids = set(result.stdout.split())
    if not pids:
        raise RuntimeError(f"No simulator is listening on port {port}. Start wsgi_sim.py first.")

    certificates = []
    for pid in pids:
        if not pid.isdecimal():
            raise RuntimeError("Invalid process ID returned by lsof")
        for descriptor in (PROC_ROOT / pid / "fd").iterdir():
            try:
                target = descriptor.readlink()
            except FileNotFoundError:
                continue
            if str(target) == "/memfd:solcast-simulator-cert (deleted)":
                certificates.append(descriptor)

    if len(certificates) != 1:
        raise RuntimeError(
            f"Expected one in-memory simulator certificate on port {port}; found {len(certificates)}. "
            "Run the current wsgi_sim.py as the same user in this container."
        )
    return certificates[0]


def _verify_simulator(certificate: Path, port: int) -> None:
    """Verify the live TLS handshake without spending API quota."""
    context = ssl.create_default_context(cafile=str(certificate))
    with (
        socket.create_connection(("localhost", port), timeout=5) as connection,
        context.wrap_socket(connection, server_hostname="localhost"),
    ):
        pass


def _should_suppress_wrangler_log(line: str) -> bool:
    """Filter the noisy Cloudflare module-attach block that repeats on local boots."""
    return line.strip().startswith(NOISY_WRANGLER_LOG_PREFIX)


def _prime_scheduler(opener: OpenerDirector, api_keys: tuple[str, ...], port: int, stop: Event) -> None:
    """Prime discovery and one immediate scheduled tick so local runs warm up quickly."""
    print("[local-cron:info] Priming JS proxy discovery and one immediate tick", flush=True)

    for api_key in dict.fromkeys(api_keys):
        if stop.is_set():
            return
        try:
            query = urlencode({"format": "json", "api_key": api_key})
            with opener.open(f"https://127.0.0.1:{port}/rooftop_sites?{query}", timeout=15) as response:
                response.read()
        except (OSError, URLError) as err:
            print(f"[local-cron:error] Discovery prime failed for api_key={api_key}: {err}", flush=True)

    if stop.is_set():
        return

    try:
        query = urlencode({"at": str(int(datetime.now(UTC).timestamp() * 1000))})
        with opener.open(f"https://127.0.0.1:{port}/__scheduled?{query}", timeout=15) as response:
            response.read()
    except (OSError, URLError) as err:
        print(f"[local-cron:error] Prime tick failed: {err}", flush=True)
    else:
        print("[local-cron:info] Prime tick complete", flush=True)


def _run_schedules(crons: list[str], port: int, stop: Event, api_keys: tuple[str, ...] = ()) -> None:
    """Emulate deployed Cron Triggers against Wrangler's local scheduled endpoint."""
    # Only the loopback Wrangler development certificate is untrusted here.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))

    if api_keys:
        _prime_scheduler(opener, api_keys, port, stop)

    now = datetime.now(UTC)
    schedules = {cron: CronSim(cron, now) for cron in crons}
    due = {cron: next(schedule) for cron, schedule in schedules.items()}

    while due and not stop.is_set():
        delay = max(0.0, (min(due.values()) - datetime.now(UTC)).total_seconds())
        if stop.wait(delay):
            return

        now = datetime.now(UTC)
        for cron, scheduled_at in list(due.items()):
            if scheduled_at > now:
                continue

            query = urlencode({"cron": cron, "at": str(int(datetime.now(UTC).timestamp() * 1000))})
            print(f"[local-cron:info] Dispatching {cron} at {scheduled_at.isoformat()}", flush=True)
            try:
                with opener.open(f"https://127.0.0.1:{port}/__scheduled?{query}", timeout=15) as response:
                    response.read()
            except (OSError, URLError) as err:
                print(f"[local-cron:error] Scheduled event {cron} failed: {err}", flush=True)
            else:
                print(f"[local-cron:info] Completed {cron}", flush=True)

            # Do not replay missed occurrences in a burst after a slow collection.
            schedules[cron] = CronSim(cron, datetime.now(UTC))
            due[cron] = next(schedules[cron])


def _launch_wrangler(
    command: list[str],
    environment: dict[str, str],
    crons: list[str] | None = None,
    port: int = 9443,
    api_keys: tuple[str, ...] = DEFAULT_API_KEYS,
) -> None:
    """Launch Wrangler and suppress repetitive module-attach table noise."""
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=environment,
    ) as process:
        assert process.stdout is not None
        suppress_block = False
        stop = Event()
        scheduler = None
        try:
            for line in process.stdout:
                if crons and scheduler is None and "[wrangler:info] Ready on https://" in line:
                    scheduler = Thread(target=_run_schedules, args=(crons, port, stop, api_keys), daemon=True)
                    scheduler.start()
                    print(f"[local-cron:info] Following configured UTC schedules: {', '.join(crons)}", flush=True)

                if suppress_block:
                    if line.startswith("⎔"):
                        suppress_block = False
                        print(line, end="", flush=True)
                        continue
                    if line.startswith(("│", "├", "└", "┌", "  ", "Total ")):
                        continue
                    if line.strip() == "":
                        continue
                    suppress_block = False

                if _should_suppress_wrangler_log(line):
                    suppress_block = True
                    continue

                print(line, end="", flush=True)
        finally:
            stop.set()
            if scheduler is not None:
                scheduler.join(timeout=16)

        raise SystemExit(process.wait())


def main(argv: list[str] | None = None) -> None:
    """Check simulator trust and launch Wrangler with scheduler emulation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Wrangler configuration path",
    )
    parser.add_argument("--port", type=int, default=9443, help="Wrangler HTTPS listening port")
    parser.add_argument("--simulator-port", type=int, help="Simulator HTTPS port override")
    parser.add_argument(
        "--api-key",
        action="append",
        help="Simulator account to prime; repeat for multiple accounts (default: 1 and 2)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify simulator TLS and config without starting Wrangler",
    )

    args = parser.parse_args(argv)

    try:
        config_path = args.config.resolve()
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)

        triggers = config.get("triggers", {})
        crons = list(dict.fromkeys(triggers.get("crons", [])))
        if not crons:
            parser.error("triggers.crons must define at least one cron expression.")
        for cron in crons:
            if len(cron.split()) != 5:
                parser.error(f"Expected a five-field cron expression: {cron}")
            next(CronSim(cron, datetime.now(UTC)))

        variables = config.get("vars", {})
        solcast_host = str(variables.get("SOLCAST_HOST", "localhost"))
        simulator_port = int(args.simulator_port or variables.get("SOLCAST_PORT", 8443))
        if solcast_host != "localhost":
            parser.error('This local launcher requires SOLCAST_HOST = "localhost" (or omit it).')

        certificate = _simulator_certificate(simulator_port)
        _verify_simulator(certificate, simulator_port)
        print(f"Verified simulator HTTPS on localhost:{simulator_port}; trusting {certificate}", flush=True)

        if args.check_only:
            return

        wrangler = shutil.which("wrangler")
        if wrangler is None:
            parser.error("Wrangler is not on PATH. Activate your Node/nvm environment first.")

        environment = dict(os.environ, NODE_EXTRA_CA_CERTS=str(certificate))
        command = [
            wrangler,
            "dev",
            "--config",
            str(config_path),
            "--local",
            "--local-protocol",
            "https",
            "--ip",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--test-scheduled",
            "--var",
            f"SOLCAST_HOST:{solcast_host}",
            "--var",
            f"SOLCAST_PORT:{simulator_port}",
        ]

        _launch_wrangler(
            command,
            environment,
            crons,
            args.port,
            tuple(args.api_key) if args.api_key else DEFAULT_API_KEYS,
        )
    except KeyboardInterrupt:
        parser.exit(130)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        CronSimError,
        StopIteration,
    ) as err:
        parser.exit(1, f"Local JS proxy not started: {err}\n")


if __name__ == "__main__":
    main()
