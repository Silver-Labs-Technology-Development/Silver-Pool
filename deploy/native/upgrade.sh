#!/bin/sh
# Upgrade a clean checkout with fast-forward-only Git, then rebuild and restart.
# This script never resets, cleans, rebases or overwrites local data.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
APPLY=0
RUN_TESTS=1

usage() {
    cat <<EOF
Usage: $0 [--apply] [--no-tests]

Without --apply this prints the plan and exits. With --apply it:
  1. refuses a dirty working tree;
  2. backs up the database;
  3. runs git fetch and git merge --ff-only @{u};
  4. runs the installer and test suites;
  5. preflights and restarts the services.

Rollback is manual: git revert the merge commit and restore the printed backup.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --no-tests) RUN_TESTS=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [ "$APPLY" -ne 1 ]; then
    usage
    exit 0
fi
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "working tree is not clean; commit or stash changes before upgrading" >&2
    git -C "$ROOT" status --short >&2
    exit 2
fi
if ! git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    echo "current branch has no upstream; configure one before upgrading" >&2
    exit 2
fi

echo "backing up before upgrade"
"$ROOT/deploy/native/backup.sh"

echo "fetching"
git -C "$ROOT" fetch origin
git -C "$ROOT" merge --ff-only '@{u}'

echo "installing"
"$ROOT/deploy/native/install.sh" --no-preflight

if [ "$RUN_TESTS" -eq 1 ]; then
    if "$ROOT/.venv/bin/python" -c 'import pytest' >/dev/null 2>&1; then
        TEST_PYTHON="$ROOT/.venv/bin/python"
    elif python3 -c 'import pytest' >/dev/null 2>&1; then
        TEST_PYTHON=python3
    else
        echo "pytest is not available; install requirements-dev.txt or rerun with --no-tests" >&2
        exit 2
    fi
    echo "running Python tests"
    (cd "$ROOT" && "$TEST_PYTHON" -m pytest -q)
    echo "running site tests"
    (cd "$ROOT/site" && npm test)
fi

"$ROOT/deploy/native/preflight.sh"
"$ROOT/deploy/native/start.sh"
echo "upgrade complete"
