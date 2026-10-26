"""Small real HTTP workload for the Kubernetes canary demo."""
import os
import random
import time
from fastapi import FastAPI, HTTPException

app = FastAPI(title='Rollit Kubernetes workload')
VERSION = os.getenv('APP_VERSION', 'v1.0.0')
ERROR_PROBABILITY = float(os.getenv('ERROR_PROBABILITY', '0'))
EXTRA_LATENCY_MS = float(os.getenv('EXTRA_LATENCY_MS', '0'))

@app.get('/health')
def health():
    return {'status': 'ok', 'version': VERSION}

@app.get('/work')
def work():
    time.sleep(max(0, EXTRA_LATENCY_MS) / 1000)
    if random.random() < ERROR_PROBABILITY:
        raise HTTPException(status_code=503, detail=f'{VERSION} simulated failure')
    return {'version': VERSION, 'status': 'processed'}
