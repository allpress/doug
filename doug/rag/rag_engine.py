"""
RAG (Retrieval-Augmented Generation) engine for Doug.

Provides optional semantic search across indexed repositories
using embeddings and a lightweight vector database.

Requires optional dependencies:
    pip install doug[rag]
"""

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from doug.config import DougConfig

logger = logging.getLogger(__name__)

# Chunk size for splitting code into indexable segments
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_TOP_K = 10


def _check_rag_dependencies() -> Tuple[bool, str]:
    """Check if RAG dependencies are installed."""
    missing = []
    try:
        import chromadb  # noqa: F401
    except ImportError:
        missing.append("chromadb")

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError:
        missing.append("sentence-transformers")

    if missing:
        return False, (
            f"Missing RAG dependencies: {', '.join(missing)}. "
            f"Install with: pip install doug[rag]"
        )
    return True, "RAG dependencies available"


class CodeChunker:
    """Splits source code into indexable chunks.

    Uses a combination of structural awareness (function/class boundaries)
    and sliding-window chunking for files that don't have clear structure.
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_file(
        self,
        content: str,
        file_path: str,
        repo_name: str,
    ) -> List[Dict[str, Any]]:
        """Split a file into chunks with metadata.

        Args:
            content: File content.
            file_path: Relative path within the repository.
            repo_name: Repository name.

        Returns:
            List of chunk dicts with 'text', 'metadata', and 'id' keys.
        """
        if not content.strip():
            return []

        lines = content.split("\n")

        # Try structural chunking first (by function/class)
        structural = self._structural_chunks(lines, file_path, repo_name)
        if structural:
            return structural

        # Fall back to sliding window
        return self._sliding_window_chunks(lines, file_path, repo_name)

    def _structural_chunks(
        self,
        lines: List[str],
        file_path: str,
        repo_name: str,
    ) -> List[Dict[str, Any]]:
        """Try to chunk by function/class boundaries."""
        chunks: List[Dict[str, Any]] = []

        # Detect structural boundaries
        boundary_patterns = [
            re.compile(r"^(?:def|class|async def)\s+\w+", re.MULTILINE),  # Python
            re.compile(r"^(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|enum)\s+\w+"),  # Java
            re.compile(r"^(?:export\s+)?(?:default\s+)?(?:function|class|const)\s+\w+"),  # JS/TS
            re.compile(r"^func\s+(?:\([^)]*\)\s*)?\w+"),  # Go
        ]

        boundaries: List[int] = [0]
        for i, line in enumerate(lines):
            for pattern in boundary_patterns:
                if pattern.match(line.strip()):
                    if i > 0 and i not in boundaries:
                        boundaries.append(i)
                    break

        if len(boundaries) < 2:
            return []  # No structural boundaries found

        boundaries.append(len(lines))

        for idx in range(len(boundaries) - 1):
            start = boundaries[idx]
            end = boundaries[idx + 1]
            chunk_lines = lines[start:end]
            text = "\n".join(chunk_lines).strip()

            if not text or len(text) < 20:
                continue

            # If chunk is too large, further split
            if len(text) > self.chunk_size * 3:
                sub_chunks = self._sliding_window_chunks(
                    chunk_lines, file_path, repo_name, start_line=start
                )
                chunks.extend(sub_chunks)
            else:
                chunk_id = f"{repo_name}:{file_path}:{start}-{end}"
                chunks.append({
                    "id": chunk_id,
                    "text": text,
                    "metadata": {
                        "repo": repo_name,
                        "file": file_path,
                        "start_line": start + 1,
                        "end_line": end,
                        "type": "structural",
                    },
                })

        return chunks

    def _sliding_window_chunks(
        self,
        lines: List[str],
        file_path: str,
        repo_name: str,
        start_line: int = 0,
    ) -> List[Dict[str, Any]]:
        """Chunk using a sliding window approach."""
        chunks: List[Dict[str, Any]] = []
        text = "\n".join(lines)

        pos = 0
        chunk_idx = 0
        while pos < len(text):
            end = pos + self.chunk_size
            chunk_text = text[pos:end].strip()

            if chunk_text:
                # Calculate approximate line numbers
                lines_before = text[:pos].count("\n")
                lines_in = chunk_text.count("\n")

                chunk_id = f"{repo_name}:{file_path}:w{chunk_idx}"
                chunks.append({
                    "id": chunk_id,
                    "text": chunk_text,
                    "metadata": {
                        "repo": repo_name,
                        "file": file_path,
                        "start_line": start_line + lines_before + 1,
                        "end_line": start_line + lines_before + lines_in + 1,
                        "type": "window",
                    },
                })

            pos += self.chunk_size - self.chunk_overlap
            chunk_idx += 1

        return chunks


class RAGEngine:
    """Semantic search engine for repository code.

    Uses sentence-transformers for embeddings and ChromaDB for
    vector storage. Falls back gracefully when dependencies
    are not installed.
    """

    def __init__(
        self,
        config: Optional[DougConfig] = None,
        embedding_model: str = "all-MiniLM-L6-v2",
        collection_name: str = "doug_code",
    ):
        """Initialize the RAG engine.

        Args:
            config: Doug configuration.
            embedding_model: Sentence-transformers model name.
            collection_name: ChromaDB collection name.
        """
        self.config = config or DougConfig()
        self.rag_dir = self.config.cache_dir / "rag"
        self.rag_dir.mkdir(parents=True, exist_ok=True)

        self.embedding_model_name = embedding_model
        self.collection_name = collection_name
        self.chunker = CodeChunker()

        self._model = None
        self._client = None
        self._collection = None

    def _ensure_ready(self) -> Tuple[bool, str]:
        """Ensure RAG dependencies are loaded and ready."""
        ok, msg = _check_rag_dependencies()
        if not ok:
            return False, msg

        try:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.embedding_model_name)

            if self._client is None:
                import chromadb
                self._client = chromadb.PersistentClient(
                    path=str(self.rag_dir / "chromadb")
                )
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )

            return True, "RAG engine ready"
        except Exception as e:
            return False, f"RAG initialization failed: {e}"

    def index_repositories(
        self,
        repo_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Index repositories into the vector database.

        Reads from Doug's JSON cache files, chunks code,
        generates embeddings, and stores in ChromaDB.

        Args:
            repo_names: Specific repos to index. None = all cached repos.

        Returns:
            Indexing results dict.
        """
        ok, msg = self._ensure_ready()
        if not ok:
            return {"error": msg}

        cache_dir = self.config.repo_cache_dir
        if not cache_dir.exists():
            return {"error": "No cached repositories. Run 'doug index' first."}

        # Find repos to index
        if repo_names:
            cache_files = [
                cache_dir / f"{name}.json"
                for name in repo_names
                if (cache_dir / f"{name}.json").exists()
            ]
        else:
            cache_files = sorted(cache_dir.glob("*.json"))

        if not cache_files:
            return {"error": "No repository caches found."}

        total_chunks = 0
        indexed_repos = []

        for cache_file in cache_files:
            try:
                repo_data = json.loads(cache_file.read_text())
                repo_name = repo_data["name"]
                repo_path = Path(repo_data["path"])

                chunks = self._index_repo_files(repo_name, repo_path)
                total_chunks += len(chunks)
                indexed_repos.append(repo_name)

                logger.info(
                    "RAG indexed %s: %d chunks", repo_name, len(chunks)
                )
            except Exception as e:
                logger.error("RAG indexing failed for %s: %s", cache_file.stem, e)

        return {
            "status": "indexed",
            "repos": indexed_repos,
            "total_chunks": total_chunks,
        }

    def _index_repo_files(self, repo_name: str, repo_path: Path) -> List[Dict[str, Any]]:
        """Index all source files in a repository."""
        all_chunks: List[Dict[str, Any]] = []
        source_extensions = set(self.config.source_extensions)
        skip_dirs = set(self.config.skip_dirs)

        if not repo_path.exists():
            return []

        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue

            try:
                rel_path = file_path.relative_to(repo_path)
            except ValueError:
                continue

            if any(part in skip_dirs for part in rel_path.parts):
                continue

            if file_path.suffix.lower() not in source_extensions:
                continue

            try:
                content = file_path.read_text(errors="replace")
                chunks = self.chunker.chunk_file(
                    content, str(rel_path), repo_name
                )
                all_chunks.extend(chunks)
            except OSError:
                continue

        # Batch insert into ChromaDB
        if all_chunks and self._collection is not None:
            batch_size = 100
            for i in range(0, len(all_chunks), batch_size):
                batch = all_chunks[i : i + batch_size]
                ids = [c["id"] for c in batch]
                texts = [c["text"] for c in batch]
                metadatas = [c["metadata"] for c in batch]

                # Generate embeddings
                embeddings = self._model.encode(texts).tolist()

                self._collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=metadatas,
                )

        return all_chunks

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        repo_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic search across indexed code.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.
            repo_filter: Optional repo name to filter results.

        Returns:
            List of search result dicts with 'text', 'metadata', 'score'.
        """
        ok, msg = self._ensure_ready()
        if not ok:
            return [{"error": msg}]

        if self._collection is None:
            return [{"error": "No indexed data"}]

        try:
            # Generate query embedding
            query_embedding = self._model.encode([query]).tolist()

            # Build where filter
            where_filter = None
            if repo_filter:
                where_filter = {"repo": repo_filter}

            # Search
            results = self._collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                where=where_filter,
            )

            # Format results
            formatted: List[Dict[str, Any]] = []
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    result = {
                        "text": doc,
                        "metadata": (
                            results["metadatas"][0][i]
                            if results.get("metadatas")
                            else {}
                        ),
                        "score": (
                            1.0 - results["distances"][0][i]
                            if results.get("distances")
                            else 0.0
                        ),
                    }
                    formatted.append(result)

            return formatted

        except Exception as e:
            logger.error("RAG search failed: %s", e)
            return [{"error": f"Search failed: {e}"}]

    def get_status(self) -> Dict[str, Any]:
        """Get RAG engine status."""
        ok, msg = _check_rag_dependencies()

        status: Dict[str, Any] = {
            "dependencies_available": ok,
            "message": msg,
            "rag_dir": str(self.rag_dir),
            "embedding_model": self.embedding_model_name,
        }

        if ok:
            try:
                self._ensure_ready()
                if self._collection:
                    status["indexed_chunks"] = self._collection.count()
                    status["collection"] = self.collection_name
            except Exception as e:
                status["error"] = str(e)

        return status

    def clear(self) -> Dict[str, str]:
        """Clear the RAG index."""
        try:
            if self._client and self._collection:
                self._client.delete_collection(self.collection_name)
                self._collection = None

            # Also remove persistent storage
            chromadb_dir = self.rag_dir / "chromadb"
            if chromadb_dir.exists():
                shutil.rmtree(chromadb_dir)

            return {"status": "cleared"}
        except Exception as e:
            return {"error": f"Failed to clear RAG index: {e}"}
