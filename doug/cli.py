"""
Command-line interface for Doug.

Provides all user-facing commands for repository management,
indexing, querying, and plugin operations.

I'm Doug. I find your repos, index your code, and only judge
your variable names a little bit. Okay, a lot.
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from doug import __version__
from doug.config import DougConfig

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s" if not verbose else "%(levelname)s: %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _get_config(args: argparse.Namespace) -> DougConfig:
    """Build DougConfig from CLI args."""
    base_path = getattr(args, "base_path", None)
    if base_path:
        return DougConfig(base_path=Path(base_path))
    return DougConfig()


def _print_json(data: object) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def _print_results(results: dict) -> None:
    """Print clone/pull results with status indicators."""
    for msg in results.get("success", []):
        print(f"  ✅ {msg}")
    for msg in results.get("failed", []):
        print(f"  ❌ {msg}")

    total = len(results.get("success", [])) + len(results.get("failed", []))
    succeeded = len(results.get("success", []))
    failed = len(results.get("failed", []))
    print(f"\n  Total: {total} | Succeeded: {succeeded} | Failed: {failed}")


# ─── Command Handlers ────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    """Run the interactive setup wizard."""
    from doug.setup_wizard import SetupWizard

    config = _get_config(args)
    wizard = SetupWizard(config=config)
    wizard.run()
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    """Clone all configured repositories."""
    from doug.cache_manager import CacheManager

    config = _get_config(args)
    config.ensure_directories()
    manager = CacheManager(config=config)

    repos = manager.load_repository_configs()
    if not repos:
        print("No repositories configured. Run 'doug init' or 'doug add-repo <url>' first.")
        return 1

    force = getattr(args, "force", False)
    parallel = getattr(args, "parallel", None)
    total = len(repos)

    print(f"🤖 Cloning {total} repositories...")

    def on_progress(success, message, completed, total):
        icon = "✅" if success else "❌"
        print(f"  {icon} [{completed}/{total}] {message}")

    results = manager.clone_all(force=force, parallel=parallel, on_progress=on_progress)

    succeeded = len(results.get("success", []))
    failed = len(results.get("failed", []))
    print(f"\n  Done: {succeeded} succeeded, {failed} failed")

    return 0 if not results["failed"] else 1


def cmd_pull(args: argparse.Namespace) -> int:
    """Pull latest for all repositories."""
    from doug.cache_manager import CacheManager

    config = _get_config(args)
    manager = CacheManager(config=config)

    repos = manager.load_repository_configs()
    if not repos:
        print("No repositories configured.")
        return 1

    parallel = getattr(args, "parallel", None)

    print(f"🤖 Pulling updates for {len(repos)} repositories...")
    results = manager.pull_all(parallel=parallel)
    _print_results(results)

    return 0 if not results["failed"] else 1


def cmd_index(args: argparse.Namespace) -> int:
    """Index repositories into JSON caches."""
    from doug.indexer import GlobalIndexer

    config = _get_config(args)
    config.ensure_directories()
    indexer = GlobalIndexer(config=config)

    repo_name = getattr(args, "repo_name", None)
    parallel = getattr(args, "parallel", None)

    if repo_name:
        repo_path = config.repos_dir / repo_name
        if not repo_path.exists():
            print(f"Repository not found: {repo_name}")
            return 1

        print(f"🤖 Indexing {repo_name}...")
        result = indexer.index_repo(repo_path)
        if result:
            print(f"  ✅ Indexed: {repo_name}")
            print(f"     Files: {result['summary']['total_files']}")
            print(f"     Source: {result['summary']['source_files']}")
            print(f"     APIs: {result['summary']['api_endpoints']}")
            return 0
        else:
            print(f"  ❌ Failed to index {repo_name}")
            return 1
    else:
        cloned = indexer._find_repos()
        if not cloned:
            print("No repositories found. Run 'doug clone' first.")
            return 1

        print(f"🤖 Indexing {len(cloned)} repositories...")
        global_index = indexer.index_all(parallel=parallel)

        print(f"\n  ✅ Indexed {global_index['total_repos']} repositories")
        print(f"     Total files: {global_index.get('total_files', 0)}")
        print(f"     Source files: {global_index.get('total_source_files', 0)}")
        print(f"     API endpoints: {global_index.get('total_apis', 0)}")
        return 0


def cmd_add_repo(args: argparse.Namespace) -> int:
    """Add a repository URL to configuration."""
    from doug.cache_manager import CacheManager

    config = _get_config(args)
    config.ensure_directories()
    manager = CacheManager(config=config)

    url = args.url
    branch = getattr(args, "branch", None)

    success, message = manager.add_repo(url, branch=branch)
    if success:
        print(f"  ✅ {message}")
        return 0
    else:
        print(f"  ❌ {message}")
        return 1


def cmd_remove_repo(args: argparse.Namespace) -> int:
    """Remove a repository from configuration."""
    from doug.cache_manager import CacheManager

    config = _get_config(args)
    manager = CacheManager(config=config)

    success, message = manager.remove_repo(args.name)
    if success:
        print(f"  ✅ {message}")
        # Optionally remove cloned repo and cache
        if getattr(args, "purge", False):
            repo_path = config.repos_dir / args.name
            if repo_path.exists():
                shutil.rmtree(repo_path)
                print(f"  🗑️  Removed cloned repo: {repo_path}")
            cache_file = config.repo_cache_dir / f"{args.name}.json"
            if cache_file.exists():
                cache_file.unlink()
                print(f"  🗑️  Removed cache: {cache_file}")
        return 0
    else:
        print(f"  ❌ {message}")
        return 1


def cmd_query(args: argparse.Namespace) -> int:
    """Execute a query against the cache."""
    from doug.ai_query import AIQueryTool

    config = _get_config(args)
    query_tool = AIQueryTool(config=config)

    subcmd = args.query_command
    if not subcmd:
        print("No query subcommand specified. Use 'doug query --help' for options.")
        return 1

    if subcmd == "status":
        _print_json(query_tool.status())

    elif subcmd == "repos":
        repos = query_tool.list_repos()
        if repos:
            for r in repos:
                print(f"  • {r}")
        else:
            print("  No repositories cached.")

    elif subcmd == "apis":
        repo_name = getattr(args, "repo_name", None)
        apis = query_tool.list_apis(repo_name=repo_name)
        if getattr(args, "json_output", False):
            _print_json(apis)
        else:
            if not apis:
                print("  No API endpoints found.")
            else:
                for api in apis:
                    repo = api.get("repo", "")
                    prefix = f"[{repo}] " if repo else ""
                    print(f"  {prefix}{api['method']:6s} {api['path']}  ({api['file']})")

    elif subcmd == "search":
        query_str = args.term
        scope = getattr(args, "scope", "all")
        results = query_tool.search(query_str, scope=scope)
        if getattr(args, "json_output", False):
            _print_json(results)
        else:
            print(f"  Search: \"{query_str}\" ({results['total_matches']} matches)")
            for category, items in results.get("results", {}).items():
                print(f"\n  --- {category.upper()} ---")
                for item in items[:20]:  # Limit output
                    if category == "apis":
                        print(f"    [{item.get('repo')}] {item['method']} {item['path']}")
                    elif category == "files":
                        print(f"    [{item.get('repo')}] {item['path']}")
                    elif category == "classes":
                        print(f"    [{item.get('repo')}] {item.get('class')} ({item['path']})")
                    elif category == "readme_mentions":
                        print(f"    [{item.get('repo')}] ...{item.get('excerpt', '')[:100]}...")

    elif subcmd == "repo":
        repo_name = args.repo_name
        section = getattr(args, "section", None)
        if section:
            result = query_tool.repo_detail(repo_name, section)
        else:
            result = query_tool.repo_summary(repo_name)
        _print_json(result)

    elif subcmd == "overview":
        print(query_tool.quick_overview())

    elif subcmd == "find":
        repo_name = args.repo_name
        pattern = args.pattern
        result = query_tool.find_file(repo_name, pattern)
        _print_json(result)

    else:
        print(f"Unknown query command: {subcmd}")
        return 1

    return 0


def cmd_plugin(args: argparse.Namespace) -> int:
    """Plugin management commands."""
    from doug.plugins.base import PluginManager

    config = _get_config(args)
    config.ensure_directories()
    plugin_mgr = PluginManager(config=config)

    subcmd = args.plugin_command
    if not subcmd:
        print("No plugin subcommand specified. Use 'doug plugin --help' for options.")
        return 1

    if subcmd == "list":
        plugins = plugin_mgr.list_plugins()
        for p in plugins:
            status = "✅ enabled" if p.get("enabled") else "⬜ disabled"
            configured = "configured" if p.get("configured") else "not configured"
            print(f"  {p['name']:15s} {status}  ({configured})")
            if p.get("description"):
                print(f"    {p['description']}")

    elif subcmd == "enable":
        plugin_name = args.plugin_name
        config.enable_plugin(plugin_name, True)
        config.save()
        print(f"  ✅ Plugin '{plugin_name}' enabled")

    elif subcmd == "disable":
        plugin_name = args.plugin_name
        config.enable_plugin(plugin_name, False)
        config.save()
        print(f"  ⬜ Plugin '{plugin_name}' disabled")

    elif subcmd == "configure":
        plugin_name = args.plugin_name
        plugin = plugin_mgr.get_plugin(plugin_name)
        if not plugin:
            print(f"  ❌ Plugin not found: {plugin_name}")
            return 1
        success = plugin.setup()
        return 0 if success else 1

    elif subcmd == "run":
        plugin_name = args.plugin_name
        action = args.action
        # Collect extra keyword args from remaining args
        kwargs = {}
        remaining = getattr(args, "extra_args", []) or []
        for item in remaining:
            if "=" in item:
                k, v = item.split("=", 1)
                kwargs[k] = v
        result = plugin_mgr.execute_plugin(plugin_name, action, **kwargs)
        _print_json(result)

    else:
        print(f"Unknown plugin command: {subcmd}")
        return 1

    return 0


def cmd_rag(args: argparse.Namespace) -> int:
    """RAG (semantic search) commands."""
    from doug.rag.rag_engine import RAGEngine

    config = _get_config(args)
    engine = RAGEngine(config=config)

    subcmd = args.rag_command
    if not subcmd:
        print("No RAG subcommand specified. Use 'doug rag --help' for options.")
        return 1

    if subcmd == "status":
        _print_json(engine.get_status())

    elif subcmd == "index":
        repo_names = getattr(args, "repo_names", None)
        print("🤖 Indexing repositories into vector database...")
        result = engine.index_repositories(repo_names=repo_names)
        _print_json(result)

    elif subcmd == "search":
        query_str = args.term
        top_k = getattr(args, "top_k", 10)
        repo_filter = getattr(args, "repo", None)
        results = engine.search(query_str, top_k=top_k, repo_filter=repo_filter)
        if getattr(args, "json_output", False):
            _print_json(results)
        else:
            for r in results:
                if "error" in r:
                    print(f"  ❌ {r['error']}")
                else:
                    meta = r.get("metadata", {})
                    score = r.get("score", 0)
                    print(f"  [{score:.3f}] {meta.get('repo', '?')}:{meta.get('file', '?')}"
                          f" (L{meta.get('start_line', '?')}-{meta.get('end_line', '?')})")
                    # Show first 120 chars of text
                    text_preview = r.get("text", "")[:120].replace("\n", " ")
                    print(f"         {text_preview}")
                    print()

    elif subcmd == "clear":
        result = engine.clear()
        _print_json(result)

    else:
        print(f"Unknown RAG command: {subcmd}")
        return 1

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show overall system status."""
    from doug.ai_query import AIQueryTool
    from doug.cache_manager import CacheManager

    config = _get_config(args)
    manager = CacheManager(config=config)
    query_tool = AIQueryTool(config=config)

    print("🤖 Doug System Status")
    print("=" * 50)

    # Configuration
    config_status = config.get_status()
    print(f"\n  Base Path:       {config_status['base_path']}")
    print(f"  Config Exists:   {'✅' if config_status['config_exists'] else '❌'}")
    print(f"  Workers:         {config_status['parallel_workers']}")

    # Repositories
    cache_status = manager.get_cache_status()
    print(f"\n  Configured:      {cache_status['configured_repos']} repos")
    print(f"  Cloned:          {cache_status['cloned_repos']} repos")

    # Cache
    query_status = query_tool.status()
    print(f"  Cached/Indexed:  {query_status['cached_repos']} repos")
    if query_status.get("indexed_at"):
        print(f"  Last Indexed:    {query_status['indexed_at']}")
    if query_status.get("total_files"):
        print(f"  Total Files:     {query_status['total_files']}")
        print(f"  Source Files:    {query_status['total_source_files']}")
        print(f"  API Endpoints:   {query_status['total_apis']}")

    # Plugins
    print(f"\n  Plugins:")
    for name, enabled in config_status.get("plugins", {}).items():
        status = "✅ enabled" if enabled else "⬜ disabled"
        print(f"    {name:15s} {status}")

    print()
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    """Clean caches and/or cloned repos."""
    config = _get_config(args)

    target = getattr(args, "target", "cache")

    if target in ("cache", "all"):
        if config.cache_dir.exists():
            shutil.rmtree(config.cache_dir)
            config.cache_dir.mkdir(parents=True, exist_ok=True)
            print("  🗑️  Cache cleared")
        else:
            print("  Cache directory doesn't exist")

    if target in ("repos", "all"):
        if config.repos_dir.exists():
            shutil.rmtree(config.repos_dir)
            config.repos_dir.mkdir(parents=True, exist_ok=True)
            print("  🗑️  Cloned repositories removed")
        else:
            print("  Repositories directory doesn't exist")

    if target == "config":
        if config.config_dir.exists():
            shutil.rmtree(config.config_dir)
            print("  🗑️  Configuration cleared")

    return 0


