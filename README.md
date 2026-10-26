# Rollit — Smart Release Safety Lab

A **working local DevOps portfolio project** that can launch a canary release, route simulated traffic to it, collect health evidence, and automatically roll back if it violates SLO policies. A browser UI makes the demonstration easy during interviews.

> **Scope:** This is an educational **simulation** of canary routing and rollback, not a controller changing real Kubernetes deployments. Metrics are generated from the simulator. All state is in memory and resets when the process restarts. The Kubernetes deployment runs the simulator itself; its two pods do **not** share state. Use one replica for consistent demo state or introduce Redis/Postgres for multi-replica production use.

## Run locally

Needs Python 3.12+ or Docker.

### Docker (full stack)
```bash
docker compose up --build -d
```
Open:
- App UI: http://localhost:8000
- Swagger API: http://localhost:8000/docs
- Prometheus: http://localhost:9090 (query `rollit_error_rate`)
- Grafana: http://localhost:3000 (login `admin` / `change-me-local`; Prometheus datasource preconfigured)

Set `ADMIN_TOKEN` and `GRAFANA_PASSWORD` to your own values in a **local `.env`** (gitignored). Never expose this demo stack on public networks with demo credentials.

### Python-only
```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Show an auto-rollback

1. Open http://localhost:8000; click **Start 20% canary**.
2. Click **Inject failure**.
3. Click **Send 250 test requests**. Once at least 20 canary samples arrive, errors/latency exceed policy and the canary is removed automatically.
4. Click **Clear failure**. Start a *new* canary version, send enough requests, then **Promote healthy canary**.

To get a deterministic rollback from your terminal (Linux/macOS/Git Bash), use `sh scripts/demo.sh` on a fresh app instance. Repeated requests can be inspected using `GET /api/status`.

Default rule: at least 20 canary requests, canary error rate > 10% **OR** p95 latency > 400 ms => automatic simulated rollback. Otherwise, the release is eligible to promote. Thresholds can be tuned with `MIN_SAMPLES`, `MAX_ERROR_RATE`, `MAX_P95_MS` environment variables. This deliberately simplified statistical policy is not suitable for production decisions without confidence bounds and baseline comparison.

## Tests
```bash
pip install -r requirements-dev.txt
pytest -q
```

## DevOps skill mapping
| Requirement | Where it appears |
|---|---|
| Linux + shell | `scripts/demo.sh`, Docker commands, process/port inspection |
| AWS | Terraform creates a versioned, encrypted, private S3 audit bucket (optional; may incur charges) |
| Docker | Dockerfile + three-service Compose stack |
| Kubernetes | `k8s/deployment.yml` contains deployment, probes, limits and service |
| Git | Commit and push to GitHub to trigger CI |
| CI/CD | GitHub Actions tests/builds; Jenkinsfile is an alternative CI pipeline |
| Python | FastAPI simulator and automated tests |
| Terraform | `terraform/main.tf` with infrastructure-as-code |
| Prometheus + Grafana | `/metrics`, scraping configuration, provisioned datasource |
| AI-assisted and cloud-native | Rule-based release advisor is implemented; AI/LLM analysis is a future extension, **not** currently implemented |

## Kubernetes demo (Minikube)
```bash
minikube start
minikube image build -t rollit:local .
kubectl create secret generic rollit-admin --from-literal=token=replace-with-a-strong-secret
kubectl apply -f k8s/deployment.yml
# For consistent simulation state, run a single pod:
kubectl scale deployment rollit --replicas=1
kubectl port-forward service/rollit 8000:80
```
Use your secret in the UI, replacing `local-demo-only`. For production, switch to image registry builds, managed secrets, persistent state, restricted ingress and TLS.

## AWS Terraform (optional)
```bash
cd terraform
terraform init
terraform plan
terraform apply
# Later: terraform destroy
```
AWS credentials must be configured independently. The S3 bucket is **not connected to the app's event log** yet; it illustrates an IaC cloud module you can extend. AWS resources may incur costs.

## CI
GitHub Actions runs pytest and a Docker build on push/PR. Jenkinsfile offers equivalent test+build jobs. Neither deploys to AWS/Kubernetes automatically, so it should be described as a **CI pipeline**, not a complete CD delivery pipeline.

## Suggested interview demo
**Problem:** bad releases can degrade user experience. **Approach:** canary + observable SLO policies. **Demo:** run app -> start release -> inject latency/errors -> simulate traffic -> automatic rollback -> inspect Prometheus metrics. **Tradeoffs:** simulator vs real traffic; thresholds vs statistical confidence; single instance in-memory vs durable shared state; production security and credentials.

## Future upgrades
Connect to actual Kubernetes via a restricted service account, use Argo Rollouts, add Redis for shared state, compare baseline vs canary, adopt OpenTelemetry, send audit events to AWS S3, and attach optional LLM explanations. Do not let an LLM alone approve production rollbacks.

---

## Real Kubernetes canary deployment (new)

The original dashboard (`app/main.py`) remains an **in-memory simulator**. The separate
Kubernetes demo here operates on **real Kubernetes Deployments and actual HTTP requests**.
It deliberately does not claim service-mesh traffic splitting, actual end-user canary
percentages, an automatic in-cluster operator, or production-safe rollout management.

### Prerequisites

- Docker Desktop with Kubernetes enabled, or a `kind` Kubernetes cluster
- `docker`, `kubectl`, Python 3.10+
- Your current `kubectl` context must point to your own test cluster; always verify
  it with `kubectl config current-context` before proceeding

### 1. Build and load the local image

```bash
docker build -t rollit:local .
# ONLY for kind, change cluster name if yours differs:
kind load docker-image rollit:local --name kind
```

Docker Desktop's integrated Kubernetes generally uses the local Docker image
without a separate image-loading command. If you use a different Kubernetes
runtime or remote cluster, push the image to a registry and replace the image
in `k8s/canary-demo.yaml` with its fully-qualified image name.

### 2. Deploy stable and canary applications

```bash
kubectl config current-context
kubectl apply -f k8s/canary-demo.yaml
kubectl -n rollit-demo rollout status deploy/rollit-stable --timeout=120s
kubectl -n rollit-demo rollout status deploy/rollit-canary --timeout=120s
kubectl -n rollit-demo get deploy,pods,svc
```

The stable workload is version `v1.0.0` with no injected faults. The canary is
`v1.1.0` with 40% artificial errors and 550 ms artificial delay.

### 3. Reach the canary's REAL Kubernetes Service

Keep this command running in a second terminal:

```bash
kubectl -n rollit-demo port-forward svc/rollit-canary 18081:80
```

Verify `http://127.0.0.1:18081/health` in your browser or with `curl`.

