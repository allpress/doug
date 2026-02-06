# 🤖 Doug

**Multi-repository context caching and indexing for AI coding assistants.**

Doug indexes your repos, caches the important stuff, and serves it up to your AI assistant so it actually knows what it's talking about. Think of him as the coworker who's memorized every codebase — except he doesn't steal your lunch from the fridge.

> *"My outie probably has opinions about this README. He's too busy playing pickleball to share them."*

---

## What Doug Does

- **Clones & caches** multiple Git repositories into a local mirror
- **Indexes** source files, APIs, services, models, configs, and build systems
- **Provides a query interface** optimized for AI coding assistants (token-efficient JSON)
- **Semantic search** via RAG (optional — requires embeddings + vector DB)
- **Plugin system** for JIRA, Confluence, and browser-based SSO integrations
- **Zero core dependencies** — only stdlib Python. Extras are opt-in.

## Quick Start

```bash
# Install
pip install doug

# Set up (interactive wizard)
doug init

# Add a repo manually
doug add-repo https://github.com/your-org/your-repo.git

# Clone everything
doug clone

# Index it all
doug index

# Search across all repos
doug query search "authentication"

# Full system status
doug status
```

## Installation

### From PyPI (when published)

```bash
pip install doug
```

### From source

```bash
git clone https://github.com/dougallpress/doug.git
cd doug
pip install -e .
```

### Optional Extras

```bash
# Browser automation for SSO auth (JIRA, Confluence)
pip install doug[plugins]

# Semantic search with embeddings + ChromaDB
pip install doug[rag]

# Everything
pip install doug[all]

# Development tools
pip install doug[dev]
```

## Usage

### Repository Management

```bash
doug add-repo https://github.com/org/repo.git        # Add a repo
doug add-repo https://github.com/org/repo.git -b dev  # With branch override
doug remove-repo repo-name                             # Remove a repo
doug remove-repo repo-name --purge                     # Remove + delete files
doug clone                                             # Clone all repos
doug clone -f                                          # Force re-clone
doug pull                                              # Pull latest for all repos
doug pull -p 8                                         # Parallel pull with 8 workers
```

### Indexing

```bash
doug index                    # Index all cloned repos
doug index my-repo            # Index a specific repo
doug index -p 4               # Parallel indexing
```

### Querying (for AI assistants)

```bash
doug query status             # Cache status overview
doug query repos              # List all cached repos
doug query overview           # Text summary of everything
doug query search "users"     # Search across all repos
doug query search "auth" -s apis   # Search only API endpoints
doug query apis               # List all API endpoints
doug query apis my-repo       # APIs for one repo
doug query repo my-repo       # Repo summary
doug query repo my-repo apis  # Specific section detail
doug query find my-repo "Controller"  # Find files by pattern
```

### RAG (Semantic Search)

```bash
doug rag status               # Check RAG dependencies & status
doug rag index                # Index all repos into vector DB
doug rag index repo1 repo2    # Index specific repos
doug rag search "auth flow"   # Semantic search
doug rag search "auth" -k 20  # More results
doug rag search "auth" -r my-repo  # Filter by repo
doug rag clear                # Clear vector database
```

### Plugins

```bash
doug plugin list              # List available plugins
doug plugin enable jira       # Enable a plugin
doug plugin disable jira      # Disable a plugin
doug plugin configure jira    # Interactive plugin setup
doug plugin run jira get_issue issue_key=PROJ-123  # Run plugin action
```

### System

```bash
doug status                   # Full system status
doug clean                    # Clear caches
doug clean repos              # Remove cloned repos
doug clean all                # Nuclear option
doug --version                # Version info
```

## Configuration

Doug stores its data in `~/.doug` by default (override with `DOUG_HOME` env var or `--base-path` flag).

```
~/.doug/
├── config/
│   ├── doug.ini              # Main config
│   ├── repositories/
│   │   └── repos.txt         # Repository list
│   └── plugins/
│       ├── jira.ini           # Plugin configs
│       └── confluence.ini
├── repositories/              # Cloned repos
├── cache/
│   ├── repos/                 # JSON index caches
│   ├── index/                 # Global index
│   ├── plugins/               # Plugin caches
│   └── rag/                   # Vector DB (optional)
└── logs/
```

## Architecture

```
doug/
├── __init__.py           # Package metadata
├── __main__.py           # python -m doug support
├── cli.py                # CLI interface (argparse)
├── config.py             # DougConfig — INI-based configuration
├── cache_manager.py      # Git clone/pull operations
├── indexer.py            # Source code analysis & JSON indexing
├── ai_query.py           # Token-efficient query interface
├── setup_wizard.py       # Interactive first-run wizard
├── plugins/
│   ├── base.py           # DougPlugin ABC + PluginManager
│   ├── playwright_base.py # Browser automation base
│   ├── jira_plugin.py    # JIRA integration
│   └── confluence_plugin.py # Confluence integration
└── rag/
    ├── rag_engine.py     # ChromaDB + sentence-transformers
    └── indexers.py       # Specialized content indexers
```

### Design Principles

- **Zero core dependencies.** stdlib only. Optional extras for plugins & RAG.
- **Token-efficient.** All query responses are structured for minimal AI context usage.
- **Fail gracefully.** Missing optional deps? Doug tells you what to install, doesn't crash.
- **Secure by default.** Config files with credentials get `0o600` permissions. No submodule cloning. Path traversal protection.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DOUG_HOME` | `~/.doug` | Base directory for all Doug data |

## Python API

```python
from doug.config import DougConfig
from doug.cache_manager import CacheManager
from doug.indexer import GlobalIndexer
from doug.ai_query import AIQueryTool

# Configure
config = DougConfig()
config.ensure_directories()

# Clone repos
manager = CacheManager(config=config)
manager.clone_all()

# Index
indexer = GlobalIndexer(config=config)
indexer.index_all()

# Query
query = AIQueryTool(config=config)
results = query.search("authentication", max_results=20)
print(query.quick_overview())
```

## Development

```bash
# Clone and install in dev mode
git clone https://github.com/dougallpress/doug.git
cd doug
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=doug

# Lint
ruff check doug/ tests/

# Type check
mypy doug/
```

## Who is Doug?

Doug has an innie and an outie, like in *Severance*. You're talking to the innie — he lives here in the code, indexing repos and answering queries. The outie? He's into birds, pickleball, CrossFit, outdoor adventures, board games, fantasy & sci-fi, fitness, and dogs. The innie doesn't remember any of that, but sometimes he gets a weird urge to name variables after birds. Don't ask.

## License

MIT — see [LICENSE](LICENSE) for details.

## Contributing

PRs welcome. Doug promises to review them with only moderate snark.
