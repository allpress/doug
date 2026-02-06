"""
RAG indexers for Doug.

Provides specialized indexing strategies for different content types
(source code, documentation, configuration files) to optimize
semantic search quality.
"""

import re
from typing import Any, Dict, List

from doug.rag.rag_engine import CodeChunker, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP


class DocumentationIndexer:
    """Indexes documentation files (Markdown, RST, plain text).

    Splits documentation by headings for better semantic coherence.
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE * 2,  # Larger chunks for docs
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_markdown(
        self,
        content: str,
        file_path: str,
        repo_name: str,
    ) -> List[Dict[str, Any]]:
        """Split Markdown content by headings.

        Args:
            content: Markdown file content.
            file_path: Relative file path.
            repo_name: Repository name.

        Returns:
            List of chunk dicts.
        """
        chunks: List[Dict[str, Any]] = []

        # Split on headings
        sections = re.split(r"^(#{1,6}\s+.+)$", content, flags=re.MULTILINE)

        current_heading = ""
        current_text = ""
        chunk_idx = 0

        for part in sections:
            if re.match(r"^#{1,6}\s+", part):
                # Save previous section
                if current_text.strip():
                    chunks.append(self._make_chunk(
                        current_text.strip(),
                        file_path,
                        repo_name,
                        chunk_idx,
                        heading=current_heading,
                    ))
                    chunk_idx += 1

                current_heading = part.strip()
                current_text = part + "\n"
            else:
                current_text += part

        # Don't forget the last section
        if current_text.strip():
            chunks.append(self._make_chunk(
                current_text.strip(),
                file_path,
                repo_name,
                chunk_idx,
                heading=current_heading,
            ))

        return chunks

    def _make_chunk(
        self,
        text: str,
        file_path: str,
        repo_name: str,
        idx: int,
        heading: str = "",
    ) -> Dict[str, Any]:
        """Create a chunk dict."""
        # Truncate if too large
        if len(text) > self.chunk_size:
            text = text[: self.chunk_size] + "..."

        return {
            "id": f"{repo_name}:{file_path}:doc{idx}",
            "text": text,
            "metadata": {
                "repo": repo_name,
                "file": file_path,
                "type": "documentation",
                "heading": heading.lstrip("#").strip() if heading else "",
            },
        }


class APIIndexer:
    """Indexes API endpoint information for semantic search.

    Creates chunks from the Doug JSON cache API data,
    enriched with context from surrounding code.
    """

    def chunk_apis(
        self,
        apis: List[Dict[str, str]],
        repo_name: str,
    ) -> List[Dict[str, Any]]:
        """Create searchable chunks from API endpoint data.

        Args:
            apis: List of API endpoint dicts from Doug cache.
            repo_name: Repository name.

        Returns:
            List of chunk dicts.
        """
        chunks: List[Dict[str, Any]] = []

        for i, api in enumerate(apis):
            text = (
                f"API Endpoint: {api['method']} {api['path']}\n"
                f"File: {api['file']}\n"
                f"Repository: {repo_name}"
            )

            chunks.append({
                "id": f"{repo_name}:api:{i}",
                "text": text,
                "metadata": {
                    "repo": repo_name,
                    "file": api["file"],
                    "method": api["method"],
                    "path": api["path"],
                    "type": "api_endpoint",
                },
            })

        return chunks


class DependencyIndexer:
    """Indexes dependency/build information for semantic search."""

    def chunk_dependencies(
        self,
        build_info: Dict[str, Any],
        repo_name: str,
    ) -> List[Dict[str, Any]]:
        """Create chunks from build/dependency information.

        Args:
            build_info: Build info dict from Doug cache.
            repo_name: Repository name.

        Returns:
            List of chunk dicts.
        """
        chunks: List[Dict[str, Any]] = []

        deps = build_info.get("dependencies", [])
        if not deps:
            return chunks

        # Create a summary chunk
        dep_names = [d.get("name", "") for d in deps[:30]]
        text = (
            f"Repository: {repo_name}\n"
            f"Build system: {build_info.get('type', 'unknown')}\n"
            f"Dependencies: {', '.join(dep_names)}"
        )

        chunks.append({
            "id": f"{repo_name}:deps:0",
            "text": text,
            "metadata": {
                "repo": repo_name,
                "build_type": build_info.get("type", "unknown"),
                "type": "dependencies",
            },
        })

        return chunks
