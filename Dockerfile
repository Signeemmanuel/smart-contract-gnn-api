# smart-contract-gnn-api - real serving image for a Hugging Face Docker Space (free CPU).
# Builds the full extraction + inference stack, bakes CodeBERT, installs the
# solc compiler superset, and serves uvicorn on port 7860. The vendored scgnn/
# package is COPIED in - there is NO GitHub install and no build secret.

FROM python:3.12-slim

# --- build-time knobs -------------------------------------------------------
# CodeBERT model id. Confirm it matches scgnn/extraction/features.py; if it
# differs, override here (a wrong id only means a slow first request, not a
# failure, since it would then download at runtime).
ARG CODEBERT_MODEL=microsoft/codebert-base
# The exact solc versions the corpus pins (from scripts/needed_solc.py). The
# malformed "0.5.00" pragma is intentionally omitted (not a real release).
ARG SOLC_VERSIONS="0.4.4 0.4.6 0.4.8 0.4.9 0.4.10 0.4.11 0.4.12 0.4.13 0.4.14 0.4.15 0.4.16 0.4.17 0.4.18 0.4.19 0.4.20 0.4.21 0.4.22 0.4.23 0.4.24 0.4.25 0.4.26 0.5.0 0.5.1 0.5.2 0.5.3 0.5.4 0.5.5 0.5.6 0.5.7 0.5.8 0.5.9 0.5.10 0.5.17 0.6.12 0.7.6 0.8.19"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# --- system deps ------------------------------------------------------------
# Minimal. If a particular old solc binary fails to execute at runtime, add the
# library it needs here (e.g. libstdc++6).
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- Python deps (installed as root, into system site-packages) ------------
# CPU torch FIRST, from the CPU wheel index, so nothing pulls a CUDA build.
RUN pip install --upgrade pip \
 && pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu

# The model stack, pinned to the training-lock versions for identical predictions
# (the PCA in pca.joblib was fitted with scikit-learn 1.3.2 - keep it pinned).
RUN pip install \
      numpy==1.26.4 \
      torch-geometric==2.8.0 \
      transformers==5.12.0 \
      scikit-learn==1.3.2 \
      joblib==1.5.3 \
      safetensors==0.8.0 \
      huggingface_hub==1.19.0 \
      slither-analyzer==0.11.5 \
      solc-select==1.2.0

# The web layer.
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# --- non-root user (Hugging Face Spaces runs containers as uid 1000) -------
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface
WORKDIR /home/user/app

# --- install the solc compiler superset (as the runtime user) --------------
# They land in ~/.solc-select/artifacts, which the extraction code reads; the
# compiler is chosen per-contract and invoked by path (no global "solc-select use").
RUN solc-select install $SOLC_VERSIONS

# --- application code: vendored scgnn package + the app --------------------
COPY --chown=user:user scgnn/ ./scgnn/
COPY --chown=user:user app/ ./app/

# --- bake CodeBERT so the first request is neither slow nor offline ---------
RUN python -c "from transformers import AutoTokenizer, AutoModel; AutoTokenizer.from_pretrained('$CODEBERT_MODEL'); AutoModel.from_pretrained('$CODEBERT_MODEL')"

EXPOSE 7860
# ${PORT:-7860}: HF leaves PORT unset (uses 7860 via app_port); portable elsewhere.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]