#!/bin/sh
# Stop the native Silver Pool website and backend.
set -eu
systemctl --user stop silver-pool-web.service 2>/dev/null || true
systemctl --user stop silver-pool.service 2>/dev/null || true
echo "stopped silver-pool-web.service and silver-pool.service"
