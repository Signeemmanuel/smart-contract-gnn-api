"""Static flaw metadata for the front end, sourced from ``scgnn.schema`` so the
codes, human names and DASP numbers stay identical across all three repositories
rather than being redefined here.
"""

from __future__ import annotations

from fastapi import APIRouter

from scgnn.schema import FLAW_DASP, FLAW_DISPLAY_NAMES, FLAWS

from ..schema_models import FlawMeta

router = APIRouter(tags=["flaws"])


@router.get("/flaws", response_model=list[FlawMeta])
async def list_flaws() -> list[FlawMeta]:
    return [
        FlawMeta(type=code, name=FLAW_DISPLAY_NAMES[code], dasp=FLAW_DASP[code])
        for code in FLAWS
    ]
