"""4. Teslimat Ajanı (Web Packager).

metadata.json + model.glb + cad.json -> delivery_<ürün>_<tarih>/ klasörü (+ ZIP).

Paket içeriği:
  index.html            endüstriyel sunum sayfası (Three.js)
  model.glb             parametrik CAD montajı (düğüm başına parça)
  studio.hdr            sentetik stüdyo HDRI (PBR yansımaları)
  urun-1..3.jpg         müşterinin gönderdiği orijinal fotoğraflar
  vendor/three/…        Three.js modülleri (internet gerekmeden açılır)

**Fotoğraf neden pakette:** bu mimaride model fotoğraftan üretilmiyor, ürün
fotoğraftan *tanınıyor*. Müşterinin "bu gerçekten benim ürünüm mü" sorusunu
cevaplayan tek şey, orijinal fotoğrafın modelin yanında durmasıdır. Sağ
paneldeki fotoğraf bu yüzden süs değil, doğrulama aracıdır.

Three.js yerel kopyası varsa (`vendor/three/`) pakete alınır ve sayfa
internetsiz çalışır; yoksa sayfa CDN'e düşer ve bu `index.html` içinde
import map ile çözülür.
"""
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from jinja2 import Environment, FileSystemLoader, select_autoescape

from cad import materials as mat_lib
from cad import standards as std
from core import optimize
from core.config import PROJECT_ROOT, settings
from core.images import list_images, pick_representatives
from core.jobs import slugify

TEMPLATES_DIR = PROJECT_ROOT / "templates"
VENDOR_THREE = PROJECT_ROOT / "vendor" / "three"
HDRI_NAME = "studio.hdr"
PROJ_MASK_NAME = "projection-mask-{}.png"


def _projection_algorithm() -> str:
    """Hizalama kodunun parmak izi — projeksiyon önbellek anahtarına girer.

    Elle tutulan bir sürüm numarası unutuluyor: algoritma düzeltilip paket
    yeniden kurulduğunda eski önbellek sessizce kullanılmaya devam ediyor ve
    düzeltme hiç görünmüyor (yaşandı). Kaynağın özeti bunu imkânsız kılar.
    """
    try:
        from core import projection

        return hashlib.sha1(
            Path(projection.__file__).read_bytes()).hexdigest()[:10]
    except Exception:
        return "0"
# Fotoğrafların TAMAMI projeksiyon aramasına girer: hangi karenin modele
# oturacağı önceden bilinemez — müşterinin sekiz fotoğrafında kazanan, ilk üç
# temsilcinin arasında olmayabilir. Arama bittikten sonra pakete yalnız
# kazanan kare konur, geri kalanı silinir; yani hem daha iyi hizalama hem
# daha küçük paket.
MAX_PHOTOS = 12
# Sürüm sabit: import map CDN'e düşerse de aynı sürüm yüklensin.
THREE_VERSION = "0.180.0"
THREE_CDN = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/"

