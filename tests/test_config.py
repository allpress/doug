"""Tests for doug.config module."""

import configparser
from pathlib import Path

import pytest

from doug.config import DougConfig, _find_base_path


@pytest.fixture
def tmp_base(tmp_path):
    """Create a temporary base directory for testing."""
    return tmp_path / "doug_test"


@pytest.fixture
def config(tmp_base):
    """Create a DougConfig with a temporary base path."""
    return DougConfig(base_path=tmp_base)


class TestFindBasePath:
    def test_uses_env_var(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom_doug"
        monkeypatch.setenv("DOUG_HOME", str(custom))
        result = _find_base_path()
        assert result == custom.resolve()

    def test_defaults_to_home(self, monkeypatch):
        monkeypatch.delenv("DOUG_HOME", raising=False)
        result = _find_base_path()
        assert result == Path.home() / ".doug"


class TestDougConfig:
    def test_init_creates_config_object(self, config, tmp_base):
        assert config.base_path == tmp_base.resolve()
        assert config.config_dir == tmp_base.resolve() / "config"
        assert config.cache_dir == tmp_base.resolve() / "cache"
        assert config.repos_dir == tmp_base.resolve() / "repositories"

    def test_default_values(self, config):
        assert config.parallel_workers == 4
        assert config.cache_freshness_hours == 24
        assert config.max_file_size_kb == 1024
        assert config.readme_max_chars == 2000
        assert config.max_depth == 20
        assert config.use_personality_voice is True
        assert config.show_progress is True
        assert config.color_output is True

    def test_skip_dirs_is_list(self, config):
        skip_dirs = config.skip_dirs
        assert isinstance(skip_dirs, list)
        assert ".git" in skip_dirs
        assert "node_modules" in skip_dirs
        assert "__pycache__" in skip_dirs

    def test_source_extensions_is_list(self, config):
        exts = config.source_extensions
        assert isinstance(exts, list)
        assert ".py" in exts
        assert ".java" in exts
        assert ".ts" in exts

    def test_config_extensions_is_list(self, config):
        exts = config.config_extensions
        assert isinstance(exts, list)
        assert ".json" in exts
        assert ".yaml" in exts

    def test_ensure_directories(self, config):
        config.ensure_directories()
        assert config.config_dir.exists()
        assert config.cache_dir.exists()
        assert config.repos_dir.exists()
        assert config.repos_config_dir.exists()
        assert config.plugins_config_dir.exists()
        assert config.repo_cache_dir.exists()
        assert config.index_cache_dir.exists()
        assert config.plugin_cache_dir.exists()

    def test_save_and_reload(self, config):
        config.set("cache", "parallel_workers", "8")
        config.save()

        config2 = DougConfig(base_path=config.base_path)
        assert config2.parallel_workers == 8

    def test_plugin_enabled(self, config):
        assert config.is_plugin_enabled("jira") is False
        config.enable_plugin("jira", True)
        assert config.is_plugin_enabled("jira") is True
        config.enable_plugin("jira", False)
        assert config.is_plugin_enabled("jira") is False

    def test_plugin_config(self, config):
        config.ensure_directories()
        config.set_plugin_config("test_plugin", "settings", {"key1": "val1", "key2": "val2"})

        result = config.get_plugin_config("test_plugin")
        assert result["settings.key1"] == "val1"
        assert result["settings.key2"] == "val2"

    def test_has_plugin(self, config):
        config.ensure_directories()
        assert config.has_plugin("nonexistent") is False
        config.set_plugin_config("existing", "section", {"key": "val"})
        assert config.has_plugin("existing") is True

    def test_get_repository_files(self, config):
        config.ensure_directories()
        assert config.get_repository_files() == []

        repos_file = config.repos_config_dir / "repos.txt"
        repos_file.write_text("https://github.com/org/repo.git\n")
        files = config.get_repository_files()
        assert len(files) == 1
        assert files[0].name == "repos.txt"

    def test_get_set_raw_values(self, config):
        config.set("custom", "mykey", "myvalue")
        assert config.get("custom", "mykey") == "myvalue"

    def test_get_status(self, config):
        status = config.get_status()
        assert "base_path" in status
        assert "plugins" in status
        assert isinstance(status["plugins"], dict)

    def test_loads_user_config(self, tmp_base):
        config_dir = tmp_base / "config"
        config_dir.mkdir(parents=True)
        ini = configparser.ConfigParser()
        ini.add_section("cache")
        ini.set("cache", "parallel_workers", "16")
        with open(config_dir / "defaults.ini", "w") as f:
            ini.write(f)

        config = DougConfig(base_path=tmp_base)
        assert config.parallel_workers == 16
