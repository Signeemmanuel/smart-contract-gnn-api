"""Stand-in for the real analysis, returning the genuine ``scgnn.schema`` shape.

This is the one piece that is deliberately fake in this increment. It builds its
result with the *real* ``scgnn.schema`` dataclasses, so the wire contract
(including the line de-duplication and ordering guarantees) is exercised end to
end exactly as the real path will produce it. The next increment replaces
``run_mock_analysis`` with a call into the worker pool running
``scgnn.inference.analyze_source(loaded, src, threshold=...)`` under a wall-clock
timeout.
"""

from __future__ import annotations

import asyncio

from scgnn.schema import AnalysisResult, FlawResult


async def run_mock_analysis(source: str, threshold: float) -> dict:
    # A short await keeps the event loop free, standing in for the seconds-long
    # real analysis that will run off the loop in a worker process.
    await asyncio.sleep(0.2)

    # A transparently canned signal so the demo is not always identical, without
    # implying real detection. Real detection comes from analyze_source.
    flaws: list[FlawResult] = []
    if "call.value" in source or "call{value" in source:
        flaws.append(FlawResult(type="reentrancy", confidence=0.91, lines=[42, 47, 53]))

    return AnalysisResult(source=source, flaws=flaws).to_dict()
