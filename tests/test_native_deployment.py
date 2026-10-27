from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "native"
TOOLS = NATIVE / "tools"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_native_env_example_is_placeholder_only_and_loopback_safe():
    values = parse_env(ROOT / ".env.native.example")
    assert values["BTCS_NETWORK"] == "main"
    assert values["BTCS_AUTO_PAYOUTS"] == "false"
    assert values["BTCS_RPC_URL"] == "http://127.0.0.1:10567"
    assert values["BTCS_RPC_PASSWORD"].startswith("replace-with-")
    assert values["BTCS_POOL_ADDRESS"] == ""
    assert values["BTCS_POOL_SCRIPT_PUBKEY"] == ""
    assert values["BTCS_STRATUM_HOST"] == "127.0.0.1"
    assert values["BTCS_STRATUM_PASSWORD"].startswith("replace-with-")
    assert values["BTCS_PUBLIC_STRATUM_HOST"] == ""
    assert values["BTCS_POOL_DB"].startswith("data/")
    assert values["SILVER_POOL_HTTP_BIND"] == "127.0.0.1"
    text = (ROOT / ".env.native.example").read_text(encoding="utf-8")
    assert "bs1" not in text
    assert "24.114." not in text


def test_native_scripts_are_executable_and_parse():
    scripts = sorted(NATIVE.glob("*.sh"))
    assert {path.name for path in scripts} >= {
        "install.sh",
        "preflight.sh",
        "start.sh",
        "stop.sh",
        "status.sh",
        "logs.sh",
        "backup.sh",
        "restore.sh",
        "upgrade.sh",
        "verify-mainnet.sh",
        "check-secrets.sh",
    }
    for script in scripts:
        assert script.stat().st_mode & 0o111, f"{script} is not executable"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script}: {result.stderr}"
    for tool in sorted(TOOLS.glob("*.py")):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(tool)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{tool}: {result.stderr}"


def test_native_units_have_hardening_and_expected_entrypoints():
    backend = (NATIVE / "systemd" / "silver-pool.service.in").read_text(encoding="utf-8")
    website = (NATIVE / "systemd" / "silver-pool-web.service.in").read_text(encoding="utf-8")
    for unit in (backend, website):
        assert "EnvironmentFile=@REPO@/.env.native" in unit
        assert "NoNewPrivileges=true" in unit
        assert "PrivateTmp=true" in unit
        assert "ProtectSystem=strict" in unit
        assert "ProtectHome=read-only" in unit
        assert "Restart=on-failure" in unit
    assert "ExecStart=@VENV@/bin/python -m btcs_pool.server" in backend
    assert "ReadWritePaths=@REPO@/data @REPO@/logs @REPO@/run" in backend
    assert "Environment=SITE_ROOT=@REPO@/site/_site" in website
    assert "ExecStart=@NODE@ @REPO@/site/scripts/serve.mjs" in website


def test_gitignore_ignores_live_runtime_and_allows_examples():
    assert (ROOT / ".gitignore").read_text(encoding="utf-8").count("!.env.native.example") == 1
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env.native"], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0
    allowed = subprocess.run(
        ["git", "check-ignore", "-q", ".env.native.example"], cwd=ROOT, check=False
    )
    assert allowed.returncode == 1
    for path in ("data/mainnet/pool.sqlite3", "logs/backend.log", "run/pool.pid", "backups/pool.sqlite3"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=ROOT, check=False
        )
        assert result.returncode == 0, f"{path} is not ignored"


def test_secret_scan_passes_for_tracked_tree():
    result = subprocess.run(
        [sys.executable, str(TOOLS / "secret_scan.py"), "--quiet"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_mainnet_smoke_refuses_block_submission():
    source = (TOOLS / "mainnet_smoke.py").read_text(encoding="utf-8")
    assert "class NoSubmitRPC" in source
    assert "mainnet smoke refuses block submission" in source
    assert "no_block_submission" in source
    assert "refusing to submit it during the mainnet smoke test" in source


def test_site_server_supports_native_build_and_env_proxy():
    source = (ROOT / "site" / "scripts" / "serve.mjs").read_text(encoding="utf-8")
    assert "process.env.SITE_ROOT" in source
    assert "SILVER_POOL_HTTP_BIND" in source
    assert "SILVER_POOL_HTTP_PORT" in source
    assert "BTCS_POOL_API_HOST" in source
    assert "BTCS_POOL_API_PORT" in source
