#!/usr/bin/env python3
"""Launch local Wrangler with the running simulator's memory-backed certificate."""

import argparse
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tomllib

PROC_ROOT = Path("/proc")
DEFAULT_CONFIG = Path(__file__).with_name("solcast-proxy-worker") / "wrangler.toml"


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
        raise RuntimeError(
            f"No simulator is listening on port {port}. Start wsgi_sim.py first."
        )
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


def main(argv: list[str] | None = None) -> None:
    """Check the simulator's live certificate and replace this process with Wrangler."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Local Wrangler configuration",
    )
    parser.add_argument(
        "--port", type=int, default=9443, help="Wrangler HTTPS listening port"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify simulator TLS without starting Wrangler",
    )
    args = parser.parse_args(argv)
    try:
        config_path = args.config.resolve()
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
        variables = config["vars"]
        if variables["SOLCAST_HOST"] != "localhost":
            parser.error('This local launcher requires SOLCAST_HOST = "localhost".')
        simulator_port = int(variables["SOLCAST_PORT"])
        certificate = _simulator_certificate(simulator_port)
        _verify_simulator(certificate, simulator_port)
        print(  # noqa: T201
            f"Verified simulator HTTPS on localhost:{simulator_port}; trusting {certificate}",
            flush=True,
        )
        if args.check_only:
            return
        wrangler = shutil.which("wrangler")
        if wrangler is None:
            parser.error(
                "Wrangler is not on PATH. Activate your Node/nvm environment first."
            )
        environment = dict(os.environ, NODE_EXTRA_CA_CERTS=str(certificate))
        os.execvpe(
            wrangler,
            [
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
            ],
            environment,
        )
    except (OSError, ValueError, KeyError, RuntimeError) as err:
        parser.exit(1, f"Local proxy not started: {err}\n")


if __name__ == "__main__":
    main()
