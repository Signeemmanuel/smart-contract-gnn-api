# Deploying smart-contract-gnn-api on a free Hugging Face Space

This is the runbook for hosting the **real** backend (the full torch / Slither /
solc / CodeBERT stack) on a **free** Hugging Face Space. It lists exactly what to
do on Hugging Face.

The inference code (`scgnn` package) is **vendored into this repository** (a
top-level `scgnn/` directory), so the deployment has **no GitHub dependency and
needs no `GH_TOKEN`**. The only external artefact pulled at runtime is the model
bundle on the Hub, downloaded with `HF_TOKEN`.

---

## 0. What the free Space gives you, and its limits

- **Hardware:** CPU Basic — **2 vCPU, 16 GB RAM, 50 GB disk** — free, no card.
- **Enough RAM:** the service needs ~1.5–2 GB resident per worker; 16 GB is ample.
- **Public URL:** `https://Signeemmanuel-smart-contract-gnn-api.hf.space`.
- **Sleeps after ~48 h idle.** First request after a sleep reloads the model
  (slow once); then normal.
- **Disk is not persistent.** Fine: CodeBERT is baked into the image at build
  time, and the small model bundle is re-downloaded from the Hub on each cold
  start.
- **CPU only.** A contract with several flaws can take tens of seconds; the
  job/polling API is built for this.

---

## 1. One-time: account and ONE token

You only need a single token now (no GitHub token any more).

1. **Hugging Face account** — the account (or org) that owns the private model
   repo `Signeemmanuel/scgnn-smartcontract`.

2. **HF access token (READ).** Settings → **Access Tokens** → *Create new token*
   → **Fine-grained**, granting **read** access to the
   `Signeemmanuel/scgnn-smartcontract` repo. This becomes the Space secret
   **`HF_TOKEN`**, used at runtime to download the private model bundle.

(If you exposed any old tokens, revoke them first and create fresh ones.)

---

## 2. Vendor the `scgnn` package into this repo (one-time)

The trained-model bundle on the Hub does **not** include the inference code, so
copy the `scgnn` package in:

1. From your model repo, copy the **`scgnn/` package directory** (the importable
   package: `inference.py`, `schema.py`, `extraction/`, `models/`, `explain/`,
   `__init__.py`, …) at the trained-model commit.
2. Place it at the **root of `smart-contract-gnn-api`**, so the layout is:

   ```
   smart-contract-gnn-api/
   ├── app/
   ├── scgnn/            <-- vendored package (import scgnn.inference works)
   ├── Dockerfile
   ├── requirements.txt
   └── ...
   ```
3. Commit it. It is now frozen with the service; future changes in the GitHub
   training repo do not affect the deployment. Re-vendor only when you
   deliberately ship a new model code version.

Do **not** copy the model repo's `training/`, `tests/`, `scripts/`, `configs/` or
`data/` directories — only the `scgnn/` package.

---

## 3. Create the Space

1. huggingface.co → **+** → **New Space**.
2. **Owner:** your account (or org).
3. **Space name:** `smart-contract-gnn-api`.
4. **License:** Apache-2.0.
5. **Space SDK:** **Docker**, then the **Blank** template.
6. **Space hardware:** **CPU basic — FREE**.
7. **Visibility:** **Public** is recommended for a frontend-facing API; lock
   access with `SCGNN_CORS_ORIGINS` (step 5). Choose Private only if every caller
   will present your HF token, which a browser app cannot do safely.

---

## 4. Files the Space repository must contain

A Space **is a git repository**. It must contain the whole `smart-contract-gnn-api` codebase
(including the vendored `scgnn/`) plus two HF-specific things:

### 4a. A `README.md` whose first lines are this YAML header

```yaml
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
```

`sdk: docker` tells HF to build your `Dockerfile`; `app_port: 7860` is the port
HF routes public traffic to (the app starts uvicorn on 7860).

### 4b. A `Dockerfile` (provided as the next code deliverable)

It installs the model stack pinned to the training-lock versions (CPU torch,
torch-geometric, transformers with **CodeBERT baked in**, scikit-learn,
slither-analyzer) and the `solc-select` compiler superset, **copies the vendored
`scgnn/`** (no `pip install` from GitHub, no build secret), runs as the Space's
non-root user with a writable HF cache, and starts uvicorn on port 7860.

### 4c. The application code

`app/`, `scgnn/`, `requirements.txt`, etc.

---

## 5. Set the secret and variables

Space → **Settings → Variables and secrets**.

**Secret** (encrypted):

| Secret | Why |
|--------|-----|
| `HF_TOKEN` | Runtime: download the private model bundle from the Hub. |

**Variables** (plain configuration):

| Variable | Value | Notes |
|----------|-------|-------|
| `SCGNN_REPO_ID` | `Signeemmanuel/scgnn-smartcontract` | The model repo. |
| `SCGNN_REVISION` | `production` | Or the viva SHA `5f87610c80520e56935d789d95e4b370216d5423` to freeze. |
| `SCGNN_DEVICE` | `cpu` | The free Space is CPU-only. |
| `SCGNN_THRESHOLD` | `0.5` | The reported decision policy. |
| `SCGNN_MAX_WORKERS` | `1` | `2` is also fine on the 2-core / 16 GB Space. |
| `SCGNN_QUEUE_MAX` | `32` | Load-shed beyond this with HTTP 503. |
| `SCGNN_CORS_ORIGINS` | your frontend URL | e.g. the deployed `scgnn-web` origin. |

**Do not set `SCGNN_MOCK`** (or set it to `0`). `1` would serve the mock instead
of the real model.

---

## 6. Push the code and let it build

- **Git:** `git remote add space https://huggingface.co/spaces/Signeemmanuel/smart-contract-gnn-api`
  then `git push space main` (HF username + an HF token as the password).
- **Web UI:** Space → **Files** → upload.

HF builds the Docker image automatically. **Watch the build logs** (*Logs* →
*Build*). First build is slow — torch, the solc superset and the CodeBERT bake
mean **10–20+ minutes** is normal. Then the container starts, resolves the
revision and loads the model (a cold start of up to a minute or two on CPU).

---

## 7. Verify

- `https://Signeemmanuel-smart-contract-gnn-api.hf.space/health` → expect `status: ok`,
  `mock_mode: false`, `model_loaded: true`, `resolved_sha` set. If
  `model_loaded` is `false`, read `error` and the runtime logs.
- `…/docs` → Swagger UI. `…/flaws` → the five DASP classes.
- `POST …/analyze` with `{ "source": "<contract>" }` → `202 { job_id }`, then
  poll `GET …/analyze/{job_id}` until `done`.

---


## 8. Operations and gotchas

- **Cold start after sleep:** free Space sleeps after ~48 h idle; next request
  wakes + reloads (slow once). A gentle external uptime pinger on `/health` keeps
  it warm if needed (within HF's terms).
- **Updating the model bundle:** re-point the `production` tag on the Hub, then
  **restart the Space** (Settings → *Restart* / *Factory reboot*). `/health`
  shows the new `resolved_sha`. No rebuild needed.
- **Updating the inference code:** re-vendor `scgnn/`, push → the Space rebuilds.
- **Logs:** Space → *Logs* tab.
- **Private model access:** the Space needs `HF_TOKEN` even within the same
  account.
- **Latency:** CPU GNNExplainer is slow per contract; the polling API handles it.
  Raise `SCGNN_ANALYZE_TIMEOUT_S` if long contracts hit the wall-clock limit.
- **Cost:** zero. To go always-on / faster later, upgrade hardware (paid) — a
  one-variable change, no code rewrite.
