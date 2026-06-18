---
title: smart-contract-gnn-api
emoji: 🔍
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Smart-contract flaw detector (SC-GNN) HTTP API.
---

# smart-contract-gnn-api

An HTTP service (FastAPI) wrapping the SC-GNN smart-contract flaw detector.
Repository **2 of 3** in the dissertation system (`scgnn-model` →
**`smart-contract-gnn-api`** → `scgnn-web`). It accepts a Solidity contract and returns the
detected DASP flaws together with the source lines held responsible, by calling
the **vendored** `scgnn` inference package. It never reimplements the extraction,
feature or model logic — the served predictions are identical to the evaluated
ones.

## How it works

- **Full HTTP surface + asynchronous job lifecycle:** `GET /health`,
  `GET /flaws`, `POST /analyze` (JSON), `POST /analyze/file` (`.sol` upload),
  `GET /analyze/{job_id}`.
- **Real engine:** a **process worker pool** loads the model once and runs
  `scgnn.inference.analyze_source` off the event loop under a **wall-clock
  timeout** (terminate-and-respawn on a wedged run). Submissions beyond
  `SCGNN_QUEUE_MAX` are shed with `503`. Failures map to structured job
  outcomes (`extraction_failed`, `timeout`).
- **Mock toggle:** `SCGNN_MOCK=1` serves a lightweight mock with the **same wire
  contract** and no torch/Slither — for local dev, tests, and giving the
  frontend a live contract URL on a tiny host.
- **Vendored code:** the `scgnn` package lives in this repo (`scgnn/`), frozen at
  the trained-model commit. No GitHub dependency. The only runtime artefact
  pulled from outside is the model **bundle** on the Hub (via `HF_TOKEN`).

## The contract

`POST /analyze` (JSON `{ "source": "..." }`) or `POST /analyze/file` (multipart
`.sol`) both return `202`:

```json
{ "job_id": "…", "status": "queued" }
```

`GET /analyze/{job_id}` returns:

```json
{ "job_id": "…", "status": "queued|running|done|failed",
  "result": { "source": "…", "flaws": [ … ], "degraded": false },
  "error": { "code": "…", "message": "…" } }
```

`result` is the canonical `scgnn.schema` payload, passed through unchanged:

```json
{ "source": "<contract text>",
  "flaws": [ { "type": "reentrancy", "confidence": 0.91, "lines": [42, 47, 53] } ],
  "degraded": false }
```

`lines` is a **ranked** list (most-influential first), never re-sorted.
`degraded` becomes `true` when a contract's CFG fell back to the one-node
placeholder (a Slither crash); it flows through automatically once `scgnn` ships
the flag. The threshold is a fixed **server policy**, not a client field.

The five flaw `type` values are fixed (DASP-aligned): `reentrancy`,
`access_control`, `arithmetic`, `unchecked_calls`, `dos`. `GET /flaws` returns
their human names and DASP numbers.

## Configuration

All via environment (see `.env.example`):

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCGNN_MOCK` | `1` = serve the mock (no model); unset/`0` = real engine | `0` |
| `HF_TOKEN` | HF **read** token for the private bundle | — |
| `SCGNN_REPO_ID` | Hugging Face model repo | `Signeemmanuel/scgnn-smartcontract` |
| `SCGNN_REVISION` | bundle ref to serve (tag or SHA) | `production` |
| `SCGNN_DEVICE` | `cpu` or `cuda` | `cpu` |
| `SCGNN_THRESHOLD` | decision threshold (the reported policy) | `0.5` |
| `SCGNN_MAX_UPLOAD_BYTES` | upload cap | `262144` |
| `SCGNN_ANALYZE_TIMEOUT_S` | wall-clock bound per analysis | `120` |
| `SCGNN_MAX_WORKERS` | concurrent analyses (RAM-bound) | `1` |
| `SCGNN_QUEUE_MAX` | bounded queue depth | `32` |
| `SCGNN_CORS_ORIGINS` | comma-separated origins (empty disables) | — |

---

## Running — three ways

### 1) Local, **mock** mode (light: dev, tests, frontend contract)

No torch, no Slither, no Hub. The `scgnn` package is vendored, so nothing is
fetched from GitHub. Use the helper script:

```bash
./run.sh test       # venv + light deps + run the test suite
./run.sh serve      # venv + light deps + start the server (mock)
./run.sh            # test then serve
```

`run.sh` defaults to mock for the light install. Manual equivalent:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                                            # run tests
SCGNN_MOCK=1 uvicorn app.main:app --host 0.0.0.0 --port 8000   # run the mock
```

