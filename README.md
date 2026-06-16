# scgnn-api

An HTTP service (FastAPI) wrapping the SC-GNN smart-contract flaw detector.
Repository **2 of 3** in the dissertation system (`scgnn-model` →
**`scgnn-api`** → `scgnn-web`). It accepts a Solidity contract and returns the
detected DASP flaws together with the source lines held responsible, by calling
the published model through the installed `scgnn` package. It never reimplements
the extraction, feature or model logic — the served predictions are identical to
the evaluated ones.

## Status

This is built incrementally. The current drop is the **service skeleton**:

- The full HTTP surface and the asynchronous job lifecycle: `GET /health`,
  `GET /flaws`, `POST /analyze` (JSON), `POST /analyze/file` (`.sol` upload) and
  `GET /analyze/{job_id}`.
- Start-up resolves the configured revision (a moving tag, or an explicit SHA)
  to an immutable commit SHA and reports it on `/health`.
- Input validation (extension, size, UTF-8, non-empty) and the structured
  job/error envelope.

Analysis is presently a **mock** that returns the genuine `scgnn.schema` shape;
`/health` advertises this with `mock_mode: true`. Still to come, in order: the
real `analyze_source` behind a **process worker pool** with a wall-clock timeout
(terminate-and-respawn), the **bounded queue** with `503` backpressure, the
**structured extraction-failure / timeout** error mapping, and the
**Dockerfile** that provisions the full extraction stack.

## The contract

`POST /analyze` (JSON body) or `POST /analyze/file` (multipart `.sol`) both
return `202`:

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

`lines` is a **ranked** list (most-influential first), not numerically sorted —
it is never re-sorted. `degraded` becomes `true` when a contract's CFG fell back
to the one-node placeholder (a Slither crash); it flows through automatically
once `scgnn` ships the flag.

The five flaw `type` values are fixed (DASP-aligned): `reentrancy`,
`access_control`, `arithmetic`, `unchecked_calls`, `dos`. `GET /flaws` returns
their human names and DASP numbers.

## Configuration

All via environment (see `.env.example`):

| Variable | Purpose | Default |
|----------|---------|---------|
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

## Running

**Quick start.** A helper script does the whole thing — venv, dependencies,
tests, server — in one command:

```bash
./run.sh            # setup + tests + start the dev server
./run.sh test       # setup + tests only
./run.sh serve      # setup + start the server
```

See the comment block at the top of `run.sh` for options (e.g. `FULL=1` for the
heavy serving stack, `SCGNN_SRC=$HOME/smart-contract-gnn-model` to install scgnn
from a local clone instead of GitHub). The manual steps below are the same thing
spelled out.

Always work inside a virtual environment, so the API's dependencies stay
isolated. This matters in particular on the model training box (`gpu-01`), which
carries a specific GPU torch build in the model repo's environment: installing
the API stack there could pull a conflicting torch and break the model side. A
fresh venv keeps the two separate.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

(`.venv/` is git-ignored.) Deactivate with `deactivate`; re-activate with the
same `source` line in a new shell.

**Serving (full stack).** Needs a GitHub credential for the private `scgnn`
repo and the heavy serving stack:

```bash
pip install -r requirements.txt
cp .env.example .env          # set HF_TOKEN
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Tests / light dev** — no torch, no Slither, no Hub access required (the suite
mocks the heavy calls and revision resolution):

```bash
pip install --no-deps "scgnn @ git+https://github.com/Signeemmanuel/smart-contract-gnn-model.git@master"
pip install -r requirements-dev.txt
pytest -q
```

`--no-deps` pulls only the `scgnn` code (its stdlib-only `schema.py`) without the
heavy dependencies, which is all the tests need. `@master` tracks the latest
commit on the default branch — fine for skeleton testing, since the suite only
touches the stable `scgnn.schema`. (For serving, `requirements.txt` stays pinned
to a specific commit — see Pinning and reproducibility.)

## Pinning and reproducibility

The point of pinning is to be able to state that the live service runs the exact
model that produced the reported results.

- **`scgnn` code commit:** `23ffacc1c145a1c79788ea2cd791d5b0dc0ced2b` (repo
  `github.com/Signeemmanuel/smart-contract-gnn-model`), pinned in
  `requirements.txt`.
- **Hugging Face bundle revision:** `SCGNN_REVISION`. The default tag
  `production` is resolved at start-up to a concrete commit SHA, which `/health`
  discloses. For the viva, set `SCGNN_REVISION=5f87610c80520e56935d789d95e4b370216d5423`
  to freeze the demo to the reported checkpoint; re-point to `production`
  afterwards.
- **Decision threshold:** `0.5`, a fixed **server policy** (`SCGNN_THRESHOLD`),
  not a client field, passed explicitly on every call (the bundle's
  `config.json` carries no threshold, so the `load_model` fallback would
  otherwise be 0.70). The value in force is reported on `/health`.
- **Updating the live model:** re-point the `production` tag (or push and tag) →
  restart the container → `/health` shows the new resolved SHA. CodeBERT is baked
  into the image and the bundle is cached, so a restart costs seconds.

**Serving-stack versions to match** (from the training lockfile; install a **CPU**
torch build on the API host, not the `+cu128` wheels): Python 3.10–3.12, torch
2.8.0, torch-geometric 2.8.0, transformers 5.12.0, scikit-learn 1.3.2,
slither-analyzer 0.11.5, solc-select 1.2.0, safetensors 0.8.0, numpy 1.26.4. The
Dockerfile (forthcoming) installs the full `solc-select` compiler superset the
corpus pins (`0.4.4`–`0.4.26`, the `0.5.x` set, `0.6.12`, `0.7.6`, `0.8.19`).

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