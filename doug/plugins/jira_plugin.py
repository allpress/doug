"""
JIRA integration plugin for Doug.

Provides JIRA issue tracking integration via REST API or browser
automation for SSO-based instances.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from doug.config import DougConfig
from doug.plugins.playwright_base import PlaywrightPlugin

logger = logging.getLogger(__name__)


class JiraPlugin(PlaywrightPlugin):
    """JIRA integration plugin.

    Supports:
    - Fetching individual issues
    - Searching with JQL
    - Caching project issues
    - Adding comments
    - Both API token and SSO authentication
    """

    def __init__(self, config: Optional[DougConfig] = None):
        """Initialize the JIRA plugin."""
        super().__init__(
            name="jira",
            description="JIRA issue tracking integration",
            config=config,
        )

    def setup(self) -> bool:
        """Interactive JIRA setup."""
        print()
        print("🎫 JIRA Plugin Setup")
        print("=" * 50)

        try:
            jira_url = input(
                "JIRA instance URL (e.g., https://your-org.atlassian.net): "
            ).strip()
            if not jira_url:
                print("❌ URL is required")
                return False

            # Ensure URL doesn't have trailing slash
            jira_url = jira_url.rstrip("/")

            print()
            print("Authentication options:")
            print("  1. API Token (recommended for Atlassian Cloud)")
            print("  2. SSO (browser login)")
            print("  3. Basic Auth (username/password)")

            auth_method = input("Choose method (1-3): ").strip()

            import configparser
            config = configparser.ConfigParser()
            config["jira"] = {"url": jira_url, "auth_method": auth_method}

            if auth_method == "1":
                email = input("Email: ").strip()
                api_token = input("API Token: ").strip()
                config["jira"]["email"] = email
                config["jira"]["api_token"] = api_token

            elif auth_method == "2":
                email = input("Email (optional, for pre-fill): ").strip()
                if email:
                    config["jira"]["email"] = email

                print("\nOpening browser for SSO login...")
                success, msg = self.perform_sso_login(jira_url, email)
                if not success:
                    print(f"❌ SSO login failed: {msg}")
                    return False
                print(f"✅ {msg}")

            elif auth_method == "3":
                username = input("Username: ").strip()
                password = input("Password: ").strip()
                config["jira"]["username"] = username
                config["jira"]["password"] = password

            else:
                print("❌ Invalid option")
                return False

            self.write_plugin_config(config)
            print("✅ JIRA plugin configured!")
            return True

        except (EOFError, KeyboardInterrupt):
            print("\n❌ Setup cancelled")
            return False

    def is_configured(self) -> bool:
        """Check if JIRA is properly configured."""
        if not self.config_path.exists():
            return False

        config = self.read_plugin_config()
        return config.has_option("jira", "url")

    def execute(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute a JIRA action."""
        actions = {
            "get_issue": self._get_issue,
            "search_issues": self._search_issues,
            "cache_project": self._cache_project,
            "list_cached": self._list_cached,
        }

        handler = actions.get(action)
        if not handler:
            return {
                "error": f"Unknown action: {action}",
                "available_actions": list(actions.keys()),
            }

        return handler(**kwargs)

    def get_available_actions(self) -> List[Dict[str, str]]:
        """List available JIRA actions."""
        return [
            {"action": "get_issue", "description": "Fetch a specific JIRA issue by key"},
            {"action": "search_issues", "description": "Search issues using JQL"},
            {"action": "cache_project", "description": "Cache all issues for a project"},
            {"action": "list_cached", "description": "List cached JIRA data"},
        ]

    def _get_api_client(self) -> Optional[Any]:
        """Create an API client based on auth configuration.

        Returns:
            Tuple of (requests.Session, base_url) or None if not available.
        """
        config = self.read_plugin_config()
        auth_method = config.get("jira", "auth_method", fallback="1")

        try:
            import requests
        except ImportError:
            logger.error("requests library not installed. Install with: pip install doug[plugins]")
            return None

        session = requests.Session()
        session.headers["Content-Type"] = "application/json"
        session.headers["Accept"] = "application/json"

        self._base_url = config.get("jira", "url")

        if auth_method == "1":
            email = config.get("jira", "email")
            token = config.get("jira", "api_token")
            session.auth = (email, token)
        elif auth_method == "3":
            username = config.get("jira", "username")
            password = config.get("jira", "password")
            session.auth = (username, password)

        return session

    def _get_issue(self, issue_key: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Fetch a specific JIRA issue."""
        if not issue_key:
            return {"error": "issue_key is required"}

        session = self._get_api_client()
        if not session:
            return {"error": "API client not available. Install 'requests' package."}

        try:
            url = f"{self._base_url}/rest/api/3/issue/{issue_key}"
            response = session.get(url)
            response.raise_for_status()

            data = response.json()

            return {
                "key": data["key"],
                "summary": data["fields"].get("summary"),
                "status": data["fields"].get("status", {}).get("name"),
                "assignee": data["fields"].get("assignee", {}).get("displayName") if data["fields"].get("assignee") else None,
                "priority": data["fields"].get("priority", {}).get("name"),
                "type": data["fields"].get("issuetype", {}).get("name"),
                "created": data["fields"].get("created"),
                "updated": data["fields"].get("updated"),
                "description": (data["fields"].get("description") or "")[:1000],
            }

        except Exception as e:
            return {"error": f"Failed to fetch issue {issue_key}: {e}"}

    def _search_issues(self, jql: str = "", max_results: int = 50, **kwargs: Any) -> Dict[str, Any]:
        """Search JIRA issues with JQL."""
        if not jql:
            return {"error": "jql query is required"}

        session = self._get_api_client()
        if not session:
            return {"error": "API client not available"}

        try:
            url = f"{self._base_url}/rest/api/3/search"
            response = session.get(url, params={"jql": jql, "maxResults": max_results})
            response.raise_for_status()

            data = response.json()
            issues = []
            for issue in data.get("issues", []):
                issues.append({
                    "key": issue["key"],
                    "summary": issue["fields"].get("summary"),
                    "status": issue["fields"].get("status", {}).get("name"),
                    "type": issue["fields"].get("issuetype", {}).get("name"),
                })

            return {
                "total": data.get("total", 0),
                "returned": len(issues),
                "issues": issues,
            }

        except Exception as e:
            return {"error": f"Search failed: {e}"}

    def _cache_project(self, project_key: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Cache all issues for a JIRA project."""
        if not project_key:
            return {"error": "project_key is required"}

        result = self._search_issues(jql=f"project = {project_key} ORDER BY updated DESC")
        if "error" in result:
            return result

        cache_file = self.cache_dir / f"{project_key}.json"
        cache_data = {
            "project": project_key,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "issues": result.get("issues", []),
            "total": result.get("total", 0),
        }

        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)

        return {
            "status": "cached",
            "project": project_key,
            "issues_cached": len(cache_data["issues"]),
            "cache_file": str(cache_file),
        }

    def _list_cached(self, **kwargs: Any) -> Dict[str, Any]:
        """List cached JIRA data."""
        cached_files = sorted(self.cache_dir.glob("*.json"))
        cached = []
        for f in cached_files:
            try:
                data = json.loads(f.read_text())
                cached.append({
                    "project": data.get("project", f.stem),
                    "issues": data.get("total", 0),
                    "cached_at": data.get("cached_at"),
                })
            except (json.JSONDecodeError, OSError):
                cached.append({"file": f.stem, "error": "Failed to read"})

        return {"cached_projects": cached}
