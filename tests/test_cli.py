"""Tests for doug.cli module."""

from pathlib import Path

import pytest

from doug.cli import build_parser, main
from doug.config import DougConfig


@pytest.fixture
def base_path(tmp_path):
    """Temp base path for CLI testing."""
    return str(tmp_path / "doug_cli_test")


class TestBuildParser:
    def test_creates_parser(self):
        parser = build_parser()
        assert parser is not None

    def test_version_flag(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_no_command_parses(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_clone_command(self):
        parser = build_parser()
        args = parser.parse_args(["clone", "--force", "-p", "8"])
        assert args.command == "clone"
        assert args.force is True
        assert args.parallel == 8

    def test_index_command(self):
        parser = build_parser()
        args = parser.parse_args(["index", "myrepo"])
        assert args.command == "index"
        assert args.repo_name == "myrepo"

    def test_add_repo_command(self):
        parser = build_parser()
        args = parser.parse_args(["add-repo", "https://github.com/org/repo.git", "-b", "develop"])
        assert args.command == "add-repo"
        assert args.url == "https://github.com/org/repo.git"
        assert args.branch == "develop"

    def test_remove_repo_command(self):
        parser = build_parser()
        args = parser.parse_args(["remove-repo", "myrepo", "--purge"])
        assert args.command == "remove-repo"
        assert args.name == "myrepo"
        assert args.purge is True

    def test_query_search(self):
        parser = build_parser()
        args = parser.parse_args(["query", "search", "users", "-s", "apis"])
        assert args.command == "query"
        assert args.query_command == "search"
        assert args.term == "users"
        assert args.scope == "apis"

    def test_query_apis(self):
        parser = build_parser()
        args = parser.parse_args(["query", "apis", "myrepo"])
        assert args.command == "query"
        assert args.query_command == "apis"
        assert args.repo_name == "myrepo"

    def test_plugin_enable(self):
        parser = build_parser()
        args = parser.parse_args(["plugin", "enable", "jira"])
        assert args.command == "plugin"
        assert args.plugin_command == "enable"
        assert args.plugin_name == "jira"

    def test_clean_command(self):
        parser = build_parser()
        args = parser.parse_args(["clean", "all"])
        assert args.command == "clean"
        assert args.target == "all"

    def test_rag_search_command(self):
        parser = build_parser()
        args = parser.parse_args(["rag", "search", "auth flow", "-k", "20"])
        assert args.command == "rag"
        assert args.rag_command == "search"
        assert args.term == "auth flow"
        assert args.top_k == 20

    def test_context_generate_command(self):
        parser = build_parser()
        args = parser.parse_args(["context", "generate", "-t", "8000"])
        assert args.command == "context"
        assert args.context_command == "generate"
        assert args.max_tokens == 8000

    def test_context_generate_with_repos(self):
        parser = build_parser()
        args = parser.parse_args(["context", "generate", "repo1", "repo2"])
        assert args.repos == ["repo1", "repo2"]

    def test_context_claudemd_command(self):
        parser = build_parser()
        args = parser.parse_args(["context", "claudemd", "myrepo"])
        assert args.command == "context"
        assert args.context_command == "claudemd"
        assert args.repo_name == "myrepo"

    def test_context_claudemd_all(self):
        parser = build_parser()
        args = parser.parse_args(["context", "claudemd"])
        assert args.context_command == "claudemd"
        assert args.repo_name is None

    def test_context_map_command(self):
        parser = build_parser()
        args = parser.parse_args(["context", "map"])
        assert args.command == "context"
        assert args.context_command == "map"

    def test_mcp_serve_command(self):
        parser = build_parser()
        args = parser.parse_args(["mcp", "serve", "-t", "sse", "--port", "8080"])
        assert args.command == "mcp"
        assert args.mcp_command == "serve"
        assert args.transport == "sse"
        assert args.port == 8080

    def test_mcp_serve_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["mcp", "serve"])
        assert args.transport == "stdio"
        assert args.host == "localhost"
        assert args.port == 3333

    def test_mcp_install_command(self):
        parser = build_parser()
        args = parser.parse_args(["mcp", "install"])
        assert args.command == "mcp"
        assert args.mcp_command == "install"


class TestMainFunction:
    def test_no_args_returns_zero(self):
        result = main([])
        assert result == 0

    def test_status_with_base_path(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "status"])
        assert result == 0

    def test_add_repo(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "add-repo", "https://github.com/org/repo.git"])
        assert result == 0

    def test_add_repo_invalid(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "add-repo", "not-a-url"])
        assert result == 1

    def test_remove_repo_not_found(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "remove-repo", "nonexistent"])
        assert result == 1

    def test_clean_cache(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "clean", "cache"])
        assert result == 0

    def test_query_status_empty(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "query", "status"])
        assert result == 0

    def test_query_repos_empty(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "query", "repos"])
        assert result == 0

    def test_query_overview_empty(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "query", "overview"])
        assert result == 0

    def test_plugin_list(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "plugin", "list"])
        assert result == 0

    def test_plugin_enable(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "plugin", "enable", "jira"])
        assert result == 0

    def test_query_no_subcommand(self, base_path):
        """Test that 'doug query' without a subcommand returns 1."""
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "query"])
        assert result == 1

    def test_plugin_no_subcommand(self, base_path):
        """Test that 'doug plugin' without a subcommand returns 1."""
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "plugin"])
        assert result == 1

    def test_rag_no_subcommand(self, base_path):
        """Test that 'doug rag' without a subcommand returns 1."""
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "rag"])
        assert result == 1

    def test_context_no_subcommand(self, base_path):
        """Test that 'doug context' without a subcommand returns 1."""
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "context"])
        assert result == 1

    def test_context_generate_empty(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "context", "generate"])
        assert result == 0

    def test_context_map_empty(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "context", "map"])
        assert result == 0

    def test_context_claudemd_missing_repo(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "context", "claudemd", "nonexistent"])
        assert result == 0  # prints error content but doesn't fail

    def test_mcp_no_subcommand(self, base_path):
        """Test that 'doug mcp' without a subcommand returns 1."""
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "mcp"])
        assert result == 1

    def test_mcp_install(self, base_path):
        config = DougConfig(base_path=Path(base_path))
        config.ensure_directories()

        result = main(["--base-path", base_path, "mcp", "install"])
        assert result == 0
