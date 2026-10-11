"""CAD modeli edinme: yerel kütüphane → uzak API → parametrik üretim.

Ürün tanındıktan sonra model üç kaynaktan gelebilir. Sıra `.env` → `CAD_SOURCES`
ile değiştirilebilir, varsayılan `local,remote,parametric`.

**1. Yerel kütüphane (`cad_library/`)** — elinizdeki gerçek CAD dosyaları.
Tedarikçiden gelen, satın alınan ya da kendi çizdiğiniz `.glb` dosyasını bir
klasöre koyup yanına `manifest.json` yazarsınız; sistem düğüm adlarına patlatma
eksenlerini işler ve dosyayı olduğu gibi kullanır. Kütüphane büyüdükçe sistem
"eşleştirme" yönüne kayar, çünkü gerçek bir katalog modeli her zaman üretilmiş
modelden iyidir.

**2. Uzak API** — `CAD_API_URL` tanımlıysa denenir. Burada dürüst olmak gerekir:
**GrabCAD'in açık indirme API'si yoktur** (oturum ister, içerik yeniden
dağıtılamaz), **Thangs'in API'si de anahtarla kapalıdır** ve içeriği çoğunlukla
STEP/SLDPRT'tir — yani `.glb` değildir ve parçaları adlandırılmış/ayrılmış
gelmez. Bu yüzden belirli bir sağlayıcıya kod gömülmedi; bunun yerine **genel
bir sözleşme** var: arama adresi JSON döner, içinde bir `.glb` indirme bağlantısı
bulunur. Anahtarınız olan herhangi bir servisi `.env` ile bağlarsınız. Varsayılan
kapalıdır ve kapalıyken zincir hiç yavaşlamaz.

**3. Parametrik üretim** — her zaman çalışan taban yol. `cad/library.py`
ürünü bir aileye eşleştirir, `cad/standards.py` ölçüleri verir, montaj
Boolean katılardan kurulur.

Manifest biçimi (`cad_library/<klasör>/manifest.json`):

```json
{
  "label": "DN50 3 parçalı küresel vana",
  "keywords": ["küresel vana", "ball valve", "dn50"],
  "model": "model.glb",
  "representative": false,
  "specs": [{"label": "Anma çapı", "value": "DN50"}],
  "parts": [
    {"node": "Body", "name": "Gövde", "group": "housing",
     "axis": [0, 0, 0], "distance": 0, "stage": 0,
     "material": "stainless_cast", "note": "Döküm gövde"}
  ]
}
```
"""
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cad import gltf, library, materials
from core.config import PROJECT_ROOT, settings

LIBRARY_DIR = PROJECT_ROOT / "cad_library"
MANIFEST = "manifest.json"


@dataclass
class CadModel:
    """Edinilen model: ya hazır GLB baytı ya da parametrik montaj."""
    source: str                       # local | remote | parametric
    label: str
    family: str
    representative: bool
    glb: bytes = b""
    assembly: object = None
    catalog: List[dict] = field(default_factory=list)
    params: Dict[str, object] = field(default_factory=dict)
    report: Dict[str, object] = field(default_factory=dict)
    match_reason: str = ""
    confidence: str = "low"
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    diagonal_mm: float = 0.0
    specs: List[dict] = field(default_factory=list)


class RetrievalError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# 1. Yerel kütüphane
# --------------------------------------------------------------------------- #

