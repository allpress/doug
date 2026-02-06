"""Tests for doug.mcp_server module."""

import json

import pytest

from doug.config import DougConfig
from doug.mcp_server import DougMCPServer, _check_mcp_dependencies


@pytest.fixture
def config(tmp_path):
    """Config with temp base path."""
    config = DougConfig(base_path=tmp_path / "doug")
    config.ensure_directories()
    return config


@pytest.fixture
def sample_cache(config):
    """Create sample cache data."""
    repo_data = {
        "name": "myapp",
        "path": "/repos/myapp",
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "summary": {
            "total_files": 50,
            "source_files": 30,
            "controllers": 3,
            "services": 5,
            "repositories": 4,
            "models": 6,
            "tests": 10,
            "configs": 5,
            "api_endpoints": 8,
        },
        "structure": {"dirs": {"src": {"dirs": {}, "files": []}}, "files": ["README.md"]},
        "apis": [
            {"method": "GET", "path": "/api/users", "file": "src/UserController.java"},
            {"method": "POST", "path": "/api/users", "file": "src/UserController.java"},
        ],
        "services": [
            {
                "path": "src/UserService.java", "name": "UserService.java",
                "class": "UserService", "type": "service",
            },
        ],
        "models": [
            {"path": "src/User.java", "name": "User.java", "class": "User", "type": "model"},
        ],
        "controllers": [
            {
                "path": "src/UserController.java", "name": "UserController.java",
                "class": "UserController", "type": "controller",
            },
        ],
        "configs": [
            {"path": "application.yml", "name": "application.yml"},
        ],
        "build": {"type": "gradle", "dependencies": []},
        "readme": "# MyApp\nSample app.",
    }

    cache_file = config.repo_cache_dir / "myapp.json"
    cache_file.write_text(json.dumps(repo_data, indent=2))

    global_index = {
        "total_repos": 1,
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "total_files": 50,
        "total_source_files": 30,
        "total_apis": 2,
        "repos": {"myapp": {"files": 50, "source_files": 30, "apis": 2}},
    }
    (config.index_cache_dir / "global_index.json").write_text(json.dumps(global_index))

    apis_index = {
        "total_apis": 2,
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "endpoints": [
            {"method": "GET", "path": "/api/users", "file": "src/UserController.java", "repo": "myapp"},
            {"method": "POST", "path": "/api/users", "file": "src/UserController.java", "repo": "myapp"},
        ],
    }
    (config.index_cache_dir / "apis.json").write_text(json.dumps(apis_index))

    return config


class TestCheckDependencies:
    def test_returns_tuple(self):
        ok, msg = _check_mcp_dependencies()
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_suggests_install_on_missing(self):
        ok, msg = _check_mcp_dependencies()
        if not ok:
            assert "pip install doug[mcp]" in msg


class TestDougMCPServer:
    def test_instantiation(self, config):
        server = DougMCPServer(config=config)
        assert server.config is config

    def test_instantiation_default_config(self):
        server = DougMCPServer()
        assert server.config is not None


class TestHandleToolCall:
    """Test the synchronous _handle_tool_call method directly."""

    @pytest.fixture
    def server_with_tools(self, sample_cache):
        from doug.ai_query import AIQueryTool
        from doug.context_generator import ContextGenerator

        server = DougMCPServer(config=sample_cache)
        query_tool = AIQueryTool(config=sample_cache)
        context_gen = ContextGenerator(config=sample_cache)
        return server, query_tool, context_gen

    def test_search_repos(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("search_repos", {"query": "User"}, qt, cg)
        assert "total_matches" in result
        assert result["total_matches"] > 0

    def test_list_apis(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("list_apis", {}, qt, cg)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_list_apis_filtered(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("list_apis", {"repo_name": "myapp"}, qt, cg)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_repo_summary(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("repo_summary", {"repo_name": "myapp"}, qt, cg)
        assert result["name"] == "myapp"

    def test_repo_summary_not_found(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("repo_summary", {"repo_name": "nope"}, qt, cg)
        assert "error" in result

    def test_repo_detail(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call(
            "repo_detail", {"repo_name": "myapp", "section": "apis"}, qt, cg
        )
        assert result["section"] == "apis"
        assert len(result["data"]) == 2

    def test_find_file(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call(
            "find_file", {"repo_name": "myapp", "pattern": "UserService"}, qt, cg
        )
        assert result["total"] >= 1

    def test_semantic_search_missing_deps(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call(
            "semantic_search", {"query": "user auth"}, qt, cg
        )
        # Either returns results or an error about missing deps
        assert isinstance(result, (list, dict))

    def test_generate_context(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("generate_context", {}, qt, cg)
        assert "document" in result
        assert "myapp" in result["document"]

    def test_generate_context_with_repos(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call(
            "generate_context", {"repos": ["myapp"]}, qt, cg
        )
        assert "document" in result

    def test_unknown_tool(self, server_with_tools):
        server, qt, cg = server_with_tools
        result = server._handle_tool_call("nonexistent_tool", {}, qt, cg)
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_error_handling(self, server_with_tools):
        server, qt, cg = server_with_tools
        # Pass invalid args to trigger an exception
        result = server._handle_tool_call("search_repos", {}, qt, cg)
        assert "error" in result
