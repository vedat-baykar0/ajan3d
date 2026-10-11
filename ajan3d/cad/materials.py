"""PBR malzeme kütüphanesi ve yoğunluklar.

İki işi birden yapar:

1. **Görsel:** her malzeme glTF `pbrMetallicRoughness` değerleriyle tanımlı.
   Doku atlası yok — renk/metaliklik/pürüzlülük sayısal, yansımayı stüdyo HDRI
   veriyor. Bu, "fotoğraftan çıkarılmış doku" yaklaşımının tersi: ışık dokunun
   içine pişmiş olmadığı için parça gerçekten metal gibi davranıyor, sahnede
   döndükçe parlaklık tepesi yüzey üzerinde geziyor.

2. **Mühendislik:** `density` (g/cm³) ile her parçanın hacminden **kütlesi**
   hesaplanıyor. Kütle ancak kapalı (su geçirmez) bir katı için anlamlıdır;
   bu yüzden aynı zamanda modelin "içi dolu" olduğunun ölçülebilir kanıtıdır.
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Material:
    """Bir malzemenin görsel + fiziksel tanımı.

    `color` **sRGB** cinsindendir (okunabilir olsun diye); glTF'ye yazılırken
    lineere çevrilir (`cad/gltf.srgb_to_linear`). Metaller için bu renk
    yansıma katsayısı F0'dır, bu yüzden ölçülmüş değerlere göre seçildi:
    çelik F0 ≈ 0.56 lineer (≈0.78 sRGB), pirinç ≈ (0.71, 0.65, 0.26) lineer.
    Yalıtkanlarda ise olağan albedo anlamı geçerli.
    """
    key: str
    label: str                       # müşteriye gösterilecek ad
    color: Tuple[float, float, float]
    metallic: float
    roughness: float
    density: float                   # g/cm³
    opacity: float = 1.0
    xray_opacity: float = 0.10       # X-Ray modunda saydamlık


def _m(key, label, color, metallic, roughness, density, **kw) -> Material:
    return Material(key, label, color, metallic, roughness, density, **kw)


MATERIALS = {
    # --- paslanmaz çelik aile ---------------------------------------------
    # Parlatılmış paslanmazın F0'ı ~0.56 lineerdir (~0.78 sRGB) ve tablo
    # başlangıçta bütün aileyi o değere yakın tutuyordu. Sonuç tek parçaymış
    # gibi duran bir "gümüş blok"tu: döküm gövde, çekme saplama ve parlatılmış
    # küre aynı renkte okunuyordu.
    #
    # Oysa F0 yüzey işlemiyle birlikte düşer: kum püskürtülmüş döküm yüzeyde
    # mikro çıkıntılar ışığı birbirine çarptırıp yutar (çoklu saçılma), ölçülen
    # yansıtma parlatılmış numunenin belirgin altına iner. Tablo artık bu
    # sıralamayı taşıyor — döküm koyu ve mat, çekme/işlenmiş orta, parlatılmış
    # açık ve aynasal. Parçalar birbirinden böyle ayrılıyor.
    "stainless_cast": _m("stainless_cast", "CF8M döküm paslanmaz çelik (AISI 316)",
                         (0.688, 0.697, 0.710), 1.0, 0.54, 7.98),
    "stainless_machined": _m("stainless_machined", "İşlenmiş paslanmaz çelik (AISI 316)",
                             (0.786, 0.795, 0.806), 1.0, 0.25, 7.98),
    "stainless_bright": _m("stainless_bright", "Çekme paslanmaz saplama (A2-70)",
                           (0.826, 0.833, 0.843), 1.0, 0.15, 7.98),
    "stainless_polished": _m("stainless_polished", "Parlatılmış paslanmaz çelik",
                             (0.858, 0.866, 0.876), 1.0, 0.07, 7.98),
    "stainless_blasted": _m("stainless_blasted", "Kumlanmış paslanmaz çelik, mat",
                            (0.650, 0.659, 0.672), 1.0, 0.66, 7.98),
    # --- diğer metaller ---
    "carbon_steel": _m("carbon_steel", "Karbon çeliği", (0.755, 0.758, 0.765),
                       1.0, 0.42, 7.85),
    "zinc_plated": _m("zinc_plated", "Galvaniz kaplı çelik (8.8 kalite)",
                      (0.800, 0.808, 0.818), 1.0, 0.38, 7.85),
    "cast_iron": _m("cast_iron", "GJL-250 pik döküm", (0.470, 0.472, 0.482),
                    0.85, 0.68, 7.20),
    "ductile_epoxy": _m("ductile_epoxy", "GGG40 sfero döküm, epoksi boyalı",
                        (0.145, 0.360, 0.560), 0.05, 0.40, 7.10),
    "brass": _m("brass", "CW617N pirinç", (0.870, 0.838, 0.548), 1.0, 0.30, 8.45),
    "bronze": _m("bronze", "CuSn12 bronz", (0.840, 0.748, 0.612), 1.0, 0.42, 8.80),
    "aluminium": _m("aluminium", "Alüminyum (EN AW-6082)", (0.958, 0.962, 0.962),
                    1.0, 0.34, 2.70),
    "chrome": _m("chrome", "Sert krom kaplama", (0.772, 0.778, 0.772), 1.0, 0.06, 7.85),
    # --- yalıtkan / sızdırmazlık (albedo) ---
    "ptfe": _m("ptfe", "PTFE (teflon) oturma", (0.945, 0.947, 0.934), 0.0, 0.33, 2.20),
    "tfm": _m("tfm", "TFM 1600 oturma", (0.912, 0.920, 0.902), 0.0, 0.28, 2.17),
    "graphite": _m("graphite", "Grafit salmastra", (0.225, 0.228, 0.238), 0.25, 0.78, 1.90),
    "nbr": _m("nbr", "NBR elastomer", (0.160, 0.160, 0.170), 0.0, 0.88, 1.25),
    "epdm": _m("epdm", "EPDM conta", (0.175, 0.180, 0.185), 0.0, 0.84, 1.15),
    "peek": _m("peek", "PEEK yatak burcu", (0.780, 0.680, 0.440), 0.0, 0.42, 1.32),
    # --- pnömatik aktüatör (müşterinin ürün fotoğrafından) ---
    # Gövde ham ekstrüzyon alüminyum (anotlu, mat), uç kapakları MAVİ boyalı,
    # gösterge sarı/siyah, hava portu tapaları kırmızı. Bu dört renk ürünü
    # uzaktan tanıtan şeydir; tek tip gümüş yapmak aktüatörü vananın
    # devamı gibi gösteriyordu.
    "aluminium_anodised": _m("aluminium_anodised", "Anotlu alüminyum gövde",
                             (0.845, 0.852, 0.860), 0.92, 0.38, 2.70),
    "actuator_blue": _m("actuator_blue", "Boyalı alüminyum uç kapağı",
                        (0.075, 0.300, 0.520), 0.05, 0.36, 2.70),
    "indicator_yellow": _m("indicator_yellow", "Gösterge kadranı (PA, sarı)",
                           (0.880, 0.720, 0.060), 0.0, 0.42, 1.40),
    "port_red": _m("port_red", "Hava portu tapası (PE, kırmızı)",
                   (0.620, 0.075, 0.075), 0.0, 0.48, 0.95),

    # --- kumanda / kaplama ---
    "vinyl_red": _m("vinyl_red", "Vinil kol kılıfı", (0.660, 0.110, 0.105),
                    0.0, 0.52, 1.30),
    "vinyl_blue": _m("vinyl_blue", "Vinil kol kılıfı", (0.120, 0.330, 0.620),
                     0.0, 0.52, 1.30),
    "plastic_black": _m("plastic_black", "Teknik plastik", (0.185, 0.188, 0.196),
                        0.0, 0.45, 1.40),
}

DEFAULT = "stainless_machined"


def get(key: str) -> Material:
    return MATERIALS.get(key, MATERIALS[DEFAULT])


def mass_g(volume_mm3: float, material: str) -> float:
    """Hacimden (mm³) kütle (g). 1 cm³ = 1000 mm³."""
    return (max(0.0, volume_mm3) / 1000.0) * get(material).density


# --------------------------------------------------------------------------- #
# Metinden malzeme seçimi
# --------------------------------------------------------------------------- #

# Sıra önemli: en belirleyici anahtar kelime önce taranır.
_HINTS = (
    ("stainless_cast", ("cf8m", "cf8", "cf3m", "a351", "döküm paslanmaz", "dokum paslanmaz",
                        "cast stainless", "316 döküm")),
    ("stainless_bright", ("a2-70", "a4-70", "a2-80", "çekme paslanmaz")),
    ("stainless_machined", ("316", "304", "aisi", "paslanmaz", "stainless", "inox",
                            "1.4401", "1.4408", "1.4301")),
    ("ductile_epoxy", ("sfero", "ductile", "ggg", "gjs", "epoksi", "epoxy")),
    ("cast_iron", ("pik döküm", "pik dokum", "gri döküm", "cast iron", "gg25", "gjl")),
    ("brass", ("pirinç", "pirinc", "brass", "cw617", "ms58")),
    ("bronze", ("bronz", "bronze", "cusn")),
    ("aluminium", ("alüminyum", "aluminyum", "aluminium", "aluminum")),
    ("chrome", ("krom", "chrome", "nikel kaplama")),
    ("zinc_plated", ("galvaniz", "galvanized", "zinc", "çinko", "cinko")),
    ("carbon_steel", ("karbon çelik", "karbon celik", "carbon steel", "st37", "s235",
                      "çelik", "celik", "steel")),
    ("tfm", ("tfm", "tfm1600", "tfm 1600")),
    ("ptfe", ("ptfe", "teflon", "pfa", "fep")),
    ("graphite", ("grafit", "graphite")),
    ("nbr", ("nbr", "nitril", "nitrile", "buna")),
    ("epdm", ("epdm", "viton", "fkm", "kauçuk", "kaucuk", "rubber", "lastik")),
    ("peek", ("peek", "pps")),
    ("plastic_black", ("plastik", "plastic", "pa66", "poliamit", "abs", "pvc")),
)


def from_text(*texts: str, default: str = DEFAULT) -> str:
    """Serbest metinden malzeme anahtarı seçer (Vision/Araştırma çıktısı için)."""
    blob = " ".join(str(t).lower() for t in texts if t)
    for key, words in _HINTS:
        if any(w in blob for w in words):
            return key
    return default


def body_code(key: str) -> str:
    """Üstteki etiket şeridinde gösterilecek kısa malzeme kodu."""
    return {
        "stainless_cast": "CF8M / 316",
        "stainless_machined": "AISI 316",
        "stainless_bright": "A2-70",
        "aluminium_anodised": "Alüminyum",
        "actuator_blue": "Boyalı Al",
        "stainless_polished": "AISI 316 parlak",
        "stainless_blasted": "AISI 316 kumlanmış",
        "carbon_steel": "Karbon çeliği",
        "zinc_plated": "Galvaniz 8.8",
        "cast_iron": "GJL-250",
        "ductile_epoxy": "GGG40",
        "brass": "CW617N",
        "bronze": "CuSn12",
        "aluminium": "EN AW-6082",
        "chrome": "Cr kaplama",
    }.get(key, get(key).label)
