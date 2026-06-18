"""Service configuration, read from the environment.

Every operational value the service needs is a setting here, never a constant
buried in code: the Hugging Face repository and revision, the device, the
decision threshold, the upload and timeout limits, the worker cap and the CORS
origins. Secrets (the HF token) are read but never logged or echoed.

The ``SCGNN_REVISION`` default is a *moving tag* (``production``) that you
re-point deliberately when a checkpoint is ready; the loader resolves whatever
ref this names to an immutable commit SHA at start-up (see ``model_loader``), so
an experimental push never goes live merely because the container restarted. For
the viva, set ``SCGNN_REVISION`` to the exact bundle SHA to freeze the demo.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCGNN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- mode -------------------------------------------------------------
    # When true, serve a lightweight MOCK instead of loading the real model and
    # extraction stack. Lets the same image run as the contract-only stub on a
    # tiny host (e.g. Render free) and as the real service on a 2GB+ host (e.g. a
    # Hugging Face Space) with one env var.
    mock: bool = False

    # --- model source -----------------------------------------------------
    repo_id: str = "Signeemmanuel/scgnn-smartcontract"
    revision: str = "production"  # moving tag; resolved to a commit SHA at start-up
    device: str = "cpu"

    # --- decision policy --------------------------------------------------
    # Passed explicitly to analyze_source so the served policy is the reported
    # one (0.5), regardless of the 0.70 fallback baked into load_model.
    threshold: float = 0.5

    # --- limits / robustness ---------------------------------------------
    max_upload_bytes: int = 256 * 1024  # 256 KiB
    analyze_timeout_s: int = 120  # wall-clock bound over the whole analysis
    max_workers: int = 1  # raise only with RAM headroom (~1.5-2 GB resident/worker)
    queue_max: int = 32  # bounded queue; reject with 503 when full

    # --- web --------------------------------------------------------------
    cors_origins: str = ""  # comma-separated; empty disables CORS

    # --- secret -----------------------------------------------------------
    # Read automatically by huggingface_hub too; declared here only so /health
    # can report presence (never the value). Honours both common env names.
    hf_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
    )

    @field_validator("threshold")
    @classmethod
    def _threshold_in_unit_interval(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        return v

    @field_validator("device")
    @classmethod
    def _known_device(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"cpu", "cuda"}:
            raise ValueError("device must be 'cpu' or 'cuda'")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()