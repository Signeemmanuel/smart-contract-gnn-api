"""Revision resolution and (for this increment) a stub model load.

The design point that survives into the real loader: we never load a *moving*
ref directly. We resolve the configured ref (a tag such as ``production``, or an
explicit SHA for the viva) to a concrete commit SHA via a cheap Hub metadata
call, then load *that SHA*. This pins the load deterministically and lets
``/health`` always disclose the exact commit the service is serving, even while
tracking a tag.

In this stub increment we resolve the revision but do not yet pull the heavy
bundle; ``mock_mode`` is therefore ``True`` and analysis is mocked. The next
increment replaces ``load`` so it additionally calls
``scgnn.inference.load_model(repo_id, resolved_sha, device)`` and starts the
worker pool. Start-up never crashes the process: if resolution fails (no token,
no network, private repo unreachable) the service stays up and ``/health``
reports ``model_loaded=false`` with the reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .settings import Settings

_log = logging.getLogger("scgnn_api.model")


@dataclass
class ModelState:
    repo_id: str
    configured_revision: str
    device: str
    hf_token_present: bool
    loaded: bool = False
    resolved_sha: str | None = None
    mock_mode: bool = True
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


def load(settings: Settings) -> ModelState:
    """Stub start-up: resolve the revision and report it.

    Replaced next increment by resolve-then-load against ``scgnn.inference``.
    """
    token = settings.hf_token
    state = ModelState(
        repo_id=settings.repo_id,
        configured_revision=settings.revision,
        device=settings.device,
        hf_token_present=bool(token),
        mock_mode=True,
    )
    try:
        state.resolved_sha = resolve_revision(settings.repo_id, settings.revision, token)
        state.loaded = True  # simulated readiness; the real load_model arrives next
        _log.info(
            "Resolved %s@%s -> %s",
            settings.repo_id,
            settings.revision,
            state.resolved_sha,
        )
    except Exception as exc:  # noqa: BLE001 - start-up must stay up and report
        state.loaded = False
        state.error = f"{type(exc).__name__}: {exc}"
        _log.warning("Revision resolution failed; serving in degraded state: %s", state.error)
    return state
