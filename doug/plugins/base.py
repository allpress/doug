"""
Plugin base classes for Doug.

Provides abstract base classes for creating Doug plugins
with a consistent interface for setup, configuration, and execution.
"""

import configparser
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from doug.config import DougConfig

logger = logging.getLogger(__name__)


class DougPlugin(ABC):
    """Abstract base class for all Doug plugins.

    Plugins extend Doug with integrations to external services
    (JIRA, Confluence, GitLab, etc.) and provide caching capabilities
    for their data.

    Subclasses must implement:
        - setup(): Interactive plugin configuration
        - is_configured(): Check if plugin is ready
        - execute(): Perform a plugin action
        - get_available_actions(): List available actions
    """

    def __init__(self, name: str, description: str, config: Optional[DougConfig] = None):
        """Initialize a plugin.

        Args:
            name: Plugin identifier (e.g., 'jira', 'confluence').
            description: Human-readable description.
            config: Doug configuration.
        """
        self.name = name
        self.description = description
        self.config = config or DougConfig()

        # Plugin-specific directories
        self.cache_dir = self.config.plugin_cache_dir / name
        self.config_path = self.config.plugins_config_dir / f"{name}.ini"

        # Ensure directories exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def setup(self) -> bool:
        """Interactive setup/configuration for this plugin.

        Should prompt the user for required configuration values
        and save them to the plugin's config file.

        Returns:
            True if setup completed successfully.
        """

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the plugin is properly configured and ready to use.

        Returns:
            True if all required configuration is present.
        """

    @abstractmethod
    def execute(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute a plugin action.

        Args:
            action: Action name (from get_available_actions).
            **kwargs: Action-specific parameters.

        Returns:
            Action result dict.
        """

    @abstractmethod
    def get_available_actions(self) -> List[Dict[str, str]]:
        """Get list of available actions for this plugin.

        Returns:
            List of dicts with 'action' and 'description' keys.
        """

    def get_info(self) -> Dict[str, Any]:
        """Get plugin metadata and status.

        Returns:
            Plugin info dict.
        """
        return {
            "name": self.name,
            "description": self.description,
            "configured": self.is_configured(),
            "enabled": self.config.is_plugin_enabled(self.name),
            "actions": self.get_available_actions(),
            "cache_dir": str(self.cache_dir),
        }

    def read_plugin_config(self) -> configparser.ConfigParser:
        """Read the plugin's INI configuration file.

        Returns:
            ConfigParser with plugin configuration.
        """
        plugin_config = configparser.ConfigParser()
        if self.config_path.exists():
            plugin_config.read(str(self.config_path))
        return plugin_config

    def write_plugin_config(self, plugin_config: configparser.ConfigParser) -> None:
        """Write the plugin's INI configuration file.

        Args:
            plugin_config: ConfigParser to save.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            plugin_config.write(f)
        # Restrict permissions — config may contain credentials
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass


class PluginManager:
    """Manages loading, enabling, and executing plugins.

    Discovers available plugins, handles their lifecycle, and provides
    a unified interface for plugin operations.
    """

    def __init__(self, config: Optional[DougConfig] = None):
        """Initialize the plugin manager.

        Args:
            config: Doug configuration.
        """
        self.config = config or DougConfig()
        self._plugins: Dict[str, DougPlugin] = {}
        # Instance-level registry avoids shared state between managers
        self._plugin_registry: Dict[str, type] = {}
        self._discover_plugins()

    def register_plugin(self, name: str, plugin_class: type) -> None:
        """Register a plugin class.

        Args:
            name: Plugin identifier.
            plugin_class: Plugin class (must be DougPlugin subclass).
        """
        if not issubclass(plugin_class, DougPlugin):
            raise TypeError(f"{plugin_class} is not a subclass of DougPlugin")
        self._plugin_registry[name] = plugin_class

    def _discover_plugins(self) -> None:
        """Discover and load available plugins."""
        self._load_builtin_plugins()

    def _load_builtin_plugins(self) -> None:
        """Load built-in plugins from the plugins directory."""
        try:
            from doug.plugins.jira_plugin import JiraPlugin
            self._plugin_registry["jira"] = JiraPlugin
        except ImportError:
            logger.debug("JIRA plugin not available")

        try:
            from doug.plugins.confluence_plugin import ConfluencePlugin
            self._plugin_registry["confluence"] = ConfluencePlugin
        except ImportError:
            logger.debug("Confluence plugin not available")

    def get_plugin(self, name: str) -> Optional[DougPlugin]:
        """Get a plugin instance by name.

        Args:
            name: Plugin identifier.

        Returns:
            Plugin instance, or None if not available.
        """
        if name in self._plugins:
            return self._plugins[name]

        plugin_class = self._plugin_registry.get(name)
        if plugin_class:
            try:
                plugin = plugin_class(config=self.config)
                self._plugins[name] = plugin
                return plugin
            except Exception as e:
                logger.error("Failed to instantiate plugin %s: %s", name, e)

        return None

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all available plugins with their status.

        Returns:
            List of plugin info dicts.
        """
        plugins: List[Dict[str, Any]] = []

        # Include registered plugins
        for name in sorted(self._plugin_registry.keys()):
            plugin = self.get_plugin(name)
            if plugin:
                plugins.append(plugin.get_info())
            else:
                plugins.append({
                    "name": name,
                    "description": "Plugin available but failed to load",
                    "configured": False,
                    "enabled": False,
                })

        # Include known plugin names even if not imported
        for name in ("jira", "confluence", "playwright"):
            if not any(p["name"] == name for p in plugins):
                plugins.append({
                    "name": name,
                    "description": f"{name.title()} plugin (not installed)",
                    "configured": False,
                    "enabled": self.config.is_plugin_enabled(name),
                })

        return plugins

    def execute_plugin(self, name: str, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute an action on a plugin.

        Args:
            name: Plugin identifier.
            action: Action to execute.
            **kwargs: Action parameters.

        Returns:
            Action result dict.
        """
        plugin = self.get_plugin(name)
        if not plugin:
            return {"error": f"Plugin not found: {name}"}

        if not plugin.is_configured():
            return {"error": f"Plugin {name} is not configured. Run 'doug plugin configure {name}'"}

        if not self.config.is_plugin_enabled(name):
            return {"error": f"Plugin {name} is not enabled. Run 'doug plugin enable {name}'"}

        try:
            return plugin.execute(action, **kwargs)
        except Exception as e:
            logger.error("Plugin %s action %s failed: %s", name, action, e)
            return {"error": f"Plugin action failed: {e}"}
