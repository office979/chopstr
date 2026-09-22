"""ClipProjectWorkflow in der Temporal-Zeitraffer-Testumgebung mit gemockten Activities.

Die Testumgebung lädt beim ersten Start ein Test-Server-Binary herunter; ohne Netz wird übersprungen.
Aufruf nur dieses Tests: pytest -m network tests/test_workflow.py
"""

from __future__ import annotations

import uuid

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio import activity  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from chopstr_worker.workflows.clip_project import ClipProjectParams, ClipProjectWorkflow  # noqa: E402

pytestmark = pytest.mark.network

calls: list[tuple] = []


@activity.defn(name="probe_and_extract")
async def fake_probe(source_id: str) -> dict:
    calls.append(("probe_and_extract", source_id))
    return {"source_id": source_id}


@activity.defn(name="transcribe_de")
async def fake_transcribe(source_id: str) -> str:
    calls.append(("transcribe_de", source_id))
    return "asr/key.json"


@activity.defn(name="diarize")
async def fake_diarize(source_id: str) -> str:
    calls.append(("diarize", source_id))
    return "diar/key.json"


@activity.defn(name="heatmap")
async def fake_heatmap(source_id: str) -> str:
    calls.append(("heatmap", source_id))
    return "heatmap/key.json"


@activity.defn(name="fuse_and_nlp")
async def fake_fuse(source_id: str) -> str:
    calls.append(("fuse_and_nlp", source_id))
    return "tv-1"


@activity.defn(name="detect_candidates")
async def fake_detect(source_id: str) -> list[str]:
    calls.append(("detect_candidates", source_id))
    return []


@activity.defn(name="render_pack")
async def fake_render(candidate_id: str, destination: str) -> str:
    calls.append(("render_pack", candidate_id, destination))
    return f"renders/{candidate_id}-{destination}.mp4"


@activity.defn(name="notify")
async def fake_notify(source_id: str, event: str) -> None:
    calls.append(("notify", source_id, event))


ACTIVITIES = [fake_probe, fake_transcribe, fake_diarize, fake_heatmap, fake_fuse, fake_detect, fake_render, fake_notify]


async def _env():
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # Download des Test-Servers oder Start fehlgeschlagen (kein Netz)
        pytest.skip(f"Temporal-Testumgebung nicht verfügbar: {exc.__class__.__name__}")


async def test_workflow_runs_pipeline_then_renders_approved():
    calls.clear()
    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=tq, workflows=[ClipProjectWorkflow], activities=ACTIVITIES):
            handle = await env.client.start_workflow(
                ClipProjectWorkflow.run,
                ClipProjectParams(source_id="src-1", cpu_queue=tq, gpu_queue=tq, review_days=1),
                id=f"wf-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )
            await handle.signal(ClipProjectWorkflow.approve, args=["cand-1", "tiktok"])
            await handle.signal(ClipProjectWorkflow.finish_review)
            result = await handle.result()
    assert result == ["renders/cand-1-tiktok.mp4"]
    names = [c[0] for c in calls]
    assert names[0] == "probe_and_extract"
    assert set(names[1:4]) == {"transcribe_de", "diarize", "heatmap"}
    assert names[4:6] == ["fuse_and_nlp", "detect_candidates"]
    assert ("notify", "src-1", "candidates_ready") in calls
    assert ("render_pack", "cand-1", "tiktok") in calls
    assert ("notify", "src-1", "renders_ready") in calls


async def test_workflow_review_timeout_without_approvals():
    calls.clear()
    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=tq, workflows=[ClipProjectWorkflow], activities=ACTIVITIES):
            handle = await env.client.start_workflow(
                ClipProjectWorkflow.run,
                ClipProjectParams(source_id="src-2", cpu_queue=tq, gpu_queue=tq, review_days=14),
                id=f"wf-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )
            result = await handle.result()  # Zeitraffer überspringt die 14 Tage
    assert result == []
    assert not any(c[0] == "render_pack" for c in calls)
