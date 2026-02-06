"""
Confluence integration plugin for Doug.

Provides Confluence wiki integration for caching documentation pages
and spaces for AI assistant context.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from doug.config import DougConfig
from doug.plugins.playwright_base import PlaywrightPlugin

logger = logging.getLogger(__name__)


class ConfluencePlugin(PlaywrightPlugin):
    """Confluence integration plugin.

    Supports:
    - Fetching individual pages
    - Searching across spaces
    - Caching space contents
    - Both API token and SSO authentication
    """

    def __init__(self, config: Optional[DougConfig] = None):
        """Initialize the Confluence plugin."""
        super().__init__(
            name="confluence",
            description="Confluence documentation wiki integration",
            config=config,
        )

    def setup(self) -> bool:
        """Interactive Confluence setup."""
        print()
        print("📝 Confluence Plugin Setup")
        print("=" * 50)

        try:
            confluence_url = input(
                "Confluence URL (e.g., https://your-org.atlassian.net/wiki): "
            ).strip()
            if not confluence_url:
                print("❌ URL is required")
                return False

            confluence_url = confluence_url.rstrip("/")

            print()
            print("Authentication options:")
            print("  1. API Token (recommended for Atlassian Cloud)")
            print("  2. SSO (browser login)")

            auth_method = input("Choose method (1-2): ").strip()

            import configparser
            config = configparser.ConfigParser()
            config["confluence"] = {"url": confluence_url, "auth_method": auth_method}

            if auth_method == "1":
                email = input("Email: ").strip()
                api_token = input("API Token: ").strip()
                config["confluence"]["email"] = email
                config["confluence"]["api_token"] = api_token

            elif auth_method == "2":
                email = input("Email (optional, for pre-fill): ").strip()
                if email:
                    config["confluence"]["email"] = email

                print("\nOpening browser for SSO login...")
                success, msg = self.perform_sso_login(confluence_url, email)
                if not success:
                    print(f"❌ SSO login failed: {msg}")
                    return False
                print(f"✅ {msg}")

            else:
                print("❌ Invalid option")
                return False

            self.write_plugin_config(config)
            print("✅ Confluence plugin configured!")
            return True

        except (EOFError, KeyboardInterrupt):
            print("\n❌ Setup cancelled")
            return False

    def is_configured(self) -> bool:
        """Check if Confluence is properly configured."""
        if not self.config_path.exists():
            return False

        config = self.read_plugin_config()
        return config.has_option("confluence", "url")

    def execute(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute a Confluence action."""
        actions = {
            "get_page": self._get_page,
            "search": self._search,
            "cache_space": self._cache_space,
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
        """List available Confluence actions."""
        return [
            {"action": "get_page", "description": "Fetch a specific Confluence page by ID"},
            {"action": "search", "description": "Search Confluence using CQL"},
            {"action": "cache_space", "description": "Cache all pages in a space"},
            {"action": "list_cached", "description": "List cached Confluence data"},
        ]

    def _get_api_client(self) -> Optional[Any]:
        """Create an API client based on auth configuration."""
        config = self.read_plugin_config()
        auth_method = config.get("confluence", "auth_method", fallback="1")

        try:
            import requests
        except ImportError:
            logger.error("requests library not installed")
            return None

        session = requests.Session()
        session.headers["Content-Type"] = "application/json"
        session.headers["Accept"] = "application/json"

        self._base_url = config.get("confluence", "url")

        if auth_method == "1":
            email = config.get("confluence", "email")
            token = config.get("confluence", "api_token")
            session.auth = (email, token)

        return session

    def _get_page(self, page_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Fetch a specific Confluence page."""
        if not page_id:
            return {"error": "page_id is required"}

        session = self._get_api_client()
        if not session:
            return {"error": "API client not available"}

        try:
            url = (
                f"{self._base_url}/rest/api/content/{page_id}"
                f"?expand=body.storage,space,version"
            )
            response = session.get(url)
            response.raise_for_status()

            data = response.json()
            body_html = data.get("body", {}).get("storage", {}).get("value", "")

            # Strip HTML tags for plain text (basic)
            body_text = re.sub(r"<[^>]+>", " ", body_html)
            body_text = re.sub(r"\s+", " ", body_text).strip()

            return {
                "id": data["id"],
                "title": data.get("title"),
                "space": data.get("space", {}).get("key"),
                "version": data.get("version", {}).get("number"),
                "content": body_text[:5000],  # Truncate for token efficiency
            }

        except Exception as e:
            return {"error": f"Failed to fetch page {page_id}: {e}"}

    def _search(self, cql: str = "", max_results: int = 25, **kwargs: Any) -> Dict[str, Any]:
        """Search Confluence using CQL."""
        if not cql:
            return {"error": "cql query is required"}

        session = self._get_api_client()
        if not session:
            return {"error": "API client not available"}

        try:
            url = f"{self._base_url}/rest/api/content/search"
            response = session.get(url, params={"cql": cql, "limit": max_results})
            response.raise_for_status()

            data = response.json()
            pages = []
            for result in data.get("results", []):
                pages.append({
                    "id": result["id"],
                    "title": result.get("title"),
                    "space": result.get("space", {}).get("key") if "space" in result else None,
                    "type": result.get("type"),
                })

            return {
                "total": data.get("totalSize", 0),
                "returned": len(pages),
                "pages": pages,
            }

        except Exception as e:
            return {"error": f"Search failed: {e}"}

    def _cache_space(self, space_key: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Cache all pages in a Confluence space."""
        if not space_key:
            return {"error": "space_key is required"}

        result = self._search(cql=f'space = "{space_key}" AND type = "page" ORDER BY lastModified DESC')
        if "error" in result:
            return result

        cache_file = self.cache_dir / f"space_{space_key}.json"
        cache_data = {
            "space": space_key,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "pages": result.get("pages", []),
            "total": result.get("total", 0),
        }

        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)

        return {
            "status": "cached",
            "space": space_key,
            "pages_cached": len(cache_data["pages"]),
            "cache_file": str(cache_file),
        }

    def _list_cached(self, **kwargs: Any) -> Dict[str, Any]:
        """List cached Confluence data."""
        cached_files = sorted(self.cache_dir.glob("*.json"))
        cached = []
        for f in cached_files:
            try:
                data = json.loads(f.read_text())
                cached.append({
                    "space": data.get("space", f.stem),
                    "pages": data.get("total", 0),
                    "cached_at": data.get("cached_at"),
                })
            except (json.JSONDecodeError, OSError):
                cached.append({"file": f.stem, "error": "Failed to read"})

        return {"cached_spaces": cached}
