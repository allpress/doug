"""Tests for doug.indexer module."""

import json
import shutil
from pathlib import Path

import pytest

from doug.config import DougConfig
from doug.indexer import (
    GlobalIndexer,
    RepoIndexer,
    _classify_file,
    _detect_build_system,
    _extract_api_endpoints,
    _md5_hash,
)


class TestMd5Hash:
    def test_consistent(self):
        assert _md5_hash("hello") == _md5_hash("hello")

    def test_different_inputs(self):
        assert _md5_hash("hello") != _md5_hash("world")

    def test_empty_string(self):
        result = _md5_hash("")
        assert isinstance(result, str)
        assert len(result) == 32


class TestClassifyFile:
    def test_controller(self):
        assert _classify_file(Path("UserController.java")) == "controller"

    def test_service(self):
        assert _classify_file(Path("UserService.java")) == "service"

    def test_repository(self):
        assert _classify_file(Path("UserRepository.java")) == "repository"

    def test_model(self):
        assert _classify_file(Path("UserEntity.java")) == "model"

    def test_test_file(self):
        assert _classify_file(Path("test_user.py")) == "test"
        assert _classify_file(Path("UserTest.java")) == "test"
        assert _classify_file(Path("user.spec.ts")) == "test"

    def test_handler(self):
        assert _classify_file(Path("UserHandler.go")) == "controller"

    def test_unknown(self):
        assert _classify_file(Path("utils.py")) is None

    def test_content_spring_controller(self):
        content = '@RestController\npublic class UserApi {}'
        assert _classify_file(Path("UserApi.java"), content) == "controller"

    def test_content_spring_entity(self):
        content = '@Entity\npublic class User {}'
        assert _classify_file(Path("User.java"), content) == "model"

    def test_test_dir_path(self):
        assert _classify_file(Path("src/test/java/Helper.java")) == "test"


class TestExtractApiEndpoints:
    def test_spring_get_mapping(self):
        content = '''
@RestController
@RequestMapping("/api/v1")
public class UserController {
    @GetMapping("/users")
    public List<User> getUsers() { }

    @PostMapping("/users")
    public User createUser() { }
}
'''
        endpoints = _extract_api_endpoints(content, Path("UserController.java"))
        methods = {e["method"] for e in endpoints}
        paths = {e["path"] for e in endpoints}
        assert "GET" in methods
        assert "POST" in methods
        assert "/api/v1/users" in paths

    def test_express_routes(self):
        content = '''
app.get('/api/users', getUsers);
app.post('/api/users', createUser);
router.delete('/api/users/:id', deleteUser);
'''
        endpoints = _extract_api_endpoints(content, Path("routes.js"))
        assert len(endpoints) == 3
        methods = {e["method"] for e in endpoints}
        assert methods == {"GET", "POST", "DELETE"}

    def test_fastapi_routes(self):
        content = '''
@app.get("/api/users")
async def get_users():
    pass

@router.post("/api/users")
async def create_user():
    pass
'''
        endpoints = _extract_api_endpoints(content, Path("main.py"))
        assert len(endpoints) >= 2
        methods = {e["method"] for e in endpoints}
        assert "GET" in methods
        assert "POST" in methods

    def test_flask_route(self):
        content = '''
@app.route('/api/users', methods=['GET', 'POST'])
def users():
    pass
'''
        endpoints = _extract_api_endpoints(content, Path("app.py"))
        assert len(endpoints) >= 1

    def test_no_endpoints(self):
        content = 'def helper_function():\n    pass\n'
        endpoints = _extract_api_endpoints(content, Path("utils.py"))
        assert endpoints == []

    def test_non_matching_extension(self):
        content = "some random content"
        endpoints = _extract_api_endpoints(content, Path("data.csv"))
        assert endpoints == []


class TestDetectBuildSystem:
    def test_gradle(self, tmp_path):
        (tmp_path / "build.gradle").write_text(
            "implementation 'org.springframework:spring-core:5.3.0'\n"
        )
        result = _detect_build_system(tmp_path)
        assert result["type"] == "gradle"
        assert len(result["dependencies"]) >= 1

    def test_gradle_kts(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text(
            'implementation("org.jetbrains.kotlin:kotlin-stdlib:1.8.0")\n'
        )
        result = _detect_build_system(tmp_path)
        assert result["type"] == "gradle"

    def test_maven(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><dependencies>"
            "<dependency><groupId>org.springframework</groupId>"
            "<artifactId>spring-core</artifactId></dependency>"
            "</dependencies></project>"
        )
        result = _detect_build_system(tmp_path)
        assert result["type"] == "maven"
        assert len(result["dependencies"]) >= 1

    def test_npm(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"express": "^4.18.0"},
            "devDependencies": {"jest": "^29.0.0"},
        }))
        result = _detect_build_system(tmp_path)
        assert result["type"] == "npm"
        assert len(result["dependencies"]) == 2

    def test_pip_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text(
            "flask>=2.0.0\nrequests\n# comment\nsqlalchemy>=1.4\n"
        )
        result = _detect_build_system(tmp_path)
        assert result["type"] == "pip"
        assert len(result["dependencies"]) == 3

    def test_pip_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "myproject"\n')
        result = _detect_build_system(tmp_path)
        assert result["type"] == "pip"

    def test_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text(
            "module example.com/myapp\n\ngo 1.21\n\nrequire (\n"
            "\tgithub.com/gin-gonic/gin v1.9.0\n)\n"
        )
        result = _detect_build_system(tmp_path)
        assert result["type"] == "go"

    def test_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"\n')
        result = _detect_build_system(tmp_path)
        assert result["type"] == "cargo"

    def test_unknown(self, tmp_path):
        result = _detect_build_system(tmp_path)
        assert result["type"] == "unknown"