UI_TEXT = {
    "tr": {
        "eyebrow": "Teknik Ürün Sunumu",
        "assemble": "Birleştir",
        "explode": "Parçala",
        "xray": "X-Ray",
        "labels": "Etiketler",
        "spin": "Döndür",
        "reset": "Sıfırla",
        "fullscreen": "Tam ekran",
        "snapshot": "Görüntü al",
        "share": "Linki kopyala",
        "shared": "Kopyalandı",
        "parts": "Parça listesi",
        "specs": "Teknik özellikler",
        "standard_parts": "Standart bileşenler",
        "standards": "Standartlar",
        "sources": "Kaynaklar",
        "photo": "Müşteri fotoğrafı",
        "summary": "Ürün",
        "photo_texture": "Foto doku",
        "model_info": "Model doğrulama",
        "materials": "Malzeme dökümü",
        "applications": "Kullanım alanları",
        "loading": "CAD montajı yükleniyor",
        "downloading": "İndiriliyor",
        "preparing": "Sahne hazırlanıyor",
        "hint": "Sürükle döndür · tekerlek yakınlaştır · parçaya tıkla incele",
        "qty": "Adet",
        "mass": "Kütle",
        "material": "Malzeme",
        "total_mass": "Toplam kütle",
        "dimensions": "Ölçüler",
        "solid": "su geçirmez katı",
        "representative": "Temsili model",
        "representative_note": "Bu ürün kütüphanedeki parametrik ailelere "
                               "eşleşmedi; gösterilen montaj temsilidir.",
        "all": "Tümü",
        "isolate": "Yalnız bu parça",
        "close": "Kapat",
        "groups": {"housing": "Gövde", "internal": "İç mekanizma",
                   "seal": "Sızdırmazlık", "fastener": "Bağlantı elemanı",
                   "actuator": "Kumanda"},
    },
    "en": {
        "eyebrow": "Technical Product Showcase",
        "assemble": "Assemble", "explode": "Explode", "xray": "X-Ray",
        "labels": "Labels", "spin": "Spin", "reset": "Reset",
        "fullscreen": "Fullscreen", "snapshot": "Snapshot",
        "share": "Copy link", "shared": "Copied",
        "parts": "Parts list", "specs": "Specifications",
        "standard_parts": "Standard components", "standards": "Standards",
        "sources": "Sources", "photo": "Customer photo",
        "summary": "Product",
        "photo_texture": "Photo skin",
        "model_info": "Model validation", "materials": "Material breakdown",
        "applications": "Applications", "loading": "Loading CAD assembly",
        "downloading": "Downloading",
        "preparing": "Preparing scene",
        "hint": "Drag to rotate · scroll to zoom · click a part to inspect",
        "qty": "Qty", "mass": "Mass", "material": "Material",
        "total_mass": "Total mass", "dimensions": "Dimensions",
        "solid": "watertight solids", "representative": "Representative model",
        "representative_note": "This product did not match a parametric family; "
                               "the assembly shown is representative.",
        "all": "All", "isolate": "Isolate", "close": "Close",
        "groups": {"housing": "Housing", "internal": "Internals",
                   "seal": "Sealing", "fastener": "Fasteners",
                   "actuator": "Actuation"},
    },
}

END_LABELS = {"flanged": "Flanşlı", "threaded": "Dişli", "welded": "Kaynaklı",
              "wafer": "Wafer", "clamp": "Clamp", "compression": "Sıkmalı"}
ACT_LABELS = {"lever": "Kol", "handwheel": "Volan", "gear": "Redüktör",
              "pneumatic": "Pnömatik", "electric": "Elektrikli",
              "none": "Çıplak mil"}

# Döküm kalitesi ve malzeme sınıfı damgaları. Üst şeritteki malzeme kodu
# öncelikle ürünün ÜZERİNDE OKUNAN değerden kurulur: malzeme ailesi aynı olsa
# da (paslanmaz döküm) kalite farklı olabilir ve müşteri bunu bilir —
# CF8/304 damgalı bir vanaya "CF8M / 316" yazmak modeli yanlış gösterir.
_CAST_RE = re.compile(
    r"\b(CF8M|CF8C|CF8|CF3M|CF3|WCB|WCC|LCB|LCC|GGG\s?-?\s?\d{2}|GJS[-\w]*|"
    r"GJL[-\w]*|GG\s?-?\s?\d{2}|CW617N|CuSn\d+|A\s?351)\b", re.I)
_GRADE_RE = re.compile(
    r"\b(?:AISI\s*)?(316Ti|316L|316|304L|304|321|1\.4[0-9]{3})\b", re.I)


