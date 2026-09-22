"""Objektspeicher: S3-kompatibel (MinIO, Hetzner, AWS eu-*) oder lokaler Ordner.

- Mit ``S3_ENDPOINT``: boto3 mit path-style Adressierung (MinIO). boto3 wird lazy importiert,
  und der Endpoint muss die Residency-Prüfung bestehen.
- Ohne ``S3_ENDPOINT``: lokaler Ordner ``LOCAL_STORAGE_DIR`` (Default: ``<work_dir>/storage``),
  Buckets als Unterordner. Damit laufen Tests und lokale Entwicklung ohne MinIO.

Keys sind bucketlos; der Aufrufer wählt ``bucket="sources"`` oder ``"derived"``.
``derived_key()`` liefert deterministische Output-Keys aus sha256(asset_key + params + version),
damit Aktivitäten idempotent sind (``exists()`` vor teurer Arbeit prüfen).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import config, residency

BUCKETS = ("sources", "derived")


def derived_key(asset_key: str, params: dict[str, Any] | None, version: str, ext: str, prefix: str = "") -> str:
    """Deterministischer Output-Key: ``<prefix>/<sha256(asset+params+version)>.<ext>``."""
    raw = json.dumps([asset_key, params or {}, version], sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    ext = ext.lstrip(".")
    name = f"{digest}.{ext}" if ext else digest
    return f"{prefix.strip('/')}/{name}" if prefix else name


class Storage:
    """Einheitliche Schnittstelle über S3 und lokalem Ordner."""

    def __init__(self, s: config.Settings | None = None):
        self.s = s or config.settings()
        self._client = None
        if self.s.is_local_storage:
            base = self.s.local_storage_dir or os.path.join(self.s.work_dir or tempfile.gettempdir(), "chopstr-storage")
            self.local_root = Path(base)
            self.local_root.mkdir(parents=True, exist_ok=True)
        else:
            residency.assert_eu_host(self.s.s3_endpoint, self.s)
            self.local_root = None

    # -- intern ---------------------------------------------------------------------------------
    def _bucket_name(self, bucket: str) -> str:
        if bucket == "sources":
            return self.s.s3_bucket_sources
        if bucket == "derived":
            return self.s.s3_bucket_derived
        return bucket

    def _local_path(self, bucket: str, key: str) -> Path:
        assert self.local_root is not None
        p = (self.local_root / self._bucket_name(bucket) / key.lstrip("/")).resolve()
        if not str(p).startswith(str(self.local_root.resolve())):
            raise ValueError("Ungültiger Storage-Key")
        return p

    def _s3(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.s.s3_endpoint,
                region_name=self.s.s3_region,
                aws_access_key_id=self.s.s3_access_key or None,
                aws_secret_access_key=self.s.s3_secret_key or None,
                config=Config(s3={"addressing_style": "path" if self.s.s3_force_path_style else "auto"}),
            )
        return self._client

    # -- API ------------------------------------------------------------------------------------
    def exists(self, bucket: str, key: str) -> bool:
        if self.local_root is not None:
            return self._local_path(bucket, key).is_file()
        from botocore.exceptions import ClientError

        try:
            self._s3().head_object(Bucket=self._bucket_name(bucket), Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def size(self, bucket: str, key: str) -> int:
        if self.local_root is not None:
            return self._local_path(bucket, key).stat().st_size
        return int(self._s3().head_object(Bucket=self._bucket_name(bucket), Key=key)["ContentLength"])

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> str:
        if self.local_root is not None:
            p = self._local_path(bucket, key)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            return key
        extra = {"ContentType": content_type} if content_type else {}
        self._s3().put_object(Bucket=self._bucket_name(bucket), Key=key, Body=data, **extra)
        return key

    def put_file(self, bucket: str, key: str, path: str | os.PathLike, content_type: str | None = None) -> str:
        if self.local_root is not None:
            p = self._local_path(bucket, key)
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, p)
            return key
        extra = {"ContentType": content_type} if content_type else {}
        self._s3().upload_file(str(path), self._bucket_name(bucket), key, ExtraArgs=extra or None)
        return key

    def put_json(self, bucket: str, key: str, obj: Any) -> str:
        return self.put_bytes(bucket, key, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def get_bytes(self, bucket: str, key: str) -> bytes:
        if self.local_root is not None:
            return self._local_path(bucket, key).read_bytes()
        return self._s3().get_object(Bucket=self._bucket_name(bucket), Key=key)["Body"].read()

    def get_json(self, bucket: str, key: str) -> Any:
        return json.loads(self.get_bytes(bucket, key).decode("utf-8"))

    def download_to(self, bucket: str, key: str, path: str | os.PathLike) -> str:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.local_root is not None:
            shutil.copyfile(self._local_path(bucket, key), dest)
        else:
            self._s3().download_file(self._bucket_name(bucket), key, str(dest))
        return str(dest)

    def delete(self, bucket: str, key: str) -> None:
        if self.local_root is not None:
            p = self._local_path(bucket, key)
            if p.exists():
                p.unlink()
            return
        self._s3().delete_object(Bucket=self._bucket_name(bucket), Key=key)

    def list(self, bucket: str, prefix: str) -> list[str]:
        """Alle Keys unter ``prefix`` (sortiert). Lokal per Ordnerdurchlauf, in S3 per Paginator."""
        prefix = prefix.lstrip("/")
        if self.local_root is not None:
            base = self._local_path(bucket, prefix)
            root = self._local_path(bucket, "")
            if base.is_file():
                return [prefix]
            if not base.is_dir():
                return []
            return sorted(str(f.relative_to(root)).replace(os.sep, "/") for f in base.rglob("*") if f.is_file())
        keys: list[str] = []
        paginator = self._s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket_name(bucket), Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return sorted(keys)


__all__ = ["BUCKETS", "Storage", "derived_key"]
