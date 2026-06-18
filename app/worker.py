"""A process-based worker pool for running ``analyze_source`` off the event loop.

Why processes, not threads: ``analyze_source`` runs ``solc``/Slither/CodeBERT/
GNNExplainer and can wedge in ways a Python thread cannot be made to stop. A
worker *process* can be terminated, so a hard wall-clock timeout is actually
enforceable. Each worker loads the model **once** at start (so CodeBERT and the
bundle are paid for once, not per request) and then serves jobs.

Default is a single worker (one CodeBERT copy in RAM — the right choice on a
free 2GB-class host). Raise ``max_workers`` only with RAM headroom. On a
per-request timeout the pool is recycled (workers terminated and respawned); with
one worker that cleanly reclaims the wedged job, which is the common case.

The pool is created and torn down by the application lifespan; it is never built
per request.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import multiprocessing as mp
import threading
from concurrent.futures import Future

_log = logging.getLogger("scgnn_api.worker")

_READY = "__ready__"
_STOP = None  # sentinel placed on the input queue to ask a worker to exit


def _worker_main(in_q: "mp.Queue", out_q: "mp.Queue", cfg: dict) -> None:
    """Worker entry point: load the model once, then serve jobs until stopped."""
    try:
        from scgnn.inference import analyze_source, load_model

        loaded = load_model(cfg["repo_id"], cfg["revision"], cfg["device"])
    except Exception as exc:  # noqa: BLE001 - report load failure, then exit
        out_q.put((_READY, "error", f"{type(exc).__name__}: {exc}"))
        return

    out_q.put((_READY, "ok", None))

    while True:
        item = in_q.get()
        if item is _STOP:
            break
        seq, source, threshold = item
        try:
            result = analyze_source(loaded, source, threshold=threshold)
            out_q.put((seq, "ok", result))
        except Exception as exc:  # noqa: BLE001 - extraction/inference failures are routine
            out_q.put((seq, "error", f"{type(exc).__name__}: {exc}"))


class WorkerPoolError(RuntimeError):
    pass


class AnalysisTimeout(RuntimeError):
    pass


class WorkerPool:
    """Owns the worker processes and bridges their results to asyncio futures."""

    def __init__(self, repo_id: str, revision: str, device: str, max_workers: int = 1) -> None:
        self._cfg = {"repo_id": repo_id, "revision": revision, "device": device}
        self._max_workers = max(1, int(max_workers))
        self._ctx = mp.get_context("spawn")  # clean child, no inherited threads/loop
        self._in_q: mp.Queue | None = None
        self._out_q: mp.Queue | None = None
        self._procs: list = []
        self._reader: threading.Thread | None = None
        self._pending: dict[int, Future] = {}
        self._seq = itertools.count(1)
        self._sem = asyncio.Semaphore(self._max_workers)  # cap in-flight to worker count
        self._lock = threading.Lock()
        self._closing = False

    # -- lifecycle ---------------------------------------------------------

    def start(self, ready_timeout: float = 600.0) -> None:
        """Spawn the workers and block until each has loaded the model."""
        self._in_q = self._ctx.Queue()
        self._out_q = self._ctx.Queue()
        self._closing = False
        self._procs = [
            self._ctx.Process(target=_worker_main, args=(self._in_q, self._out_q, self._cfg), daemon=True)
            for _ in range(self._max_workers)
        ]
        for p in self._procs:
            p.start()

        # Wait for one READY per worker, off the dispatch path.
        ready = 0
        while ready < self._max_workers:
            tag, status, payload = self._out_q.get(timeout=ready_timeout)
            if tag != _READY:
                continue
            if status == "error":
                self._terminate_procs()
                raise WorkerPoolError(f"model load failed in worker: {payload}")
            ready += 1

        self._reader = threading.Thread(target=self._drain, name="scgnn-pool-reader", daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        """Background thread: resolve pending futures from worker results."""
        assert self._out_q is not None
        while not self._closing:
            try:
                seq, status, payload = self._out_q.get(timeout=0.5)
            except Exception:
                continue
            if seq == _READY:
                continue
            with self._lock:
                fut = self._pending.pop(seq, None)
            if fut is not None and not fut.done():
                fut.set_result((status, payload))

    def _terminate_procs(self) -> None:
        for p in self._procs:
            if p.is_alive():
                p.terminate()
        for p in self._procs:
            p.join(timeout=5)
        self._procs = []

    async def shutdown(self) -> None:
        self._closing = True
        if self._in_q is not None:
            for _ in self._procs:
                try:
                    self._in_q.put(_STOP)
                except Exception:
                    pass
        await asyncio.get_running_loop().run_in_executor(None, self._terminate_procs)

    async def _recycle(self) -> None:
        """Terminate and respawn all workers (used to reclaim a wedged job)."""
        loop = asyncio.get_running_loop()
        with self._lock:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(AnalysisTimeout("worker recycled"))
            self._pending.clear()
        await loop.run_in_executor(None, self._terminate_procs)
        await loop.run_in_executor(None, self.start)

    # -- per-request -------------------------------------------------------

    async def run(self, source: str, threshold: float, timeout: float) -> dict:
        """Run one analysis under a hard wall-clock timeout.

        Returns the result dict, or raises AnalysisTimeout / RuntimeError. On
        timeout the wedged worker is killed and replaced.
        """
        if self._in_q is None:
            raise WorkerPoolError("worker pool not started")

        async with self._sem:
            seq = next(self._seq)
            fut: Future = Future()
            with self._lock:
                self._pending[seq] = fut
            self._in_q.put((seq, source, threshold))
            try:
                status, payload = await asyncio.wait_for(asyncio.wrap_future(fut), timeout)
            except asyncio.TimeoutError:
                with self._lock:
                    self._pending.pop(seq, None)
                _log.warning("analysis exceeded %.0fs; recycling worker", timeout)
                await self._recycle()
                raise AnalysisTimeout(f"analysis exceeded the {timeout:.0f}s limit")

        if status == "ok":
            return payload
        raise RuntimeError(payload)  # extraction/inference failure text from the worker