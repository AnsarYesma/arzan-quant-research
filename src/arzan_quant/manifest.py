from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    """Raised when an export manifest or referenced file is invalid."""


@dataclass(frozen=True)
class FileVerification:
    path: Path
    size_bytes: int
    sha256: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(manifest_path: Path) -> list[FileVerification]:
    payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError("manifest.files must be a non-empty list")

    root = manifest_path.parent.resolve()
    verified: list[FileVerification] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ManifestError("each manifest file entry must be an object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes", entry.get("bytes"))
        if not isinstance(relative, str) or not relative:
            raise ManifestError("manifest file path must be a non-empty string")
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise ManifestError(f"manifest path escapes export root: {relative}")
        if not candidate.is_file():
            raise ManifestError(f"missing export file: {relative}")
        actual_size = candidate.stat().st_size
        if expected_size is not None and actual_size != expected_size:
            raise ManifestError(f"size mismatch for {relative}")
        actual_hash = sha256_file(candidate)
        if not isinstance(expected_hash, str) or actual_hash != expected_hash.lower():
            raise ManifestError(f"SHA-256 mismatch for {relative}")
        verified.append(FileVerification(candidate, actual_size, actual_hash))
    return verified
