#!/usr/bin/env python3
"""Scan tracked files (and optionally a release archive) for secrets.

The scan is deliberately conservative: it targets credential-bearing
filenames, private-key blocks and non-placeholder RPC/Stratum assignments. It
does not print secret values.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[2]

ALLOWED_ENV_NAMES = {".env.example", ".env.native.example"}
ALLOWED_SECRET_VALUES = {
    "",
    "test",
    "rpcpass",
    "secret",
    "pool-secret",
    "super-secret",
    "change-this-local-password",
    "pool-e2e-secret",
    "replace-with-a-long-random-rpc-password",
    "replace-with-the-node-rpc-password",
    "replace-with-a-long-random-stratum-password",
}
SECRET_NAME_PATTERNS = (
    re.compile(r"^\.env$"),
    re.compile(r"^\.env\.(?!example$|native\.example$).+"),
    re.compile(r"^wallet\.dat(\..*)?$"),
    re.compile(r".*\.(pem|key|p12|pfx)$"),
    re.compile(r".*\.(sqlite|sqlite3|db)$"),
    re.compile(r"^(id_rsa|id_ed25519)$"),
)
SECRET_PATH_PARTS = {"secrets", "backups", "data"}
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
RPC_ASSIGNMENT_RE = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?(?:rpcpassword|BTCS_RPC_PASSWORD|BTCS_STRATUM_PASSWORD)"
    r"[ \t]*=[ \t]*([^\s#]+)"
)
RPC_ARGUMENT_RE = re.compile(r"-rpcpass" r"word=([^\s]+)")


def is_secret_name(path: Path) -> bool:
    name = path.name
    if name in ALLOWED_ENV_NAMES:
        return False
    if any(pattern.match(name) for pattern in SECRET_NAME_PATTERNS):
        return True
    return any(part in SECRET_PATH_PARTS for part in path.parts)


def scan_text(label: str, text: str, findings: list[str], skip_assignments: bool = False) -> None:
    if PRIVATE_KEY_RE.search(text):
        findings.append(f"{label}: private-key block")
    if skip_assignments:
        return
    for match in RPC_ASSIGNMENT_RE.finditer(text):
        value = match.group(1)
        if value in ALLOWED_SECRET_VALUES:
            continue
        if value.startswith(("$", "${", "<")):
            continue
        findings.append(f"{label}: non-placeholder credential assignment")
    for match in RPC_ARGUMENT_RE.finditer(text):
        value = match.group(1)
        if value in ALLOWED_SECRET_VALUES:
            continue
        findings.append(f"{label}: non-placeholder -rpcpassword argument")


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT)
    return [REPO_ROOT / item.decode("utf-8") for item in raw.split(b"\0") if item]


def scan_archive(path: Path, findings: list[str]) -> None:
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                relative = Path(member.name)
                if is_secret_name(relative):
                    findings.append(f"{path.name}:{member.name}: secret-bearing filename")
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                data = handle.read()
                if b"\0" in data[:4096]:
                    continue
                scan_text(
                    f"{path.name}:{member.name}",
                    data.decode("utf-8", errors="replace"),
                    findings,
                    skip_assignments=member.name.startswith("tests/"),
                )
        return
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative = Path(member.filename)
                if is_secret_name(relative):
                    findings.append(f"{path.name}:{member.filename}: secret-bearing filename")
                    continue
                data = archive.read(member)
                if b"\0" in data[:4096]:
                    continue
                scan_text(
                    f"{path.name}:{member.filename}",
                    data.decode("utf-8", errors="replace"),
                    findings,
                    skip_assignments=member.filename.startswith("tests/"),
                )
        return
    findings.append(f"{path}: unsupported archive format (use tar or zip)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="append", default=[], help="release archive to scan")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    findings: list[str] = []
    files = tracked_files()
    for path in files:
        relative = path.relative_to(REPO_ROOT)
        if is_secret_name(relative):
            findings.append(f"{relative}: secret-bearing filename")
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(f"{relative}: cannot read ({exc})")
            continue
        if b"\0" in data[:4096]:
            continue
        scan_text(
            str(relative),
            data.decode("utf-8", errors="replace"),
            findings,
            skip_assignments=str(relative).startswith("tests/"),
        )
    for archive in args.archive:
        scan_archive(Path(archive).expanduser().resolve(), findings)
    unignored = []
    for candidate in (".env", ".env.native", ".env.mainnet.local"):
        path = REPO_ROOT / candidate
        if path.exists():
            result = subprocess.run(
                ["git", "check-ignore", "-q", str(path)], cwd=REPO_ROOT, check=False
            )
            if result.returncode != 0:
                unignored.append(candidate)
    for candidate in unignored:
        findings.append(f"{candidate}: exists but is not ignored by Git")
    if findings:
        for finding in findings:
            print(f"FAIL {finding}", file=sys.stderr)
        print(f"secret scan failed: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"secret scan passed: {len(files)} tracked files, {len(args.archive)} archive(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