class PackagingError(RuntimeError):
    pass


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def _write_hdri(dest: Path) -> bool:
    """Stüdyo HDRI'sını pakete yazar. Başarısızlık sunumu durdurmaz."""
    if not settings.hdri_enabled:
        return False
    try:
        from core.hdri import write_studio_hdr
        write_studio_hdr(dest, width=settings.hdri_width)
        return True
    except Exception as e:                                   # noqa: BLE001
        print(f"  Uyarı: stüdyo HDRI üretilemedi ({e}); nötr ortam kullanılacak")
        return False

def _keep_only(out: Path, photos: List[str], keep) -> List[str]:
    """Kullanılmayan aday fotoğrafları paketten siler.

    Adaylar yalnız hizalama araması için kopyalandı. Sayfada galeri yok;
    tek gereken, modele YANSITILAN karelerdir. Çok yönlü projeksiyonda bu
    birkaç tanedir; geri kalanını bırakmak paketi boşuna büyütürdü.
    """
    if isinstance(keep, str):
        keep = [keep] if keep else []
    wanted = [name for name in photos if name in set(keep)]
    if not wanted and photos:
        wanted = [photos[0]]
    for name in photos:
        if name not in wanted:
            (out / name).unlink(missing_ok=True)
    return wanted


def _copy_photos(source_folder: Path, out: Path) -> List[str]:
    """Müşterinin fotoğraflarını küçültüp pakete alır."""
    try:
        images = list_images(Path(source_folder))
    except (FileNotFoundError, OSError):
        return []
    names: List[str] = []
    for index, path in enumerate(pick_representatives(images, MAX_PHOTOS), 1):
        name = f"urun-{index}.jpg"
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.thumbnail((settings.photo_max_side, settings.photo_max_side),
                              Image.LANCZOS)
                img.save(out / name, format="JPEG", quality=86, optimize=True)
            names.append(name)
        except Exception as e:                               # noqa: BLE001
            print(f"  Uyarı: fotoğraf kopyalanamadı ({path.name}: {e})")
    return names


