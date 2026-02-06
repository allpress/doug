"""
Playwright browser automation base for Doug plugins.

Provides base classes for browser-based integrations with support
for SSO authentication, session persistence, and cookie management.
"""

import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from doug.config import DougConfig
from doug.plugins.base import DougPlugin

logger = logging.getLogger(__name__)


class PlaywrightPlugin(DougPlugin):
    """Base class for browser automation plugins.

    Extends DougPlugin with Playwright-specific capabilities:
    - Auto-install Playwright dependencies
    - Authentication state persistence
    - Screenshot capture
    - Cross-browser support
    - Cookie/session management

    Subclasses should implement the abstract methods from DougPlugin
    and can use the browser automation helpers provided here.
    """

    def __init__(self, name: str, description: str, config: Optional[DougConfig] = None):
        """Initialize the Playwright plugin.

        Args:
            name: Plugin identifier.
            description: Human-readable description.
            config: Doug configuration.
        """
        super().__init__(name, description, config)

        # Playwright-specific directories
        self.auth_dir = self.config.plugins_config_dir / name / ".auth"
        self.screenshots_dir = self.cache_dir / "screenshots"

        self.auth_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def ensure_playwright_ready(self) -> Tuple[bool, str]:
        """Check and install Playwright if needed.

        Returns:
            Tuple of (success, message).
        """
        try:
            import playwright  # noqa: F401
            from playwright.sync_api import sync_playwright  # noqa: F401

            return True, "Playwright is ready"
        except ImportError:
            logger.info("Installing Playwright...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "playwright"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return True, "Playwright installed successfully"
            except subprocess.CalledProcessError as e:
                return False, f"Failed to install Playwright: {e.stderr}"

    def get_auth_state_path(self, profile: str = "default") -> Path:
        """Get the path for storing authentication state.

        Args:
            profile: Auth profile name (for multiple accounts).

        Returns:
            Path to the auth state JSON file.
        """
        return self.auth_dir / f"{profile}.json"

    def has_auth_state(self, profile: str = "default") -> bool:
        """Check if authentication state exists.

        Args:
            profile: Auth profile name.

        Returns:
            True if auth state file exists.
        """
        return self.get_auth_state_path(profile).exists()

    def perform_sso_login(
        self,
        base_url: str,
        email: Optional[str] = None,
        profile: str = "default",
    ) -> Tuple[bool, str]:
        """Perform SSO login using a browser window.

        Opens a Chromium browser for the user to complete authentication,
        then saves the auth state for future use.

        Args:
            base_url: The SSO login URL.
            email: Optional email to pre-fill.
            profile: Auth profile name.

        Returns:
            Tuple of (success, message).
        """
        ready, msg = self.ensure_playwright_ready()
        if not ready:
            return False, msg

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()

                # Navigate to login page
                page.goto(base_url)

                # Pre-fill email if provided
                if email:
                    try:
                        email_input = page.query_selector(
                            'input[type="email"], input[name="email"], '
                            'input[id="email"], input[name="username"]'
                        )
                        if email_input:
                            email_input.fill(email)
                            submit = page.query_selector(
                                'button[type="submit"], input[type="submit"]'
                            )
                            if submit:
                                submit.click()
                    except Exception:
                        pass  # Non-critical, user can fill manually

                print()
                print("🌐 Browser opened for authentication.")
                print("   Please complete the login process.")
                print("   Press ENTER when you're logged in and see your dashboard...")
                print()

                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    browser.close()
                    return False, "Login cancelled"

                # Save authentication state
                auth_path = self.get_auth_state_path(profile)
                context.storage_state(path=str(auth_path))

                # Set restrictive permissions on auth file
                try:
                    os.chmod(auth_path, 0o600)
                except (OSError, AttributeError):
                    pass

                browser.close()

            return True, "Authentication saved successfully"

        except Exception as e:
            return False, f"SSO login failed: {e}"

    @contextmanager
    def authenticated_browser(
        self,
        profile: str = "default",
        headless: bool = True,
    ) -> Generator[Any, None, None]:
        """Context manager for an authenticated Playwright browser context.

        Properly cleans up the browser and Playwright process on exit.

        Args:
            profile: Auth profile name.
            headless: Whether to run headless.

        Yields:
            Playwright BrowserContext with loaded auth state.

        Raises:
            FileNotFoundError: If no auth state exists.
            ImportError: If Playwright is not installed.
        """
        auth_path = self.get_auth_state_path(profile)
        if not auth_path.exists():
            raise FileNotFoundError(
                f"No auth state found for profile '{profile}'. "
                f"Run plugin setup first."
            )

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = None
        context = None
        try:
            browser = pw.chromium.launch(headless=headless)
            context = browser.new_context(storage_state=str(auth_path))
            yield context
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            try:
                pw.stop()
            except Exception:
                pass

    def create_authenticated_context(self, profile: str = "default") -> Any:
        """Create a Playwright browser context with saved auth state.

        .. deprecated::
            Use :meth:`authenticated_browser` context manager instead
            to ensure proper cleanup of browser and Playwright processes.

        Args:
            profile: Auth profile name.

        Returns:
            Playwright BrowserContext with loaded auth state.

        Raises:
            FileNotFoundError: If no auth state exists.
            ImportError: If Playwright is not installed.
        """
        auth_path = self.get_auth_state_path(profile)
        if not auth_path.exists():
            raise FileNotFoundError(
                f"No auth state found for profile '{profile}'. "
                f"Run plugin setup first."
            )

        from playwright.sync_api import sync_playwright

        p = sync_playwright().start()
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(auth_path))

        return context

    def take_screenshot(self, page: Any, name: str) -> Path:
        """Take a screenshot of the current page.

        Args:
            page: Playwright Page object.
            name: Screenshot filename (without extension).

        Returns:
            Path to the saved screenshot.
        """
        screenshot_path = self.screenshots_dir / f"{name}.png"
        page.screenshot(path=str(screenshot_path))
        return screenshot_path

    def clear_auth(self, profile: str = "default") -> bool:
        """Clear saved authentication state.

        Args:
            profile: Auth profile name.

        Returns:
            True if auth was cleared.
        """
        auth_path = self.get_auth_state_path(profile)
        if auth_path.exists():
            auth_path.unlink()
            return True
        return False
