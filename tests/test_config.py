"""Unit tests for configuration module."""

from pathlib import Path
import pytest

from config import AppConfig, ConfigurationError, load_config


def test_paths_resolve_relative_to_root(tmp_path: Path):
    """Paths resolve correctly regardless of the current working directory."""
    templates_file = tmp_path / "templates.json"
    templates_file.write_text("{}", encoding="utf-8")

    cfg = load_config(
        root_dir=tmp_path,
        env_overrides={
            "DATA_DIR": "custom_data",
            "LOGS_DIR": "custom_logs",
            "TEMPLATES_FILE_PATH": str(templates_file),
            "APP_ENV": "development",
            "LOG_LEVEL": "DEBUG",
        },
    )

    assert cfg.project_root == tmp_path
    assert cfg.data_dir == tmp_path / "custom_data"
    assert cfg.logs_dir == tmp_path / "custom_logs"
    assert cfg.templates_file_path == templates_file
    assert cfg.data_dir.exists()
    assert cfg.logs_dir.exists()


def test_required_directories_created(tmp_path: Path):
    """ensure_directories creates data and logs folders if they don't exist."""
    data_dir = tmp_path / "new_data_dir"
    logs_dir = tmp_path / "new_logs_dir"
    templates_file = tmp_path / "templates.json"
    templates_file.write_text("{}", encoding="utf-8")

    cfg = load_config(
        root_dir=tmp_path,
        env_overrides={
            "DATA_DIR": str(data_dir),
            "LOGS_DIR": str(logs_dir),
            "TEMPLATES_FILE_PATH": str(templates_file),
        },
    )

    assert data_dir.is_dir()
    assert logs_dir.is_dir()


def test_invalid_app_env_raises_error(tmp_path: Path):
    """Invalid APP_ENV raises clear ConfigurationError."""
    with pytest.raises(ConfigurationError, match="Invalid APP_ENV"):
        load_config(
            root_dir=tmp_path,
            env_overrides={"APP_ENV": "invalid_environment"},
        )


def test_invalid_log_level_raises_error(tmp_path: Path):
    """Invalid LOG_LEVEL raises clear ConfigurationError."""
    with pytest.raises(ConfigurationError, match="Invalid LOG_LEVEL"):
        load_config(
            root_dir=tmp_path,
            env_overrides={"LOG_LEVEL": "INVALID_LEVEL"},
        )


def test_nonexistent_template_parent_dir_raises_error(tmp_path: Path):
    """Missing parent directory for template path raises ConfigurationError."""
    bad_template_path = tmp_path / "nonexistent_dir" / "templates.json"
    with pytest.raises(ConfigurationError, match="Templates directory does not exist"):
        load_config(
            root_dir=tmp_path,
            env_overrides={"TEMPLATES_FILE_PATH": str(bad_template_path)},
        )