# ES modülü içindeki göreli import hedefleri.
_RELATIVE_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["'](\.[^"']*)["']""")


def missing_modules(root: Path) -> List[str]:
    """Vendor klasöründeki modül grafiğinde eksik dosyaları bulur.

    Bir ES modülü kendi `import`larını kendisi çeker; eksik bir hedef sayfayı
    **sessizce** çalışmaz hale getirir — tek iz konsoldaki 404'tür, kullanıcı
    yükleme ekranında kalır. İki kez yaşandı: three r180 build'i
    `three.module.min.js` + `three.core.min.js` olarak ikiye bölünmüş ve
    yalnızca ilki kopyalanmıştı; Draco yolu açıldığında da `DRACOLoader.js`
    eksikti. Bu yüzden paket, grafiği doğrulanmadan yazılmıyor.
    """
    out: List[str] = []
    for script in sorted(Path(root).rglob("*.js")):
        try:
            text = script.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for target in _RELATIVE_IMPORT.findall(text):
            if not (script.parent / target).resolve().exists():
                out.append(f"{script.name} -> {target}")
    return out


def _projection_search(model_path: Path, out: Path, photos: List[str]
                       ) -> List[dict]:
    """Hizalamayı arar (pahalı adım) ve sonucu iş dizinine önbellekler.

    Dönen liste ÇOK YÖNLÜ projeksiyondur: ilk kayıt en iyi oturan yöndür
    (sayfanın açılış kamerası ondan kurulur), geri kalanlar ürünün başka
    yüzlerini giydirir.
    """
    cache = model_path.parent.parent / "projection.json"
    key = (f"v{_projection_algorithm()}:{model_path.stat().st_size}:"
           f"{model_path.stat().st_mtime_ns}:{','.join(photos)}")
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            data = cached.get("projectors") or []
            if data:
                print(f"  Fotoğraf projeksiyonu (önbellek): {len(data)} yön, "
                      f"toplam kaplama "
                      f"%{cached.get('total_coverage', 0) * 100:.0f}")
            return data
    except Exception:
        pass

    try:
        from core import projection as proj

        found, info = proj.build_multi(
            model_path, [out / name for name in photos],
            min_iou=settings.projection_min_iou)
    except Exception as exc:
        print(f"  Uyarı: fotoğraf projeksiyonu kurulamadı ({exc})")
        return []
    if not found:
        print("  Uyarı: fotoğraf projeksiyonu — hiçbir kare yeterince "
              f"örtüşmedi (eşik {settings.projection_min_iou:.2f}); saf PBR")
        data: List[dict] = []
    else:
        data = [p.as_dict() for p in found]
        print(f"  Fotoğraf projeksiyonu: {len(data)} yön, toplam kaplama "
              f"%{info.get('total_coverage', 0) * 100:.0f} "
              f"(yüzeyin bu kadarı gerçek fotoğraf giyiyor; "
              f"kalanı endüstriyel PBR çelik)")
        for item in data:
            print(f"    · {item['photo']}: örtüşme {item['iou']:.2f}, "
                  f"kaplama %{item['coverage'] * 100:.0f}")
    try:
        cache.write_text(json.dumps(
            {"key": key, "projectors": data, "info": info,
             "total_coverage": info.get("total_coverage", 0.0)},
            ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    except Exception:
        pass
    return data


def _build_projection(model_path: Path, out: Path,
                      photos: List[str]) -> List[dict]:
    """Müşteri fotoğraflarını modelin kabuğuna oturtan projektör KÜMESİ.

    Tek projektör ürünün yalnız bir yüzünü giydiriyordu; ziyaretçi modeli
    çevirince arkası çıplak PBR olarak kalıyordu. Fotoğraflar farklı
    açılardan çekildiği için birlikte çok daha fazla yüzey kaplarlar
    (ölçüldü: %38 -> %65).

    İsteğe bağlı adım: başarısız olursa sayfa saf PBR ile çalışır (düğme
    gizli kalır). Hizalama ölçülerek bulunur ve kalitesi `iou` ile
    raporlanır — "oturdu mu" sorusunun gözle değil sayıyla cevabı vardır.

    Arama ~30 sn sürdüğü için iş dizininde önbelleklenir. Maske PNG'leri ise
    **her seferinde** teslim klasörüne yazılır: önbellek yalnız SAYILARI
    taşır, dosyaları değil. Yazımı önbellek dalının içinde bırakmak sessiz
    bir hataydı — ikinci paketlemede maske dosyası eksik kalıyor, sayfa onu
    404 alıyor, maske kapısı her pikseli kapatıyor ve fotoğraf modelde HİÇ
    görünmüyordu (yaşandı, tarayıcıda yakalandı).
    """
    if not settings.projection_enabled or not photos:
        return []
    found = _projection_search(model_path, out, photos)
    if not found:
        return []
    from core import projection as proj

    out_list: List[dict] = []
    for index, item in enumerate(found):
        data = dict(item)
        name = PROJ_MASK_NAME.format(index + 1)
        try:
            written = proj.export_mask(out / data["photo"], out / name)
        except Exception as exc:
            print(f"  Uyarı: {data['photo']} maskesi yazılamadı "
                  f"({type(exc).__name__})")
            written = None
        data["mask"] = name if written else ""
        if not written:
            print(f"  Uyarı: {data['photo']} maskesi yok; arka planı sızabilir")
        out_list.append(data)
    return out_list


def _copy_three(out: Path) -> bool:
    """Three.js modüllerini pakete alır (internetsiz açılabilsin diye)."""
    if not VENDOR_THREE.exists():
        return False
    target = out / "vendor" / "three"
    shutil.copytree(VENDOR_THREE, target, dirs_exist_ok=True)
    if not (target / "three.module.min.js").exists():
        return False
    broken = missing_modules(target)
    if broken:
        raise PackagingError(
            "Three.js modül grafiği eksik, sayfa açılmazdı: "
            + "; ".join(broken[:4])
            + f" (vendor/three içine eksik dosyaları koyun)")
    return True


def _swatches() -> dict:
    """Parça listesindeki renk kareleri: malzeme anahtarı -> hex.

    Sayfadaki küçük renk karesi, listedeki satırla 3B'deki parçayı gözle
    eşleştirmenin en hızlı yolu; GLB'deki PBR rengiyle aynı tablodan gelir.
    """
    out = {}
    for key, material in mat_lib.MATERIALS.items():
        r, g, b = (max(0, min(255, int(round(c * 255)))) for c in material.color)
        out[key] = f"#{r:02x}{g:02x}{b:02x}"
    return out


def _material_code(identity: dict, spec: dict, params: dict) -> str:
    """Üst şeritte gösterilecek kısa malzeme kodu.

    Sıra kasıtlı: önce ürünün ÜZERİNDE okunan damga, sonra araştırmanın
    doğruladığı kalite, en son malzeme ailesinin genel kodu. Aile kodu tek
    başına yanıltıcı olabiliyor — "paslanmaz döküm" ailesinin genel kodu
    CF8M/316'dır ama fotoğraftaki vanada CF8 (AISI 304) yazıyordu ve şerit
    ürünle çelişen bir kalite ilan ediyordu.
    """
    sources = [identity.get("body_material", ""),
               " ".join(str(m) for m in (identity.get("markings") or [])),
               spec.get("identified_as", ""),
               " ".join(f"{s.get('label')} {s.get('value')}"
                        for s in (spec.get("specs") or []))]
    for text in sources:
        if not text:
            continue
        cast = _CAST_RE.search(text)
        grade = _GRADE_RE.search(text)
        if cast and grade:
            return f"{cast.group(1).upper()} / {grade.group(1).upper()}"
        if cast:
            return cast.group(1).upper()
    material = params.get("body_material")
    if material:
        return mat_lib.body_code(str(material))
    return str(identity.get("body_material") or "")


def _chips(identity: dict, spec: dict, cad: dict) -> List[dict]:
    """Üst şeritteki teknik etiketler: CF8M/316, DN50, PN40, …"""
    params = cad.get("params") or {}
    chips: List[dict] = []

    def add(label: str, value) -> None:
        if value not in (None, "", 0):
            chips.append({"label": label, "value": str(value)})

    add("Malzeme", _material_code(identity, spec, params))

    dn = params.get("dn")
    if dn:
        add("Anma çapı", f"DN{dn}  ({std.nps_label(int(dn))})")
    else:
        add("Anma çapı", spec.get("nominal_size") or identity.get("nominal_size"))

    pn = params.get("pn")
    if pn:
        add("Basınç", f"PN{pn}")
    else:
        add("Basınç", spec.get("pressure_rating") or identity.get("pressure_rating"))

    # Sıra ürünü AYIRT ETME gücüne göre: bağlantı ve montaj arayüzü iki ürünü
    # birbirinden ayırır, sıcaklık aralığı ayırmaz. Şerit kesilirse en sondaki
    # düşer, bu yüzden sıcaklık sona konuyor (ISO 5211 pabucu bu yüzden
    # şeritten düşüyordu — ürünün en ayırt edici özelliklerinden biri olduğu
    # hâlde).
    end = params.get("end")
    if end:
        add("Bağlantı", END_LABELS.get(str(end), str(end)))
    if params.get("pieces"):
        add("Gövde", f"{params['pieces']} parçalı")
    if params.get("iso5211"):
        add("Montaj", f"ISO 5211 {params['iso5211']}")
    act = params.get("actuation")
    if act and params.get("dn"):
        add("Kumanda", ACT_LABELS.get(str(act), str(act)))
    add("Sıcaklık", spec.get("temperature_range"))
    return chips[:8]


# Etiketlenecek parçanın kütle eşiği (montaj kütlesine oran).
KEY_PART_MASS_SHARE = 0.01
# Bu gruplar hiçbir zaman etiketlenmez: ürünü anlatmazlar, yalnız sayıca
# çokturlar. 21 parçalık vanada 13'ü bu ikisinden.
KEY_PART_SKIP_GROUPS = ("fastener", "seal")


def _mark_key_parts(parts: List[dict]) -> List[dict]:
    """Patlatmada ETİKETİ görünecek "ana parça"ları işaretler.

    Patlatma açıldığında 21 etiket birden çıkıyor ve ürünü okunmaz bir ok
    yumağına çeviriyordu. Cıvata, somun, pul, conta — ürünü anlatan şeyler
    değil, yalnız sayıca çok olan şeyler.

    Ölçüt iki parçalı ve aileden bağımsız: bağlantı elemanı/sızdırmazlık
    DEĞİL, ve montaj kütlesinin en az %1'i. Ad listesi tutmak yerine kütle
    kullanmak yeni ailelerde de çalışır; kelebek vanada disk ve mil, süzgeçte
    sepet kendiliğinden ana parça çıkar.

    İşaret yalnız ETİKETİ etkiler: parça listesinde hepsi durur ve
    tıklanınca yine seçilir.
    """
    total = sum(float(p.get("total_mass_g") or 0) for p in parts) or 1.0
    for part in parts:
        share = float(part.get("total_mass_g") or 0) / total
        part["key"] = (part.get("group") not in KEY_PART_SKIP_GROUPS
                       and share >= KEY_PART_MASS_SHARE)
    return parts


def _pipeline(cad: dict) -> Optional[dict]:
    """Vananın oturduğu boru hattının tanımı (sayfa bunu 3B'de kurar).

    Ürünü boşlukta göstermek ölçeği ve işlevi anlatmıyor; hattın içinde
    göstermek ikisini birden anlatıyor. Boru çapı anma ölçüsünden gelir
    (EN 10220 dış çap), eksen ise bütün ailelerin paylaştığı sözleşmedir:
    **akış Z, mil +Y** (bkz. cad/families/*.py başlıkları). Aile bunu
    `params["flow_axis"]` ile ezebilir.

    Anma ölçüsü bilinmiyorsa None döner ve sayfa boruyu hiç kurmaz — yanlış
    çapta bir boru çizmektense hiç çizmemek doğru.
    """
    params = (cad.get("params") or {})
    dn = params.get("dn")
    if not dn:
        return None
    try:
        from cad import standards as std

        outer = float(std.pipe_od(int(dn)))
    except Exception:
        return None
    bore = float(params.get("bore_mm") or dn)
    line = cad.get("flow_line") or {}
    return {
        "axis": [float(v) for v in (line.get("axis")
                                    or params.get("flow_axis", (0.0, 0.0, 1.0)))],
        # Eksenin GEÇTİĞİ nokta ve vananın uç yüzeyleri (model mm). Bunlar
        # olmadan sayfa boruyu sınır kutusunun merkezine koyuyor ve boru
        # vananın deliğinden değil, gövdesinin üstünden geçiyordu.
        "origin_mm": [float(v) for v in (line.get("origin") or (0.0, 0.0, 0.0))],
        "ends_mm": ([float(v) for v in line["ends_mm"]]
                    if line.get("ends_mm") else None),
        "od_mm": outer,
        "bore_mm": bore,
        "dn": int(dn),
        "label": f"DN{int(dn)} boru hattı",
    }


def build_package(job_dir: Path, lang: str = "tr", make_zip: bool = True,
                  out_dir: Optional[Path] = None) -> Path:
    job_dir = Path(job_dir)
    meta_path = job_dir / "metadata.json"
    if not meta_path.exists():
        raise PackagingError(f"{meta_path} bulunamadı (önce tanıma adımı)")
    model_path = job_dir / "model.glb"
    if not model_path.exists():
        raise PackagingError(f"{model_path} bulunamadı (önce CAD adımı)")

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    identity = metadata.get("identity") or {}
    spec = metadata.get("spec") or {}
    cad = _load_json(job_dir / "cad.json")
    ui = UI_TEXT.get(lang, UI_TEXT["en"])

    name_slug = slugify(identity.get("product_name")
                        or identity.get("product_name_en", ""), "urun").replace("-", "_")
    out = out_dir or job_dir / f"delivery_{name_slug}_{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)

    # Web için sıkıştırılmış sürüm varsa O gider; sayfa her hâlükârda
    # "model.glb" ister, hangi sürümün geldiğini `cad.json` kaydeder.
    web = cad.get("web_model") or {}
    source_model = job_dir / str(web.get("file") or "model.glb")
    if not source_model.exists():
        source_model = model_path
    uses_draco = bool(web.get("draco")) and source_model.name == web.get("file")
    shutil.copy2(source_model, out / "model.glb")
    has_draco_decoder = optimize.copy_decoder(out) if uses_draco else False
    if uses_draco and not has_draco_decoder:
        # Çözücü pakete konamadıysa sıkıştırılmış model açılamaz; sıkıştırılmamış
        # sürüme dönmek, açılmayan bir sayfa göndermekten iyidir.
        shutil.copy2(model_path, out / "model.glb")
        uses_draco = False
        print("  Uyarı: Draco çözücüsü pakete konamadı; sıkıştırılmamış model kullanıldı")

    has_hdri = _write_hdri(out / HDRI_NAME)
    photos = _copy_photos(metadata.get("source_folder", ""), out)
    three_local = _copy_three(out)
    projectors = _build_projection(out / "model.glb", out, photos)
    photos = _keep_only(out, photos, [p["photo"] for p in projectors])

    validation = cad.get("validation") or {}
    parts = cad.get("parts") or []
    # Parça listesi gruplanır: gövde -> iç mekanizma -> sızdırmazlık -> bağlantı
    order = {"housing": 0, "internal": 1, "seal": 2, "fastener": 3, "actuator": 4}
    parts = sorted(parts, key=lambda p: (order.get(p.get("group", ""), 9),
                                         -float(p.get("total_mass_g") or 0)))
    parts = _mark_key_parts(parts)

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR),
                      autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("viewer.html.j2").render(
        lang=lang,
        ui=ui,
        identity=identity,
        spec=spec,
        cad=cad,
        validation=validation,
        parts=parts,
        materials=cad.get("materials") or [],
        chips=_chips(identity, spec, cad),
        specs=(spec.get("specs") or []) + list(cad.get("extra_specs") or []),
        standard_parts=spec.get("standard_parts") or [],
        standards=spec.get("standards") or [],
        applications=spec.get("applications") or [],
        sources=(spec.get("reference_urls") or [])[:6],
        photos=photos,
        projection=projectors[0] if projectors else None,
        projectors=projectors,
        pipeline=_pipeline(cad),
        swatches=_swatches(),
        has_hdri=has_hdri,
        hdri_file=HDRI_NAME,
        # Gercek yuzde cubugu icin dosya boyutlari sayfaya gomuluyor: tunel
        # yanitlari parcali geldiginden tarayici Content-Length goremiyor.
        model_bytes=(out / "model.glb").stat().st_size,
        hdri_bytes=(out / HDRI_NAME).stat().st_size if has_hdri else 0,
        draco=uses_draco,
        draco_path="vendor/draco/",
        three_local=three_local,
        three_cdn=THREE_CDN,
        model_file="model.glb",
        diagonal_mm=float(cad.get("diagonal_mm") or 0.0),
        generated=datetime.now().strftime("%d.%m.%Y"),
    )
    (out / "index.html").write_text(html, encoding="utf-8")

    if make_zip:
        shutil.make_archive(str(out), "zip", root_dir=out)
    return out
