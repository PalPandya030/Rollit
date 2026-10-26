#!/usr/bin/env sh
set -eu
BASE="${BASE:-http://localhost:8000}"
TOKEN="${ADMIN_TOKEN:-local-demo-only}"
echo 'Starting canary release...'
curl -fsS -X POST "$BASE/api/releases/start?token=$TOKEN" -H 'Content-Type: application/json' -d '{"version":"v1.1.0","traffic_pct":100}'
echo '\nInjecting a failure...'
curl -fsS -X POST "$BASE/api/faults?token=$TOKEN" -H 'Content-Type: application/json' -d '{"error_probability":0.7,"extra_latency_ms":600}'
echo '\nGenerating traffic and auto-rollback...'
curl -fsS -X POST "$BASE/api/traffic?token=$TOKEN" -H 'Content-Type: application/json' -d '{"count":100}'
echo
