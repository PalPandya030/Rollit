#!/usr/bin/env python3
"""Measure REAL Kubernetes canary HTTP responses, then promote or stop it.

Requires a local kubectl context. Only modifies deployments in rollit-demo.
This is a teaching demo, not production rollout traffic shifting.
"""
import argparse
import json
import math
import subprocess
import sys
import time
import urllib.error
import urllib.request

NAMESPACE = 'rollit-demo'
CANARY = 'rollit-canary'
STABLE = 'rollit-stable'

def kubectl(*args, capture=True):
    command = ['kubectl', '--namespace', NAMESPACE, *args]
    return subprocess.run(command, check=True, capture_output=capture, text=True)

def percentile95(values):
    if not values:
        return float('inf')
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]

def sample(url, count, timeout):
    latencies = []
    errors = 0
    for _ in range(count):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if response.status >= 500:
                    errors += 1
                else:
                    response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            errors += 1
        latencies.append((time.monotonic() - started) * 1000)
    return errors / count, percentile95(latencies)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18081/work', help='Canary port-forward URL')
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--max-error-rate', type=float, default=0.10)
    parser.add_argument('--max-p95-ms', type=float, default=400)
    parser.add_argument('--timeout', type=float, default=3)
    parser.add_argument('--apply', action='store_true', help='Actually change Kubernetes deployments')
    args = parser.parse_args()
    if not 20 <= args.samples <= 1000:
        parser.error('--samples must be 20..1000')
    if not 0 <= args.max_error_rate <= 1 or args.max_p95_ms <= 0:
        parser.error('Invalid thresholds')
    try:
        canary_data = json.loads(kubectl('get', 'deployment', CANARY, '-o', 'json').stdout)
        stable_data = json.loads(kubectl('get', 'deployment', STABLE, '-o', 'json').stdout)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f'Could not query Kubernetes: {exc}', file=sys.stderr)
        return 2
    if canary_data['spec']['replicas'] < 1:
        print('Canary is scaled down. Re-enable it before sampling.', file=sys.stderr)
        return 2
    error_rate, p95 = sample(args.url, args.samples, args.timeout)
    failed = error_rate > args.max_error_rate or p95 > args.max_p95_ms
    print(f'Canary: samples={args.samples}, error_rate={error_rate:.1%}, p95={p95:.1f} ms')
    print(f'Decision: {"ROLL BACK CANARY" if failed else "PROMOTE CANARY"}')
    if not args.apply:
        print('Dry run only; add --apply to modify the demo Kubernetes namespace.')
        return 0
    try:
        if failed:
            # Stable is a separate deployment, so it keeps serving while canary is shut off.
            kubectl('scale', 'deployment/' + CANARY, '--replicas=0')
            print('Real Kubernetes action: scaled canary Deployment to zero replicas. Stable remains intact.')
        else:
            container = canary_data['spec']['template']['spec']['containers'][0]
            image = container['image']
            env = {x['name']: x.get('value', '') for x in container.get('env', []) if 'value' in x}
            if not image:
                raise ValueError('Canary image is missing')
            # Change stable Deployment to match the proven canary version.
            kubectl('set', 'image', 'deployment/' + STABLE, f'workload={image}')
            kubectl('set', 'env', 'deployment/' + STABLE,
                    'APP_VERSION=' + env.get('APP_VERSION', 'v1.1.0'),
                    'ERROR_PROBABILITY=' + env.get('ERROR_PROBABILITY', '0'),
                    'EXTRA_LATENCY_MS=' + env.get('EXTRA_LATENCY_MS', '0'))
            kubectl('rollout', 'status', 'deployment/' + STABLE, '--timeout=120s', capture=False)
            kubectl('scale', 'deployment/' + CANARY, '--replicas=0')
            print('Real Kubernetes action: promoted canary config to stable and stopped canary.')
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as exc:
        print(f'Kubernetes update failed: {exc}', file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
