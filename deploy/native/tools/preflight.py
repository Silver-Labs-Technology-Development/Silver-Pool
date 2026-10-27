#!/usr/bin/env python3
"""Read-only preflight for the native Silver Pool deployment.

Validates the environment file, BTCS node, mainnet template, coinbase output,
database path, ports, payout lock and public-endpoint honesty before any
service is started.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import socket
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(TOOLS))

from _env import load_environment, repo_relative, secure_mode  # noqa: E402
from btcs_pool.block import target_from_bits  # noqa: E402
from btcs_pool.config import PoolConfig  # noqa: E402
from btcs_pool.rpc import BTCSRpc, RPCError  # noqa: E402

PLACEHOLDER_MARKERS = (
    "replace-",
    "replace_",
    "changeme",
    "change-this",
    "change_this",
    "your-",
    "your_",
    "<replace",
    "example.com",
    "example.org",
)
MIN_SECRET_LENGTH = 12


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str, level: str = "error") -> None:
        self.checks.append(
            {
                "name": name,
                "ok": bool(ok),
                "level": level if not ok else "ok",
                "detail": detail,
            }
        )

    def fail(self, name: str, detail: str) -> None:
        self.add(name, False, detail, "error")

    def warn(self, name: str, detail: str) -> None:
        self.add(name, True, detail, "warning")

    def info(self, name: str, detail: str) -> None:
        self.add(name, True, detail, "info")

    @property
    def ok(self) -> bool:
        return not any(item["level"] == "error" for item in self.checks)


def _is_private_host(host: str) -> bool:
    if host in {"localhost", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def _port_available(host: str, port: int) -> tuple[bool, str]:
    if port <= 0 or port > 65535:
        return False, f"invalid port {port}"
    bind_host = "" if host in {"0.0.0.0", "::"} else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
        except OSError as exc:
            return False, f"{host}:{port} unavailable: {exc.strerror or exc}"
    return True, f"{host}:{port} available"


def _check_placeholders(cfg: PoolConfig, env: dict[str, str], report: Report) -> None:
    secret_keys = {"BTCS_RPC_PASSWORD", "BTCS_STRATUM_PASSWORD"}
    for key in secret_keys:
        value = env.get(key, "")
        if not value:
            if key == "BTCS_RPC_PASSWORD":
                report.fail(key, "empty RPC password")
            else:
                report.warn(key, "empty: any non-empty miner password is accepted")
            continue
        lowered = value.lower()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            report.fail(key, "still contains a placeholder value")
        elif len(value) < MIN_SECRET_LENGTH:
            report.fail(key, f"shorter than {MIN_SECRET_LENGTH} characters")
        else:
            report.info(key, f"configured ({len(value)} characters, value not printed)")
    for key in ("BTCS_RPC_USER", "BTCS_POOL_ADDRESS", "BTCS_POOL_SCRIPT_PUBKEY"):
        value = env.get(key, "")
        if value and any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
            report.fail(key, "still contains a placeholder value")


def _check_rpc_url(cfg: PoolConfig, report: Report) -> str | None:
    parsed = urlparse(cfg.rpc_url)
    if parsed.scheme not in {"http", "https"}:
        report.fail("rpc_url", "BTCS_RPC_URL must be http:// or https://")
        return None
    if not parsed.hostname:
        report.fail("rpc_url", "BTCS_RPC_URL has no hostname")
        return None
    if parsed.path not in {"", "/"}:
        report.fail("rpc_url", "BTCS_RPC_URL must not include a wallet path")
        return None
    if not _is_private_host(parsed.hostname):
        report.fail(
            "rpc_url",
            f"RPC host {parsed.hostname!r} is not loopback/private; never expose node RPC publicly",
        )
        return None
    report.info("rpc_url", f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}")
    return parsed.hostname


def _check_node(cfg: PoolConfig, report: Report) -> tuple[BTCSRpc, dict, dict]:
    rpc = BTCSRpc(
        cfg.rpc_url,
        cfg.rpc_user,
        cfg.rpc_password,
        cfg.rpc_wallet,
        timeout=cfg.rpc_timeout_seconds,
    )
    try:
        chain = rpc.getblockchaininfo()
        network = rpc.getnetworkinfo()
        mempool = rpc.getmempoolinfo()
    except RPCError as exc:
        report.fail("node_rpc", str(exc))
        return rpc, {}, {}

    chain_name = chain.get("chain")
    if chain_name != cfg.network:
        report.fail(
            "chain",
            f"node reports {chain_name!r}, configured network is {cfg.network!r}",
        )
    else:
        report.info("chain", str(chain_name))

    blocks = int(chain.get("blocks", 0))
    headers = int(chain.get("headers", 0))
    progress = float(chain.get("verificationprogress", 0))
    ibd = bool(chain.get("initialblockdownload", True))
    if ibd:
        report.fail("sync", "node is in initial block download")
    elif progress < 0.999:
        report.fail("sync", f"verification progress {progress:.6f} < 0.999")
    elif blocks < headers:
        report.fail("sync", f"blocks {blocks} < headers {headers}")
    else:
        report.info("sync", f"height {blocks}, progress {progress:.6f}, IBD false")
    connections = int(network.get("connections", 0))
    if connections < 1:
        report.warn("peers", "node reports no peer connections")
    else:
        report.info("peers", f"{connections} connections")
    report.info(
        "node_version",
        f"{network.get('subversion', 'unknown')} (protocol {network.get('protocolversion', '?')})",
    )
    report.info("mempool", f"{int(mempool.get('size', 0))} transactions")
    return rpc, chain, network


def _check_template(rpc: BTCSRpc, chain: dict, report: Report) -> dict:
    try:
        template = rpc.getblocktemplate(["segwit"])
        best_hash = rpc.getbestblockhash()
        block_count = int(rpc.getblockcount())
    except RPCError as exc:
        report.fail("block_template", str(exc))
        return {}
    if not isinstance(template, dict) or not template.get("height"):
        report.fail("block_template", "getblocktemplate returned no usable template")
        return {}
    height = int(template["height"])
    if height != block_count + 1:
        report.fail(
            "template_height",
            f"template height {height} != node height {block_count} + 1",
        )
    else:
        report.info("template_height", str(height))
    if template.get("previousblockhash") != best_hash:
        report.fail("template_previous", "template previousblockhash is not the current best block")
    try:
        target = target_from_bits(str(template["bits"]))
        if target <= 0:
            raise ValueError("target is zero")
        report.info("template_bits", f"{template['bits']} (target 0x{target:064x})")
    except (KeyError, ValueError) as exc:
        report.fail("template_bits", f"invalid bits: {exc}")
    coinbase_value = int(template.get("coinbasevalue", 0))
    if coinbase_value <= 0:
        report.fail("template_coinbase", "coinbasevalue is not positive")
    else:
        report.info(
            "template_coinbase",
            f"{coinbase_value} satoshi, {len(template.get('transactions', []))} transactions",
        )
    if not template.get("default_witness_commitment"):
        report.warn("template_segwit", "no default_witness_commitment in template")
    else:
        report.info("template_segwit", "witness commitment present")
    if chain.get("blocks") is not None and int(chain["blocks"]) != block_count:
        report.warn("template_node", "block count changed while preflight was running")
    return template


def _check_coinbase(
    rpc: BTCSRpc, cfg: PoolConfig, report: Report, address: str = ""
) -> str:
    script = ""
    if cfg.pool_script_pubkey:
        try:
            raw = bytes.fromhex(cfg.pool_script_pubkey)
        except ValueError:
            report.fail("coinbase_script", "BTCS_POOL_SCRIPT_PUBKEY is not valid hex")
            return ""
        if not 2 <= len(raw) <= 10_000:
            report.fail("coinbase_script", "BTCS_POOL_SCRIPT_PUBKEY has an invalid length")
            return ""
        script = cfg.pool_script_pubkey
        report.info("coinbase_script", f"configured ({len(raw)} bytes)")
    elif cfg.pool_address:
        try:
            info = rpc.validateaddress(cfg.pool_address)
        except RPCError as exc:
            report.fail("coinbase_address", str(exc))
            return ""
        if not info.get("isvalid"):
            report.fail("coinbase_address", "BTCS_POOL_ADDRESS is not valid on this network")
            return ""
        script = info.get("scriptPubKey", "")
        if not script:
            report.fail("coinbase_address", "validateaddress returned no scriptPubKey")
            return ""
        report.info(
            "coinbase_address",
            f"valid {len(bytes.fromhex(script))}-byte script"
            + (" (P2WPKH/P2WSH witness)" if info.get("iswitness") else ""),
        )
        if cfg.rpc_wallet:
            try:
                wallet_info = rpc.getaddressinfo(cfg.pool_address)
                if wallet_info.get("ismine") is False:
                    report.warn(
                        "coinbase_ownership",
                        "BTCS_POOL_ADDRESS is not owned by the configured wallet; block rewards will go elsewhere",
                    )
                else:
                    report.info("coinbase_ownership", "address is in the configured wallet")
            except RPCError as exc:
                report.warn(
                    "coinbase_ownership",
                    f"could not check wallet ownership: {exc}",
                )
    else:
        report.fail(
            "coinbase",
            "set BTCS_POOL_ADDRESS or BTCS_POOL_SCRIPT_PUBKEY; preflight will not create a wallet address",
        )
    if address and cfg.pool_address and address != cfg.pool_address:
        report.warn("coinbase_address", "address differs from the value provided to preflight")
    return script


def _check_database(cfg: PoolConfig, report: Report) -> dict:
    path = repo_relative(cfg.db_path)
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        parent.chmod(0o700)
    except OSError as exc:
        report.fail("database_path", f"cannot create {parent}: {exc}")
        return {"path": str(path)}
    if not os.access(parent, os.W_OK):
        report.fail("database_path", f"{parent} is not writable")
        return {"path": str(path)}
    free = shutil.disk_usage(parent).free
    if free < 1 * 1024**3:
        report.fail("disk_space", f"{free // 1024**2} MiB free; need at least 1 GiB")
    else:
        report.info("disk_space", f"{free // 1024**2} MiB free")
    result = {"path": str(path), "exists": path.exists()}
    if path.exists():
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                tables = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
                version = None
                try:
                    version = connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                except sqlite3.Error:
                    version = None
            finally:
                connection.close()
            result.update({"integrity": integrity, "tables": tables, "schema_version": version})
            if integrity != "ok":
                report.fail("database_integrity", f"quick_check returned {integrity!r}")
            else:
                report.info(
                    "database",
                    f"existing {path.stat().st_size // 1024} KiB, {tables} tables, schema {version}",
                )
        except sqlite3.Error as exc:
            report.fail("database", f"cannot read existing database: {exc}")
    else:
        report.info("database", f"new database will be initialized at {path}")
    return result


def _check_ports(cfg: PoolConfig, env: dict[str, str], report: Report) -> None:
    targets = [
        ("api", cfg.api_host, cfg.api_port),
        ("stratum", cfg.stratum_host, cfg.stratum_port),
        (
            "website",
            env.get("SILVER_POOL_HTTP_BIND", "127.0.0.1"),
            int(env.get("SILVER_POOL_HTTP_PORT", "8080")),
        ),
    ]
    seen: set[tuple[str, int]] = set()
    for name, host, port in targets:
        key = (host, port)
        if key in seen:
            report.fail(f"port_{name}", f"duplicate bind {host}:{port}")
            continue
        seen.add(key)
        available, detail = _port_available(host, port)
        if available:
            report.info(f"port_{name}", detail)
        else:
            report.warn(
                f"port_{name}",
                detail + " (if the service is already running this is expected)",
            )


def _check_public_endpoint(cfg: PoolConfig, report: Report) -> None:
    if not cfg.public_stratum_host:
        report.info("public_stratum", "not configured; API/site will report Not configured")
        return
    host = cfg.public_stratum_host
    if any(marker in host.lower() for marker in PLACEHOLDER_MARKERS):
        report.fail("public_stratum", "contains a placeholder hostname")
        return
    report.warn(
        "public_stratum",
        f"advertised as {host}:{cfg.public_stratum_port}; external TCP reachability has NOT been verified",
    )
    if cfg.public_stratum_port <= 0 or cfg.public_stratum_port > 65535:
        report.fail("public_stratum", "invalid public stratum port")


def _check_ignored(path: Path, report: Report) -> None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=REPO_ROOT,
            check=False,
        )
    except OSError as exc:
        report.warn("git_ignore", f"git unavailable: {exc}")
        return
    if result.returncode == 0:
        report.info("git_ignore", f"{path.name} is ignored by Git")
    else:
        report.fail("git_ignore", f"{path} is NOT ignored by Git; do not commit it")


def run(env_file: Path, strict_ports: bool = False) -> tuple[Report, dict]:
    report = Report()
    summary: dict = {
        "checked_at": time.time(),
        "env_file": str(env_file),
        "repo_root": str(REPO_ROOT),
    }
    if not env_file.exists():
        report.fail("env_file", f"missing {env_file}; copy .env.native.example and edit it")
        return report, summary
    mode_ok, mode_detail = secure_mode(env_file)
    if mode_ok:
        report.info("env_file", f"{env_file} mode {mode_detail}")
    else:
        report.fail("env_file", mode_detail)
    _check_ignored(env_file, report)
    try:
        env = load_environment(env_file)
    except (OSError, ValueError) as exc:
        report.fail("env_file", str(exc))
        return report, summary
    summary["env_keys"] = sorted(env.keys())
    try:
        cfg = PoolConfig.from_env()
    except (TypeError, ValueError) as exc:
        report.fail("config", str(exc))
        return report, summary

    summary.update(
        {
            "network": cfg.network,
            "fee_percent": cfg.pool_fee,
            "auto_payouts": cfg.auto_payouts,
            "maturity_confirmations": cfg.maturity_confirmations,
            "api": f"{cfg.api_host}:{cfg.api_port}",
            "stratum": f"{cfg.stratum_host}:{cfg.stratum_port}",
            "public_stratum": cfg.public_stratum,
            "db_path": str(repo_relative(cfg.db_path)),
            "coinbase_address_configured": bool(cfg.pool_address),
            "coinbase_script_configured": bool(cfg.pool_script_pubkey),
        }
    )

    if cfg.auto_payouts:
        report.fail("payout_safety", "BTCS_AUTO_PAYOUTS must remain false")
    else:
        report.info("payout_safety", "BTCS_AUTO_PAYOUTS=false")
    if cfg.network != "main":
        report.fail("network", f"expected mainnet, got {cfg.network!r}")
    if cfg.pool_fee < 0 or cfg.pool_fee > 5:
        report.fail("pool_fee", "must be between 0 and 5 percent")
    else:
        report.info("pool_fee", f"{cfg.pool_fee:.2f}%")
    if cfg.maturity_confirmations <= 0:
        report.fail("maturity", "BTCS_MATURITY_CONFIRMATIONS must be positive")
    _check_placeholders(cfg, env, report)
    _check_rpc_url(cfg, report)
    _check_public_endpoint(cfg, report)
    _check_ports(cfg, env, report)
    if strict_ports and any(
        item["name"].startswith("port_") and item["level"] == "warning"
        for item in report.checks
    ):
        report.fail("ports", "--strict-ports requested and a port is unavailable")

    rpc, chain, _network = _check_node(cfg, report)
    if chain:
        summary.update(
            {
                "chain": chain.get("chain"),
                "height": chain.get("blocks"),
                "headers": chain.get("headers"),
                "verification_progress": chain.get("verificationprogress"),
                "difficulty": chain.get("difficulty"),
            }
        )
        template = _check_template(rpc, chain, report)
        if template:
            summary["template"] = {
                "height": template.get("height"),
                "bits": template.get("bits"),
                "coinbase_value_satoshi": template.get("coinbasevalue"),
                "transactions": len(template.get("transactions", [])),
            }
            script = _check_coinbase(rpc, cfg, report)
            summary["coinbase_script_bytes"] = len(bytes.fromhex(script)) if script else 0
    summary["database"] = _check_database(cfg, report)
    return report, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        default=str(REPO_ROOT / ".env.native"),
        help="path to the native environment file",
    )
    parser.add_argument("--json", action="store_true", help="print JSON evidence")
    parser.add_argument(
        "--strict-ports",
        action="store_true",
        help="fail when a configured local port is already in use",
    )
    args = parser.parse_args()
    report, summary = run(Path(args.env_file), strict_ports=args.strict_ports)
    summary["ok"] = report.ok
    summary["checks"] = report.checks
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for item in report.checks:
            label = "PASS" if item["ok"] and item["level"] != "warning" else (
                "WARN" if item["ok"] else "FAIL"
            )
            print(f"{label:4} {item['name']}: {item['detail']}")
        print()
        print("PREFLIGHT", "PASS" if report.ok else "FAIL")
        if summary.get("height") is not None:
            template = summary.get("template", {})
            print(
                f"network={summary.get('chain')} height={summary.get('height')} "
                f"template={template.get('height')} bits={template.get('bits')} "
                f"coinbase={template.get('coinbase_value_satoshi')} sat"
            )
        print(
            f"api={summary.get('api')} stratum={summary.get('stratum')} "
            f"db={summary.get('database', {}).get('path')}"
        )
        print(
            f"payouts={summary.get('auto_payouts')} fee={summary.get('fee_percent')}% "
            f"public_stratum={summary.get('public_stratum', {}).get('endpoint') or 'not configured'}"
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
