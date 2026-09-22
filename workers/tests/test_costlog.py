from __future__ import annotations

import pytest

from chopstr_worker import config, costlog


def test_estimate_eur_uses_env_prices(monkeypatch):
    monkeypatch.setenv("GPU_EUR_PER_HOUR", "3.6")
    monkeypatch.setenv("LLM_EUR_PER_1M_INPUT", "1.0")
    monkeypatch.setenv("LLM_EUR_PER_1M_OUTPUT", "10.0")
    monkeypatch.setenv("CPU_EUR_PER_HOUR", "0")
    monkeypatch.setenv("STORAGE_EUR_PER_GB_MONTH", "0")
    config.reload()
    c = costlog.Cost(workspace_id="w", job_type="asr", gpu_seconds=3600, llm_input_tokens=500_000, llm_output_tokens=100_000)
    assert costlog.estimate_eur(c) == pytest.approx(3.6 + 0.5 + 1.0)


def test_estimate_gladia_by_minutes(monkeypatch):
    monkeypatch.setenv("GLADIA_EUR_PER_HOUR", "6.0")
    config.reload()
    c = costlog.Cost(workspace_id="w", job_type="asr", provider="gladia-eu", source_minutes=30)
    assert costlog.estimate_eur(c) == pytest.approx(3.0)


def test_record_writes_job_costs_row(fake_db):
    c = costlog.Cost(workspace_id="w1", source_id="s1", job_type="ingest", cpu_seconds=10, storage_bytes=1024)
    eur = costlog.record(fake_db, c)
    assert len(fake_db.job_costs) == 1
    row = fake_db.job_costs[0]
    assert row["workspace_id"] == "w1" and row["job_type"] == "ingest"
    assert row["cpu_seconds"] == 10
    assert row["estimated_eur"] == eur


def test_make_sink(fake_db):
    sink = costlog.make_sink(fake_db, "w1", source_id="s1")
    sink({"provider": "mistral-eu", "model": "m", "in": 10, "out": 5, "job_type": "llm_propose"})
    row = fake_db.job_costs[0]
    assert row["provider"] == "mistral-eu"
    assert row["llm_input_tokens"] == 10 and row["llm_output_tokens"] == 5
    assert row["job_type"] == "llm_propose"
