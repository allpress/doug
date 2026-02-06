"""
Repository indexing engine for Doug.

Generates structured JSON indexes of repository contents including
source files, API endpoints, build systems, and directory trees.
Supports parallel indexing and language-agnostic file parsing.

I read all your code so the AI doesn't have to scroll through
10,000 files wondering where UserController lives. You're welcome.
"""

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from doug.config import DougConfig

logger = logging.getLogger(__name__)

# --- API Endpoint Detection Patterns ---

_SPRING_CLASS_MAPPING = re.compile(
    r'@(?:Request|Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.MULTILINE,
)
_SPRING_REST_CONTROLLER = re.compile(r"@(?:Rest)?Controller", re.MULTILINE)
_SPRING_METHOD_MAPPING = re.compile(
    r'@(Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.MULTILINE,
)
_SPRING_REQUEST_MAPPING = re.compile(
    r'@RequestMapping\(\s*(?:.*?method\s*=\s*RequestMethod\.(\w+))?.*?(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.MULTILINE | re.DOTALL,
)

_EXPRESS_ROUTE = re.compile(
    r"(?:app|router)\.(get|post|put|delete|patch|all)\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE | re.IGNORECASE,
)

_FLASK_ROUTE = re.compile(
    r"@(?:app|blueprint|bp)\.(route|get|post|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE | re.IGNORECASE,
)
_FLASK_METHODS = re.compile(
    r"methods\s*=\s*\[([^\]]+)\]",
    re.MULTILINE,
)

_FASTAPI_ROUTE = re.compile(
    r"@(?:app|router)\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE | re.IGNORECASE,
)

