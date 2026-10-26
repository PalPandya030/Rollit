"""Rollit: an educational, policy-based canary-release control plane."""
import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from fastapi.responses import Response

app = FastAPI(title='Rollit', version='1.0.0')
REQUESTS = Counter('rollit_http_requests_total', 'Demo traffic', ['version','outcome'])
ERROR_RATE = Gauge('rollit_error_rate', 'Measured canary error rate')
LATENCY = Gauge('rollit_p95_latency_ms', 'Measured canary p95 latency')
ROLLBACKS = Counter('rollit_rollbacks_total', 'Automatic rollback decisions')

@dataclass
class State:
    stable: str = 'v1.0.0'
    canary: str | None = None
    traffic_pct: int = 0
    error_probability: float = 0.01
    extra_latency_ms: float = 0
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    events: deque = field(default_factory=lambda: deque(maxlen=50))
    last_decision: str = 'No canary running'

state = State()
lock = threading.RLock()
MIN_SAMPLES = int(os.getenv('MIN_SAMPLES', '20'))
MAX_ERROR_RATE = float(os.getenv('MAX_ERROR_RATE', '0.10'))
MAX_P95_MS = float(os.getenv('MAX_P95_MS', '400'))
API_TOKEN = os.getenv('ADMIN_TOKEN', 'local-demo-only')

class StartRelease(BaseModel):
    version: str = Field(min_length=1, max_length=40, pattern=r'^[a-zA-Z0-9._-]+$')
    traffic_pct: int = Field(default=20, ge=1, le=100)

class FaultSettings(BaseModel):
    error_probability: float = Field(ge=0, le=1)
    extra_latency_ms: float = Field(ge=0, le=2000)

class TrafficRequest(BaseModel):
    count: int = Field(default=100, ge=1, le=1000)

def add_event(message: str):
    state.events.appendleft({'at': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()), 'message': message})

def p95(values):
    if not values: return 0
    values = sorted(values)
    return round(values[max(0, int((len(values)-1)*0.95))], 1)

def snapshot():
    canary_samples = [x for x in state.samples if x['canary']]
    n = len(canary_samples)
    errors = sum(1 for x in canary_samples if not x['ok'])
    err = errors / n if n else 0
    latency = p95([x['ms'] for x in canary_samples])
    ERROR_RATE.set(err)
    LATENCY.set(latency)
    return {'stable_version':state.stable, 'canary_version':state.canary,
            'canary_traffic_percent':state.traffic_pct, 'samples':n,
            'canary_error_rate':round(err, 4), 'canary_p95_latency_ms':latency,
            'decision':state.last_decision, 'recent_events':list(state.events)}

def evaluate():
    stats = snapshot()
    if not state.canary:
        state.last_decision = 'No canary running'
    elif stats['samples'] < MIN_SAMPLES:
        state.last_decision = f"Collecting data ({stats['samples']}/{MIN_SAMPLES} canary requests)"
    elif stats['canary_error_rate'] > MAX_ERROR_RATE or stats['canary_p95_latency_ms'] > MAX_P95_MS:
        bad = state.canary
        state.canary = None
        state.traffic_pct = 0
        state.last_decision = f'ROLLED BACK {bad} to {state.stable}'
        ROLLBACKS.inc()
        add_event(state.last_decision)
    else:
        state.last_decision = 'Canary healthy: eligible to promote'
    return snapshot()

def admin(token: str):
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail='Invalid admin token')

@app.get('/health')
def health():
    return {'status':'ok'}

@app.get('/api/status')
def status():
    with lock: return snapshot()

@app.post('/api/releases/start')
def start(release: StartRelease, token: str = ''):
    admin(token)
    with lock:
        if state.canary:
            raise HTTPException(status_code=409, detail='A canary already exists')
        if release.version == state.stable:
            raise HTTPException(status_code=400, detail='Use a new version')
        state.canary = release.version
        state.traffic_pct = release.traffic_pct
        state.samples.clear()
        state.last_decision = 'Canary started'
        add_event(f'Started {release.version} at {release.traffic_pct}%')
        return snapshot()

@app.post('/api/faults')
def faults(settings: FaultSettings, token: str = ''):
    admin(token)
    with lock:
        state.error_probability = settings.error_probability
        state.extra_latency_ms = settings.extra_latency_ms
        add_event('Updated demo fault profile')
        return {'ok':True, **settings.model_dump()}

