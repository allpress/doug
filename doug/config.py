"""
Configuration management for Doug.

Handles reading/writing INI configuration files with cross-platform
path handling and type-safe accessors.

I keep track of where everything goes so you don't have to.
Think of me as your digital filing cabinet, except I don't judge
your directory structure. Much.
"""

import configparser
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _find_base_path() -> Path:
    """Find the Doug base path.

    Resolution order:
    1. DOUG_HOME environment variable
    2. ~/.doug (user home directory)
    """
    env_path = os.environ.get("DOUG_HOME")
    if env_path:
        return Path(env_path).resolve()

    return Path.home() / ".doug"


class DougConfig:
    """Configuration manager for Doug.

    Reads configuration from INI files and provides type-safe accessors
    with default value fallbacks.
    """

    # Default configuration values
    DEFAULTS = {
        "cache": {
            "parallel_workers": "4",
            "cache_freshness_hours": "24",
            "max_file_size_kb": "1024",
            "readme_max_chars": "2000",
        },
        "indexer": {
            "skip_dirs": ".git,node_modules,__pycache__,.venv,venv,dist,build,.idea,.vscode,target,.gradle",
            "source_extensions": ".py,.java,.kt,.js,.ts,.jsx,.tsx,.go,.rs,.rb,.php,.cs,.cpp,.c,.h,.swift,.scala",
            "config_extensions": ".json,.yaml,.yml,.toml,.ini,.cfg,.xml,.properties,.env",
            "max_depth": "20",
        },
        "ui": {
            "use_personality_voice": "true",
            "show_progress": "true",
            "color_output": "true",
        },
        "plugins": {
            "jira_enabled": "false",
            "confluence_enabled": "false",
            "playwright_enabled": "false",
        },
    }

    def __init__(self, base_path: Optional[Path] = None):
        """Initialize configuration.

        Args:
            base_path: Root path for Doug. If None, auto-detected.
        """
        self.base_path = Path(base_path).resolve() if base_path else _find_base_path()

        # Core directories
        self.config_dir = self.base_path / "config"
        self.cache_dir = self.base_path / "cache"
        self.repos_dir = self.base_path / "repositories"

        # Sub-directories
        self.repos_config_dir = self.config_dir / "repositories"
        self.plugins_config_dir = self.config_dir / "plugins"
        self.voice_config_dir = self.config_dir / "voice"

        self.repo_cache_dir = self.cache_dir / "repos"
        self.index_cache_dir = self.cache_dir / "indexes"
        self.plugin_cache_dir = self.cache_dir / "plugins"

        # Load configuration
        self._config = configparser.ConfigParser()
        self._load_defaults()
        self._load_user_config()

    def _load_defaults(self) -> None:
        """Load default configuration values."""
        for section, values in self.DEFAULTS.items():
            if not self._config.has_section(section):
                self._config.add_section(section)
            for key, value in values.items():
                self._config.set(section, key, value)

    def _load_user_config(self) -> None:
        """Load user configuration from defaults.ini if it exists."""
        config_path = self.config_dir / "defaults.ini"
        if config_path.exists():
            self._config.read(str(config_path))

    def ensure_directories(self) -> None:
        """Create all required directories."""
        dirs = [
            self.config_dir,
            self.cache_dir,
            self.repos_dir,
            self.repos_config_dir,
            self.plugins_config_dir,
            self.voice_config_dir,
            self.repo_cache_dir,
            self.index_cache_dir,
            self.plugin_cache_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        """Save current configuration to defaults.ini."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.config_dir / "defaults.ini"
        with open(config_path, "w") as f:
            self._config.write(f)

    # --- Type-safe property accessors ---

    @property
    def parallel_workers(self) -> int:
        return self._config.getint("cache", "parallel_workers", fallback=4)

    @property
    def cache_freshness_hours(self) -> int:
        return self._config.getint("cache", "cache_freshness_hours", fallback=24)

    @property
    def max_file_size_kb(self) -> int:
        return self._config.getint("cache", "max_file_size_kb", fallback=1024)

    @property
    def readme_max_chars(self) -> int:
        return self._config.getint("cache", "readme_max_chars", fallback=2000)

    @property
    def skip_dirs(self) -> List[str]:
        raw = self._config.get("indexer", "skip_dirs", fallback="")
        return [d.strip() for d in raw.split(",") if d.strip()]

    @property
    def source_extensions(self) -> List[str]:
        raw = self._config.get("indexer", "source_extensions", fallback="")
        return [e.strip() for e in raw.split(",") if e.strip()]

    @property
    def config_extensions(self) -> List[str]:
        raw = self._config.get("indexer", "config_extensions", fallback="")
        return [e.strip() for e in raw.split(",") if e.strip()]

    @property
    def max_depth(self) -> int:
        return self._config.getint("indexer", "max_depth", fallback=20)

    @property
    def use_personality_voice(self) -> bool:
        return self._config.getboolean("ui", "use_personality_voice", fallback=True)

    @property
    def show_progress(self) -> bool:
        return self._config.getboolean("ui", "show_progress", fallback=True)

    @property
    def color_output(self) -> bool:
        return self._config.getboolean("ui", "color_output", fallback=True)

    # --- Plugin configuration ---

    def is_plugin_enabled(self, plugin_name: str) -> bool:
        key = f"{plugin_name}_enabled"
        return self._config.getboolean("plugins", key, fallback=False)

    def enable_plugin(self, plugin_name: str, enabled: bool = True) -> None:
        key = f"{plugin_name}_enabled"
        if not self._config.has_section("plugins"):
            self._config.add_section("plugins")
        self._config.set("plugins", key, str(enabled).lower())

    def get_plugin_config(self, plugin_name: str) -> Dict[str, Any]:
        config_path = self.plugins_config_dir / f"{plugin_name}.ini"
        if not config_path.exists():
            return {}

        plugin_config = configparser.ConfigParser()
        plugin_config.read(str(config_path))

        result: Dict[str, Any] = {}
        for section in plugin_config.sections():
            for key, value in plugin_config.items(section):
                result[f"{section}.{key}"] = value

        return result

    def set_plugin_config(self, plugin_name: str, section: str, values: Dict[str, str]) -> None:
        config_path = self.plugins_config_dir / f"{plugin_name}.ini"
        self.plugins_config_dir.mkdir(parents=True, exist_ok=True)

        plugin_config = configparser.ConfigParser()
        if config_path.exists():
            plugin_config.read(str(config_path))

        if not plugin_config.has_section(section):
            plugin_config.add_section(section)

        for key, value in values.items():
            plugin_config.set(section, key, value)

        # Set restrictive permissions on plugin config (may contain creds)
        with open(config_path, "w") as f:
            plugin_config.write(f)
        try:
            os.chmod(config_path, 0o600)
        except (OSError, AttributeError):
            pass

    def has_plugin(self, plugin_name: str) -> bool:
        config_path = self.plugins_config_dir / f"{plugin_name}.ini"
        return config_path.exists()

    # --- Repository configuration ---

    def get_repository_files(self) -> List[Path]:
        if not self.repos_config_dir.exists():
            return []
        return sorted(self.repos_config_dir.glob("*.txt"))

    def get(self, section: str, key: str, fallback: str = "") -> str:
        return self._config.get(section, key, fallback=fallback)

    def set(self, section: str, key: str, value: str) -> None:
        if not self._config.has_section(section):
            self._config.add_section(section)
        self._config.set(section, key, value)

    def get_status(self) -> Dict[str, Any]:
        return {
            "base_path": str(self.base_path),
            "config_exists": (self.config_dir / "defaults.ini").exists(),
            "parallel_workers": self.parallel_workers,
            "cache_freshness_hours": self.cache_freshness_hours,
            "repository_files": [str(f) for f in self.get_repository_files()],
            "plugins": {
                "jira": self.is_plugin_enabled("jira"),
                "confluence": self.is_plugin_enabled("confluence"),
                "playwright": self.is_plugin_enabled("playwright"),
            },
        }
