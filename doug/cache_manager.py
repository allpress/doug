"""
Repository cache manager for Doug.

Handles cloning, pulling, and managing multiple Git repositories
with support for parallel operations and branch overrides.

I fetch your repos so you don't have to remember which branch
you were supposed to be on. Spoiler: it was always main.
"""

import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from doug.config import DougConfig

logger = logging.getLogger(__name__)

# Regex for sanitizing repo names — only allow safe filesystem chars
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_\-.]")


def _extract_repo_name(url: str) -> str:
    """Extract repository name from a Git URL.

    Handles both HTTPS and SSH URLs:
        https://github.com/org/repo.git -> repo
        git@github.com:org/repo.git -> repo

    Returns a sanitized name safe for use as a directory name.
    """
    url = url.strip().rstrip("/")

    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]

    # Handle SSH URLs (git@github.com:org/repo)
    if url.startswith("git@"):
        name = url.split("/")[-1].split(":")[-1]
    else:
        # Handle HTTPS URLs
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        name = path.split("/")[-1] if "/" in path else path

    # Sanitize: strip path separators and restrict to safe chars
    name = _SAFE_NAME_RE.sub("", name)
    return name or "unknown-repo"


def _run_git(args: List[str], cwd: Optional[Path] = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a git command cross-platform.

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory.
        timeout: Command timeout in seconds.

    Returns:
        CompletedProcess result.
    """
    cmd = ["git"] + args
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)

    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class CacheManager:
    """Manages cloning and updating of Git repositories.

    Supports parallel operations, branch overrides, and provides
    status reporting for all managed repositories.
    """

    def __init__(self, config: Optional[DougConfig] = None):
        self.config = config or DougConfig()
        self.repos_dir = self.config.repos_dir

    def load_repository_configs(self) -> List[Dict[str, Optional[str]]]:
        """Load repository URLs from all configuration files."""
        repos: List[Dict[str, Optional[str]]] = []
        seen_urls: set = set()

        for repo_file in self.config.get_repository_files():
            try:
                with open(repo_file) as f:
                    for line in f:
                        line = line.strip()

                        if not line or line.startswith("#"):
                            continue

                        if "#" in line:
                            line = line[: line.index("#")].strip()

                        url = line
                        branch = None
                        if "," in line:
                            parts = line.rsplit(",", 1)
                            url = parts[0].strip()
                            branch = parts[1].strip() if len(parts) > 1 else None

                        if url not in seen_urls:
                            seen_urls.add(url)
                            repos.append({"url": url, "branch": branch})

            except OSError as e:
                logger.error("Failed to read repository file %s: %s", repo_file, e)

        return repos

    def get_repo_path(self, url: str) -> Path:
        name = _extract_repo_name(url)
        return self.repos_dir / name

    def clone_repo(
        self, url: str, branch: Optional[str] = None, force: bool = False
    ) -> Tuple[bool, str]:
        repo_path = self.get_repo_path(url)
        repo_name = _extract_repo_name(url)

        # Validate the resolved path is within repos_dir (prevent path traversal)
        try:
            repo_path.resolve().relative_to(self.repos_dir.resolve())
        except ValueError:
            return False, f"{repo_name}: Path traversal detected, skipping"

        if repo_path.exists():
            if force:
                import shutil
                shutil.rmtree(repo_path)
                logger.info("Removed existing clone: %s", repo_path)
            else:
                return True, f"{repo_name}: Already cloned"

        repo_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            args = ["clone", "--no-recurse-submodules", url, str(repo_path)]
            result = _run_git(args, timeout=600)

            if result.returncode != 0:
                return False, f"{repo_name}: Clone failed - {result.stderr.strip()}"

            if branch:
                checkout_result = _run_git(["checkout", branch], cwd=repo_path)
                if checkout_result.returncode != 0:
                    return False, (
                        f"{repo_name}: Cloned but branch checkout failed "
                        f"- {checkout_result.stderr.strip()}"
                    )

            return True, f"{repo_name}: Cloned successfully"

        except subprocess.TimeoutExpired:
            return False, f"{repo_name}: Clone timed out"
        except Exception as e:
            return False, f"{repo_name}: Clone error - {e}"

    def pull_repo(
        self, url: str, branch_override: Optional[str] = None
    ) -> Tuple[bool, str]:
        repo_path = self.get_repo_path(url)
        repo_name = _extract_repo_name(url)

        if not repo_path.exists():
            return False, f"{repo_name}: Not cloned yet"

        try:
            if branch_override:
                checkout_result = _run_git(["checkout", branch_override], cwd=repo_path)
                if checkout_result.returncode != 0:
                    return False, (
                        f"{repo_name}: Branch checkout failed "
                        f"- {checkout_result.stderr.strip()}"
                    )

            result = _run_git(["pull", "--ff-only"], cwd=repo_path, timeout=300)

            if result.returncode != 0:
                # Fallback to rebase instead of merge (cleaner history)
                logger.warning("%s: ff-only failed, trying --rebase", repo_name)
                result = _run_git(["pull", "--rebase"], cwd=repo_path, timeout=300)
                if result.returncode != 0:
                    return False, f"{repo_name}: Pull failed - {result.stderr.strip()}"

            return True, f"{repo_name}: Updated"

        except subprocess.TimeoutExpired:
            return False, f"{repo_name}: Pull timed out"
        except Exception as e:
            return False, f"{repo_name}: Pull error - {e}"

    def clone_all(
        self, force: bool = False, parallel: Optional[int] = None
    ) -> Dict[str, List[str]]:
        workers = parallel or self.config.parallel_workers
        repos = self.load_repository_configs()
        results: Dict[str, List[str]] = {"success": [], "failed": []}

        if not repos:
            logger.warning("No repositories configured")
            return results

        self.repos_dir.mkdir(parents=True, exist_ok=True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self.clone_repo, repo["url"], repo.get("branch"), force
                ): repo
                for repo in repos
            }

            for future in as_completed(futures):
                repo = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        results["success"].append(message)
                    else:
                        results["failed"].append(message)
                except Exception as e:
                    repo_name = _extract_repo_name(repo["url"])
                    results["failed"].append(f"{repo_name}: {e}")

        return results

    def pull_all(self, parallel: Optional[int] = None) -> Dict[str, List[str]]:
        workers = parallel or self.config.parallel_workers
        repos = self.load_repository_configs()
        results: Dict[str, List[str]] = {"success": [], "failed": []}

        if not repos:
            logger.warning("No repositories configured")
            return results

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.pull_repo, repo["url"], repo.get("branch")): repo
                for repo in repos
            }

            for future in as_completed(futures):
                repo = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        results["success"].append(message)
                    else:
                        results["failed"].append(message)
                except Exception as e:
                    repo_name = _extract_repo_name(repo["url"])
                    results["failed"].append(f"{repo_name}: {e}")

        return results

    def add_repo(self, url: str, branch: Optional[str] = None) -> Tuple[bool, str]:
        if not (
            url.startswith("http://")
            or url.startswith("https://")
            or url.startswith("git@")
        ):
            return False, "Invalid URL. Must start with http://, https://, or git@"

        repos_file = self.config.repos_config_dir / "repos.txt"
        repos_file.parent.mkdir(parents=True, exist_ok=True)

        existing = set()
        if repos_file.exists():
            with open(repos_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        existing.add(line.split(",")[0].strip())

        if url in existing:
            return False, f"Repository already configured: {url}"

        entry = f"{url},{branch}" if branch else url
        with open(repos_file, "a") as f:
            f.write(f"\n{entry}\n")

        return True, f"Added: {url}"

    def remove_repo(self, name_or_url: str) -> Tuple[bool, str]:
        repos_file = self.config.repos_config_dir / "repos.txt"
        if not repos_file.exists():
            return False, "No repository configuration file found"

        with open(repos_file) as f:
            lines = f.readlines()

        new_lines = []
        removed = False
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                url_part = stripped.split(",")[0].strip()
                repo_name = _extract_repo_name(url_part)
                if repo_name == name_or_url or url_part == name_or_url:
                    removed = True
                    continue
            new_lines.append(line)

        if not removed:
            return False, f"Repository not found: {name_or_url}"

        with open(repos_file, "w") as f:
            f.writelines(new_lines)

        return True, f"Removed: {name_or_url}"

    def get_cloned_repos(self) -> List[Path]:
        if not self.repos_dir.exists():
            return []

        return sorted(
            p for p in self.repos_dir.iterdir()
            if p.is_dir() and (p / ".git").exists()
        )

    def get_repo_info(self, repo_path: Path) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "name": repo_path.name,
            "path": str(repo_path),
        }

        try:
            result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
            if result.returncode == 0:
                info["branch"] = result.stdout.strip()

            result = _run_git(
                ["log", "-1", "--format=%H|%s|%aI"],
                cwd=repo_path,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split("|", 2)
                if len(parts) >= 3:
                    info["last_commit"] = {
                        "hash": parts[0][:12],
                        "message": parts[1],
                        "date": parts[2],
                    }

            result = _run_git(["remote", "get-url", "origin"], cwd=repo_path)
            if result.returncode == 0:
                info["remote_url"] = result.stdout.strip()

        except Exception as e:
            info["error"] = str(e)

        return info

    def get_cache_status(self) -> Dict[str, Any]:
        cloned = self.get_cloned_repos()
        configured = self.load_repository_configs()

        status: Dict[str, Any] = {
            "configured_repos": len(configured),
            "cloned_repos": len(cloned),
            "repos_dir": str(self.repos_dir),
            "repos_dir_exists": self.repos_dir.exists(),
            "repositories": [],
        }

        for repo_path in cloned:
            status["repositories"].append(self.get_repo_info(repo_path))

        return status
