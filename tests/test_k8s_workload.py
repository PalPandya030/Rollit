from fastapi.testclient import TestClient
from app.workload import app
from scripts.k8s_release_guard import percentile95, sample


def test_workload_endpoints():
    client = TestClient(app)
    assert client.get('/health').status_code == 200
    assert client.get('/work').status_code == 200


def test_percentile():
    assert percentile95([10] * 19 + [200]) == 10
    assert percentile95([]) == float('inf')


def test_sampling_real_http(monkeypatch):
    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return b'ok'
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: FakeResponse())
    error_rate, p95 = sample('http://example.test/work', 20, 1)
    assert error_rate == 0
    assert p95 >= 0
