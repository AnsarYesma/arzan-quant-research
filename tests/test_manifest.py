import hashlib
import json

import pytest

from arzan_quant.manifest import ManifestError, verify_manifest


def test_export_bytes_field_is_verified(tmp_path):
    import hashlib

    data = tmp_path / "data.parquet"
    data.write_bytes(b"fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": data.name,
                        "bytes": 999,
                        "sha256": hashlib.sha256(b"fixture").hexdigest(),
                    }
                ]
            }
        )
    )
    with pytest.raises(ManifestError, match="size mismatch"):
        verify_manifest(manifest)


def test_manifest_verification(tmp_path) -> None:
    data = tmp_path / "part.parquet"
    data.write_bytes(b"synthetic parquet placeholder")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "part.parquet",
                        "size_bytes": data.stat().st_size,
                        "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    verified = verify_manifest(manifest)
    assert len(verified) == 1


def test_manifest_prevents_path_escape(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"files": [{"path": "../outside", "sha256": "0" * 64}]}),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="escapes export root"):
        verify_manifest(manifest)
