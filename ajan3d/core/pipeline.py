"""Üretim zinciri: fotoğraf klasörü -> teslim paketi.

`run_all.py` ile ajans orkestratörünün (`run_agency.py`) aynı mantığı iki kez
yazmaması için adımlar burada toplandı.

Adımlar:
  1. **Tanıma** (Claude, ücretli)        -> metadata.json: identity
  2. **Teknik veri** (Claude + web_search, ücretli, İSTEĞE BAĞLI)
                                          -> metadata.json: spec
  3. **CAD montajı** (yerel, ücretsiz)    -> model.glb + cad.json
  4. **Paketleme**                        -> delivery_<ürün>_<tarih>/ + .zip

Eski zincirden farkı: 3D üretim adımı (ücretsiz HF Space, TRELLIS/InstantMesh)
tamamen kaldırıldı. Model artık kotaya, kuyruğa veya ağa bağlı değil; yerel ve
saniyeler sürüyor. Bunun yan etkisi şu: zincirdeki tek **geçici** hata kaynağı
Anthropic çağrılarıdır. Kota/kuyruk kaynaklı yeniden deneme mantığı korundu
çünkü hız sınırı hâlâ gerçek.

**Teknik veri adımı asla zinciri durdurmaz.** Kaliteyi artıran ek bir adımdır;
başarısız olursa durum dosyaya yazılır ve montaj tanıma çıktısıyla kurulur.
Ücretli bir aramanın müşteri teslimini engellemesi kabul edilemez.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from agents import cad_agent
from agents.cad_agent import CadError
from agents.packager_agent import PackagingError, build_package
from agents.vision_agent import VisionError, identify_folder, save_metadata
from core.config import settings
from core.jobs import find_latest_job, make_job_id

Progress = Callable[[str], None]


class PipelineError(RuntimeError):
    """Zincirin bir adımı başarısız oldu.

    retriable=True: aynı komut sonra tekrar denenirse düzelebilir
    (hız sınırı, ağ). retriable=False: insan kararı gerekiyor
    (tanınamayan ürün, eksik ayar, bozuk veri).
    """

    def __init__(self, stage: str, message: str, retriable: bool = False):
        super().__init__(message)
        self.stage = stage
        self.retriable = retriable


@dataclass
class PipelineResult:
    job_dir: Path
    delivery_dir: Path
    zip_path: Optional[Path]
    object_name: str
    metadata: dict


# Geçici olduğu bilinen hata işaretleri (ağ/hız sınırı kaynaklı).
_RETRIABLE_HINTS = ("hız sınırı", "rate limit", "429", "timeout", "bağlan",
                    "geçici", "overloaded", "sunucu hatası")


def _looks_retriable(message: str) -> bool:
    low = message.lower()
    return any(h in low for h in _RETRIABLE_HINTS)


def resolve_job_dir(folder: Path, new: bool = False) -> Path:
    """Aynı klasörün yarım işini sürdürür; yoksa yeni iş dizini adı üretir."""
    folder = Path(folder).resolve()
    if not new:
        existing = find_latest_job(settings.jobs_dir, folder)
        if existing:
            return existing
    return settings.jobs_dir / make_job_id(folder)


def _run_spec(job_dir: Path, metadata: dict, on_progress: Progress) -> dict:
    """Teknik veri adımı. Hata zinciri durdurmaz; durum metadata'ya yazılır."""
    if not settings.spec_enabled:
        return metadata
    if metadata.get("spec"):
        on_progress("Teknik veri atlandı (zaten var): "
                    + str(metadata["spec"].get("identified_as", ""))[:70])
        return metadata

    on_progress("Teknik Veri Ajanı (web araması) çalışıyor")
    try:
        from agents.spec_agent import attach_to_metadata, research
        result, info = research(metadata["identity"],
                                on_progress=lambda m: on_progress(f"  {m}"))
        attach_to_metadata(job_dir, result, info)
        on_progress(f"Teknik veri: {result.identified_as[:70]} "
                    f"({info.searches} arama, {len(result.specs)} özellik, "
                    f"{len(result.standard_parts)} standart parça, "
                    f"${info.cost_usd})")
    except Exception as e:
        # SpecError dahil her şey: bu adım kaliteyi artırır, zorunlu değildir.
        on_progress(f"Teknik veri atlandı ({type(e).__name__}: {str(e)[:160]})")
        path = job_dir / "metadata.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["spec_run"] = {"ok": False, "error": str(e)[:400]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))


