#!/usr/bin/env python3
"""Offline coin staging: validate a registry or prepare isolated regtest plans.

This tool has no network, subprocess, mining, wallet or payout implementation.
It is intentionally separate from the single-coin BTCS backend.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "coins.example.json"
ALGORITHMS = {
    "btcs": "sha256d",
    "btc": "sha256d",
    "bch": "sha256d",
    "ltc": "scrypt",
    "doge": "scrypt-auxpow",
}
DISABLED_FLAGS = {
    "download_enabled", "node_start_enabled", "pool_start_enabled",
    "explorer_enabled", "payouts_enabled",
}
COIN_KEYS = {
    "id", "name", "algorithm", "daemon", "config_filename", "description",
    "source_url", "pool_adapter", "regtest", *DISABLED_FLAGS,
}
REGTEST_KEYS = {"ports", "expected_genesis_hash", "genesis_source_url"}
PORT_KEYS = {"rpc", "p2p", "api", "stratum"}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
FILENAME_RE = re.compile(r"[a-z][a-z0-9_-]*\.conf\Z")
DAEMON_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")


class ProfileError(ValueError):
    pass


def _keys(obj: object, expected: set[str], label: str) -> dict:
    if not isinstance(obj, dict):
        raise ProfileError(f"{label} must be an object")
    missing, extra = expected - obj.keys(), obj.keys() - expected
    if missing or extra:
        raise ProfileError(
            f"{label} has missing keys {sorted(missing)} or unknown keys {sorted(extra)}"
        )
    return obj


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ProfileError(f"{label} must be nonempty text without control characters")
    return value


def _https(value: object, label: str) -> str:
    text = _text(value, label)
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ProfileError(f"{label} must be an HTTPS source URL without credentials")
    return text


def validate_registry(registry: object) -> dict:
    registry = _keys(registry, {"schema_version", "mode", "coins"}, "registry")
    if type(registry["schema_version"]) is not int or registry["schema_version"] != 1:
        raise ProfileError("unsupported registry schema_version")
    if registry["mode"] != "test-only":
        raise ProfileError("registry mode must be test-only")
    coins = registry["coins"]
    if not isinstance(coins, list) or not coins:
        raise ProfileError("registry coins must be a nonempty list")
    seen_ids: set[str] = set()
    seen_ports: dict[int, str] = {}
    for coin in coins:
        coin = _keys(coin, COIN_KEYS, "coin")
        coin_id = coin["id"]
        if not isinstance(coin_id, str) or coin_id not in ALGORITHMS:
            raise ProfileError(f"unknown coin id {coin_id!r}")
        if coin_id in seen_ids:
            raise ProfileError(f"duplicate coin id {coin_id}")
        seen_ids.add(coin_id)
        if coin["algorithm"] != ALGORITHMS[coin_id]:
            raise ProfileError(f"unexpected algorithm for {coin_id}")
        for key in ("name", "description"):
            _text(coin[key], f"{coin_id}.{key}")
        _https(coin["source_url"], f"{coin_id}.source_url")
        if not isinstance(coin["daemon"], str) or not DAEMON_RE.fullmatch(coin["daemon"]):
            raise ProfileError(f"invalid daemon name for {coin_id}")
        if not isinstance(coin["config_filename"], str) or not FILENAME_RE.fullmatch(coin["config_filename"]):
            raise ProfileError(f"invalid config filename for {coin_id}")
        for flag in DISABLED_FLAGS:
            if coin[flag] is not False:
                raise ProfileError(f"{coin_id}.{flag} must remain false in staging")
        expected_adapter = "existing-btcs-sha256d" if coin_id == "btcs" else None
        if coin["pool_adapter"] != expected_adapter:
            raise ProfileError(f"pool adapter unavailable for {coin_id}")
        regtest = _keys(coin["regtest"], REGTEST_KEYS, f"{coin_id}.regtest")
        genesis = regtest["expected_genesis_hash"]
        if not isinstance(genesis, str) or not HASH_RE.fullmatch(genesis):
            raise ProfileError(f"{coin_id} requires an explicit lowercase 64-character genesis hash")
        _https(regtest["genesis_source_url"], f"{coin_id}.genesis_source_url")
        ports = _keys(regtest["ports"], PORT_KEYS, f"{coin_id}.ports")
        for kind, port in ports.items():
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ProfileError(f"invalid unprivileged port for {coin_id}.{kind}")
            if port in seen_ports:
                raise ProfileError(f"port collision: {coin_id}.{kind} and {seen_ports[port]}")
            seen_ports[port] = f"{coin_id}.{kind}"
    return registry


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ProfileError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def load_registry(path: Path) -> dict:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (OSError, ValueError) as exc:
        raise ProfileError(f"cannot read registry: {exc}") from exc
    return validate_registry(registry)


def _safe_path(value: str | Path, label: str) -> Path:
    text = str(value)
    if any(ord(c) < 32 for c in text) or "#" in text or ".." in Path(text).parts:
        raise ProfileError(f"{label} contains unsafe path characters or traversal")
    path = Path(text)
    if not path.is_absolute() or path == Path(path.anchor):
        raise ProfileError(f"{label} must be an explicit absolute path below the filesystem root")
    # A mounted drive is fine. Symlink aliases make data isolation harder to review.
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ProfileError(f"{label} must not use symlink paths")
    return path.resolve(strict=False)


def _node_config(coin: dict, datadir: Path) -> str:
    ports = coin["regtest"]["ports"]
    return "\n".join([
        f"# Silver Pool {coin['id']} regtest STAGING ONLY; runtime is not verified.",
        "# No process is started by scripts/coins.py. Use a reviewed binary later.",
        "# Local cookie authentication: no RPC password or wallet material here.",
        "regtest=1", f"datadir={datadir}", "server=1", "daemon=0",
        "listen=0", "discover=0", "dnsseed=0", "connect=0",
        "dbcache=64", "maxmempool=32", "maxconnections=4", "prune=0", "txindex=0",
        "", "[regtest]", "rpcbind=127.0.0.1", "rpcallowip=127.0.0.1",
        f"rpcport={ports['rpc']}", f"port={ports['p2p']}", "",
    ])


def build_plan(registry: dict, storage_root: str | Path, coin_ids: list[str] | None = None,
               network: str = "regtest") -> dict:
    validate_registry(registry)
    if network != "regtest":
        raise ProfileError("only isolated regtest planning is supported")
    root = _safe_path(storage_root, "storage root")
    available = {coin["id"]: coin for coin in registry["coins"]}
    selected = list(available) if coin_ids is None else coin_ids
    if not selected or len(set(selected)) != len(selected):
        raise ProfileError("select at least one coin without duplicates")
    unknown = set(selected) - available.keys()
    if unknown:
        raise ProfileError(f"unknown coins: {sorted(unknown)}")
    profiles = []
    for coin_id in selected:
        coin = available[coin_id]
        datadir = _safe_path(root / "nodes" / coin_id / network, "node datadir")
        pool_db = _safe_path(root / "pools" / coin_id / network / "pool.sqlite3", "pool database")
        if datadir.exists() or pool_db.exists():
            raise ProfileError(f"refusing to plan over existing node data or pool database for {coin_id}")
        profiles.append({
            "coin": coin_id,
            "name": coin["name"],
            "algorithm": coin["algorithm"],
            "status": "disabled-test-staging",
            "pool_adapter": coin["pool_adapter"],
            "node_runtime_verified": False,
            "backend_adapter_available": coin_id == "btcs",
            "pool_integration_verified": False,
            "network": network,
            "node_datadir": str(datadir),
            # Bitcoin-family daemons append their own regtest subdirectory.
            "node_chain_directory": str(datadir / network),
            "pool_database": str(pool_db),
            "ports": dict(coin["regtest"]["ports"]),
            "rpc_url": f"http://127.0.0.1:{coin['regtest']['ports']['rpc']}",
            "api_host": "127.0.0.1",
            "stratum_host": "127.0.0.1",
            "identity_expectation": {
                "chain": "regtest",
                "genesis_hash": coin["regtest"]["expected_genesis_hash"],
                "source_url": coin["regtest"]["genesis_source_url"],
                "verified": False,
                "requires_reviewed_pinned_binary": True,
                "note": "Genesis is necessary but not unique across forks; verify the binary and RPC implementation too.",
            },
            "capabilities": {flag: False for flag in sorted(DISABLED_FLAGS)},
            "node_config_filename": coin["config_filename"],
            "node_config": _node_config(coin, datadir),
            "pool_config": {
                "enabled": False, "auto_payouts": False, "payouts_enabled": False,
                "note": "Planning metadata only; not consumed by the BTCS backend.",
            },
            "description": coin["description"],
        })
    return {
        "schema_version": 1,
        "mode": "test-only",
        "status": "plan-only",
        "storage_root": str(root),
        "storage_confirmed": False,
        "starts_processes": False,
        "downloads_data": False,
        "payouts_enabled": False,
        "profiles": profiles,
        "next_checks": [
            "Confirm target drive, available storage/RAM and selected coins with the operator.",
            "Choose and verify a pinned official binary before any installation.",
            "Check actual free ports and node option compatibility; reservations are not live port checks.",
            "Verify chain, genesis and implementation against the selected binary.",
            "Complete real-node adapter tests before enabling any additional mining pool.",
        ],
    }


def write_bundle(plan: dict, output_directory: str | Path) -> Path:
    """Write review artifacts only, using exclusive creation and no overwrite."""
    output = _safe_path(output_directory, "output directory")
    storage = Path(plan["storage_root"])
    if output == storage or storage in output.parents:
        raise ProfileError("write review artifacts outside the planned storage root")
    files = {"plan.json": json.dumps(plan, indent=2) + "\n"}
    for profile in plan["profiles"]:
        files[f"{profile['coin']}-regtest.conf"] = profile["node_config"]
    if output.exists() and not output.is_dir():
        raise ProfileError("output directory is not a directory")
    if any((output / name).exists() or (output / name).is_symlink() for name in files):
        raise ProfileError("refusing to overwrite existing plan/config artifacts")
    output.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for name, content in files.items():
            path = output / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return output / "plan.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate disabled registry profiles offline")
    validate.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    plan_parser = commands.add_parser("plan", help="prepare regtest review artifacts; never install/start")
    plan_parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    plan_parser.add_argument("--coin", action="append", dest="coins", help="candidate id; repeat to select several")
    plan_parser.add_argument("--network", choices=["regtest"], default="regtest")
    plan_parser.add_argument("--storage-root", required=True, help="explicit absolute target path; no data is written there")
    plan_parser.add_argument("--write-dir", help="optional absolute directory for plan.json/config review artifacts")
    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.registry)
        if args.command == "validate":
            result = {
                "valid": True, "mode": "test-only", "ready_to_start": False,
                "coins": [coin["id"] for coin in registry["coins"]],
                "message": "Registry is valid for offline planning; all execution capabilities remain disabled.",
            }
        else:
            result = build_plan(registry, args.storage_root, args.coins, args.network)
            if args.write_dir:
                artifact = write_bundle(result, args.write_dir)
                result["written_plan"] = str(artifact)
        print(json.dumps(result, indent=2))
        return 0
    except (ProfileError, OSError) as exc:
        print(f"coin staging failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
