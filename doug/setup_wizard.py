"""
Interactive setup wizard for Doug.

Guides users through first-time configuration including repository setup,
plugin configuration, and optional feature selection.

Think of me as your onboarding buddy, except I won't make you watch
a 45-minute compliance video. You're welcome.
"""

import logging
from typing import Any, Dict, List, Optional

from doug.config import DougConfig

logger = logging.getLogger(__name__)


class SetupWizard:
    """Interactive setup wizard for first-time Doug configuration.

    Walks users through:
    1. Repository configuration
    2. Plugin setup
    3. Optional features (voice, RAG, etc.)
    """

    def __init__(self, config: Optional[DougConfig] = None):
        """Initialize the setup wizard.

        Args:
            config: Doug configuration. If None, uses default.
        """
        self.config = config or DougConfig()

    def run(self) -> None:
        """Run the full interactive setup wizard."""
        self._print_header()

        # Ensure all directories exist
        self.config.ensure_directories()

        # Step 1: Repositories
        self._setup_repositories()

        # Step 2: Plugins
        self._setup_plugins()

        # Step 3: Optional features
        self._setup_optional_features()

        # Step 4: Save configuration
        self.config.save()

        self._print_footer()

    def _print_header(self) -> None:
        """Print the setup wizard header."""
        print()
        print("🤖 Doug Setup Wizard")
        print("=" * 60)
        print()
        print("Hey! I'm Doug. I'll help you get your multi-repository")
        print("context caching system set up. It's easier than it sounds,")
        print("I promise. My outie probably does this in his sleep.")
        print()
        print(f"Base directory: {self.config.base_path}")
        print()

    def _print_footer(self) -> None:
        """Print completion message with next steps."""
        print()
        print("=" * 60)
        print("✅ Setup complete! Nice work, team.")
        print()
        print("Next steps:")
        print("  1. Run 'doug clone' to clone your repositories")
        print("  2. Run 'doug index' to build the cache")
        print("  3. Use 'doug query status' to verify everything's golden")
        print()
        print("For help: doug --help")
        print()

    def _setup_repositories(self) -> None:
        """Interactive repository configuration."""
        print("📦 Repository Setup")
        print("-" * 60)
        print()
        print("Add Git repositories for Doug to index and cache.")
        print("You can also add repositories later with 'doug add-repo <url>'")
        print()

        repos: List[str] = []

        while True:
            prompt = "Enter a Git repository URL (or press ENTER to finish): "
            try:
                url = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not url:
                break

            # Validate URL format
            if not (
                url.startswith("http://")
                or url.startswith("https://")
                or url.startswith("git@")
            ):
                print("❌ Invalid URL. Must start with http://, https://, or git@")
                continue

            # Check for optional branch specification
            try:
                branch_input = input(
                    "  Branch override (press ENTER for default): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if branch_input:
                entry = f"{url},{branch_input}"
            else:
                entry = url

            repos.append(entry)
            print(f"  ✅ Added: {url}" + (f" (branch: {branch_input})" if branch_input else ""))
            print()

        if repos:
            self._save_repositories(repos)
            print(f"\n✅ Saved {len(repos)} repositories")
        else:
            print("\n⚠️  No repositories added. Add them later with 'doug add-repo <url>'")

        print()

    def _save_repositories(self, repos: List[str]) -> None:
        """Save repository list to configuration file."""
        repos_file = self.config.repos_config_dir / "repos.txt"
        repos_file.parent.mkdir(parents=True, exist_ok=True)

        with open(repos_file, "w") as f:
            f.write("# Doug Repository List\n")
            f.write("# One Git URL per line\n")
            f.write("# Append ,branch-name to specify a branch override\n")
            f.write("# Lines starting with # are comments\n\n")
            for repo in repos:
                f.write(f"{repo}\n")

    def _setup_plugins(self) -> None:
        """Interactive plugin configuration."""
        print("🔌 Plugin Setup")
        print("-" * 60)
        print()

        available_plugins = self._get_available_plugins()

        print("Available plugins:")
        for key, info in available_plugins.items():
            status = "enabled" if self.config.is_plugin_enabled(key) else "disabled"
            print(f"  • {info['name']}: {info['description']} [{status}]")

        print()

        try:
            answer = input("Would you like to configure any plugins? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if answer != "y":
            print()
            return

        for key, info in available_plugins.items():
            try:
                answer = input(f"\nEnable {info['name']}? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if answer == "y":
                self.config.enable_plugin(key, True)
                print(f"  ✅ {info['name']} enabled")

                # Plugin-specific configuration
                if key == "jira":
                    self._configure_jira()
                elif key == "confluence":
                    self._configure_confluence()

        print()

    def _configure_jira(self) -> None:
        """Configure JIRA plugin interactively."""
        print()
        print("  🎫 JIRA Configuration")
        try:
            url = input("  JIRA URL (e.g., https://your-org.atlassian.net): ").strip()
            if not url:
                return

            print("  Authentication method:")
            print("    1. API Token (recommended)")
            print("    2. SSO (browser-based)")
            print("    3. Basic Auth")

            method = input("  Choose (1-3): ").strip()

            config_values = {"url": url, "auth_method": method}

            if method == "1":
                email = input("  Email: ").strip()
                token = input("  API Token: ").strip()
                config_values["email"] = email
                config_values["api_token"] = token
            elif method == "3":
                username = input("  Username: ").strip()
                password = input("  Password: ").strip()
                config_values["username"] = username
                config_values["password"] = password

            self.config.set_plugin_config("jira", "jira", config_values)
            print("  ✅ JIRA configured")

        except (EOFError, KeyboardInterrupt):
            print()

    def _configure_confluence(self) -> None:
        """Configure Confluence plugin interactively."""
        print()
        print("  📝 Confluence Configuration")
        try:
            url = input("  Confluence URL (e.g., https://your-org.atlassian.net/wiki): ").strip()
            if not url:
                return

            print("  Authentication method:")
            print("    1. API Token (recommended)")
            print("    2. SSO (browser-based)")

            method = input("  Choose (1-2): ").strip()

            config_values = {"url": url, "auth_method": method}

            if method == "1":
                email = input("  Email: ").strip()
                token = input("  API Token: ").strip()
                config_values["email"] = email
                config_values["api_token"] = token

            self.config.set_plugin_config("confluence", "confluence", config_values)
            print("  ✅ Confluence configured")

        except (EOFError, KeyboardInterrupt):
            print()

    def _setup_optional_features(self) -> None:
        """Configure optional features."""
        print("⚙️  Optional Features")
        print("-" * 60)
        print()

        # Parallel workers
        try:
            workers = input(
                f"Parallel workers for cloning/indexing "
                f"(default: {self.config.parallel_workers}): "
            ).strip()
            if workers and workers.isdigit():
                self.config.set("cache", "parallel_workers", workers)
        except (EOFError, KeyboardInterrupt):
            print()
            return

        # Cache freshness
        try:
            hours = input(
                f"Cache freshness in hours "
                f"(default: {self.config.cache_freshness_hours}): "
            ).strip()
            if hours and hours.isdigit():
                self.config.set("cache", "cache_freshness_hours", hours)
        except (EOFError, KeyboardInterrupt):
            print()
            return

        # Personality voice
        try:
            voice = input(
                "Enable Doug's snarky personality voice for AI responses? (Y/n): "
            ).strip().lower()
            if voice == "n":
                self.config.set("ui", "use_personality_voice", "false")
                print("  ⬜ Personality voice disabled (boring, but okay)")
            else:
                self.config.set("ui", "use_personality_voice", "true")
                print("  ✅ Doug voice enabled — you're gonna love this")
        except (EOFError, KeyboardInterrupt):
            print()

        print()

    @staticmethod
    def _get_available_plugins() -> Dict[str, Dict[str, str]]:
        """Get list of available plugins and their descriptions."""
        return {
            "jira": {
                "name": "JIRA",
                "description": "Issue tracking integration (Atlassian JIRA)",
            },
            "confluence": {
                "name": "Confluence",
                "description": "Documentation wiki integration (Atlassian Confluence)",
            },
            "playwright": {
                "name": "Playwright",
                "description": "Browser automation for SSO and web-based integrations",
            },
        }
