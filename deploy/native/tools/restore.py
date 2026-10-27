#!/usr/bin/env python3
"""Restore a Silver Pool SQLite backup with a safety copy of current state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(TOOLS))

from _env import load_environment, repo_relative  # noqa: E402
from btcs_pool.config import PoolConfig  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()


def service_active() -> bool:
    try:
        return (
            subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", "silver-pool.service"],
                check=False,
            ).returncode
            == 0
        )
    except OSError:
        return False


def checkpoint_copy(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(str(source), timeout=30)
    target_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    destination.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", help="backup .sqlite3 file to restore")
    parser.add_argument(
        "--env-file", default=str(REPO_ROOT / ".env.native"), help="native environment file"
    )
    parser.add_argument("--db", help="override the destination database path")
    parser.add_argument("--yes", action="store_true", help="confirm the restore")
    parser.add_argument(
        "--allow-running",
        action="store_true",
        help="do not refuse when silver-pool.service is active (unsafe)",
    )
    args = parser.parse_args()
    if not args.yes:
        print("refusing to restore without --yes", file=sys.stderr)
        return 2
    backup = Path(args.backup).expanduser().resolve()
    if not backup.is_file():
        print(f"backup not found: {backup}", file=sys.stderr)
        return 2
    if integrity(backup) != "ok":
        print("backup failed SQLite integrity_check", file=sys.stderr)
        return 2
    if service_active() and not args.allow_running:
        print(
            "silver-pool.service is active; run deploy/native/stop.sh first",
            file=sys.stderr,
        )
        return 2
    load_environment(args.env_file)
    cfg = PoolConfig.from_env()
    destination = repo_relative(args.db or cfg.db_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safety = destination.parent / f"pre-restore-{stamp}.sqlite3"
    if destination.exists():
        checkpoint_copy(destination, safety)
        if integrity(safety) != "ok":
            print("safety copy failed integrity_check; refusing restore", file=sys.stderr)
            return 2
        print(f"safety_copy={safety}")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(destination) + suffix)
        sidecar.unlink(missing_ok=True)
    temporary = destination.with_name(destination.name + ".restore-tmp")
    shutil.copy2(backup, temporary)
    temporary.chmod(0o600)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    if integrity(destination) != "ok":
        print("restored database failed integrity_check", file=sys.stderr)
        return 2
    manifest = {
        "restored_at": time.time(),
        "restored_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backup": str(backup),
        "backup_sha256": sha256(backup),
        "destination": str(destination),
        "safety_copy": str(safety) if safety.exists() else None,
        "integrity": "ok",
    }
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
