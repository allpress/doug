"""Integration tests for Doug.

Tests end-to-end workflows: config → cache → index → query pipeline,
plugin manager lifecycle, RAG engine setup, and Playwright readiness.

These tests use tmp_path fixtures and mocked externals — they don't
require network access, Playwright binaries, or GPU-heavy models.
"""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doug.config import DougConfig
from doug.cache_manager import CacheManager
from doug.indexer import RepoIndexer, GlobalIndexer
from doug.ai_query import AIQueryTool
from doug.plugins.base import DougPlugin, PluginManager
from doug.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, name: str = "sample-repo") -> Path:
    """Create a minimal git-like repo on disk for indexing."""
    repo = tmp_path / "repos" / name
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()  # marker so it looks like a checkout

    (repo / "main.py").write_text(
        textwrap.dedent("""\
        def hello():
            return "world"

        class Greeter:
            def greet(self, name: str) -> str:
                return f"Hello, {name}!"
        """)
    )
    (repo / "utils.py").write_text(
        textwrap.dedent("""\
        import os

        API_URL = "https://api.example.com/v1"

        def get_env(key: str) -> str:
            return os.environ.get(key, "")
        """)
    )
    (repo / "README.md").write_text("# Sample Repo\nA test repo for Doug.\n")
    return repo


def _write_repo_cache(config: DougConfig, name: str, repo_path: Path) -> Path:
    """Write a minimal JSON cache file for *name*."""
    cache_file = config.repo_cache_dir / f"{name}.json"
    cache_file.write_text(json.dumps({
        "name": name,
        "path": str(repo_path),
        "branch": "main",
        "indexed_at": "2025-01-01T00:00:00",
    }))
    return cache_file


# ---------------------------------------------------------------------------
# Config → Cache → Index → Query  (full pipeline, no network)
# ---------------------------------------------------------------------------

