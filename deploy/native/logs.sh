#!/bin/sh
# Follow or show the native service logs.
set -eu
case "${1:-follow}" in
    follow|-f|--follow)
        exec journalctl --user -u silver-pool.service -u silver-pool-web.service -f
        ;;
    tail|--tail)
        exec journalctl --user -u silver-pool.service -u silver-pool-web.service -n "${2:-200}" --no-pager
        ;;
    *)
        echo "usage: $0 [follow|tail [lines]]" >&2
        exit 2
        ;;
esac