`/health` will show `mock_mode: true`. Use the test-data pack to exercise the
endpoints.

### 2) Local, **real** model (Docker)

The real stack (CPU torch, torch-geometric, transformers/CodeBERT,
scikit-learn, slither-analyzer, the solc compiler superset) is heavy and is built
by the `Dockerfile` — CodeBERT is baked in and the model bundle is downloaded at
start-up. Build and run:

```bash
docker build -t smart-contract-gnn-api .

docker run --rm -p 7860:7860 \
  -e HF_TOKEN=hf_your_read_token \
  -e SCGNN_REPO_ID=Signeemmanuel/scgnn-smartcontract \
  -e SCGNN_REVISION=production \
  -e SCGNN_THRESHOLD=0.5 \
  -e SCGNN_MAX_WORKERS=1 \
  smart-contract-gnn-api

# then:  curl http://localhost:7860/health   -> model_loaded: true, mock_mode: false
```

The **first build is slow** (torch + ~36 solc compilers + the CodeBERT bake):
10–20+ minutes is normal. Needs ~2 GB RAM at runtime. `.env` is excluded from the
image by `.dockerignore` — pass secrets with `-e` or `--env-file`.

### 3) Deploy **free** on a Hugging Face Space (Docker)

The repo is Space-ready: the `README.md` header above declares `sdk: docker` and
`app_port: 7860`, and the `Dockerfile` runs as the Space's non-root user on 7860.
Summary (full runbook in `docs/HUGGINGFACE_DEPLOYMENT.md`):

1. Create a **Docker** Space on **CPU basic (free, 16 GB)**.
2. Push this repo to the Space (it must include the vendored `scgnn/`).
3. Space → Settings → set the **secret** `HF_TOKEN`, and the **variables**
   `SCGNN_REPO_ID`, `SCGNN_REVISION`, `SCGNN_DEVICE=cpu`, `SCGNN_THRESHOLD=0.5`,
   `SCGNN_MAX_WORKERS`, `SCGNN_QUEUE_MAX`, `SCGNN_CORS_ORIGINS`. Do **not** set
   `SCGNN_MOCK`.
4. Watch the build, then check `https://<user>-smart-contract-gnn-api.hf.space/health`.

---

## Pinning and reproducibility

The live service runs the exact model that produced the reported results:

- **Inference code:** **vendored** in `scgnn/`, a frozen snapshot of the
  trained-model commit. Immune to any change in the training repo; re-vendor only
  to ship a new code version.
- **Model bundle:** `SCGNN_REVISION`. The default tag `production` is resolved at
  start-up to a concrete commit SHA, which `/health` discloses. For the viva, set
  `SCGNN_REVISION=5f87610c80520e56935d789d95e4b370216d5423` to freeze to the
  reported checkpoint; re-point to `production` afterwards.
- **Decision threshold:** `0.5`, a fixed server policy (`SCGNN_THRESHOLD`), passed
  explicitly (the bundle's `config.json` carries no threshold, so `load_model`
  would otherwise fall back to 0.70). Reported on `/health`.
- **Updating the live model:** re-point the `production` tag on the Hub, then
  restart the Space/container → `/health` shows the new resolved SHA. No rebuild.

The `Dockerfile` pins the serving stack to the training-lock versions (Python
3.12, torch 2.8.0 **CPU**, torch-geometric 2.8.0, transformers 5.12.0,
scikit-learn 1.3.2, slither-analyzer 0.11.5, solc-select 1.2.0, safetensors
0.8.0, numpy 1.26.4) and installs the solc superset the corpus pins
(`0.4.4`–`0.4.26`, the `0.5.x` set, `0.6.12`, `0.7.6`, `0.8.19`).

## Honest limitations (surface these in the UI)

- Detection is reasonable on well-supported classes and weaker on others; **dos**
  in particular is unreliable. `confidence` is a probability, not certainty.
- Localisation (`lines`) is **approximate** and can be empty — treat the lines as
  hints to guide a human reviewer, not authoritative bug locations.
- A `degraded: true` result came from a degraded (one-node) CFG and is less
  reliable.
- The tool is a **decision-support aid, not a guarantee**: the absence of a
  detected flaw is not proof a contract is safe.

## Licence

Apache-2.0. See `LICENSE`.