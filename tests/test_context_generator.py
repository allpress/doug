"""Tests for doug.context_generator module."""

import json

import pytest

from doug.config import DougConfig
from doug.context_generator import ContextGenerator


@pytest.fixture
def config(tmp_path):
    """Config with temp base path."""
    config = DougConfig(base_path=tmp_path / "doug")
    config.ensure_directories()
    return config


@pytest.fixture
def sample_cache(config):
    """Create sample cache data matching test_ai_query pattern."""
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
        "structure": {
            "dirs": {
                "src": {
                    "dirs": {
                        "controllers": {"dirs": {}, "files": ["UserController.java"]},
                        "services": {"dirs": {}, "files": ["UserService.java"]},
                        "models": {"dirs": {}, "files": ["User.java"]},
                    },
                    "files": [],
                },
                "config": {"dirs": {}, "files": ["application.yml"]},
            },
            "files": ["README.md", "build.gradle"],
        },
        "apis": [
            {"method": "GET", "path": "/api/users", "file": "src/UserController.java"},
            {"method": "POST", "path": "/api/users", "file": "src/UserController.java"},
            {"method": "GET", "path": "/api/orders", "file": "src/OrderController.java"},
        ],
        "services": [
            {
                "path": "src/UserService.java", "name": "UserService.java",
                "class": "UserService", "type": "service",
            },
            {
                "path": "src/OrderService.java", "name": "OrderService.java",
                "class": "OrderService", "type": "service",
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
            {"path": ".eslintrc.json", "name": ".eslintrc.json"},
        ],
        "build": {
            "type": "gradle",
            "dependencies": [
                {"name": "org.springframework:spring-core", "scope": "compile"},
                {"name": "junit:junit", "scope": "test"},
            ],
        },
        "readme": "# MyApp\n\nThis is a sample application for testing purposes.\n\nIt does many things.",
    }

    cache_file = config.repo_cache_dir / "myapp.json"
    cache_file.write_text(json.dumps(repo_data, indent=2))

    global_index = {
        "total_repos": 1,
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "total_files": 50,
        "total_source_files": 30,
        "total_apis": 3,
        "repos": {
            "myapp": {
                "files": 50,
                "source_files": 30,
                "apis": 3,
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
def generator(sample_cache):
    return ContextGenerator(config=sample_cache)


class TestEstimateTokens:
    def test_basic(self):
        assert ContextGenerator.estimate_tokens("hello world!") == 3  # 12 // 4

    def test_empty(self):
        assert ContextGenerator.estimate_tokens("") == 0

    def test_long_text(self):
        text = "a" * 400
        assert ContextGenerator.estimate_tokens(text) == 100


class TestGenerateContextDocument:
    def test_generates_markdown(self, generator):
        doc = generator.generate_context_document()
        assert "# Project Context" in doc
        assert "myapp" in doc

    def test_includes_header_stats(self, generator):
        doc = generator.generate_context_document()
        assert "Repositories: 1" in doc
        assert "Source Files:" in doc
        assert "API Endpoints:" in doc

    def test_includes_apis(self, generator):
        doc = generator.generate_context_document()
        assert "/api/users" in doc
        assert "GET" in doc

    def test_includes_services(self, generator):
        doc = generator.generate_context_document()
        assert "UserService" in doc

    def test_includes_api_map(self, generator):
        doc = generator.generate_context_document()
        assert "Cross-Repository API Map" in doc

    def test_respects_max_tokens(self, generator):
        doc_full = generator.generate_context_document()
        doc_short = generator.generate_context_document(max_tokens=50)
        assert len(doc_short) < len(doc_full)

    def test_filters_repos(self, generator):
        doc = generator.generate_context_document(repos=["myapp"])
        assert "myapp" in doc

    def test_nonexistent_repo_filter(self, generator):
        doc = generator.generate_context_document(repos=["nonexistent"])
        # Should produce a document but without repo sections
        assert "# Project Context" in doc

    def test_empty_cache(self, config):
        gen = ContextGenerator(config=config)
        doc = gen.generate_context_document()
        assert "No repositories indexed" in doc


class TestGenerateClaudeMd:
    def test_generates_claude_md(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "# CLAUDE.md" in content
        assert "Auto-generated by Doug" in content

    def test_includes_project_overview(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "## Project Overview" in content
        assert "sample application" in content

    def test_includes_build_commands(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "## Build & Run" in content
        assert "./gradlew" in content

    def test_includes_architecture(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "## Architecture" in content
        assert "gradle" in content

    def test_includes_key_directories(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "Key Directories" in content
        assert "src/" in content

    def test_includes_controllers(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "UserController" in content

    def test_includes_services(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "UserService" in content

    def test_includes_api_table(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "## API Endpoints" in content
        assert "| Method" in content
        assert "/api/users" in content

    def test_includes_configs(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "## Configuration Files" in content
        assert "application.yml" in content

    def test_includes_conventions(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "## Coding Conventions" in content
        assert "gradle" in content

    def test_detects_language(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "Java" in content

    def test_detects_naming_style(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "PascalCase" in content

    def test_detects_test_framework(self, generator):
        content = generator.generate_claude_md("myapp")
        assert "JUnit" in content

    def test_detects_linter(self, generator):
        content = generator.generate_claude_md("myapp")
        assert ".eslintrc.json" in content

    def test_missing_repo(self, generator):
        content = generator.generate_claude_md("nonexistent")
        assert "not found" in content.lower()


class TestGenerateArchitectureMap:
    def test_generates_map(self, generator):
        map_doc = generator.generate_architecture_map()
        assert "# Architecture Map" in map_doc

    def test_includes_topology(self, generator):
        map_doc = generator.generate_architecture_map()
        assert "Service Topology" in map_doc
        assert "myapp" in map_doc
        assert "gradle" in map_doc

    def test_includes_api_domains(self, generator):
        map_doc = generator.generate_architecture_map()
        assert "API Domain Map" in map_doc
        assert "/api/" in map_doc

    def test_filters_repos(self, generator):
        map_doc = generator.generate_architecture_map(repos=["myapp"])
        assert "myapp" in map_doc

    def test_empty_cache(self, config):
        gen = ContextGenerator(config=config)
        map_doc = gen.generate_architecture_map()
        assert "No repositories indexed" in map_doc


class TestInferConventions:
    def test_infers_language(self, generator):
        data = generator.query_tool._load_repo_cache("myapp")
        conventions = generator._infer_conventions(data)
        assert conventions["primary_language"] == "Java"

    def test_infers_naming(self, generator):
        data = generator.query_tool._load_repo_cache("myapp")
        conventions = generator._infer_conventions(data)
        assert "PascalCase" in conventions.get("naming_style", "")

    def test_infers_test_framework(self, generator):
        data = generator.query_tool._load_repo_cache("myapp")
        conventions = generator._infer_conventions(data)
        assert conventions["test_framework"] == "JUnit"

    def test_infers_linters(self, generator):
        data = generator.query_tool._load_repo_cache("myapp")
        conventions = generator._infer_conventions(data)
        assert ".eslintrc.json" in conventions.get("linters", [])

    def test_fallback_language_from_build(self):
        conventions = ContextGenerator._infer_conventions(
            ContextGenerator.__new__(ContextGenerator),
            {"build": {"type": "pip", "dependencies": []},
             "services": [], "models": [], "controllers": [], "configs": []},
        )
        assert conventions["primary_language"] == "Python"


class TestHelpers:
    def test_extract_first_paragraph(self):
        readme = "# Title\n\nThis is the first paragraph.\n\nSecond paragraph."
        result = ContextGenerator._extract_first_paragraph(readme)
        assert result == "This is the first paragraph."

    def test_extract_first_paragraph_with_badges(self):
        readme = "# Title\n![badge](url)\n\nActual content here."
        result = ContextGenerator._extract_first_paragraph(readme)
        assert result == "Actual content here."

    def test_extract_first_paragraph_truncates(self):
        readme = "# Title\n\n" + "x" * 600
        result = ContextGenerator._extract_first_paragraph(readme)
        assert len(result) <= 504  # 500 + "..."

    def test_extract_first_paragraph_empty(self):
        result = ContextGenerator._extract_first_paragraph("")
        assert result == "No description available."

    def test_extract_top_dirs(self):
        structure = {
            "dirs": {
                "src": {"dirs": {"main": {"dirs": {}, "files": []}}, "files": []},
                "tests": {"dirs": {}, "files": []},
            },
            "files": ["README.md"],
        }
        dirs = ContextGenerator._extract_top_dirs(structure, max_depth=2)
        assert "src/" in dirs
        assert "tests/" in dirs
        assert any("main/" in d for d in dirs)
