#!/usr/bin/env bash
# Usage: deploy/healthcheck.sh [base-url]
# Default http://127.0.0.1 — pass the public URL to check a deploy:
#   deploy/healthcheck.sh https://demo.example.com
#   deploy/healthcheck.sh http://140.82.x.x
set -u

BASE="${1:-http://127.0.0.1}"
BASE="${BASE%/}"
URL="${BASE}/api/health"

body="$(curl -fsS --max-time 10 "${URL}" 2>/dev/null)" || {
    echo "FAIL: GET ${URL} did not return 2xx"
    exit 1
}

echo "${body}" | python3 -c '
import json, sys
h = json.load(sys.stdin)
print(json.dumps(h, sort_keys=True))
ok = h.get("status") == "ok" and h.get("hardware_mode") == "simulated"
sys.exit(0 if ok else 1)
' || {
    echo "FAIL: unexpected health body"
    exit 1
}
echo "PASS: ${URL}"
