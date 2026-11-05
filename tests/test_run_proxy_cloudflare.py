"""Tests for automatic local simulator certificate handoff to Wrangler."""

import importlib.util
from pathlib import Path
import ssl
import subprocess
from types import ModuleType
from unittest.mock import patch

import pytest


@pytest.fixture
def launcher(tmp_path: Path) -> ModuleType:
    """Load the local launcher without launching Wrangler."""
    spec = importlib.util.spec_from_file_location(
        "solcast_local_launcher", Path(__file__).with_name("run_proxy_cloudflare.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "wrangler.toml"
    config.write_text('[vars]\nSOLCAST_HOST = "localhost"\nSOLCAST_PORT = "8443"\n')
    module.DEFAULT_CONFIG = config
    return module


@pytest.fixture
def simulator_certificate(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Expose the simulator's public descriptor beside an unrelated private descriptor."""
    descriptors = tmp_path / "123" / "fd"
    descriptors.mkdir(parents=True)
    certificate = descriptors / "4"
    certificate.symlink_to("/memfd:solcast-simulator-cert (deleted)")
    (descriptors / "6").symlink_to("/memfd:solcast-simulator-key (deleted)")
    monkeypatch.setattr(launcher, "PROC_ROOT", tmp_path)
    return certificate


def test_find_live_certificate(
    launcher: ModuleType, simulator_certificate: Path
) -> None:
    """Select only the public memfd owned by the listener, ignoring duplicate lsof PIDs."""
    with patch.object(
        launcher.subprocess,
        "run",
        return_value=subprocess.CompletedProcess([], 0, "123\n123\n", ""),
    ) as inspect:
        assert launcher._simulator_certificate(8443) == simulator_certificate
    inspect.assert_called_once_with(
        ["lsof", "-t", "-a", "-iTCP:8443", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("exit_code", "output", "error", "message"),
    [
        pytest.param(1, "", "", "No simulator is listening", id="no-listener"),
        pytest.param(
            2, "", "permission denied", "Cannot inspect port", id="lsof-error"
        ),
        pytest.param(0, "invalid", "", "Invalid process ID", id="invalid-pid"),
    ],
)
def test_listener_errors(
    launcher: ModuleType, exit_code: int, output: str, error: str, message: str
) -> None:
    """Report listener inspection errors rather than falling back to stale certificates."""
    with (
        patch.object(
            launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], exit_code, output, error),
        ),
        pytest.raises(RuntimeError, match=message),
    ):
        launcher._simulator_certificate(8443)


def test_no_memory_certificate(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a listener that has no live simulator certificate."""
    (tmp_path / "123" / "fd").mkdir(parents=True)
    monkeypatch.setattr(launcher, "PROC_ROOT", tmp_path)
    with (
        patch.object(
            launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "123", ""),
        ),
        pytest.raises(RuntimeError, match="found 0"),
    ):
        launcher._simulator_certificate(8443)


def test_ambiguous_certificate(
    launcher: ModuleType, simulator_certificate: Path
) -> None:
    """Reject ambiguity rather than trusting an arbitrary descriptor."""
    simulator_certificate.with_name("7").symlink_to(
        "/memfd:solcast-simulator-cert (deleted)"
    )
    with (
        patch.object(
            launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "123", ""),
        ),
        pytest.raises(RuntimeError, match="found 2"),
    ):
        launcher._simulator_certificate(8443)


def test_verify_tls(launcher: ModuleType) -> None:
    """Validate trust and localhost identity without an API request or private key access."""
    with (
        patch.object(launcher.ssl, "create_default_context") as create_context,
        patch.object(launcher.socket, "create_connection") as connect,
    ):
        launcher._verify_simulator(Path("/proc/123/fd/4"), 8443)
    create_context.assert_called_once_with(cafile="/proc/123/fd/4")
    connect.assert_called_once_with(("localhost", 8443), timeout=5)
    create_context.return_value.wrap_socket.assert_called_once_with(
        connect.return_value.__enter__.return_value, server_hostname="localhost"
    )


def test_launch_replaces_stale_trust(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Override inherited certificate settings for Wrangler without changing the parent shell."""
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/old/cert.pem")
    with (
        patch.object(
            launcher, "_simulator_certificate", return_value=Path("/proc/123/fd/4")
        ) as discover,
        patch.object(launcher, "_verify_simulator") as verify,
        patch.object(launcher.shutil, "which", return_value="/bin/wrangler"),
        patch.object(launcher.os, "execvpe") as execute,
    ):
        launcher.main([])
    discover.assert_called_once_with(8443)
    verify.assert_called_once_with(Path("/proc/123/fd/4"), 8443)
    command, arguments, environment = execute.call_args.args
    assert command == "/bin/wrangler"
    assert arguments == [
        "/bin/wrangler",
        "dev",
        "--config",
        str(launcher.DEFAULT_CONFIG.resolve()),
        "--local",
        "--local-protocol",
        "https",
        "--ip",
        "127.0.0.1",
        "--port",
        "9443",
        "--test-scheduled",
    ]
    assert environment["NODE_EXTRA_CA_CERTS"] == "/proc/123/fd/4"
    assert launcher.os.environ["NODE_EXTRA_CA_CERTS"] == "/old/cert.pem"


def test_check_only(launcher: ModuleType) -> None:
    """Verify live TLS without launching or stopping any service."""
    with (
        patch.object(
            launcher, "_simulator_certificate", return_value=Path("/proc/123/fd/4")
        ),
        patch.object(launcher, "_verify_simulator") as verify,
        patch.object(launcher.os, "execvpe") as execute,
    ):
        launcher.main(["--check-only"])
    verify.assert_called_once_with(Path("/proc/123/fd/4"), 8443)
    execute.assert_not_called()


def test_tls_failure_prevents_launch(
    launcher: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never launch Wrangler when the current certificate fails verification."""
    with (
        patch.object(
            launcher, "_simulator_certificate", return_value=Path("/proc/123/fd/4")
        ),
        patch.object(
            launcher,
            "_verify_simulator",
            side_effect=ssl.SSLError("certificate mismatch"),
        ),
        patch.object(launcher.os, "execvpe") as execute,
        pytest.raises(SystemExit) as exc,
    ):
        launcher.main([])
    assert exc.value.code == 1
    assert "Local proxy not started:" in capsys.readouterr().err
    execute.assert_not_called()


def test_missing_wrangler(
    launcher: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report a missing executable instead of trying to install or start anything."""
    with (
        patch.object(
            launcher, "_simulator_certificate", return_value=Path("/proc/123/fd/4")
        ),
        patch.object(launcher, "_verify_simulator"),
        patch.object(launcher.shutil, "which", return_value=None),
        patch.object(launcher.os, "execvpe") as execute,
        pytest.raises(SystemExit) as exc,
    ):
        launcher.main([])
    assert exc.value.code == 2
    assert "Wrangler is not on PATH" in capsys.readouterr().err
    execute.assert_not_called()

