"""İş dizini yardımcıları: isimlendirme ve aynı klasör için yarım kalmış işi bulma."""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def slugify(text: str, fallback: str = "urun") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.translate(_TR).lower()).strip("-")
    return slug[:60] or fallback


def make_job_id(folder: Path) -> str:
    return f"{slugify(folder.name, 'job')}-{datetime.now():%Y%m%d-%H%M%S}"


def find_latest_job(jobs_dir: Path, source_folder: Path) -> Optional[Path]:
    """Aynı fotoğraf klasörü için oluşturulmuş en yeni iş dizinini döner."""
    if not jobs_dir.exists():
        return None
    target = str(source_folder.resolve()).lower()
    candidates = []
    for meta in jobs_dir.glob("*/metadata.json"):
        try:
            src = json.loads(meta.read_text(encoding="utf-8")).get("source_folder", "")
        except (OSError, ValueError):
            continue
        if src.lower() == target:
            candidates.append(meta.parent)
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)
