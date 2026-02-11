"""
Text Chunker for Document Ingestion

Splits document content into overlapping chunks for embedding and RAG.
Ported from RegenAI koi-sensors/sensors/email/chunker.py.
"""

import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class TextChunker:
    """
    Split text into chunks suitable for embedding.
    Tokens are approximated as whitespace-separated words.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Split text into overlapping chunks."""
        if not text or not text.strip():
            return []

        tokens = text.split()
        total_tokens = len(tokens)

        if total_tokens <= self.chunk_size:
            return [{
                'text': text.strip(),
                'index': 0,
                'start_token': 0,
                'end_token': total_tokens,
                'total_chunks': 1,
            }]

        chunks = []
        start = 0
        chunk_index = 0

        while start < total_tokens:
            end = min(start + self.chunk_size, total_tokens)
            chunk_tokens = tokens[start:end]
            chunk_text = ' '.join(chunk_tokens)

            if len(chunk_tokens) >= self.min_chunk_size or start == 0:
                chunks.append({
                    'text': chunk_text,
                    'index': chunk_index,
                    'start_token': start,
                    'end_token': end,
                })
                chunk_index += 1

            start = end - self.chunk_overlap
            if start <= (chunks[-1]['start_token'] if chunks else 0):
                start = end

        for chunk in chunks:
            chunk['total_chunks'] = len(chunks)

        return chunks


class SentenceAwareChunker(TextChunker):
    """Chunk text while respecting sentence boundaries."""

    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        if not text or not text.strip():
            return []

        tokens = text.split()
        total_tokens = len(tokens)

        if total_tokens <= self.chunk_size:
            return [{
                'text': text.strip(),
                'index': 0,
                'start_token': 0,
                'end_token': total_tokens,
                'total_chunks': 1,
            }]

        chunks = []
        start = 0
        chunk_index = 0

        while start < total_tokens:
            target_end = min(start + self.chunk_size, total_tokens)
            end = self._find_sentence_boundary(tokens, start, target_end)
            chunk_tokens = tokens[start:end]
            chunk_text = ' '.join(chunk_tokens)

            if len(chunk_tokens) >= self.min_chunk_size or start == 0:
                chunks.append({
                    'text': chunk_text,
                    'index': chunk_index,
                    'start_token': start,
                    'end_token': end,
                })
                chunk_index += 1

            start = max(end - self.chunk_overlap, start + 1)

        for chunk in chunks:
            chunk['total_chunks'] = len(chunks)

        return chunks

    def _find_sentence_boundary(self, tokens, start, target_end):
        """Find a sentence boundary near target_end."""
        search_start = max(start, target_end - self.chunk_size // 5)
        for i in range(target_end - 1, search_start - 1, -1):
            token = tokens[i]
            if token.endswith('.') or token.endswith('!') or token.endswith('?'):
                return i + 1
        return target_end