# ─── Argument Parser ─────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="doug",
        description="🤖 Doug — Multi-repository context caching for AI coding assistants",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  doug init                     # Interactive setup wizard\n"
            "  doug add-repo <url>           # Add a repository\n"
            "  doug clone                    # Clone all configured repos\n"
            "  doug index                    # Index all repositories\n"
            "  doug query search \"users\"     # Search across repos\n"
            "  doug query apis               # List all API endpoints\n"
            "  doug rag search \"auth flow\"   # Semantic search across code\n"
            "  doug status                   # Show system status\n"
        ),
    )

    parser.add_argument(
        "--version", action="version", version=f"doug {__version__}"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--base-path", dest="base_path", help="Override Doug base directory"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ─── init ─────────────────────────────────
    subparsers.add_parser("init", help="Interactive setup wizard")

    # ─── clone ────────────────────────────────
    clone_parser = subparsers.add_parser("clone", help="Clone all configured repositories")
    clone_parser.add_argument(
        "-f", "--force", action="store_true", help="Force re-clone existing repos"
    )
    clone_parser.add_argument(
        "-p", "--parallel", type=int, help="Number of parallel workers"
    )

    # ─── pull ─────────────────────────────────
    pull_parser = subparsers.add_parser("pull", help="Pull latest for all repositories")
    pull_parser.add_argument(
        "-p", "--parallel", type=int, help="Number of parallel workers"
    )

    # ─── index ────────────────────────────────
    index_parser = subparsers.add_parser("index", help="Index repositories into JSON caches")
    index_parser.add_argument(
        "repo_name", nargs="?", help="Index a specific repository (optional)"
    )
    index_parser.add_argument(
        "-p", "--parallel", type=int, help="Number of parallel workers"
    )

    # ─── add-repo ─────────────────────────────
    add_parser = subparsers.add_parser("add-repo", help="Add a repository URL")
    add_parser.add_argument("url", help="Git repository URL")
    add_parser.add_argument(
        "-b", "--branch", help="Default branch override"
    )

    # ─── remove-repo ──────────────────────────
    remove_parser = subparsers.add_parser("remove-repo", help="Remove a repository")
    remove_parser.add_argument("name", help="Repository name or URL")
    remove_parser.add_argument(
        "--purge", action="store_true", help="Also delete cloned repo and cache"
    )

    # ─── query ────────────────────────────────
    query_parser = subparsers.add_parser("query", help="Query cached repositories")
    query_sub = query_parser.add_subparsers(dest="query_command", help="Query commands")

    query_sub.add_parser("status", help="Cache status overview")
    query_sub.add_parser("repos", help="List all cached repositories")
    query_sub.add_parser("overview", help="Text overview of all repositories")

    # query apis
    apis_parser = query_sub.add_parser("apis", help="List API endpoints")
    apis_parser.add_argument("repo_name", nargs="?", help="Filter by repository")
    apis_parser.add_argument("-j", "--json", dest="json_output", action="store_true")

    # query search
    search_parser = query_sub.add_parser("search", help="Search across repositories")
    search_parser.add_argument("term", help="Search term")
    search_parser.add_argument(
        "-s", "--scope", choices=["all", "files", "apis", "classes"], default="all"
    )
    search_parser.add_argument("-j", "--json", dest="json_output", action="store_true")

    # query repo
    repo_parser = query_sub.add_parser("repo", help="Repository details")
    repo_parser.add_argument("repo_name", help="Repository name")
    repo_parser.add_argument(
        "section", nargs="?",
        choices=["apis", "services", "models", "controllers", "configs",
                 "structure", "build", "summary", "readme"],
        help="Specific section to view"
    )

    # query find
    find_parser = query_sub.add_parser("find", help="Find files in a repository")
    find_parser.add_argument("repo_name", help="Repository name")
    find_parser.add_argument("pattern", help="File name or path pattern")

    # ─── rag ──────────────────────────────────
    rag_parser = subparsers.add_parser("rag", help="RAG semantic search commands")
    rag_sub = rag_parser.add_subparsers(dest="rag_command", help="RAG commands")

    rag_sub.add_parser("status", help="RAG engine status")

    rag_index_parser = rag_sub.add_parser("index", help="Index repos into vector database")
    rag_index_parser.add_argument(
        "repo_names", nargs="*", help="Specific repos to index (default: all)"
    )

    rag_search_parser = rag_sub.add_parser("search", help="Semantic code search")
    rag_search_parser.add_argument("term", help="Natural language search query")
    rag_search_parser.add_argument(
        "-k", "--top-k", type=int, default=10, dest="top_k",
        help="Number of results (default: 10)"
    )
    rag_search_parser.add_argument(
        "-r", "--repo", help="Filter by repository"
    )
    rag_search_parser.add_argument("-j", "--json", dest="json_output", action="store_true")

    rag_sub.add_parser("clear", help="Clear RAG vector database")

    # ─── plugin ───────────────────────────────
    plugin_parser = subparsers.add_parser("plugin", help="Plugin management")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command", help="Plugin commands")

    plugin_sub.add_parser("list", help="List available plugins")

    enable_parser = plugin_sub.add_parser("enable", help="Enable a plugin")
    enable_parser.add_argument("plugin_name", help="Plugin name")

    disable_parser = plugin_sub.add_parser("disable", help="Disable a plugin")
    disable_parser.add_argument("plugin_name", help="Plugin name")

    configure_parser = plugin_sub.add_parser("configure", help="Configure a plugin")
    configure_parser.add_argument("plugin_name", help="Plugin name")

    run_parser = plugin_sub.add_parser("run", help="Run a plugin action")
    run_parser.add_argument("plugin_name", help="Plugin name")
    run_parser.add_argument("action", help="Action to execute")
    run_parser.add_argument(
        "extra_args", nargs="*", help="Extra key=value arguments"
    )

    # ─── status ───────────────────────────────
    subparsers.add_parser("status", help="Show overall system status")

    # ─── clean ────────────────────────────────
    clean_parser = subparsers.add_parser("clean", help="Clean caches and data")
    clean_parser.add_argument(
        "target", nargs="?", default="cache",
        choices=["cache", "repos", "config", "all"],
        help="What to clean (default: cache)"
    )

    return parser


# ─── Main Entry Point ────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    _setup_logging(verbose=getattr(args, "verbose", False))

    command = args.command

    if not command:
        parser.print_help()
        return 0

    handlers = {
        "init": cmd_init,
        "clone": cmd_clone,
        "pull": cmd_pull,
        "index": cmd_index,
        "add-repo": cmd_add_repo,
        "remove-repo": cmd_remove_repo,
        "query": cmd_query,
        "plugin": cmd_plugin,
        "rag": cmd_rag,
        "status": cmd_status,
        "clean": cmd_clean,
    }

    handler = handlers.get(command)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 130
    except Exception as e:
        if getattr(args, "verbose", False):
            logger.exception("Error: %s", e)
        else:
            print(f"\n❌ Error: {e}")
            print("   Run with -v for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
