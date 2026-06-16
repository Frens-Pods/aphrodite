#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v python >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    python() { python3 "$@"; }
  fi
fi

PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_production_endpoint_preflight.py -q >/tmp/aphrodite-production-endpoint-preflight-tests.txt
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_signed_interaction_negative_fixtures.py -q >/tmp/aphrodite-signed-interaction-negative-fixture-tests.txt
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests -q
PYTHONDONTWRITEBYTECODE=1 python scripts/mcp_smoke.py >/tmp/aphrodite-mcp-smoke.json
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite doctor >/tmp/aphrodite-doctor.json
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite preflight >/tmp/aphrodite-preflight.json
# endpoint-preflight is an operator live-readiness report (exits non-zero until APHRODITE_DISCORD_PUBLIC_KEY
# is configured); its verdict must not fail the build. Its logic is gated by test_production_endpoint_preflight.py above.
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite endpoint-preflight >/tmp/aphrodite-endpoint-preflight.json || true
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite dispatch-test 'image_gen:v1:status' >/tmp/aphrodite-image-gen-dispatch.json
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite dispatch-test 'skillopt:v1:status' >/tmp/aphrodite-skillopt-dispatch.json
python - <<'PY'
import json
for path in (
    '/tmp/aphrodite-doctor.json',
    '/tmp/aphrodite-preflight.json',
):
    data = json.load(open(path))
    assert data.get('ok') is True, (path, data)
print('aphrodite verify ok')
PY