@pytest.fixture
def sample_repo(tmp_path):
    """Create a sample repository structure for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    src = repo / "src" / "main" / "java" / "com" / "example"
    src.mkdir(parents=True)

    (src / "UserController.java").write_text(
        '@RestController\n@RequestMapping("/api/v1")\n'
        "public class UserController {\n"
        '    @GetMapping("/users")\n'
        "    public List<User> getUsers() {}\n}\n"
    )

    (src / "UserService.java").write_text(
        "@Service\npublic class UserService {\n"
        "    public List<User> findAll() {}\n}\n"
    )

    (src / "User.java").write_text(
        "@Entity\npublic class User {\n"
        "    private Long id;\n    private String name;\n}\n"
    )

    (repo / "application.yml").write_text("server:\n  port: 8080\n")

    (repo / "build.gradle").write_text(
        "implementation 'org.springframework.boot:spring-boot-starter-web:3.0.0'\n"
    )

    (repo / "README.md").write_text("# Test Repository\nThis is a test repo.\n")

    return repo


class TestRepoIndexer:
    def test_index_basic(self, sample_repo):
        config = DougConfig(base_path=sample_repo.parent / "doug")
        indexer = RepoIndexer(sample_repo, config=config)
        result = indexer.index()

        assert result["name"] == "test-repo"
        assert result["summary"]["total_files"] > 0
        assert result["summary"]["source_files"] > 0
        assert "indexed_at" in result
        assert result["build"]["type"] == "gradle"
        assert result["readme"] is not None
        assert "Test Repository" in result["readme"]

    def test_index_detects_apis(self, sample_repo):
        config = DougConfig(base_path=sample_repo.parent / "doug")
        indexer = RepoIndexer(sample_repo, config=config)
        result = indexer.index()

        assert len(result["apis"]) >= 1
        api_paths = {e["path"] for e in result["apis"]}
        assert any("/users" in p for p in api_paths)

    def test_index_classifies_files(self, sample_repo):
        config = DougConfig(base_path=sample_repo.parent / "doug")
        indexer = RepoIndexer(sample_repo, config=config)
        result = indexer.index()

        assert result["summary"]["controllers"] >= 1
        assert result["summary"]["services"] >= 1
        assert result["summary"]["models"] >= 1

    def test_index_builds_tree(self, sample_repo):
        config = DougConfig(base_path=sample_repo.parent / "doug")
        indexer = RepoIndexer(sample_repo, config=config)
        result = indexer.index()

        structure = result["structure"]
        assert "dirs" in structure
        assert "files" in structure
        assert "src" in structure["dirs"]

    def test_skips_git_dir(self, sample_repo):
        config = DougConfig(base_path=sample_repo.parent / "doug")
        indexer = RepoIndexer(sample_repo, config=config)
        result = indexer.index()

        assert ".git" not in result["structure"].get("dirs", {})


class TestGlobalIndexer:
    def test_index_all(self, sample_repo):
        base = sample_repo.parent / "doug"
        config = DougConfig(base_path=base)
        config.ensure_directories()

        dest = config.repos_dir / "test-repo"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(sample_repo, dest)

        indexer = GlobalIndexer(config=config)
        result = indexer.index_all()

        assert result["total_repos"] == 1
        assert "test-repo" in result["repos"]

        assert (config.index_cache_dir / "global_index.json").exists()
        assert (config.index_cache_dir / "apis.json").exists()
        assert (config.index_cache_dir / "repos_quick_ref.json").exists()
        assert (config.repo_cache_dir / "test-repo.json").exists()

    def test_index_single_repo(self, sample_repo):
        base = sample_repo.parent / "doug"
        config = DougConfig(base_path=base)
        config.ensure_directories()

        dest = config.repos_dir / "test-repo"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(sample_repo, dest)

        indexer = GlobalIndexer(config=config)
        result = indexer.index_repo(dest)

        assert result is not None
        assert result["name"] == "test-repo"
        assert (config.repo_cache_dir / "test-repo.json").exists()

    def test_index_all_empty(self, tmp_path):
        config = DougConfig(base_path=tmp_path / "doug")
        config.ensure_directories()

        indexer = GlobalIndexer(config=config)
        result = indexer.index_all()
        assert result["total_repos"] == 0
