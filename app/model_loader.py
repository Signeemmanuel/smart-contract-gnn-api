"""Revision resolution and the shared model-state record.

We never load a *moving* ref directly: the configured ref (a tag such as
``production``, or an explicit SHA for the viva) is resolved to a concrete commit
SHA via a cheap Hub metadata call, then *that SHA* is what the worker pool loads.
This pins the load deterministically and lets ``/health`` always disclose the
exact commit being served, even while tracking a tag.

The actual heavy load (``scgnn.inference.load_model`` + the extraction stack)
happens inside the worker processes; see ``analysis`` and ``worker``. Resolution
here stays light (one HTTPS metadata call) and never crashes start-up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger("scgnn_api.model")


@dataclass
class ModelState:
    repo_id: str
    configured_revision: str
    device: str
    hf_token_present: bool
    loaded: bool = False
    resolved_sha: str | None = None
    mock_mode: bool = False
    error: str | None = None


def resolve_revision(repo_id: str, revision: str, token: str | None) -> str:
    """Resolve a branch/tag/SHA ref to an immutable commit SHA via the HF Hub.

    Raises if the Hub cannot be reached or the ref does not exist; the caller
    turns that into a degraded (but live) service rather than a crash.
    """
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    info = api.model_info(repo_id=repo_id, revision=revision, files_metadata=False)
    if not info.sha:
        raise RuntimeError("the Hub returned no commit SHA for the requested revision")
    return info.sha