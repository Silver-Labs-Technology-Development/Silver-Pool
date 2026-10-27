"""Shared helpers for the native Silver Pool operator tools.

These tools intentionally read one explicit environment file instead of
inheriting a developer shell. They never print secret values.
"""
from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_env_file(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"environment file not found: {path}")
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            raise ValueError(f"{path}:{number}: invalid environment key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_environment(path: str | Path) -> dict[str, str]:
    values = parse_env_file(path)
    for key, value in values.items():
        os.environ[key] = value
    return values


def secure_mode(path: str | Path) -> tuple[bool, str]:
    path = Path(path)
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return False, f"{path} has mode {mode:04o}; run: chmod 600 {path}"
    return True, f"{mode:04o}"


def repo_relative(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value