_GO_ROUTE = re.compile(
    r"(?:Handle|HandleFunc|GET|POST|PUT|DELETE|PATCH)\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

# --- File Classification Patterns ---
# Match against stem; use a lookahead/lookbehind to handle camelCase
# e.g. "UserController" should match Controller

_CONTROLLER_PATTERNS = re.compile(
    r"(?:Controller|Handler|Resource|Endpoint|Router)\b",
    re.IGNORECASE,
)
_SERVICE_PATTERNS = re.compile(
    r"(?:Service|Manager|Provider|Processor|Worker|UseCase)\b",
    re.IGNORECASE,
)
_REPOSITORY_PATTERNS = re.compile(
    r"(?:Repository|Repo|DAO|DataAccess|Store|Gateway)\b",
    re.IGNORECASE,
)
_MODEL_PATTERNS = re.compile(
    r"(?:Model|Entity|DTO|Schema|Domain|Record|Pojo)\b",
    re.IGNORECASE,
)
_TEST_PATTERNS = re.compile(
    r"(?:Test\b|Spec\b|test_|_test\.|\.test\.|\.spec\.)",
    re.IGNORECASE,
)


def _md5_hash(content: str) -> str:
    """Generate MD5 hash of content for change detection."""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


def _classify_file(file_path: Path, content: str = "") -> Optional[str]:
    """Classify a source file by its role."""
    # Use the stem for name-based classification to avoid extension matching
    stem = file_path.stem
    full_path = str(file_path)

    if _TEST_PATTERNS.search(stem) or "/test" in full_path.lower():
        return "test"
    if _CONTROLLER_PATTERNS.search(stem):
        return "controller"
    if _SERVICE_PATTERNS.search(stem):
        return "service"
    if _REPOSITORY_PATTERNS.search(stem):
        return "repository"
    if _MODEL_PATTERNS.search(stem):
        return "model"

    # Check content for annotations/decorators
    if content:
        if _SPRING_REST_CONTROLLER.search(content):
            return "controller"
        if re.search(r"@Service|@Component", content):
            return "service"
        if re.search(r"@Repository|@Mapper", content):
            return "repository"
        if re.search(r"@Entity|@Table|@Document", content):
            return "model"

    return None


def _extract_api_endpoints(content: str, file_path: Path) -> List[Dict[str, str]]:
    """Extract API endpoints from source code."""
    endpoints: List[Dict[str, str]] = []
    ext = file_path.suffix.lower()
    rel_path = str(file_path)

    if ext in (".java", ".kt"):
        class_path = ""
        class_mapping = re.search(
            r'@RequestMapping\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
            content,
        )
        if class_mapping:
            class_path = class_mapping.group(1).rstrip("/")

        for match in _SPRING_METHOD_MAPPING.finditer(content):
            method = match.group(1).upper()
            path = match.group(2)
            full_path = f"{class_path}/{path}".replace("//", "/")
            endpoints.append({"method": method, "path": full_path, "file": rel_path})

        for match in _SPRING_REQUEST_MAPPING.finditer(content):
            method = (match.group(1) or "GET").upper()
            path = match.group(2)
            if path != class_path:
                full_path = f"{class_path}/{path}".replace("//", "/")
                endpoints.append({"method": method, "path": full_path, "file": rel_path})

    elif ext in (".js", ".ts", ".mjs"):
        for match in _EXPRESS_ROUTE.finditer(content):
            method = match.group(1).upper()
            path = match.group(2)
            endpoints.append({"method": method, "path": path, "file": rel_path})

    elif ext == ".py":
        for match in _FLASK_ROUTE.finditer(content):
            method_or_route = match.group(1).upper()
            path = match.group(2)
            if method_or_route == "ROUTE":
                methods_match = _FLASK_METHODS.search(content[match.start():])
                if methods_match:
                    methods = [
                        m.strip().strip("'\"")
                        for m in methods_match.group(1).split(",")
                    ]
                    for m in methods:
                        endpoints.append({"method": m.upper(), "path": path, "file": rel_path})
                else:
                    endpoints.append({"method": "GET", "path": path, "file": rel_path})
            else:
                endpoints.append({"method": method_or_route, "path": path, "file": rel_path})

        for match in _FASTAPI_ROUTE.finditer(content):
            method = match.group(1).upper()
            path = match.group(2)
            endpoints.append({"method": method, "path": path, "file": rel_path})

    elif ext == ".go":
        for match in _GO_ROUTE.finditer(content):
            path = match.group(1)
            line_start = content.rfind("\n", 0, match.start()) + 1
            line = content[line_start: match.end()]
            method = "GET"
            for m in ("POST", "PUT", "DELETE", "PATCH"):
                if m in line.upper():
                    method = m
                    break
            endpoints.append({"method": method, "path": path, "file": rel_path})

    return endpoints


def _detect_build_system(repo_path: Path) -> Dict[str, Any]:
    """Detect the build system used by a repository."""
    build_info: Dict[str, Any] = {"type": "unknown", "dependencies": []}

    for gradle_file in ("build.gradle", "build.gradle.kts"):
        gradle_path = repo_path / gradle_file
        if gradle_path.exists():
            build_info["type"] = "gradle"
            try:
                content = gradle_path.read_text(errors="replace")
                deps = re.findall(
                    r"(?:implementation|api|compile)\s*['\"]([^'\"]+)['\"]",
                    content,
                )
                build_info["dependencies"] = [
                    {"name": d, "scope": "compile"} for d in deps[:50]
                ]
            except OSError:
                pass
            return build_info

    pom_path = repo_path / "pom.xml"
    if pom_path.exists():
        build_info["type"] = "maven"
        try:
            content = pom_path.read_text(errors="replace")
            deps = re.findall(
                r"<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>",
                content,
            )
            build_info["dependencies"] = [
                {"name": f"{g}:{a}", "scope": "compile"} for g, a in deps[:50]
            ]
        except OSError:
            pass
        return build_info

    package_json = repo_path / "package.json"
    if package_json.exists():
        build_info["type"] = "npm"
        try:
            data = json.loads(package_json.read_text(errors="replace"))
            deps = []
            for dep_type in ("dependencies", "devDependencies"):
                for name, version in data.get(dep_type, {}).items():
                    deps.append({"name": name, "version": version, "scope": dep_type})
            build_info["dependencies"] = deps[:100]
        except (json.JSONDecodeError, OSError):
            pass
        return build_info

    for py_build in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile"):
        py_path = repo_path / py_build
        if py_path.exists():
            build_info["type"] = "pip"
            if py_build == "requirements.txt":
                try:
                    content = py_path.read_text(errors="replace")
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("-"):
                            name = re.split(r"[>=<!\[]", line)[0].strip()
                            if name:
                                build_info["dependencies"].append(
                                    {"name": name, "scope": "runtime"}
                                )
                except OSError:
                    pass
            return build_info

    go_mod = repo_path / "go.mod"
    if go_mod.exists():
        build_info["type"] = "go"
        try:
            content = go_mod.read_text(errors="replace")
            deps = re.findall(r"^\s+(\S+)\s+v(\S+)", content, re.MULTILINE)
            build_info["dependencies"] = [
                {"name": d, "version": v, "scope": "runtime"} for d, v in deps[:50]
            ]
        except OSError:
            pass
        return build_info

    cargo_toml = repo_path / "Cargo.toml"
    if cargo_toml.exists():
        build_info["type"] = "cargo"
        return build_info

    return build_info


class RepoIndexer:
    """Indexes a single repository into structured JSON."""

    def __init__(self, repo_path: Path, config: Optional[DougConfig] = None):
        self.repo_path = repo_path.resolve()
        self.config = config or DougConfig()
        self.skip_dirs = set(self.config.skip_dirs)
        self.source_extensions = set(self.config.source_extensions)
        self.config_extensions = set(self.config.config_extensions)

    def index(self) -> Dict[str, Any]:
        logger.info("Indexing repository: %s", self.repo_path.name)

        all_files: List[Dict[str, Any]] = []
        source_files: List[Dict[str, Any]] = []
        api_endpoints: List[Dict[str, str]] = []
        controllers: List[Dict[str, Any]] = []
        services: List[Dict[str, Any]] = []
        repositories: List[Dict[str, Any]] = []
        models: List[Dict[str, Any]] = []
        tests: List[Dict[str, Any]] = []
        configs: List[Dict[str, Any]] = []

        # Single walk — build tree simultaneously
        tree: Dict[str, Any] = {"dirs": {}, "files": []}

        for file_path in self._walk_files():
            file_info = self._analyze_file(file_path)
            if file_info is None:
                continue

            all_files.append(file_info)

            # Build tree during walk (avoids second traversal)
            try:
                rel = file_path.relative_to(self.repo_path)
                parts = rel.parts
                node = tree
                for part in parts[:-1]:
                    if part not in node["dirs"]:
                        node["dirs"][part] = {"dirs": {}, "files": []}
                    node = node["dirs"][part]
                node["files"].append(parts[-1])
            except ValueError:
                pass

            ext = file_path.suffix.lower()
            if ext in self.source_extensions:
                source_files.append(file_info)

                classification = file_info.get("type")
                if classification == "controller":
                    controllers.append(file_info)
                elif classification == "service":
                    services.append(file_info)
                elif classification == "repository":
                    repositories.append(file_info)
                elif classification == "model":
                    models.append(file_info)
                elif classification == "test":
                    tests.append(file_info)

                if file_info.get("endpoints"):
                    api_endpoints.extend(file_info["endpoints"])

            elif ext in self.config_extensions:
                configs.append(file_info)

        readme_content = self._read_readme()
        build_info = _detect_build_system(self.repo_path)

        cache_data: Dict[str, Any] = {
            "name": self.repo_path.name,
            "path": str(self.repo_path),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_files": len(all_files),
                "source_files": len(source_files),
                "controllers": len(controllers),
                "services": len(services),
                "repositories": len(repositories),
                "models": len(models),
                "tests": len(tests),
                "configs": len(configs),
                "api_endpoints": len(api_endpoints),
            },
            "structure": tree,
            "apis": api_endpoints,
            "services": [self._slim_file_info(f) for f in services],
            "models": [self._slim_file_info(f) for f in models],
            "controllers": [self._slim_file_info(f) for f in controllers],
            "configs": [self._slim_file_info(f) for f in configs],
            "build": build_info,
            "readme": readme_content,
        }

        return cache_data

    def _walk_files(self) -> List[Path]:
        files: List[Path] = []
        max_depth = self.config.max_depth
        max_size = self.config.max_file_size_kb * 1024

        for item in self.repo_path.rglob("*"):
            if not item.is_file():
                continue

            try:
                rel = item.relative_to(self.repo_path)
            except ValueError:
                continue

            if len(rel.parts) > max_depth:
                continue

            if any(part in self.skip_dirs for part in rel.parts):
                continue

            try:
                if item.stat().st_size > max_size:
                    continue
            except OSError:
                continue

            files.append(item)

        return files

    def _analyze_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        try:
            rel_path = file_path.relative_to(self.repo_path)
        except ValueError:
            return None

        ext = file_path.suffix.lower()
        is_source = ext in self.source_extensions
        is_config = ext in self.config_extensions

        if not is_source and not is_config:
            try:
                stat = file_path.stat()
            except OSError:
                return None
            return {
                "path": str(rel_path),
                "name": file_path.name,
                "extension": ext,
                "size": stat.st_size,
            }

        content = ""
        try:
            content = file_path.read_text(errors="replace")
        except OSError:
            return None

        try:
            stat = file_path.stat()
        except OSError:
            return None

        file_info: Dict[str, Any] = {
            "path": str(rel_path),
            "name": file_path.name,
            "extension": ext,
            "size": stat.st_size,
            "hash": _md5_hash(content),
            "lines": content.count("\n") + 1,
        }

        if is_source:
            classification = _classify_file(rel_path, content)
            if classification:
                file_info["type"] = classification

            package = self._extract_package(content, ext)
            if package:
                file_info["package"] = package

            primary_class = self._extract_primary_class(content, ext)
            if primary_class:
                file_info["class"] = primary_class

            endpoints = _extract_api_endpoints(content, rel_path)
            if endpoints:
                file_info["endpoints"] = endpoints

        return file_info

    def _extract_package(self, content: str, ext: str) -> Optional[str]:
        if ext in (".java", ".kt"):
            match = re.search(r"^package\s+([\w.]+)", content, re.MULTILINE)
            return match.group(1) if match else None
        if ext == ".go":
            match = re.search(r"^package\s+(\w+)", content, re.MULTILINE)
            return match.group(1) if match else None
        return None

    def _extract_primary_class(self, content: str, ext: str) -> Optional[str]:
        if ext in (".java", ".kt"):
            match = re.search(
                r"(?:public\s+)?(?:class|interface|enum|object)\s+(\w+)",
                content,
            )
            return match.group(1) if match else None
        if ext == ".py":
            match = re.search(r"^class\s+(\w+)", content, re.MULTILINE)
            return match.group(1) if match else None
        if ext in (".ts", ".js"):
            match = re.search(
                r"(?:export\s+)?(?:default\s+)?class\s+(\w+)",
                content,
            )
            return match.group(1) if match else None
        if ext == ".go":
            match = re.search(r"type\s+(\w+)\s+struct", content)
            return match.group(1) if match else None
        return None

    def _read_readme(self) -> Optional[str]:
        for name in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
            readme_path = self.repo_path / name
            if readme_path.exists():
                try:
                    content = readme_path.read_text(errors="replace")
                    max_chars = self.config.readme_max_chars
                    if len(content) > max_chars:
                        content = content[:max_chars] + "\n\n... (truncated)"
                    return content
                except OSError:
                    pass
        return None

    @staticmethod
    def _slim_file_info(file_info: Dict[str, Any]) -> Dict[str, Any]:
        slim = {
            "path": file_info["path"],
            "name": file_info["name"],
        }
        for key in ("class", "package", "type", "lines"):
            if key in file_info:
                slim[key] = file_info[key]
        return slim


