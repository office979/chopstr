from __future__ import annotations

import pytest

from chopstr_worker import config, storage


def test_local_fallback_roundtrip(local_store, tmp_path):
    assert local_store.local_root is not None
    assert not local_store.exists("derived", "a/b.json")
    local_store.put_json("derived", "a/b.json", {"x": 1})
    assert local_store.exists("derived", "a/b.json")
    assert local_store.get_json("derived", "a/b.json") == {"x": 1}
    assert local_store.size("derived", "a/b.json") > 0
    src = tmp_path / "f.bin"
    src.write_bytes(b"abc")
    local_store.put_file("sources", "orig/f.bin", src)
    dest = local_store.download_to("sources", "orig/f.bin", tmp_path / "out" / "f.bin")
    assert (tmp_path / "out" / "f.bin").read_bytes() == b"abc" and dest.endswith("f.bin")
    local_store.delete("sources", "orig/f.bin")
    assert not local_store.exists("sources", "orig/f.bin")


def test_local_paths_are_confined(local_store):
    with pytest.raises(ValueError):
        local_store._local_path("derived", "../../etc/passwd")


def test_derived_key_is_deterministic_and_sensitive():
    k1 = storage.derived_key("src/a.mp4", {"ar": 16000}, "v1", "wav", prefix="audio")
    k2 = storage.derived_key("src/a.mp4", {"ar": 16000}, "v1", "wav", prefix="audio")
    k3 = storage.derived_key("src/a.mp4", {"ar": 16000}, "v2", "wav", prefix="audio")
    k4 = storage.derived_key("src/a.mp4", {"ar": 22050}, "v1", "wav", prefix="audio")
    assert k1 == k2
    assert k1 != k3 and k1 != k4
    assert k1.startswith("audio/") and k1.endswith(".wav")
    assert len(k1.split("/")[1]) == 64 + 4


def test_s3_endpoint_must_pass_residency(monkeypatch):
    from chopstr_worker.residency import ResidencyError

    monkeypatch.setenv("S3_ENDPOINT", "https://s3.us-east-1.amazonaws.com")
    config.reload()
    with pytest.raises(ResidencyError):
        storage.Storage(config.settings())  # bekannter Nicht-EU-Endpunkt, auch wenn konfiguriert
    monkeypatch.setenv("S3_ENDPOINT", "https://fsn1.your-objectstorage.example")
    config.reload()
    st = storage.Storage(config.settings())
    assert st.local_root is None  # S3-Modus, boto3 wird erst beim ersten Zugriff importiert
