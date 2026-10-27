#!/usr/bin/env python3
"""Render the native systemd user units with repository-specific paths."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
NATIVE = TOOLS.parent
REPO_ROOT = NATIVE.parents[1]
TEMPLATES = NATIVE / "systemd"
UNIT_NAMES = ("silver-pool.service", "silver-pool-web.service")


def render(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    if "@" in text:
        remaining = sorted(
            {part.split("@", 1)[0] for part in text.split("@")[1::2] if part}
        )
        if remaining:
            raise SystemExit(f"{template}: unexpanded placeholders: {remaining}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--venv", default=str(REPO_ROOT / ".venv"))
    parser.add_argument("--node", default=shutil.which("node") or "/usr/bin/node")
    parser.add_argument("--out-dir", default=str(Path.home() / ".config/systemd/user"))
    parser.add_argument("--no-daemon-reload", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    values = {"REPO": str(repo), "VENV": str(Path(args.venv).resolve()), "NODE": args.node}
    for name in UNIT_NAMES:
        template = TEMPLATES / f"{name}.in"
        if not template.is_file():
            raise SystemExit(f"missing unit template: {template}")
        destination = out_dir / name
        destination.write_text(render(template, values), encoding="utf-8")
        destination.chmod(0o644)
        print(f"unit={destination}")
    if not args.no_daemon_reload:
        result = subprocess.run(
            ["systemctl", "--user", "daemon-reload"], check=False
        )
        if result.returncode != 0:
            print("warning: systemctl --user daemon-reload failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