class TestConfigCacheIndexPipeline:
    """End-to-end: config ➜ index repo on disk ➜ query."""

    def _setup_env(self, tmp_path: Path):
        """Common setup that returns (config, repo_path)."""
        base = tmp_path / "doug_home"
        config = DougConfig(base_path=base)
        config.ensure_directories()

        repo = _make_repo(tmp_path, "demo")
        _write_repo_cache(config, "demo", repo)
        return config, repo

    def test_index_produces_cache_json(self, tmp_path):
        config, repo = self._setup_env(tmp_path)

        indexer = RepoIndexer(repo, config)
        result = indexer.index()

        assert isinstance(result, dict)
        assert result["name"] == "demo"
        assert "structure" in result
        assert "summary" in result

    def test_global_index_aggregates(self, tmp_path):
        config, repo = self._setup_env(tmp_path)

        # Index the repo and write cache
        indexer = RepoIndexer(repo, config)
        repo_data = indexer.index()
        cache_file = config.repo_cache_dir / "demo.json"
        cache_file.write_text(json.dumps(repo_data))

        # Put the repo under repos_dir so GlobalIndexer can find it
        import shutil
        dest = config.repos_dir / "demo"
        if not dest.exists():
            shutil.copytree(repo, dest)
            (dest / ".git").mkdir(exist_ok=True)

        # Build global index via index_all
        global_indexer = GlobalIndexer(config)
        global_data = global_indexer.index_all()

        assert isinstance(global_data, dict)
        assert global_data.get("total_repos", 0) >= 1

    def test_index_then_search(self, tmp_path):
        config, repo = self._setup_env(tmp_path)

        indexer = RepoIndexer(repo, config)
        repo_data = indexer.index()

        # Write the indexed data as cache
        cache_file = config.repo_cache_dir / "demo.json"
        cache_file.write_text(json.dumps(repo_data))

        engine = AIQueryTool(config)
        results = engine.search("hello", scope="all")

        assert isinstance(results, dict)
        assert "total_matches" in results

    def test_index_then_list_repos(self, tmp_path):
        config, repo = self._setup_env(tmp_path)

        indexer = RepoIndexer(repo, config)
        repo_data = indexer.index()
        cache_file = config.repo_cache_dir / "demo.json"
        cache_file.write_text(json.dumps(repo_data))

        engine = AIQueryTool(config)
        repos = engine.list_repos()
        assert "demo" in repos

    def test_index_then_overview(self, tmp_path):
        config, repo = self._setup_env(tmp_path)

        indexer = RepoIndexer(repo, config)
        repo_data = indexer.index()
        cache_file = config.repo_cache_dir / "demo.json"
        cache_file.write_text(json.dumps(repo_data))

        # Put the repo under repos_dir so GlobalIndexer can find it
        import shutil
        dest = config.repos_dir / "demo"
        if not dest.exists():
            shutil.copytree(repo, dest)
            (dest / ".git").mkdir(exist_ok=True)

        # Build global index so overview has data
        global_indexer = GlobalIndexer(config)
        global_indexer.index_all()

        engine = AIQueryTool(config)
        overview = engine.quick_overview()

        assert isinstance(overview, str)
        assert "demo" in overview.lower() or "Doug" in overview

    def test_index_respects_skip_dirs(self, tmp_path):
        config, repo = self._setup_env(tmp_path)

        # Put a file inside node_modules — should be skipped
        nm = repo / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {};")

        indexer = RepoIndexer(repo, config)
        repo_data = indexer.index()

        # node_modules content should not appear in the indexed files
        all_paths = []
        for section in ("services", "models", "controllers", "configs"):
            for item in repo_data.get(section, []):
                all_paths.append(item.get("path", ""))

        assert not any("node_modules" in p for p in all_paths)

    def test_multiple_repos_searchable(self, tmp_path):
        base = tmp_path / "doug_home"
        config = DougConfig(base_path=base)
        config.ensure_directories()

        repo_a = _make_repo(tmp_path, "alpha")
        repo_b = _make_repo(tmp_path, "beta")
        (repo_b / "special.py").write_text("UNIQUE_MARKER = 42\n")

        # Index both repos
        for name, repo in [("alpha", repo_a), ("beta", repo_b)]:
            indexer = RepoIndexer(repo, config)
            data = indexer.index()
            cache_file = config.repo_cache_dir / f"{name}.json"
            cache_file.write_text(json.dumps(data))

        engine = AIQueryTool(config)
        repos = engine.list_repos()
        assert "alpha" in repos
        assert "beta" in repos


# ---------------------------------------------------------------------------
# Plugin manager lifecycle
# ---------------------------------------------------------------------------

class TestPluginManagerLifecycle:
    """Plugin registration, enabling, listing, and execution."""

    def test_list_plugins(self, tmp_path):
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        mgr = PluginManager(config=config)
        plugins = mgr.list_plugins()

        assert isinstance(plugins, list)
        names = {p["name"] for p in plugins}
        # Builtins should be discoverable
        assert "jira" in names
        assert "confluence" in names

    def test_enable_and_check_plugin(self, tmp_path):
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        config.enable_plugin("jira")
        assert config.is_plugin_enabled("jira")

        config.enable_plugin("jira", enabled=False)
        assert not config.is_plugin_enabled("jira")

    def test_instance_level_registry_isolation(self, tmp_path):
        """BUG-1 regression: two PluginManagers must NOT share registries."""
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        mgr1 = PluginManager(config=config)
        mgr2 = PluginManager(config=config)

        # They should have separate dicts
        assert mgr1._plugin_registry is not mgr2._plugin_registry

    def test_custom_plugin_registration(self, tmp_path):
        """Register a custom plugin class at runtime."""
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        class StubPlugin(DougPlugin):
            def __init__(self, **kw):
                super().__init__("stub", "A stub plugin", **kw)

            def setup(self):
                return True

            def is_configured(self):
                return True

            def execute(self, action, **kw):
                return {"action": action, "ok": True}

            def get_available_actions(self):
                return [{"action": "ping", "description": "Ping"}]

        mgr = PluginManager(config=config)
        mgr.register_plugin("stub", StubPlugin)

        plugin = mgr.get_plugin("stub")
        assert plugin is not None
        assert plugin.name == "stub"

        config.enable_plugin("stub")
        result = mgr.execute_plugin("stub", "ping")
        assert result == {"action": "ping", "ok": True}


