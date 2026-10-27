#!/usr/bin/env python3
"""Create a consistent online backup of the Silver Pool SQLite database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def database_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in ("miners", "workers", "rounds", "shares", "blocks", "payouts"):
            if table in tables:
                counts[table] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
    finally:
        connection.close()
    return counts


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", default=str(REPO_ROOT / ".env.native"), help="native environment file"
    )
    parser.add_argument("--db", help="override the database path")
    parser.add_argument("--out-dir", help="override the backup directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    load_environment(args.env_file)
    cfg = PoolConfig.from_env()
    db_path = repo_relative(args.db or cfg.db_path)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    out_dir = repo_relative(args.out_dir or "backups")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = out_dir / f"pool-{stamp}.sqlite3"
    manifest_path = destination.with_suffix(".json")

    source = sqlite3.connect(str(db_path), timeout=30)
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
        source.close()
    destination.chmod(0o600)
    integrity = sqlite3.connect(str(destination)).execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        destination.unlink(missing_ok=True)
        print(f"backup integrity check failed: {integrity}", file=sys.stderr)
        return 2
    manifest = {
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(db_path),
        "backup": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": sha256(destination),
        "integrity": integrity,
        "git_head": git_head(),
        "counts": database_counts(destination),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_path.chmod(0o600)
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(f"backup={destination}")
        print(f"manifest={manifest_path}")
        print(
            f"bytes={manifest['bytes']} sha256={manifest['sha256'][:16]}… "
            f"integrity={integrity} counts={manifest['counts']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