def local_entries() -> List[dict]:
    """`cad_library/` altındaki geçerli manifestler."""
    out = []
    if not LIBRARY_DIR.exists():
        return out
    for manifest in sorted(LIBRARY_DIR.glob(f"*/{MANIFEST}")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        model = manifest.parent / str(data.get("model", "model.glb"))
        if not model.exists():
            continue
        data["_dir"] = manifest.parent
        data["_model"] = model
        out.append(data)
    return out


def _score_entry(entry: dict, text: str) -> float:
    score = 0.0
    for word in entry.get("keywords") or []:
        word = str(word).lower().strip()
        if word and word in text:
            score += 1.0 + min(1.0, len(word) / 14.0)
    return score


def from_local(identity: dict, spec: Optional[dict]) -> Optional[CadModel]:
    entries = local_entries()
    if not entries:
        return None
    text = library.identity_text(identity, spec)
    best, best_score = None, 0.0
    for entry in entries:
        score = _score_entry(entry, text)
        if score > best_score:
            best, best_score = entry, score
    if best is None or best_score < 2.0:
        return None

    data = best["_model"].read_bytes()
    mapping, catalog = {}, []
    for index, part in enumerate(best.get("parts") or [], 1):
        node = str(part.get("node", ""))
        axis = [float(v) for v in (part.get("axis") or [0, 1, 0])]
        norm = math.sqrt(sum(v * v for v in axis)) or 1.0
        mapping[node] = {
            "pid": part.get("id") or node,
            "grp": part.get("group", "internal"),
            "ax": [round(v / norm, 6) for v in axis],
            "d": float(part.get("distance", 0.6)),
            "st": int(part.get("stage", 1)),
        }
        catalog.append({
            "no": index, "id": part.get("id") or node,
            "name": part.get("name") or node, "qty": int(part.get("qty", 1)),
            "group": part.get("group", "internal"),
            "material": part.get("material", materials.DEFAULT),
            "material_label": materials.get(part.get("material", "")).label,
            "note": part.get("note", ""), "standard": part.get("standard", ""),
            "volume_cm3": 0.0, "mass_g": 0.0, "total_mass_g": 0.0,
            "watertight": bool(part.get("watertight", True)),
        })
    diagonal = float(best.get("diagonal_mm") or 0.0)
    patched = gltf.patch_extras(data, mapping, {
        "family": best.get("family", "local"),
        "label": best.get("label", best["_dir"].name),
        "diagonal_mm": diagonal,
    })
    return CadModel(
        source="local", label=str(best.get("label", best["_dir"].name)),
        family=str(best.get("family", "local")),
        representative=bool(best.get("representative", False)),
        glb=patched, catalog=catalog, diagonal_mm=diagonal,
        specs=list(best.get("specs") or []),
        match_reason=f"Yerel CAD kütüphanesinden eşleşti: {best['_dir'].name} "
                     f"({best_score:.1f} puan)",
        confidence="high",
        notes=[f"Model yerel kütüphaneden alındı ({best['_dir'].name}); "
               f"geometri olduğu gibi korundu, yalnızca patlatma sözleşmesi eklendi."],
    )


# --------------------------------------------------------------------------- #
# 2. Uzak API (isteğe bağlı, sözleşme tabanlı)
# --------------------------------------------------------------------------- #

_GLB_RE = re.compile(r"https?://[^\s\"']+\.glb(?:\?[^\s\"']*)?", re.I)


def from_remote(identity: dict, spec: Optional[dict],
                on_progress=lambda m: None) -> Optional[CadModel]:
    """`CAD_API_URL` tanımlıysa uzak katalogdan `.glb` arar.

    Sözleşme: `CAD_API_URL` içindeki `{query}` aranan ifadeyle değiştirilir,
    adres JSON döndürür ve yanıtın herhangi bir yerinde `.glb` ile biten bir
    indirme bağlantısı bulunur. Gerekiyorsa `CAD_API_TOKEN` Authorization
    başlığı olarak gönderilir.
    """
    if not settings.cad_api_url:
        return None
    import httpx

    query = " ".join(str(v) for v in (
        identity.get("product_name_en") or identity.get("product_name"),
        identity.get("nominal_size"), identity.get("pressure_rating")) if v)
    url = settings.cad_api_url.replace("{query}", httpx.QueryParams(
        {"q": query}).get("q", query).replace(" ", "+"))
    headers = {"Authorization": f"Bearer {settings.cad_api_token}"} \
        if settings.cad_api_token else {}
    on_progress(f"uzak CAD kataloğu sorgulanıyor: {query[:60]}")
    try:
        with httpx.Client(timeout=settings.cad_api_timeout,
                          follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            found = _GLB_RE.search(response.text)
            if not found:
                on_progress("uzak katalogda .glb bağlantısı yok")
                return None
            link = found.group(0)
            data = client.get(link, headers=headers).content
    except Exception as e:                                   # noqa: BLE001
        on_progress(f"uzak katalog kullanılamadı ({type(e).__name__}: {str(e)[:80]})")
        return None

    try:
        names = gltf.node_names(data)
    except ValueError as e:
        on_progress(f"indirilen dosya GLB değil ({e})")
        return None
    # Uzak modelde patlatma sözleşmesi yok: düğümler merkezden dışa açılır.
    mapping = {name: {"pid": name, "grp": "internal", "ax": [0.0, 1.0, 0.0],
                      "d": 0.6, "st": 1} for name in names if name}
    on_progress(f"uzak modelden {len(mapping)} düğüm alındı")
    return CadModel(
        source="remote", label=query, family="remote", representative=True,
        glb=gltf.patch_extras(data, mapping, {"family": "remote", "label": query}),
        catalog=[{"no": i, "id": n, "name": n, "qty": 1, "group": "internal",
                  "material": materials.DEFAULT,
                  "material_label": materials.get(materials.DEFAULT).label,
                  "note": "", "standard": "", "volume_cm3": 0.0, "mass_g": 0.0,
                  "total_mass_g": 0.0, "watertight": False}
                 for i, n in enumerate(sorted(mapping), 1)],
        match_reason=f"Uzak CAD kataloğundan indirildi ({link[:70]})",
        confidence="medium",
        notes=["Model uzak katalogdan geldi; parça adları ve montaj eksenleri "
               "kaynaktan olduğu gibi alındı, doğrulanmadı."],
    )


# --------------------------------------------------------------------------- #
# 3. Parametrik üretim
# --------------------------------------------------------------------------- #

def from_parametric(identity: dict, spec: Optional[dict]) -> CadModel:
    assembly, found, params = library.build(identity, spec)
    report = assembly.validate()
    # Girdi parametreleri (DN, PN, bağlantı…) ile ailenin HESAPLADIĞI değerleri
    # (delik çapı, küre çapı, ISO 5211 pabuç kodu, gövde boyu) birleştir.
    # Yalnızca girdiyi kaydetmek, sunum sayfasındaki ISO 5211 etiketinin
    # sessizce kaybolmasına yol açıyordu — o değer yalnızca ailede hesaplanıyor.
    merged = {**params, **assembly.params}
    return CadModel(
        source="parametric", label=assembly.label, family=assembly.family,
        representative=assembly.representative, assembly=assembly,
        catalog=assembly.catalog(), params=merged, report=report,
        match_reason=found.reason, confidence=found.confidence,
        notes=list(assembly.notes), warnings=list(assembly.warnings),
        diagonal_mm=float(report["diagonal_mm"]),
    )


# --------------------------------------------------------------------------- #
# Sıralı deneme
# --------------------------------------------------------------------------- #

def acquire(identity: dict, spec: Optional[dict] = None,
            on_progress=lambda m: None) -> CadModel:
    """Ayarlanmış kaynak sırasını dener; parametrik yol her zaman başarılıdır."""
    order = [s.strip().lower() for s in settings.cad_sources.split(",") if s.strip()]
    for source in order:
        try:
            if source == "local":
                model = from_local(identity, spec)
            elif source == "remote":
                model = from_remote(identity, spec, on_progress)
            elif source == "parametric":
                model = from_parametric(identity, spec)
            else:
                continue
        except Exception as e:                               # noqa: BLE001
            on_progress(f"{source} kaynağı atlandı ({type(e).__name__}: {str(e)[:90]})")
            continue
        if model is not None:
            on_progress(f"kaynak: {model.source} — {model.match_reason}")
            return model
    return from_parametric(identity, spec)
