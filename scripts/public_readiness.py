#!/usr/bin/env python3
"""Read-only external connectivity probe for Silver Pool.

Run from a machine OUTSIDE the pool's network. No credentials, miner
authorization, share submission, wallet access, or pool state changes.
Passing is evidence of API TLS/health/readiness and a Stratum subscription,
NOT proof of accepted mining shares, secure hosting, or payout readiness.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def api_origin(raw: str) -> str:
    """Require an HTTPS origin (no credentials, query, fragment or subpath)."""
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("--api-base must be a bare HTTPS origin, e.g. https://pool.example")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid HTTPS port") from exc
    if port is not None and port <= 0:
        raise ValueError("invalid HTTPS port")
    return raw.rstrip("/")


def fetch_json(url: str, timeout: float) -> dict:
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=timeout) as response:
            # Never count a redirect to a different host or to HTTP as a pass.
            target = urlsplit(response.geturl())
            source = urlsplit(url)
            if target.scheme != "https" or target.netloc.lower() != source.netloc.lower():
                raise ValueError("redirected away from expected HTTPS origin")
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")
            if "application/json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("response is not JSON (static-only website?)")
            payload = response.read(65537)
            if len(payload) > 65536:
                raise ValueError("response exceeds 64 KiB")
    except HTTPError as exc:
        raise ValueError(f"HTTP {exc.code} (backend not ready or unavailable)") from exc
    except (URLError, OSError) as exc:
        raise ValueError(f"connection failed: {exc.reason if isinstance(exc, URLError) else exc}") from exc

    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid JSON response") from exc
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def validate_health(payload: dict) -> None:
    data = payload.get("data")
    if payload.get("ok") is not True or not isinstance(data, dict):
        raise ValueError("API health envelope is not successful")
    if data.get("service") != "silver-pool":
        raise ValueError("wrong service at API address")
    if data.get("status") != "ok" or (data.get("database") or {}).get("healthy") is not True:
        raise ValueError("pool database health is not OK")


def validate_ready(payload: dict) -> None:
    data = payload.get("data")
    if payload.get("ok") is not True or not isinstance(data, dict):
        raise ValueError("API reports not ready")
    if data.get("ready") is not True:
        raise ValueError("pool readiness flag is not true")
    node, stratum = data.get("node") or {}, data.get("stratum") or {}
    if node.get("connected") is not True or node.get("synced") is not True:
        raise ValueError("node connection/sync not ready")
    if stratum.get("running") is not True or stratum.get("template_fresh") is not True:
        raise ValueError("Stratum listener/template not ready")
    if not stratum.get("current_job_id"):
        raise ValueError("no current mining job")


def validate_config(payload: dict, host: str, port: int) -> None:
    data = payload.get("data")
    if payload.get("ok") is not True or not isinstance(data, dict):
        raise ValueError("cannot read public pool config")
    if data.get("network") != "main":
        raise ValueError("public pool is not configured for BTCS mainnet")
    if data.get("payouts_enabled") is not False or data.get("auto_payouts") is not False:
        raise ValueError("payout safety state is not explicitly disabled")
    stratum = data.get("stratum") or {}
    if stratum.get("configured") is not True or not stratum.get("endpoint"):
        raise ValueError("Stratum endpoint is not advertised")
    if str(stratum.get("host", "")).strip("[]").lower() != host.strip("[]").lower():
        raise ValueError("advertised Stratum host differs from requested probe host")
    if stratum.get("port") != port:
        raise ValueError("advertised Stratum port differs from requested probe port")


def validate_subscribe(payload: dict) -> None:
    if payload.get("id") != 1 or payload.get("error") is not None:
        raise ValueError("Stratum subscribe was not accepted")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 3:
        raise ValueError("Stratum subscribe response has wrong format")
    subscriptions, extranonce1, extranonce2_size = result
    if not isinstance(subscriptions, list) or not isinstance(extranonce1, str):
        raise ValueError("Stratum subscribe response has invalid fields")
    if not extranonce1 or not isinstance(extranonce2_size, int) or extranonce2_size <= 0:
        raise ValueError("Stratum extranonce fields invalid")


def probe_stratum(host: str, port: int, timeout: float) -> None:
    # Subscribe is read-only: NO mining.authorize and NO mining.submit.
    message = b'{"id":1,"method":"mining.subscribe","params":["silver-pool-external-probe/1.0"]}\n'
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(message)
        buffer = bytearray()
        for _ in range(16):
            chunk = connection.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > 65536:
                raise ValueError("Stratum response too large")
            while b"\n" in buffer:
                raw, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError("invalid Stratum JSON") from exc
                if isinstance(payload, dict) and payload.get("id") == 1:
                    validate_subscribe(payload)
                    return
    raise ValueError("no Stratum subscription response received")


def run_check(name: str, fn) -> Check:
    try:
        fn()
        return Check(name, True, "passed")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return Check(name, False, str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True, help="Public HTTPS origin, not GitHub Pages")
    parser.add_argument("--stratum-host", required=True, help="Public DNS name or address")
    parser.add_argument("--stratum-port", type=int, default=3333)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        origin = api_origin(args.api_base)
        if not 1 <= args.stratum_port <= 65535:
            raise ValueError("--stratum-port must be 1..65535")
        if not 0 < args.timeout <= 30:
            raise ValueError("--timeout must be greater than 0 and at most 30 seconds")
    except ValueError as exc:
        parser.error(str(exc))

    checks = [
        run_check("HTTPS /api/health", lambda: validate_health(fetch_json(origin + "/api/health", args.timeout))),
        run_check("HTTPS /api/ready", lambda: validate_ready(fetch_json(origin + "/api/ready", args.timeout))),
        run_check(
            "HTTPS public config",
            lambda: validate_config(
                fetch_json(origin + "/api/pool/config", args.timeout),
                args.stratum_host,
                args.stratum_port,
            ),
        ),
        run_check(
            "Stratum TCP subscribe",
            lambda: probe_stratum(args.stratum_host, args.stratum_port, args.timeout),
        ),
    ]
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")

    if all(check.passed for check in checks):
        print(
            "External probes passed FROM THIS MACHINE only. This does NOT prove "
            "share acceptance, payouts, security review or production launch readiness."
        )
        return 0
    print("NOT READY: one or more external probes failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