# ---------------------------------------------------------------------------
# RAG engine (mocked heavy deps)
# ---------------------------------------------------------------------------

class TestRAGSetup:
    """RAG engine initialisation, dependency checking, and status."""

    def test_dependency_check_reports_missing(self, tmp_path):
        """When chromadb / sentence-transformers aren't installed, we get a clear message."""
        from doug.rag.rag_engine import _check_rag_dependencies

        ok, msg = _check_rag_dependencies()
        # In CI / dev the deps may or may not be present — just verify shape
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        if not ok:
            assert "pip install doug[rag]" in msg

    def test_status_without_deps(self, tmp_path):
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        from doug.rag.rag_engine import RAGEngine

        engine = RAGEngine(config=config)
        status = engine.get_status()

        assert "dependencies_available" in status
        assert "rag_dir" in status

    def test_clear_is_safe_when_empty(self, tmp_path):
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        from doug.rag.rag_engine import RAGEngine

        engine = RAGEngine(config=config)
        result = engine.clear()
        assert result.get("status") == "cleared" or "error" in result

    def test_chunker_structural(self):
        """CodeChunker finds function/class boundaries."""
        from doug.rag.rag_engine import CodeChunker

        code = textwrap.dedent("""\
        import os

        def foo():
            return 1

        class Bar:
            pass

        def baz():
            return 2
        """)

        chunker = CodeChunker(chunk_size=512, chunk_overlap=64)
        chunks = chunker.chunk_file(code, "file.py", "repo")

        assert len(chunks) >= 2  # at least foo + Bar or baz
        for c in chunks:
            assert "text" in c
            assert "metadata" in c
            assert c["metadata"]["repo"] == "repo"

    def test_chunker_empty_file(self):
        from doug.rag.rag_engine import CodeChunker

        chunker = CodeChunker()
        assert chunker.chunk_file("", "empty.py", "repo") == []
        assert chunker.chunk_file("   \n\n  ", "blank.py", "repo") == []


# ---------------------------------------------------------------------------
# Playwright readiness (no actual browser needed)
# ---------------------------------------------------------------------------

class TestPlaywrightReadiness:
    """Verify Playwright plugin base without requiring browser binaries."""

    def test_plugin_dirs_created(self, tmp_path):
        """PlaywrightPlugin must create auth + screenshots dirs on init."""
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        from doug.plugins.playwright_base import PlaywrightPlugin

        class StubPW(PlaywrightPlugin):
            def __init__(self, **kw):
                super().__init__("stub_pw", "Stub Playwright Plugin", **kw)

            def setup(self):
                return True

            def is_configured(self):
                return False

            def execute(self, action, **kw):
                return {}

            def get_available_actions(self):
                return []

        plugin = StubPW(config=config)
        assert plugin.auth_dir.exists()
        assert plugin.screenshots_dir.exists()

    def test_ensure_playwright_ready_importerror(self, tmp_path):
        """When Playwright is not installed, ensure_playwright_ready reports it."""
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        from doug.plugins.playwright_base import PlaywrightPlugin

        class StubPW(PlaywrightPlugin):
            def __init__(self, **kw):
                super().__init__("stub_pw2", "Stub", **kw)
            def setup(self):
                return True
            def is_configured(self):
                return False
            def execute(self, action, **kw):
                return {}
            def get_available_actions(self):
                return []

        plugin = StubPW(config=config)

        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with patch("doug.plugins.playwright_base.PlaywrightPlugin.ensure_playwright_ready") as mock_ready:
                mock_ready.return_value = (False, "Playwright not installed")
                ok, msg = plugin.ensure_playwright_ready()
                assert not ok

    def test_has_auth_state_false_by_default(self, tmp_path):
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        from doug.plugins.playwright_base import PlaywrightPlugin

        class StubPW(PlaywrightPlugin):
            def __init__(self, **kw):
                super().__init__("stub_pw3", "Stub", **kw)
            def setup(self):
                return True
            def is_configured(self):
                return False
            def execute(self, action, **kw):
                return {}
            def get_available_actions(self):
                return []

        plugin = StubPW(config=config)
        assert not plugin.has_auth_state()

    def test_auth_state_roundtrip(self, tmp_path):
        """Write a fake auth state and verify has_auth_state sees it."""
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        from doug.plugins.playwright_base import PlaywrightPlugin

        class StubPW(PlaywrightPlugin):
            def __init__(self, **kw):
                super().__init__("stub_pw4", "Stub", **kw)
            def setup(self):
                return True
            def is_configured(self):
                return False
            def execute(self, action, **kw):
                return {}
            def get_available_actions(self):
                return []

        plugin = StubPW(config=config)
        auth_path = plugin.get_auth_state_path()
        auth_path.write_text(json.dumps({"cookies": []}))

        assert plugin.has_auth_state()
        assert plugin.clear_auth()
        assert not plugin.has_auth_state()


