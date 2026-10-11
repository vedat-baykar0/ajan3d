"""3. CAD Ajanı — tanınan ürünü montaja çevirir.

Eski 3D üretim ajanının yerini alır. Fark şurada: o ajan bir fotoğrafı sinir
ağına verip **tahmin edilmiş bir kabuk** alıyordu; bu ajan ürünün kimliğini
kütüphaneye verip **kurulmuş bir montaj** alıyor. Çıktı tek bir yüzey değil,
her biri kapalı katı olan adlandırılmış parçalar; her parçanın malzemesi,
kütlesi ve montaj ekseni var.

Yazdığı dosyalar (iş dizinine):
  model.glb   düğüm başına parça, parça başına patlatma sözleşmesi taşıyan GLB
  cad.json    kaynak, aile, eşleşme gerekçesi, parametreler, parça kataloğu,
              doğrulama raporu

`cad.json` sunum sayfasını besler ama asıl işi **denetlenebilirlik**: hangi
ailenin neden seçildiği, hangi ölçülerin nereden geldiği ve montajın kaç
parçasının gerçekten su geçirmez katı olduğu orada yazar.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from cad import gltf, retrieval
from core import optimize
from core.config import settings

MODEL_FILE = "model.glb"
# Web icin sikistirilmis surum. Ozgun model.glb tasinabilir kalir (Draco
# uzantisi olmayan CAD araclarinda da acilir); teslim paketine bu gider.
WEB_MODEL_FILE = "model_web.glb"
REPORT_FILE = "cad.json"

Progress = Callable[[str], None]


class CadError(RuntimeError):
    pass


@dataclass
class CadResult:
    model_path: Path
    report_path: Path
    source: str
    family: str
    label: str
    parts: int
    instances: int
    all_solid: bool
    mass_g: float
    size_mm: list
    representative: bool
    size_mb: float


def build(job_dir: Path, metadata: dict, on_progress: Progress = lambda m: None,
          force: bool = False) -> CadResult:
    """Montajı kurar ve iş dizinine yazar. Zaten varsa yeniden kurmaz."""
    job_dir = Path(job_dir)
    model_path = job_dir / MODEL_FILE
    report_path = job_dir / REPORT_FILE
    if model_path.exists() and report_path.exists() and not force:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        on_progress(f"CAD montajı atlandı (zaten var): {report.get('label', '')}")
        return _result_from(model_path, report_path, report)

    identity = metadata.get("identity") or {}
    spec = metadata.get("spec") or {}
    if not identity:
        raise CadError("metadata.json içinde identity yok (önce tanıma adımı)")

    model = retrieval.acquire(identity, spec, on_progress=lambda m: on_progress(m))

    if model.source == "parametric":
        if model.assembly is None:
            raise CadError("parametrik montaj kurulamadı")
        gltf.write_glb(model.assembly, model_path)
        validation = model.report
        material_summary = model.assembly.material_summary()
        diagonal = float(validation["diagonal_mm"])
        # Hattın oturacağı eksen ve vananın uç yüzeyleri. Sayfa bunu sınır
        # kutusundan TAHMİN EDEMEZ (bkz. Assembly.flow_line açıklaması).
        flow_line = model.assembly.flow_line()
    else:
        model_path.write_bytes(model.glb)
        validation = {"parts": len(model.catalog), "instances": len(model.catalog),
                      "solid_parts": 0, "leaking_parts": [], "all_solid": False,
                      "faces": 0, "mass_g": 0.0, "size_mm": [0, 0, 0],
                      "diagonal_mm": model.diagonal_mm, "explode_outward": True,
                      "warnings": []}
        material_summary = []
        diagonal = model.diagonal_mm
        flow_line = None

    report = {
        "source": model.source,
        "family": model.family,
        "label": model.label,
        "representative": model.representative,
        "confidence": model.confidence,
        "match_reason": model.match_reason,
        "params": model.params,
        "notes": model.notes,
        "warnings": model.warnings,
        "validation": validation,
        "diagonal_mm": diagonal,
        "flow_line": flow_line,
        "parts": model.catalog,
        "materials": material_summary,
        "extra_specs": model.specs,
        "sources_tried": settings.cad_sources,
    }
    # --- Web optimizasyonu (isteğe bağlı; başarısızlığı zinciri durdurmaz) ---
    web = optimize.optimize(model_path, job_dir / WEB_MODEL_FILE,
                            on_progress=lambda m: on_progress(f"  {m}"))
    if not web.ok and web.reason:
        on_progress(f"  Draco atlandı: {web.reason}")
    report["web_model"] = {
        "file": web.path.name,
        "draco": web.draco,
        "bytes": web.after,
        "raw_bytes": web.before,
        "saved_pct": web.saved_pct,
        "reason": web.reason,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    solid = validation.get("solid_parts", 0)
    total = validation.get("parts", 0)
    on_progress(
        f"Montaj: {model.label} — {total} parça / "
        f"{validation.get('instances', total)} örnek, "
        f"{solid}/{total} su geçirmez katı, "
        f"{validation.get('mass_g', 0):.0f} g, "
        f"{model_path.stat().st_size / 1_048_576:.2f} MB")
    for warning in model.warnings[:3]:
        on_progress(f"  geometri uyarısı: {warning}")
    return _result_from(model_path, report_path, report)


def _result_from(model_path: Path, report_path: Path, report: dict) -> CadResult:
    validation = report.get("validation") or {}
    return CadResult(
        model_path=model_path, report_path=report_path,
        source=report.get("source", "parametric"),
        family=report.get("family", ""), label=report.get("label", ""),
        parts=int(validation.get("parts", 0)),
        instances=int(validation.get("instances", 0)),
        all_solid=bool(validation.get("all_solid", False)),
        mass_g=float(validation.get("mass_g", 0.0)),
        size_mm=list(validation.get("size_mm", [0, 0, 0])),
        representative=bool(report.get("representative", False)),
        size_mb=round(model_path.stat().st_size / 1_048_576, 2),
    )


def load_report(job_dir: Path) -> dict:
    path = Path(job_dir) / REPORT_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}
