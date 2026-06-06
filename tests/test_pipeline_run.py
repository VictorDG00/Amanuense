import pytest
from pathlib import Path
from unittest.mock import patch, call


def test_callback_receives_agent_start_and_done(tmp_path):
    from pipeline.run import run_pipeline_with_callback

    events = []

    def cb(event):
        events.append(event)

    # Mock every agent so nothing real runs
    with patch("pipeline.run._run_agent"):
        with patch("pipeline.run.AGENT_SEQUENCE", ["corpus-scanner", "norm-analyzer"]):
            with patch("pipeline.config.INTERMEDIATE_DIR", tmp_path / "inter"):
                with patch("pipeline.config.OUTPUT_DIR", tmp_path / "output"):
                    run_pipeline_with_callback("test-run", cb)

    types = [e["type"] for e in events]
    agents = [e.get("agent") for e in events if e["type"] in ("agent_start", "agent_done")]

    assert types.count("agent_start") == 2
    assert types.count("agent_done") == 2
    assert "corpus-scanner" in agents
    assert "norm-analyzer" in agents


def test_callback_index_and_total_are_correct(tmp_path):
    from pipeline.run import run_pipeline_with_callback

    events = []

    with patch("pipeline.run._run_agent"):
        with patch("pipeline.run.AGENT_SEQUENCE", ["a", "b", "c"]):
            with patch("pipeline.config.INTERMEDIATE_DIR", tmp_path / "inter"):
                with patch("pipeline.config.OUTPUT_DIR", tmp_path / "output"):
                    run_pipeline_with_callback("run2", events.append)

    start_events = [e for e in events if e["type"] == "agent_start"]
    assert start_events[0]["index"] == 0
    assert start_events[0]["total"] == 3
    assert start_events[2]["index"] == 2


def test_callback_reports_error_and_raises(tmp_path):
    from pipeline.run import run_pipeline_with_callback

    events = []

    with patch("pipeline.run._run_agent", side_effect=ValueError("boom")):
        with patch("pipeline.run.AGENT_SEQUENCE", ["corpus-scanner"]):
            with patch("pipeline.config.INTERMEDIATE_DIR", tmp_path / "inter"):
                with patch("pipeline.config.OUTPUT_DIR", tmp_path / "output"):
                    with pytest.raises(RuntimeError, match="corpus-scanner"):
                        run_pipeline_with_callback("run3", events.append)

    error_events = [e for e in events if e["type"] == "agent_error"]
    assert len(error_events) == 1
    assert "boom" in error_events[0]["message"]


def test_intermediate_dir_is_created(tmp_path):
    from pipeline.run import run_pipeline_with_callback

    inter_base = tmp_path / "inter"
    out = tmp_path / "output"

    with patch("pipeline.run._run_agent"):
        with patch("pipeline.run.AGENT_SEQUENCE", []):
            with patch("pipeline.config.INTERMEDIATE_DIR", inter_base):
                with patch("pipeline.config.OUTPUT_DIR", out):
                    run_pipeline_with_callback("myrun", lambda e: None)

    assert (inter_base / "myrun").is_dir()