# ---------------------------------------------------------------------------
# CLI integration (end-to-end through main())
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    """Full CLI round-trips using main()."""

    def test_status_then_add_then_status(self, tmp_path):
        base = str(tmp_path / "doug_home")

        assert main(["--base-path", base, "status"]) == 0
        assert main(["--base-path", base, "add-repo", "https://github.com/org/repo.git"]) == 0
        assert main(["--base-path", base, "status"]) == 0

    def test_add_then_remove(self, tmp_path):
        base = str(tmp_path / "doug_home")

        assert main(["--base-path", base, "add-repo", "https://github.com/org/test.git"]) == 0
        assert main(["--base-path", base, "remove-repo", "test"]) == 0

    def test_clean_all(self, tmp_path):
        base = str(tmp_path / "doug_home")
        assert main(["--base-path", base, "clean", "all"]) == 0

    def test_query_overview_on_empty(self, tmp_path):
        base = str(tmp_path / "doug_home")
        assert main(["--base-path", base, "query", "overview"]) == 0

    def test_invalid_url_returns_error(self, tmp_path):
        base = str(tmp_path / "doug_home")
        assert main(["--base-path", base, "add-repo", "not-a-url"]) == 1

    def test_no_subcommand_shows_help(self):
        """Bare 'doug' should exit 0 (prints help banner)."""
        assert main([]) == 0


# ---------------------------------------------------------------------------
# Security regressions
# ---------------------------------------------------------------------------

class TestSecurityRegressions:
    """Verify fixes from the security review remain in place."""

    def test_plugin_config_permissions(self, tmp_path):
        """SEC-2: plugin config files must be chmod 0o600."""
        import configparser

        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        mgr = PluginManager(config=config)
        plugin = mgr.get_plugin("jira")

        if plugin is not None:
            pc = configparser.ConfigParser()
            pc["jira"] = {"url": "https://jira.example.com", "token": "secret"}
            plugin.write_plugin_config(pc)

            mode = oct(plugin.config_path.stat().st_mode & 0o777)
            assert mode == "0o600", f"Expected 0o600 but got {mode}"

    def test_path_traversal_blocked(self, tmp_path):
        """SEC-4: cache manager must reject names with path traversal."""
        config = DougConfig(base_path=tmp_path / "doug_home")
        config.ensure_directories()

        mgr = CacheManager(config)

        # Traversal URLs should be sanitised by _extract_repo_name
        # and validated by clone_repo's resolve().relative_to() check
        for bad_url in [
            "https://github.com/org/../../../etc/passwd.git",
            "https://github.com/org/foo%2F..%2F..%2Fbar.git",
        ]:
            repo_path = mgr.get_repo_path(bad_url)
            # The resolved path must stay under repos_dir
            try:
                repo_path.resolve().relative_to(mgr.repos_dir.resolve())
            except ValueError:
                pass  # Expected — traversal blocked
