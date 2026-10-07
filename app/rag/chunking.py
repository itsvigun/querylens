"""Deterministic heading-aware Markdown chunks bounded by UTF-8 bytes."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

CHUNKER_VERSION = "headings-utf8-v1-2000"
MAX_CHUNK_BYTES = 2000
MAX_CORPUS_BYTES = 1_048_576
MAX_CHUNKS = 512


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


@dataclass(frozen=True)
class Chunk:
    id: str
    source_path: str
    heading: str
    ordinal: int
    line_start: int
    line_end: int
    document_hash: str
    content_hash: str
    content: str


def chunk_document(source_path: str, raw: bytes) -> list[Chunk]:
    if len(raw) > 65536 or len(source_path) > 256:
        raise ValueError("document_limit")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if not text.strip() or "\x00" in text:
        raise ValueError("invalid_document")
    document_hash = digest(raw)
    lines = text.splitlines(keepends=True)
    title = Path(source_path).stem
    heading_stack = []
    sections = []
    body = []
    fence = None
    for line_no, line in enumerate(lines, start=1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if fence is None else None
        if heading:
            if body:
                sections.append((title, list(heading_stack), body))
                body = []
            level, name = len(heading[1]), heading[2]
            if level == 1:
                title = name
                heading_stack = []
            else:
                heading_stack = [(n, h) for n, h in heading_stack if n < level]
                heading_stack.append((level, name))
        else:
            body.append((line_no, line))
    if body:
        sections.append((title, heading_stack, body))

    output = []
    for title, stack, body in sections:
        heading = " > ".join([title, *(name for _, name in stack)])
        if len(heading) > 256:
            raise ValueError("heading_limit")
        prefix = f"Source: {source_path}\nHeading: {heading}\n\n"
        capacity = MAX_CHUNK_BYTES - len(prefix.encode())
        if capacity < 256:
            raise ValueError("heading_limit")
        buffer = ""
        buffer_bytes = 0
        start = end = 0

        def emit(buffer, prefix, heading, start, end):
            if not buffer.strip():
                return
            content = prefix + buffer.strip()
            content_hash = digest(content)
            ordinal = len(output)
            output.append(
                Chunk(
                    id=digest(f"{source_path}\0{ordinal}\0{content_hash}"),
                    source_path=source_path,
                    heading=heading,
                    ordinal=ordinal,
                    line_start=start,
                    line_end=end,
                    document_hash=document_hash,
                    content_hash=content_hash,
                    content=content,
                )
            )

        for line_no, line in body:
            if buffer and buffer_bytes + len(line.encode()) > capacity:
                emit(buffer, prefix, heading, start, end)
                buffer = ""
                buffer_bytes = 0
            for character in line:
                character_bytes = len(character.encode())
                if buffer_bytes + character_bytes > capacity:
                    emit(buffer, prefix, heading, start, end)
                    buffer = ""
                    buffer_bytes = 0
                if not buffer:
                    start = line_no
                end = line_no
                buffer += character
                buffer_bytes += character_bytes
        emit(buffer, prefix, heading, start, end)
    if not output:
        raise ValueError("empty_document")
    return output


def load_corpus(root: Path) -> tuple[list[Chunk], str]:
    root = root.resolve()
    files = sorted(root.rglob("*.md"))
    if not files or len(files) > 64:
        raise ValueError("corpus_limit")
    output, manifest, size = [], [], 0
    for path in files:
        if path.is_symlink() or any(
            (root / p).is_symlink() for p in path.relative_to(root).parents if p != Path(".")
        ):
            raise ValueError("symlink_document")
        if not path.resolve().is_relative_to(root):
            raise ValueError("symlink_document")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        size += len(raw)
        if size > MAX_CORPUS_BYTES:
            raise ValueError("corpus_limit")
        source = "knowledge/" + path.relative_to(root).as_posix()
        output.extend(chunk_document(source, raw))
        manifest.append((source, digest(raw)))
        if len(output) > MAX_CHUNKS:
            raise ValueError("corpus_limit")
    return output, digest(json.dumps(manifest, separators=(",", ":")))


def chunk_record(chunk: Chunk) -> dict:
    return asdict(chunk)
