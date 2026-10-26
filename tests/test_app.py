from fastapi.testclient import TestClient
from app.main import app, state, lock

client = TestClient(app)
TOKEN = '?token=local-demo-only'

def reset():
    with lock:
        state.stable='v1.0.0'; state.canary=None; state.traffic_pct=0
        state.samples.clear();state.events.clear();state.last_decision='No canary running'
        state.error_probability=0.01;state.extra_latency_ms=0

def test_health_and_metrics():
    reset()
    assert client.get('/health').json()['status']=='ok'
    assert 'rollit_error_rate' in client.get('/metrics').text

def test_auth():
    reset()
    assert client.post('/api/releases/start',json={'version':'v2'}).status_code==403

def test_rollback_bad_release():
    reset()
    assert client.post('/api/releases/start'+TOKEN,json={'version':'v2','traffic_pct':100}).status_code==200
    client.post('/api/faults'+TOKEN,json={'error_probability':1,'extra_latency_ms':600})
    result=client.post('/api/traffic'+TOKEN,json={'count':50}).json()
    assert result['canary_version'] is None
    assert result['stable_version']=='v1.0.0'
    assert 'ROLLED BACK' in result['decision']

def test_promote_good_release():
    reset()
    client.post('/api/releases/start'+TOKEN,json={'version':'v2','traffic_pct':100})
    client.post('/api/faults'+TOKEN,json={'error_probability':0,'extra_latency_ms':0})
    result=client.post('/api/traffic'+TOKEN,json={'count':50}).json()
    assert 'healthy' in result['decision']
    result=client.post('/api/releases/promote'+TOKEN).json()
    assert result['stable_version']=='v2'
    assert result['canary_version'] is None
