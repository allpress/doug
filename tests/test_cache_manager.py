"""Tests for doug.cache_manager module."""

from unittest.mock import MagicMock, patch

import pytest

from doug.cache_manager import CacheManager, _extract_repo_name, _run_git
from doug.config import DougConfig


class TestExtractRepoName:
    def test_https_url(self):
        assert _extract_repo_name("https://github.com/org/myrepo.git") == "myrepo"

    def test_https_url_no_git_suffix(self):
        assert _extract_repo_name("https://github.com/org/myrepo") == "myrepo"

    def test_ssh_url(self):
        assert _extract_repo_name("git@github.com:org/myrepo.git") == "myrepo"

    def test_ssh_url_no_git_suffix(self):
        assert _extract_repo_name("git@github.com:org/myrepo") == "myrepo"

    def test_trailing_slash(self):
        assert _extract_repo_name("https://github.com/org/myrepo/") == "myrepo"

    def test_whitespace(self):
        assert _extract_repo_name("  https://github.com/org/myrepo.git  ") == "myrepo"

    def test_deep_path(self):
        assert _extract_repo_name("https://gitlab.com/group/subgroup/repo.git") == "repo"


@pytest.fixture
def config(tmp_path):
    """Config with temp base path."""
    return DougConfig(base_path=tmp_path / "doug_test")


@pytest.fixture
def manager(config):
    """CacheManager with temp config."""
    config.ensure_directories()
    return CacheManager(config=config)


class TestCacheManager:
    def test_get_repo_path(self, manager):
        path = manager.get_repo_path("https://github.com/org/myrepo.git")
        assert path.name == "myrepo"
        assert path.parent == manager.repos_dir

    def test_load_empty_repos(self, manager):
        repos = manager.load_repository_configs()
        assert repos == []

    def test_load_repos_from_file(self, manager):
        repos_file = manager.config.repos_config_dir / "repos.txt"
        repos_file.write_text(
            "# Comment line\n"
            "https://github.com/org/repo1.git\n"
            "https://github.com/org/repo2.git,develop\n"
            "\n"
            "https://github.com/org/repo3.git  # inline comment\n"
        )

        repos = manager.load_repository_configs()
        assert len(repos) == 3
        assert repos[0] == {"url": "https://github.com/org/repo1.git", "branch": None}
        assert repos[1] == {"url": "https://github.com/org/repo2.git", "branch": "develop"}
        assert repos[2]["url"] == "https://github.com/org/repo3.git"

    def test_load_repos_deduplicates(self, manager):
        repos_file = manager.config.repos_config_dir / "repos.txt"
        repos_file.write_text(
            "https://github.com/org/repo1.git\n"
            "https://github.com/org/repo1.git\n"
        )

        repos = manager.load_repository_configs()
        assert len(repos) == 1

    def test_add_repo(self, manager):
        success, msg = manager.add_repo("https://github.com/org/newrepo.git")
        assert success is True
        assert "Added" in msg

        repos = manager.load_repository_configs()
        assert len(repos) == 1
        assert repos[0]["url"] == "https://github.com/org/newrepo.git"

    def test_add_repo_with_branch(self, manager):
        success, _ = manager.add_repo("https://github.com/org/newrepo.git", branch="develop")
        assert success is True

        repos = manager.load_repository_configs()
        assert repos[0]["branch"] == "develop"

    def test_add_repo_invalid_url(self, manager):
        success, msg = manager.add_repo("not-a-url")
        assert success is False
        assert "Invalid" in msg

    def test_add_repo_duplicate(self, manager):
        manager.add_repo("https://github.com/org/repo.git")
        success, msg = manager.add_repo("https://github.com/org/repo.git")
        assert success is False
        assert "already configured" in msg

    def test_remove_repo(self, manager):
        manager.add_repo("https://github.com/org/repo.git")
        success, msg = manager.remove_repo("repo")
        assert success is True
        assert "Removed" in msg

        repos = manager.load_repository_configs()
        assert len(repos) == 0

    def test_remove_repo_by_url(self, manager):
        manager.add_repo("https://github.com/org/repo.git")
        success, _ = manager.remove_repo("https://github.com/org/repo.git")
        assert success is True

    def test_remove_repo_not_found(self, manager):
        success, msg = manager.remove_repo("nonexistent")
        assert success is False

    def test_get_cloned_repos_empty(self, manager):
        assert manager.get_cloned_repos() == []

    def test_get_cloned_repos_finds_git_dirs(self, manager):
        repo = manager.repos_dir / "fakerepo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()

        repos = manager.get_cloned_repos()
        assert len(repos) == 1
        assert repos[0].name == "fakerepo"

    def test_get_cache_status(self, manager):
        status = manager.get_cache_status()
        assert "configured_repos" in status
        assert "cloned_repos" in status
        assert status["configured_repos"] == 0
        assert status["cloned_repos"] == 0

    @patch("doug.cache_manager._run_git")
    def test_clone_repo_success(self, mock_git, manager):
        mock_git.return_value = MagicMock(returncode=0, stderr="", stdout="")
        success, msg = manager.clone_repo("https://github.com/org/repo.git")
        assert success is True
        assert "Cloned" in msg

    @patch("doug.cache_manager._run_git")
    def test_clone_repo_failure(self, mock_git, manager):
        mock_git.return_value = MagicMock(returncode=1, stderr="auth failed", stdout="")
        success, msg = manager.clone_repo("https://github.com/org/repo.git")
        assert success is False
        assert "failed" in msg.lower()

    def test_clone_repo_already_exists(self, manager):
        repo_path = manager.get_repo_path("https://github.com/org/repo.git")
        repo_path.mkdir(parents=True)

        success, msg = manager.clone_repo("https://github.com/org/repo.git")
        assert success is True
        assert "Already" in msg

    @patch("doug.cache_manager._run_git")
    def test_pull_repo_not_cloned(self, mock_git, manager):
        success, msg = manager.pull_repo("https://github.com/org/repo.git")
        assert success is False
        assert "Not cloned" in msg

    @patch("doug.cache_manager._run_git")
    def test_get_repo_info(self, mock_git, manager):
        repo = manager.repos_dir / "testrepo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()

        mock_git.return_value = MagicMock(
            returncode=0,
            stdout="main",
        )

        info = manager.get_repo_info(repo)
        assert info["name"] == "testrepo"
        assert "path" in info
