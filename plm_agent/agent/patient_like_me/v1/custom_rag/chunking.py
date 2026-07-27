"""Three chunking strategies for user knowledge base documents."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChunkStrategy(str, Enum):
    FIXED_SIZE = "fixed_size"
    PARAGRAPH = "paragraph"
    CUSTOM_SEPARATOR = "custom_separator"


@dataclass
class ChunkConfig:
    strategy: ChunkStrategy = ChunkStrategy.FIXED_SIZE
    chunk_size: int = 500
    chunk_overlap: int = 50
    separator: str = "\n\n"
    min_chunk_size: int = 50


@dataclass
class Chunk:
    chunk_index: int
    text: str
    char_offset: int
    char_length: int
    metadata: dict = field(default_factory=dict)


_SENTENCE_ENDS = {"。", ".", "！", "!", "？", "?", "；", ";", "\n"}


def chunk_text(text: str, config: ChunkConfig) -> list[Chunk]:
    if not text or not text.strip():
        return []
    if config.strategy == ChunkStrategy.FIXED_SIZE:
        return _chunk_fixed_size(text, config.chunk_size, config.chunk_overlap, config.min_chunk_size)
    if config.strategy == ChunkStrategy.PARAGRAPH:
        return _chunk_by_paragraph(text, config.chunk_size, config.chunk_overlap, config.min_chunk_size)
    if config.strategy == ChunkStrategy.CUSTOM_SEPARATOR:
        return _chunk_by_separator(text, config.separator, config.chunk_size, config.chunk_overlap, config.min_chunk_size)
    return _chunk_fixed_size(text, config.chunk_size, config.chunk_overlap, config.min_chunk_size)


def _find_break_point(text: str, target: int, window: int = 80) -> int:
    """Find a natural sentence boundary near *target* within a ±window range."""
    start = max(0, target - window)
    end = min(len(text), target + window)

    best = target
    best_dist = window + 1
    for i in range(start, end):
        if text[i] in _SENTENCE_ENDS:
            dist = abs(i + 1 - target)
            if dist < best_dist:
                best = i + 1
                best_dist = dist
    return best


def _chunk_fixed_size(
    text: str,
    chunk_size: int,
    overlap: int,
    min_size: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    step = max(1, chunk_size - overlap)
    pos = 0
    idx = 0

    while pos < len(text):
        end = min(pos + chunk_size, len(text))
        if end < len(text):
            end = _find_break_point(text, end)

        segment = text[pos:end].strip()
        if segment and len(segment) >= min_size:
            chunks.append(Chunk(
                chunk_index=idx,
                text=segment,
                char_offset=pos,
                char_length=end - pos,
            ))
            idx += 1

        if end >= len(text):
            break
        pos = max(pos + 1, end - overlap)

    return chunks


def _chunk_by_paragraph(
    text: str,
    chunk_size: int,
    overlap: int,
    min_size: int,
) -> list[Chunk]:
    raw_paragraphs = text.split("\n\n")

    segments: list[tuple[str, int]] = []
    offset = 0
    for p in raw_paragraphs:
        stripped = p.strip()
        real_offset = text.find(p, offset)
        if real_offset == -1:
            real_offset = offset
        if stripped:
            segments.append((stripped, real_offset))
        offset = real_offset + len(p) + 2  # +2 for \n\n

    merged = _merge_short_segments(segments, chunk_size)

    chunks: list[Chunk] = []
    for idx, (seg_text, seg_offset) in enumerate(merged):
        if len(seg_text) > chunk_size * 1.5:
            sub_chunks = _chunk_fixed_size(seg_text, chunk_size, overlap, min_size)
            for sc in sub_chunks:
                sc.chunk_index = len(chunks)
                sc.char_offset += seg_offset
                chunks.append(sc)
        elif len(seg_text) >= min_size:
            chunks.append(Chunk(
                chunk_index=len(chunks),
                text=seg_text,
                char_offset=seg_offset,
                char_length=len(seg_text),
            ))

    return chunks


def _chunk_by_separator(
    text: str,
    separator: str,
    chunk_size: int,
    overlap: int,
    min_size: int,
) -> list[Chunk]:
    if not separator:
        return _chunk_fixed_size(text, chunk_size, overlap, min_size)

    parts = text.split(separator)

    segments: list[tuple[str, int]] = []
    offset = 0
    for p in parts:
        stripped = p.strip()
        real_offset = text.find(p, offset)
        if real_offset == -1:
            real_offset = offset
        if stripped:
            segments.append((stripped, real_offset))
        offset = real_offset + len(p) + len(separator)

    merged = _merge_short_segments(segments, chunk_size)

    chunks: list[Chunk] = []
    for seg_text, seg_offset in merged:
        if len(seg_text) > chunk_size * 1.5:
            sub_chunks = _chunk_fixed_size(seg_text, chunk_size, overlap, min_size)
            for sc in sub_chunks:
                sc.chunk_index = len(chunks)
                sc.char_offset += seg_offset
                chunks.append(sc)
        elif len(seg_text) >= min_size:
            chunks.append(Chunk(
                chunk_index=len(chunks),
                text=seg_text,
                char_offset=seg_offset,
                char_length=len(seg_text),
            ))

    return chunks


def _merge_short_segments(
    segments: list[tuple[str, int]],
    chunk_size: int,
) -> list[tuple[str, int]]:
    if not segments:
        return []

    merged: list[tuple[str, int]] = []
    buf_text, buf_offset = segments[0]

    for seg_text, seg_offset in segments[1:]:
        combined_len = len(buf_text) + len(seg_text) + 1
        if combined_len <= chunk_size:
            buf_text = buf_text + "\n\n" + seg_text
        else:
            merged.append((buf_text, buf_offset))
            buf_text, buf_offset = seg_text, seg_offset

    merged.append((buf_text, buf_offset))
    return merged
