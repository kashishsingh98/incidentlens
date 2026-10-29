import pytest


@pytest.fixture
def lab(monkeypatch, tmp_path):
    path = tmp_path / "lab.db"
    monkeypatch.setenv("INCIDENTLENS_DB", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return path
