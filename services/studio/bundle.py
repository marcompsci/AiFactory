"""Deterministic release bundles. The same files always produce the same bytes and sha256, so a digest
identifies exactly what QA tested, what the manager reviewed and what the owner approved."""
from __future__ import annotations

import hashlib
import io
import shutil
import zipfile
from pathlib import Path

SKIP = {"__pycache__", ".pytest_cache", ".git", ".aiciv"}
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
MAX_BUNDLE_BYTES = 5 * 1024 * 1024


def files_of(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not (set(p.relative_to(root).parts) & SKIP))


def make(src: Path, dest: Path) -> tuple[str, list[dict]]:
    buf = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files_of(src):
            rel = p.relative_to(src).as_posix()
            data = p.read_bytes()
            info = zipfile.ZipInfo(rel, FIXED_TIME)
            info.external_attr = 0o644 << 16
            z.writestr(info, data, zipfile.ZIP_DEFLATED)
            manifest.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    raw = buf.getvalue()
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("bundle exceeds 5 MB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest(), manifest


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(bundle: Path, dest: Path) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(bundle) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest.resolve() not in target.parents:
                raise ValueError(f"unsafe path in bundle: {info.filename}")
        z.extractall(dest)
        return len(z.infolist())


def read_member(bundle: Path, name: str) -> bytes:
    with zipfile.ZipFile(bundle) as z:
        return z.read(name)