@app.post('/api/traffic')
def traffic(data: TrafficRequest, token: str = ''):
    admin(token)
    with lock:
        generated = 0
        for _ in range(data.count):
            canary = state.canary is not None and random.randrange(100) < state.traffic_pct
            version = state.canary if canary else state.stable
            ok = random.random() >= (state.error_probability if canary else 0.005)
            ms = random.uniform(30, 100) + (state.extra_latency_ms if canary else 0)
            REQUESTS.labels(version=version, outcome='success' if ok else 'error').inc()
            if canary:
                generated += 1
                state.samples.append({'canary':True, 'ok':ok, 'ms':ms})
        result = evaluate()
        return {'generated_canary_requests':generated, **result}

@app.post('/api/releases/evaluate')
def evaluation(token: str = ''):
    admin(token)
    with lock: return evaluate()

@app.post('/api/releases/promote')
def promote(token: str = ''):
    admin(token)
    with lock:
        stats = evaluate()
        if state.canary is None or state.last_decision != 'Canary healthy: eligible to promote':
            raise HTTPException(status_code=409, detail=f"Not safe to promote: {stats['decision']}")
        state.stable = state.canary
        state.canary = None
        state.traffic_pct = 0
        state.last_decision = f'Promoted {state.stable}'
        add_event(state.last_decision)
        return snapshot()

@app.get('/metrics')
def metrics():
    with lock: snapshot()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get('/', response_class=HTMLResponse)
def home():
    return '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rollit</title>
<style>body{font:16px system-ui;background:#0d1426;color:#e9f0fc;margin:0;padding:28px}main{max-width:1020px;margin:auto}h1{font-size:2.5rem;margin-bottom:0}.sub{color:#9baed0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:14px;margin:25px 0}.card,section{background:#192440;padding:22px;border-radius:14px}small{color:#a5b7d7}strong{display:block;font-size:1.5rem;margin-top:12px;overflow-wrap:anywhere}button,input{border:0;border-radius:8px;padding:11px;font-size:1rem}button{cursor:pointer;background:#6a8cff;color:#fff;margin:5px}input{background:#edf2ff;width:135px}section{margin-top:16px}pre{white-space:pre-wrap;color:#bde7d7}.warn{color:#ffc4aa}</style></head><body><main><h1>🚀 Rollit</h1><p class="sub">Smart canary-release simulator | health policies, auto-rollback, Prometheus metrics</p>
<div class="cards"><div class="card"><small>Stable release</small><strong id="stable">-</strong></div><div class="card"><small>Canary release</small><strong id="canary">-</strong></div><div class="card"><small>Error rate</small><strong id="errors">-</strong></div><div class="card"><small>P95 latency</small><strong id="latency">-</strong></div></div>
<section><h2>Deployment controls (local demo)</h2><p>Admin token <input id="token" value="local-demo-only" type="password"> New version <input id="version" value="v1.1.0"></p><button onclick="api('/api/releases/start',{version:document.getElementById('version').value,traffic_pct:20})">Start 20% canary</button><button onclick="api('/api/faults',{error_probability:0.4,extra_latency_ms:550})">Inject failure</button><button onclick="api('/api/faults',{error_probability:0,extra_latency_ms:0})">Clear failure</button><button onclick="api('/api/traffic',{count:250})">Send 250 test requests</button><button onclick="api('/api/releases/promote',{})">Promote healthy canary</button><p id="msg" class="warn"></p></section>
<section><h2>Policy decision</h2><h3 id="decision">-</h3><small id="samples"></small><h3>Activity log</h3><pre id="events"></pre></section>
<p class="sub">Demo environment only: uses in-memory simulated traffic; not actual Kubernetes traffic shifting. API docs: <a style="color:#9fc0ff" href="/docs">/docs</a> | <a style="color:#9fc0ff" href="/metrics">/metrics</a></p></main>
<script>async function refresh(){let r=await fetch('/api/status'),s=await r.json();document.getElementById('stable').textContent=s.stable_version;document.getElementById('canary').textContent=s.canary_version||'None';document.getElementById('errors').textContent=(100*s.canary_error_rate).toFixed(1)+'%';document.getElementById('latency').textContent=s.canary_p95_latency_ms+' ms';document.getElementById('decision').textContent=s.decision;document.getElementById('samples').textContent=s.samples+' canary samples';document.getElementById('events').textContent=s.recent_events.map(x=>x.at+' - '+x.message).join('\\n')||'No events yet'}async function api(url,data){let token=encodeURIComponent(document.getElementById('token').value),r=await fetch(url+'?token='+token,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let d=await r.json();document.getElementById('msg').textContent=r.ok?'Action completed: '+(d.decision||'OK'):JSON.stringify(d.detail);refresh()}refresh();setInterval(refresh,3000)</script></body></html>'''