### 4. Evaluate measurements and perform rollback

```bash
# Safest first: show measured error rate, P95 latency and intended decision
python scripts/k8s_release_guard.py

# APPLY to change Kubernetes: failures scale the canary Deployment to 0
python scripts/k8s_release_guard.py --apply
kubectl -n rollit-demo get deployments
```

The guard sends 30 **real HTTP requests** to the canary Service, calculates
error rate and P95 response latency, then compares those measurements to the
same limits as the simulator: 10% errors and 400 ms P95. For an unhealthy release,
`--apply` invokes `kubectl scale deployment/rollit-canary --replicas=0`. The
stable workload remains running and can still serve users. This is a real
Kubernetes *canary shutdown*, not `kubectl rollout undo` of stable, and the demo
uses distinct Services rather than dynamically shifting production traffic.

### 5. Try a healthy promotion

```bash
kubectl -n rollit-demo scale deploy/rollit-canary --replicas=1
kubectl -n rollit-demo set env deploy/rollit-canary ERROR_PROBABILITY=0 EXTRA_LATENCY_MS=0
kubectl -n rollit-demo rollout status deploy/rollit-canary --timeout=120s
# Re-run port-forward if it disconnected, then:
python scripts/k8s_release_guard.py --apply
kubectl -n rollit-demo get deploy
kubectl -n rollit-demo get deploy/rollit-stable -o jsonpath='{.spec.template.spec.containers[0].env}'
```

For a healthy release, the guard updates the **stable Deployment** image and
application environment to match the canary, waits for a successful rollout,
and scales the canary to zero. The script does not replace replica sets using
a service mesh; it demonstrates a promotion via real Deployment operations.

### Reset or cleanup

```bash
kubectl delete namespace rollit-demo
kubectl apply -f k8s/canary-demo.yaml  # optional reset
```

### Current limitations / production work

- This is a manually triggered host-side release guard requiring `kubectl`
  permission. It is **not** a continuously running Kubernetes operator.
- Traffic is directly sampled against canary, not split from real ingress.
- Successful promotion updates the stable Deployment but is not atomic.
- For production, use Argo Rollouts or Flagger with Kubernetes RBAC, ingress or
  service mesh, Prometheus AnalysisTemplates, approval controls, audit logs,
  and a durable release-state database.
- Never point the demonstration at a production cluster.
