"""
AI query interface for Doug.

Provides a lightweight, token-efficient query interface for AI coding
assistants to search and navigate indexed repositories.

I'm like a search engine, except I actually find what you're looking for
on the first try. Most of the time. Okay, a lot of the time.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from doug.config import DougConfig

logger = logging.getLogger(__name__)

# Default max results to avoid blowing up AI context windows
DEFAULT_MAX_RESULTS = 50


class AIQueryTool:
    """Query interface for AI assistants.

    Provides fast, token-efficient access to cached repository data.
    All methods return structured dicts suitable for JSON serialization.
    """

    def __init__(self, config: Optional[DougConfig] = None):
        self.config = config or DougConfig()
        self.cache_dir = self.config.repo_cache_dir
        self.index_dir = self.config.index_cache_dir
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _load_repo_cache(self, repo_name: str) -> Optional[Dict[str, Any]]:
        if repo_name in self._cache:
            return self._cache[repo_name]

        cache_file = self.cache_dir / f"{repo_name}.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = json.load(f)
            self._cache[repo_name] = data
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load cache for %s: %s", repo_name, e)
            return None

    def _load_global_index(self) -> Optional[Dict[str, Any]]:
        index_file = self.index_dir / "global_index.json"
        if not index_file.exists():
            return None

        try:
            with open(index_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load global index: %s", e)
            return None

    def _load_apis_index(self) -> Optional[Dict[str, Any]]:
        apis_file = self.index_dir / "apis.json"
        if not apis_file.exists():
            return None

        try:
            with open(apis_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load APIs index: %s", e)
            return None

    def status(self) -> Dict[str, Any]:
        global_index = self._load_global_index()

        cached_repos = []
        if self.cache_dir.exists():
            cached_repos = sorted(f.stem for f in self.cache_dir.glob("*.json"))

        result: Dict[str, Any] = {
            "cached_repos": len(cached_repos),
            "repos": cached_repos,
            "cache_dir": str(self.cache_dir),
            "index_dir": str(self.index_dir),
        }

        if global_index:
            result["indexed_at"] = global_index.get("indexed_at")
            result["total_files"] = global_index.get("total_files", 0)
            result["total_source_files"] = global_index.get("total_source_files", 0)
            result["total_apis"] = global_index.get("total_apis", 0)

        return result

    def list_repos(self) -> List[str]:
        if not self.cache_dir.exists():
            return []
        return sorted(f.stem for f in self.cache_dir.glob("*.json"))

    def repo_summary(self, repo_name: str) -> Dict[str, Any]:
        data = self._load_repo_cache(repo_name)
        if not data:
            return {"error": f"Repository not found: {repo_name}"}

        return {
            "name": data["name"],
            "indexed_at": data["indexed_at"],
            "summary": data["summary"],
            "build": data["build"],
            "readme": data.get("readme"),
            "api_count": len(data.get("apis", [])),
        }

    def repo_detail(self, repo_name: str, section: str) -> Dict[str, Any]:
        data = self._load_repo_cache(repo_name)
        if not data:
            return {"error": f"Repository not found: {repo_name}"}

        valid_sections = {
            "apis", "services", "models", "controllers", "configs",
            "structure", "build", "summary", "readme",
        }

        if section not in valid_sections:
            return {
                "error": f"Invalid section: {section}",
                "valid_sections": sorted(valid_sections),
            }

        return {
            "repo": repo_name,
            "section": section,
            "data": data.get(section, {}),
        }

    def list_apis(self, repo_name: Optional[str] = None) -> List[Dict[str, str]]:
        if repo_name:
            data = self._load_repo_cache(repo_name)
            if not data:
                return []
            return data.get("apis", [])

        apis_index = self._load_apis_index()
        if apis_index:
            return apis_index.get("endpoints", [])

        all_apis: List[Dict[str, str]] = []
        for name in self.list_repos():
            data = self._load_repo_cache(name)
            if data:
                for endpoint in data.get("apis", []):
                    api = dict(endpoint)
                    api["repo"] = name
                    all_apis.append(api)

        return all_apis

    def search(
        self,
        query: str,
        scope: str = "all",
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> Dict[str, Any]:
        """Search across all cached repositories.

        Args:
            query: Search term.
            scope: Search scope - 'all', 'files', 'apis', 'classes'.
            max_results: Maximum results per category (default 50).

        Returns:
            Search results dict with matches grouped by category.
        """
        query_lower = query.lower()
        results: Dict[str, List[Dict[str, Any]]] = {
            "files": [],
            "apis": [],
            "classes": [],
            "readme_mentions": [],
        }

        for repo_name in self.list_repos():
            data = self._load_repo_cache(repo_name)
            if not data:
                continue

            if scope in ("all", "files"):
                for section in ("services", "models", "controllers", "configs"):
                    for item in data.get(section, []):
                        if len(results["files"]) >= max_results:
                            break
                        if query_lower in item.get("path", "").lower():
                            results["files"].append({
                                "repo": repo_name,
                                "path": item["path"],
                                "name": item.get("name"),
                                "type": item.get("type"),
                            })
                        elif query_lower in item.get("class", "").lower():
                            if len(results["classes"]) < max_results:
                                results["classes"].append({
                                    "repo": repo_name,
                                    "path": item["path"],
                                    "class": item["class"],
                                    "type": item.get("type"),
                                })

            if scope in ("all", "apis"):
                for api in data.get("apis", []):
                    if len(results["apis"]) >= max_results:
                        break
                    if query_lower in api.get("path", "").lower():
                        results["apis"].append({
                            "repo": repo_name,
                            "method": api["method"],
                            "path": api["path"],
                            "file": api["file"],
                        })

            if scope in ("all",):
                readme = data.get("readme", "")
                if readme and query_lower in readme.lower():
                    results["readme_mentions"].append({
                        "repo": repo_name,
                        "excerpt": self._extract_context(readme, query, max_chars=200),
                    })

        results = {k: v for k, v in results.items() if v}

        total = sum(len(v) for v in results.values())
        return {
            "query": query,
            "scope": scope,
            "total_matches": total,
            "results": results,
            **({"truncated": True} if total >= max_results else {}),
        }

    def find_file(self, repo_name: str, file_pattern: str) -> Dict[str, Any]:
        data = self._load_repo_cache(repo_name)
        if not data:
            return {"error": f"Repository not found: {repo_name}"}

        pattern_lower = file_pattern.lower()
        matches: List[Dict[str, Any]] = []

        for section in ("services", "models", "controllers", "configs"):
            for item in data.get(section, []):
                if pattern_lower in item.get("path", "").lower():
                    matches.append({
                        "path": item["path"],
                        "name": item.get("name"),
                        "type": item.get("type"),
                        "section": section,
                    })

        return {
            "repo": repo_name,
            "pattern": file_pattern,
            "matches": matches,
            "total": len(matches),
        }

    def quick_overview(self) -> str:
        """Generate a text overview of all cached repositories."""
        global_index = self._load_global_index()
        if not global_index:
            return "No repositories indexed. Run 'doug index' first."

        lines = [
            "=== Doug Repository Overview ===",
            f"Total Repositories: {global_index['total_repos']}",
            f"Total Files: {global_index.get('total_files', 'N/A')}",
            f"Total Source Files: {global_index.get('total_source_files', 'N/A')}",
            f"Total API Endpoints: {global_index.get('total_apis', 'N/A')}",
            f"Last Indexed: {global_index.get('indexed_at', 'Unknown')}",
            "",
            "--- Repositories ---",
        ]

        for name, info in sorted(global_index.get("repos", {}).items()):
            lines.append(
                f"  {name}: {info.get('source_files', '?')} source files, "
                f"{info.get('apis', 0)} APIs ({info.get('build_type', 'unknown')})"
            )

        return "\n".join(lines)

    @staticmethod
    def _extract_context(text: str, query: str, max_chars: int = 200) -> str:
        idx = text.lower().find(query.lower())
        if idx == -1:
            return text[:max_chars]

        start = max(0, idx - max_chars // 2)
        end = min(len(text), idx + len(query) + max_chars // 2)

        excerpt = text[start:end]
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(text):
            excerpt = excerpt + "..."

        return excerpt
