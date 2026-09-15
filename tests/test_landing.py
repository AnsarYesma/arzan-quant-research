import gzip
import json
from argparse import Namespace

import pytest
from test_warehouse import event

from arzan_quant.cli import _ingest_api
from arzan_quant.landing import package_landing
from arzan_quant.warehouse import load_exports

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")


def test_api_failure_does_not_destroy_prior_file(tmp_path, monkeypatch):
    path = tmp_path / "landing.gz"
    path.write_bytes(b"prior")

    class Broken:
        def __init__(self, *args):
            pass

        def iter_items(self, *args):
            raise RuntimeError("network failure")
            yield

    monkeypatch.setattr("arzan_quant.cli.ResearchApiClient", Broken)
    monkeypatch.setattr("arzan_quant.cli.ApiConfig.from_environment", lambda: None)
    args = Namespace(
        observed_from="2026-08-01T00:00:00Z",
        observed_to="2026-09-01T00:00:00Z",
        output=path,
        overwrite=True,
        page_size=100,
    )
    with pytest.raises(RuntimeError, match="network"):
        _ingest_api(args)
    assert path.read_bytes() == b"prior"
    assert list(tmp_path.iterdir()) == [path]


def test_landing_roundtrip(tmp_path):
    path = tmp_path / "landing.jsonl.gz"
    record = event(1, 0)
    record["observed_at"] = record["observed_at"].isoformat()
    with gzip.open(path, "wt") as stream:
        stream.write(json.dumps(record) + "\n")
    output = tmp_path / "export"
    package_landing(
        path, output, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"
    )
    con = duckdb.connect()
    assert load_exports(con, [output])["observations"] == 1
