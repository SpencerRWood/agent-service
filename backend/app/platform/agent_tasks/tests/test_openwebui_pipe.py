import importlib.util
from pathlib import Path


def _load_pipe_class():
    path = Path(__file__).resolve().parents[5] / "scripts" / "openwebui_pipe.py"
    spec = importlib.util.spec_from_file_location("openwebui_pipe", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Pipe


def test_progress_event_formatter_includes_selected_model():
    pipe = _load_pipe_class()()

    rendered = pipe._format_progress_event(
        "agent.task.finished",
        {
            "message": "Task complete.",
            "state": "completed",
            "backend": "local_llm",
            "model": "openrouter/openai/gpt-oss-120b:free",
        },
    )

    assert rendered == (
        "agent.task.finished: Task complete. "
        "(state=completed, backend=local_llm, model=openrouter/openai/gpt-oss-120b:free)"
    )
