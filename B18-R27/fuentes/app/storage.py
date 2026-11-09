"""Private, content-addressed storage. Files are never mounted as static assets."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from .object_gate import object_gate


MAX_SOURCE_BYTES = 16 * 1024 * 1024


def object_path(root: Path, sha256: str) -> Path:
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError("Invalid object digest")
    return root / "objects" / sha256[:2] / sha256


def publish_bytes(root: Path, content: bytes) -> tuple[str, int, str]:
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ValueError("Source must be nonempty and at most 16 MiB")
    return _publish(root, content)


def publish_artifact(root: Path, content: bytes) -> tuple[str, int, str]:
    """Publish a generated private capture; source upload limits stay unchanged."""
    if not content:
        raise ValueError('Empty capture')
    return _publish(root, content)


def _publish(root: Path, content: bytes) -> tuple[str, int, str]:
    with object_gate(root):
        return _publish_locked(root,content)


def _publish_locked(root: Path, content: bytes) -> tuple[str, int, str]:
    digest = hashlib.sha256(content).hexdigest()
    target = object_path(root, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = root / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="source-", suffix=".tmp", dir=temp_dir)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Hard link publishes the fully flushed file only if this digest is absent.
            os.link(temp, target)
        except FileExistsError:
            if target.read_bytes() != content:
                raise RuntimeError("Stored object does not match its digest")
        relative = target.relative_to(root).as_posix()
        return digest, len(content), relative
    finally:
        temp.unlink(missing_ok=True)


def read_verified(root: Path, sha256: str) -> bytes:
    content = object_path(root, sha256).read_bytes()
    if hashlib.sha256(content).hexdigest() != sha256:
        raise RuntimeError("Stored object failed integrity check")
    return content


def inventory(root: Path, registered: set[str]) -> dict[str, int]:
    object_root = root / "objects"
    objects = {p.name for p in object_root.glob("*/*") if p.is_file()} if object_root.exists() else set()
    temp_root = root / "tmp"
    temporary = sum(1 for p in temp_root.iterdir() if p.is_file()) if temp_root.exists() else 0
    return {
        "registered": len(registered),
        "orphan_objects": len(objects - registered),
        "missing_objects": len(registered - objects),
        "temporary_files": temporary,
    }