def run_pipeline(
    folder: Path,
    job_dir: Optional[Path] = None,
    force: bool = False,
    lang: str = "tr",
    make_zip: bool = True,
    repackage: bool = False,
    rebuild_cad: bool = False,
    on_progress: Progress = lambda msg: None,
) -> PipelineResult:
    """Zinciri sırayla yürütür. Tamamlanmış adımlar atlanır."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise PipelineError("input", f"Klasör bulunamadı: {folder}")
    job_dir = Path(job_dir) if job_dir else resolve_job_dir(folder)
    job_dir.mkdir(parents=True, exist_ok=True)
    meta_path = job_dir / "metadata.json"

    # --- 1. Tanıma (Claude) ---
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        on_progress(f"Tanıma atlandı (zaten var): "
                    f"{metadata['identity']['product_name']}")
    else:
        on_progress("Tanıma Ajanı (Claude) çalışıyor")
        try:
            result, info = identify_folder(folder)
        except VisionError as e:
            raise PipelineError("vision", str(e), retriable=_looks_retriable(str(e))) from e
        except FileNotFoundError as e:
            raise PipelineError("vision", str(e)) from e
        save_metadata(job_dir, folder, result, info)
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        on_progress(f"{result.product_name} — {result.type_designation[:80]}")
        on_progress(f"  ölçü: {result.nominal_size or '?'} · "
                    f"basınç: {result.pressure_rating or '?'} · "
                    f"malzeme: {result.body_material or '?'} · "
                    f"aile önerisi: {result.family_hint}")

    identity = metadata["identity"]
    identification = identity.get("identification") or {}
    if not identification.get("confident", True) and not force \
            and not settings.force_low_confidence:
        issues = "; ".join(identification.get("issues") or []) or "belirtilmedi"
        # Kalıcı hata: aynı fotoğraflarla tekrar denemek sonucu değiştirmez.
        raise PipelineError(
            "identification",
            f"Ürün fotoğraftan güvenle tanınamadı ({issues}). Damgaların okunduğu "
            f"net bir fotoğraf gerekiyor ya da force ile aşılmalı.",
        )

    # --- 2. Teknik veri (ücretli, isteğe bağlı, kritik değil) ---
    metadata = _run_spec(job_dir, metadata, on_progress)

    # --- 3. CAD montajı (yerel) ---
    on_progress("CAD Ajanı (kütüphane eşleştirme + parametrik montaj) çalışıyor")
    try:
        cad = cad_agent.build(job_dir, metadata,
                              on_progress=lambda m: on_progress(f"  {m}"),
                              force=rebuild_cad)
    except CadError as e:
        raise PipelineError("cad", str(e)) from e
    on_progress(f"Kaynak: {cad.source} · aile: {cad.family}"
                + (" · TEMSİLİ MODEL" if cad.representative else ""))

    # --- 4. Paketleme ---
    # Montaj yeniden kurulduysa paket de yenilenmek zorunda; aksi halde
    # teslim klasöründe eski model.glb kalıyor ve sayfa yeni parça listesiyle
    # eski geometriyi gösteriyor. Çağıranın bunu hatırlamasına bırakılamaz.
    existing = sorted(p for p in job_dir.glob("delivery_*") if p.is_dir())
    if existing and not (repackage or rebuild_cad):
        delivery = existing[-1]
        on_progress(f"Paket atlandı (zaten var): {delivery.name}")
    else:
        on_progress("Teslimat Ajanı (Web Packager) çalışıyor")
        try:
            delivery = build_package(job_dir, lang=lang, make_zip=make_zip)
        except PackagingError as e:
            raise PipelineError("packaging", str(e)) from e
        on_progress(f"Paket: {delivery.name}")

    zip_path = Path(f"{delivery}.zip")
    return PipelineResult(
        job_dir=job_dir,
        delivery_dir=delivery,
        zip_path=zip_path if zip_path.exists() else None,
        object_name=identity.get("product_name", folder.name),
        metadata=metadata,
    )
