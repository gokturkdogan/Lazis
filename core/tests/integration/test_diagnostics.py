"""Phase 4 diagnostics: model/runtime/last-turn/pre-warm state without any message content,
honest cache reporting (an empty-session pre-warm is not a warm conversation), and the
cached integrity check behind the status view. Synthetic data only."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from lazis.errors import LlmLoadFailedError
from lazis.storage import StorageHandle
from lazis.storage import database as database_module
from tests.conftest import make_client
from tests.conversation_support import MODEL, ScriptedLLM, client_id, make_engine, run_turn

SECRET = "Tanılama-gizli-7731: kardeşimin adresi"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_diagnostics_requires_the_token_and_never_contains_content(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    llm = ScriptedLLM(reply=lambda r: f"Yanıt: {SECRET}")
    with make_client(tmp_path, storage, token, llm=llm) as client:
        assert client.get("/api/v1/diagnostics").status_code == 401
        before = client.get("/api/v1/diagnostics", headers=_auth(token)).json()
        assert before["last_turn"] is None and before["prewarm"]["state"] == "idle"
        body = {"client_id": client_id(), "content": SECRET, "model": MODEL}
        assert client.post("/api/v1/turns", json=body, headers=_auth(token)).status_code == 200
        diag = client.get("/api/v1/diagnostics", headers=_auth(token))
        assert diag.status_code == 200
        assert "Tanılama-gizli" not in diag.text and "kardeşimin" not in diag.text
        data = diag.json()
        assert data["runtime"]["available"] is True and data["runtime"]["version"] == "0.0-test"
        model = data["model"]
        assert model["active"] == MODEL and model["active_installed"] is True
        assert model["fallback"] == "qwen3.5:9b-q4_K_M" and model["automatic_fallback"] is False
        turn = data["last_turn"]
        assert turn["outcome"] == "completed" and turn["output_tokens"] and turn["prompt_tokens"]
        assert turn["failed_stage"] is None
        assert turn["ttft_ms"] is not None and turn["total_ms"] >= turn["ttft_ms"]
        assert data["cache_expected_warm"] is True  # nothing used the runtime since


def test_runtime_down_is_reported_not_hidden(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    with make_client(tmp_path, storage, token, llm=ScriptedLLM(available=False)) as client:
        data = client.get("/api/v1/diagnostics", headers=_auth(token)).json()
        assert data["runtime"] == {
            "available": False,
            "version": None,
            "error_code": "llm_unavailable",
        }
        assert data["model"]["loaded"] is None


def test_prewarm_states_and_scopes(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> list[dict[str, object]]:
        seen: list[dict[str, object]] = []
        # Empty assistant (no session yet): the pre-warm can only load the model.
        await engine.prepare(None, MODEL)
        seen.append(dict(engine.prewarm_status))
        job = engine.scheduler.background
        assert job is not None and job.task is not None
        await job.task
        seen.append(dict(engine.prewarm_status))
        diag = await engine.diagnostics()
        seen.append({"cache_expected_warm": diag["cache_expected_warm"]})
        _, sid = await run_turn(engine, "Merhaba")
        engine.scheduler.cache = None
        await engine.prepare(sid, MODEL)
        job = engine.scheduler.background
        assert job is not None and job.task is not None
        await job.task
        seen.append(dict(engine.prewarm_status))
        seen.append({"cache_expected_warm": (await engine.diagnostics())["cache_expected_warm"]})
        # A failing pre-warm is reported as failed with its code.
        engine.scheduler.cache = None
        llm.fail_with, llm.fail_after_chunks = LlmLoadFailedError("x"), 0
        await engine.prepare(sid, MODEL)
        job = engine.scheduler.background
        assert job is not None and job.task is not None
        await job.task
        seen.append(dict(engine.prewarm_status))
        await engine.close()
        return seen

    seen = asyncio.run(go())
    assert seen[0]["state"] == "running" and seen[0]["scope"] == "model_only"
    assert seen[1]["state"] == "done" and seen[1]["scope"] == "model_only"
    assert seen[2] == {"cache_expected_warm": False}  # model loaded is not a warm context
    assert seen[3]["state"] == "done" and seen[3]["scope"] == "context"
    assert seen[4] == {"cache_expected_warm": True}
    assert seen[5]["state"] == "failed" and seen[5]["code"] == "llm_load_failed"


def test_empty_session_prewarm_never_reports_a_warm_first_turn(
    tmp_path: Path, storage: StorageHandle
) -> None:
    """PHASE_3_REPORT §13.D: a system-prompt-only pre-warm did not speed up the first turn."""
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> list[dict[str, object]]:
        session = await engine.start_new_session(MODEL)
        await engine.prepare(session.id, MODEL)
        job = engine.scheduler.background
        assert job is not None and job.task is not None
        await job.task
        events, _ = await run_turn(engine, "İlk mesaj")
        await engine.close()
        return events

    events = asyncio.run(go())
    status = next(e for e in events if e.get("stage") == "processing_context")
    assert status["cache"] == "cold"


def test_last_turn_records_cancellation(tmp_path: Path, storage: StorageHandle) -> None:
    from lazis.conversation import TurnRequest

    llm = ScriptedLLM(reply=lambda r: "uzun " * 200, chunk_size=3, delay=0.01)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> dict[str, object] | None:
        handle = await engine.begin_turn(TurnRequest(None, "client-diag-0001", "Anlat", MODEL))
        async for event in engine.events(handle):
            if event["type"] == "delta":
                engine.cancel_turn("client-diag-0001")
        await engine.close()
        return engine.last_turn

    last = asyncio.run(go())
    assert last is not None and last["outcome"] == "cancelled" and last["ttft_ms"] is not None
    assert "uzun" not in json.dumps(last)


def test_last_turn_records_a_failure_with_its_stage(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM()
    llm.fail_with, llm.fail_after_chunks = LlmLoadFailedError("x"), 0
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> dict[str, object] | None:
        await run_turn(engine, "Merhaba")
        await engine.close()
        return engine.last_turn

    last = asyncio.run(go())
    assert last is not None and last["outcome"] == "failed" and last["failed_stage"]
    assert last["ttft_ms"] is None


def test_status_view_reuses_the_integrity_check(storage: StorageHandle) -> None:
    first = storage.db.status()
    assert first.quick_check == "ok"
    # Pretend the cached result is fresh but different: the status view must reuse it…
    storage.db._quick_check_cache = (time.monotonic(), "failed")
    assert storage.db.status().quick_check == "failed"
    # …and run the check again once it is older than the TTL.
    old = time.monotonic() - database_module.QUICK_CHECK_TTL_S - 1
    storage.db._quick_check_cache = (old, "failed")
    assert storage.db.status().quick_check == "ok"


def test_status_endpoint_still_reports_integrity(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    client: TestClient = make_client(tmp_path, storage, token)
    status = client.get("/api/v1/system/status", headers=_auth(token)).json()
    assert status["database"]["integrity"] == "ok"
