"""Raw payload archive (L0, ADR-0019).

Bodies are stored once, addressed by SHA-256 content hash, in a directory tree
``<root>/<provider>/<yyyy>/<mm>/<dd>/<hash>.bin``. Identical bodies are stored once. Files are
never modified after writing. Production will use S3-compatible object storage behind the same
interface.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cfi.providers.base import RawResponse


@dataclass(frozen=True, slots=True)
class ArchivedPayload:
    uri: str
    content_hash: str
    bytes: int


class RawArchive(Protocol):
    def store(self, raw: RawResponse) -> ArchivedPayload: ...

    def load(self, uri: str) -> bytes: ...


class FileSystemArchive:
    def __init__(self, root: Path) -> None:
        self.root = root

    def store(self, raw: RawResponse) -> ArchivedPayload:
        digest = hashlib.sha256(raw.body).hexdigest()
        day = raw.received_at
        relative = Path(raw.provider_id, f"{day:%Y}", f"{day:%m}", f"{day:%d}", f"{digest}.bin")
        target = self.root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(raw.body)
            temporary.replace(target)  # atomic: a partially written file is never visible
        return ArchivedPayload(
            uri=f"file:{relative.as_posix()}", content_hash=digest, bytes=len(raw.body)
        )

    def load(self, uri: str) -> bytes:
        if not uri.startswith("file:"):
            raise ValueError(f"unsupported archive URI: {uri!r}")
        path = (self.root / uri.removeprefix("file:")).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("archive URI escapes the archive root")
        return path.read_bytes()
