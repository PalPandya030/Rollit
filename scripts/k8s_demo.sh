#!/bin/sh
set -eu
# Prerequisites: kubectl, Docker Desktop Kubernetes (or kind with image loaded).
# Run from repository root after building image and applying k8s/canary-demo.yaml.
kubectl -n rollit-demo rollout status deployment/rollit-stable --timeout=120s
kubectl -n rollit-demo rollout status deployment/rollit-canary --timeout=120s
printf '\nPort-forward the canary in a separate terminal:\n'
printf 'kubectl -n rollit-demo port-forward svc/rollit-canary 18081:80\n\n'
printf 'Then run:\n'
printf 'python scripts/k8s_release_guard.py --apply\n'