class GlobalIndexer:
    """Creates global indexes across all repositories."""

    def __init__(self, config: Optional[DougConfig] = None):
        self.config = config or DougConfig()
        self.cache_dir = self.config.repo_cache_dir
        self.index_dir = self.config.index_cache_dir
        self.repos_dir = self.config.repos_dir

    def index_all(self, parallel: Optional[int] = None) -> Dict[str, Any]:
        workers = parallel or self.config.parallel_workers
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        repo_paths = self._find_repos()
        if not repo_paths:
            logger.warning("No repositories found to index")
            return {"total_repos": 0, "repos": {}}

        results: Dict[str, Dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.index_repo, repo_path): repo_path
                for repo_path in repo_paths
            }

            for future in as_completed(futures):
                repo_path = futures[future]
                try:
                    cache_data = future.result()
                    if cache_data:
                        results[cache_data["name"]] = cache_data
                        logger.info("Indexed: %s", cache_data["name"])
                except Exception as e:
                    logger.error("Failed to index %s: %s", repo_path.name, e)

        global_index = self._build_global_index(results)
        apis_index = self._build_apis_index(results)
        quick_ref = self._build_quick_ref(results)

        self._save_json(self.index_dir / "global_index.json", global_index)
        self._save_json(self.index_dir / "apis.json", apis_index)
        self._save_json(self.index_dir / "repos_quick_ref.json", quick_ref)

        return global_index

    def index_repo(self, repo_path: Path) -> Optional[Dict[str, Any]]:
        try:
            indexer = RepoIndexer(repo_path, self.config)
            cache_data = indexer.index()

            cache_file = self.cache_dir / f"{repo_path.name}.json"
            self._save_json(cache_file, cache_data)

            return cache_data
        except Exception as e:
            logger.error("Error indexing %s: %s", repo_path.name, e)
            return None

    def _find_repos(self) -> List[Path]:
        if not self.repos_dir.exists():
            return []

        return sorted(
            p for p in self.repos_dir.iterdir()
            if p.is_dir() and (p / ".git").exists()
        )

    def _build_global_index(self, results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        total_files = sum(r["summary"]["total_files"] for r in results.values())
        total_source = sum(r["summary"]["source_files"] for r in results.values())
        total_apis = sum(r["summary"]["api_endpoints"] for r in results.values())

        repos_summary: Dict[str, Any] = {}
        for name, data in sorted(results.items()):
            repos_summary[name] = {
                "files": data["summary"]["total_files"],
                "source_files": data["summary"]["source_files"],
                "apis": data["summary"]["api_endpoints"],
                "controllers": data["summary"]["controllers"],
                "services": data["summary"]["services"],
                "build_type": data["build"]["type"],
            }

        return {
            "total_repos": len(results),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "total_files": total_files,
            "total_source_files": total_source,
            "total_apis": total_apis,
            "repos": repos_summary,
        }

    def _build_apis_index(self, results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        all_apis: List[Dict[str, str]] = []
        for name, data in sorted(results.items()):
            for endpoint in data.get("apis", []):
                api = dict(endpoint)
                api["repo"] = name
                all_apis.append(api)

        return {
            "total_apis": len(all_apis),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "endpoints": all_apis,
        }

    def _build_quick_ref(self, results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        refs: Dict[str, Any] = {}
        for name, data in sorted(results.items()):
            refs[name] = {
                "summary": data["summary"],
                "build_type": data["build"]["type"],
                "readme_excerpt": (data.get("readme") or "")[:500],
            }

        return {
            "total_repos": len(refs),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "repos": refs,
        }

    @staticmethod
    def _save_json(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
