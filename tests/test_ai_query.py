"""Tests for doug.ai_query module."""

import json

import pytest

from doug.ai_query import AIQueryTool
from doug.config import DougConfig


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
            {"method": "GET", "path": "/api/orders", "file": "src/OrderController.java"},
        ],
        "services": [
            {"path": "src/UserService.java", "name": "UserService.java", "class": "UserService", "type": "service"},
            {"path": "src/OrderService.java", "name": "OrderService.java", "class": "OrderService", "type": "service"},
        ],
        "models": [
            {"path": "src/User.java", "name": "User.java", "class": "User", "type": "model"},
        ],
        "controllers": [
            {"path": "src/UserController.java", "name": "UserController.java", "class": "UserController", "type": "controller"},
        ],
        "configs": [
            {"path": "application.yml", "name": "application.yml"},
        ],
        "build": {"type": "gradle", "dependencies": []},
        "readme": "# MyApp\nThis is a sample application for testing purposes.",
    }

    cache_file = config.repo_cache_dir / "myapp.json"
    cache_file.write_text(json.dumps(repo_data, indent=2))

    global_index = {
        "total_repos": 1,
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "total_files": 50,
        "total_source_files": 30,
        "total_apis": 8,
        "repos": {
            "myapp": {
                "files": 50,
                "source_files": 30,
                "apis": 8,
                "controllers": 3,
                "services": 5,
                "build_type": "gradle",
            }
        },
    }
    (config.index_cache_dir / "global_index.json").write_text(json.dumps(global_index))

    apis_index = {
        "total_apis": 3,
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "endpoints": [
            {"method": "GET", "path": "/api/users", "file": "src/UserController.java", "repo": "myapp"},
            {"method": "POST", "path": "/api/users", "file": "src/UserController.java", "repo": "myapp"},
            {"method": "GET", "path": "/api/orders", "file": "src/OrderController.java", "repo": "myapp"},
        ],
    }
    (config.index_cache_dir / "apis.json").write_text(json.dumps(apis_index))

    return config


@pytest.fixture
def query_tool(sample_cache):
    """AIQueryTool with sample data."""
    return AIQueryTool(config=sample_cache)


class TestAIQueryTool:
    def test_status(self, query_tool):
        result = query_tool.status()
        assert result["cached_repos"] == 1
        assert "myapp" in result["repos"]
        assert result["total_files"] == 50
        assert result["total_apis"] == 8

    def test_list_repos(self, query_tool):
        repos = query_tool.list_repos()
        assert repos == ["myapp"]

    def test_repo_summary(self, query_tool):
        result = query_tool.repo_summary("myapp")
        assert result["name"] == "myapp"
        assert result["summary"]["total_files"] == 50
        assert result["build"]["type"] == "gradle"
        assert "readme" in result

    def test_repo_summary_not_found(self, query_tool):
        result = query_tool.repo_summary("nonexistent")
        assert "error" in result

    def test_repo_detail(self, query_tool):
        result = query_tool.repo_detail("myapp", "apis")
        assert result["repo"] == "myapp"
        assert result["section"] == "apis"
        assert len(result["data"]) == 3

    def test_repo_detail_invalid_section(self, query_tool):
        result = query_tool.repo_detail("myapp", "invalid")
        assert "error" in result
        assert "valid_sections" in result

    def test_list_apis_all(self, query_tool):
        apis = query_tool.list_apis()
        assert len(apis) == 3
        methods = {a["method"] for a in apis}
        assert "GET" in methods
        assert "POST" in methods

    def test_list_apis_by_repo(self, query_tool):
        apis = query_tool.list_apis(repo_name="myapp")
        assert len(apis) == 3

    def test_list_apis_empty_repo(self, query_tool):
        apis = query_tool.list_apis(repo_name="nonexistent")
        assert apis == []

    def test_search_files(self, query_tool):
        result = query_tool.search("User")
        assert result["total_matches"] > 0
        assert "results" in result

    def test_search_apis(self, query_tool):
        result = query_tool.search("users", scope="apis")
        assert any(
            item["path"] == "/api/users"
            for item in result.get("results", {}).get("apis", [])
        )

    def test_search_no_results(self, query_tool):
        result = query_tool.search("zzzznonexistent")
        assert result["total_matches"] == 0

    def test_search_classes(self, query_tool):
        result = query_tool.search("OrderService", scope="all")
        assert result["total_matches"] > 0

    def test_search_readme(self, query_tool):
        result = query_tool.search("sample application")
        assert any("readme_mentions" in k for k in result.get("results", {}))

    def test_search_max_results(self, query_tool):
        result = query_tool.search("User", max_results=1)
        # Should respect the limit
        total = result["total_matches"]
        assert total <= 4  # limited per category

    def test_find_file(self, query_tool):
        result = query_tool.find_file("myapp", "UserService")
        assert result["total"] >= 1
        assert result["matches"][0]["path"] == "src/UserService.java"

    def test_find_file_not_found_repo(self, query_tool):
        result = query_tool.find_file("nonexistent", "User")
        assert "error" in result

    def test_quick_overview(self, query_tool):
        overview = query_tool.quick_overview()
        assert "Doug Repository Overview" in overview
        assert "myapp" in overview

    def test_quick_overview_empty(self, config):
        tool = AIQueryTool(config=config)
        idx = config.index_cache_dir / "global_index.json"
        if idx.exists():
            idx.unlink()
        overview = tool.quick_overview()
        assert "No repositories indexed" in overview

    def test_status_empty(self, config):
        tool = AIQueryTool(config=config)
        for f in config.repo_cache_dir.glob("*.json"):
            f.unlink()
        for f in config.index_cache_dir.glob("*.json"):
            f.unlink()

        result = tool.status()
        assert result["cached_repos"] == 0
