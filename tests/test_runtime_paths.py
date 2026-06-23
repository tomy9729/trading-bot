from pathlib import Path

from src.config.runtime_paths import PROJECT_ROOT, get_database_path, get_log_dir


def test_runtime_paths_use_project_root_by_default(monkeypatch):
    monkeypatch.delenv("TRADING_DB_PATH", raising=False)
    monkeypatch.delenv("TRADING_LOG_DIR", raising=False)

    assert get_database_path() == (PROJECT_ROOT / "data" / "trading.db").resolve()
    assert get_log_dir() == (PROJECT_ROOT / "logs").resolve()


def test_runtime_paths_resolve_relative_override_from_project_root(monkeypatch):
    monkeypatch.setenv("TRADING_DB_PATH", "runtime/test.db")

    assert get_database_path() == (PROJECT_ROOT / "runtime" / "test.db").resolve()


def test_runtime_paths_preserve_absolute_override(tmp_path, monkeypatch):
    database_path = tmp_path / "trading.db"
    monkeypatch.setenv("TRADING_DB_PATH", str(database_path))

    assert get_database_path() == Path(database_path).resolve()
