"""CAD kütüphanesi: aile kataloğu, eşleştirme ve parametre türetme.

Sistemin "ürünü tanı → doğru montajı kur" halkası burada kapanır. İki kademeli
çalışır, çünkü iki bilgi kaynağının da zayıf yanı var:

1. **Ajanın önerisi** (`family_hint`). Vision ajanı fotoğrafa bakıp kataloğdaki
   aileden birini seçer. Güçlü sinyaldir ama modelin yanılması mümkündür ve
   ajan çıktısı serbest metinle gelir.
2. **Anahtar kelime puanlaması.** Tanınan ad, tip tanımı, araştırmanın bulduğu
   endüstri adı ve görünen özellikler tek metne dökülür ve ailelerin Türkçe +
   İngilizce anahtar kelimeleriyle puanlanır.

İkisi birleştirilir: ajanın önerisi büyük bir puan katkısıdır, ama metin
tamamen başka bir aileyi işaret ediyorsa metin kazanabilir. Hiçbir aile eşiği
geçemezse `generic_housing` seçilir ve montaj **temsili** işaretlenir —
sistemin "bilmiyorum" deme yolu budur; sessizce yanlış bir vana üretmez.

Ölçüler ayrı bir yoldan gelir: `cad/standards.py` ayrıştırıcıları aynı metinden
DN, PN, bağlantı tipi, kumanda tipi ve gövde parça sayısını okur. Yani aile
"ne olduğunu", standartlar "ne kadar olduğunu" belirler.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from cad import materials, standards as std
from cad.assembly import Assembly
from cad.families import (ball_valve, bearing, butterfly_valve, check_valve,
                          flange_joint, gate_valve, generic, strainer)

# Eşleşmenin kabul edilmesi için gereken en düşük puan. Altında kalan her şey
# temsili montaja düşer.
MATCH_THRESHOLD = 2.0
HINT_WEIGHT = 3.5


@dataclass(frozen=True)
class Family:
    id: str
    label: str
    category: str
    builder: Callable[[dict], Assembly]
    keywords: Tuple[str, ...]
    negative: Tuple[str, ...] = ()
    extra: Dict[str, object] = field(default_factory=dict)


FAMILIES: Dict[str, Family] = {
    "ball_valve": Family(
        "ball_valve", "Küresel vana", "vana", ball_valve.build,
        ("küresel vana", "kuresel vana", "küresel", "top vana", "ball valve",
         "ballvalve", "kueresel", "3 parçalı vana", "3 parcali vana",
         "three piece valve", "floating ball", "trunnion"),
        negative=("kelebek", "butterfly", "sürgü", "surgu", "gate", "rulman")),
    "gate_valve": Family(
        "gate_valve", "Sürgülü vana", "vana", gate_valve.build,
        ("sürgülü vana", "surgulu vana", "sürgü vanası", "surgu vanasi",
         "gate valve", "wedge valve", "kama vana", "stop valve", "globe valve",
         "globe vana", "glob vana", "yükselen milli", "yukselen milli")),
    "butterfly_valve": Family(
        "butterfly_valve", "Kelebek vana", "vana", butterfly_valve.build,
        ("kelebek vana", "kelebek", "butterfly valve", "butterfly", "wafer valve",
         "lug valve", "disk vana")),
    "check_valve": Family(
        "check_valve", "Çek valf", "vana", check_valve.build,
        ("çek valf", "cek valf", "çekvalf", "cekvalf", "check valve",
         "non return", "nonreturn", "tek yön", "tek yon", "klape", "swing check",
         "geri tepme")),
    "y_strainer": Family(
        "y_strainer", "Y tipi pislik tutucu", "hat ekipmanı", strainer.build,
        ("pislik tutucu", "pislik tutucusu", "süzgeç", "suzgec", "strainer",
         "y filtre", "y-filtre", "y tipi", "y-strainer", "filtre", "filter",
         "sepet filtre")),
    "flange_joint": Family(
        "flange_joint", "Flanşlı boru birleşimi", "boru bağlantısı",
        flange_joint.build,
        ("flanş", "flans", "flange", "boru bağlantısı", "boru baglantisi",
         "kaynak boyunlu", "weld neck", "slip on", "blind flange", "kör flanş",
         "rakor", "adaptör", "nipel", "pipe fitting", "boru ek parçası")),
    "ball_bearing": Family(
        "ball_bearing", "Sabit bilyalı rulman", "makine elemanı", bearing.build,
        ("rulman", "bilyalı rulman", "bilyali rulman", "bearing", "ball bearing",
         "deep groove", "yatak", "6204", "6205", "6206", "6208", "6305")),
    "generic_housing": Family(
        "generic_housing", "Gövde-kapak montajı (temsili)", "genel",
        generic.build, ()),
}

# Vision ajanının seçebileceği kimlikler (şemadaki enum ile aynı sırada tutulur).
HINTS = {
    "ball_valve": "ball_valve",
    "gate_valve": "gate_valve",
    "globe_valve": "gate_valve",
    "butterfly_valve": "butterfly_valve",
    "check_valve": "check_valve",
    "y_strainer": "y_strainer",
    "flange_joint": "flange_joint",
    "ball_bearing": "ball_bearing",
    "other": "generic_housing",
}


@dataclass
class Match:
    family: Family
    score: float
    confidence: str                  # high | medium | low
    hint: str
    reason: str
    scores: Dict[str, float] = field(default_factory=dict)


def _blob(*texts) -> str:
    parts: List[str] = []
    for item in texts:
        if not item:
            continue
        if isinstance(item, (list, tuple)):
            parts.extend(str(v) for v in item)
        elif isinstance(item, dict):
            parts.extend(f"{k} {v}" for k, v in item.items())
        else:
            parts.append(str(item))
    return re.sub(r"\s+", " ", " ".join(parts)).lower()


def identity_text(identity: dict, spec: Optional[dict] = None) -> str:
    """Eşleştirme ve ölçü ayrıştırma için kullanılan tek birleşik metin."""
    spec = spec or {}
    return _blob(
        identity.get("product_name"), identity.get("product_name_en"),
        identity.get("type_designation"), identity.get("category"),
        identity.get("nominal_size"), identity.get("pressure_rating"),
        identity.get("end_connection"), identity.get("actuation"),
        identity.get("body_material"), identity.get("visible_features"),
        identity.get("markings"), identity.get("materials"),
        spec.get("identified_as"), spec.get("standard_parts"),
        spec.get("standards"), [f"{s.get('label')} {s.get('value')}"
                                for s in (spec.get("specs") or [])],
    )


def match(identity: dict, spec: Optional[dict] = None) -> Match:
    """Tanınan ürünü bir CAD ailesine eşleştirir."""
    text = identity_text(identity, spec)
    hint = HINTS.get(str(identity.get("family_hint", "")).strip().lower(), "")

    scores: Dict[str, float] = {}
    for key, family in FAMILIES.items():
        if key == "generic_housing":
            continue
        score = 0.0
        for word in family.keywords:
            if word in text:
                # Uzun ifadeler daha ayırt edici: "küresel vana" > "vana"
                score += 1.0 + min(1.0, len(word) / 14.0)
        for word in family.negative:
            if word in text:
                score -= 1.6
        if hint == key:
            score += HINT_WEIGHT
        if score > 0:
            scores[key] = round(score, 2)

    if not scores or max(scores.values()) < MATCH_THRESHOLD:
        return Match(FAMILIES["generic_housing"], max(scores.values(), default=0.0),
                     "low", hint,
                     "Ürün kataloğdaki ailelerden hiçbirine yeterince benzemedi; "
                     "temsili gövde-kapak montajı kuruldu.", scores)

    best = max(scores, key=lambda k: scores[k])
    score = scores[best]
    runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    gap = score - runner_up
    if score >= 5.0 and gap >= 2.0:
        confidence = "high"
    elif score >= 3.0:
        confidence = "medium"
    else:
        confidence = "low"

    reason = f"'{FAMILIES[best].label}' ailesi {score:.1f} puanla eşleşti"
    if hint == best:
        reason += " (görüntü ajanının önerisiyle aynı)"
    elif hint and hint in FAMILIES:
        reason += f"; görüntü ajanı '{FAMILIES[hint].label}' önermişti"
    return Match(FAMILIES[best], score, confidence, hint, reason, scores)


# --------------------------------------------------------------------------- #
# Parametre türetme
# --------------------------------------------------------------------------- #

_SEAT_HINTS = (("tfm", ("tfm",)), ("ptfe", ("ptfe", "teflon", "pfa")),
               ("peek", ("peek",)), ("epdm", ("epdm", "kauçuk", "kaucuk", "rubber")),
               ("nbr", ("nbr", "nitril", "buna")),
               ("graphite", ("grafit", "graphite")),
               ("bronze", ("bronz", "bronze")))


def _seat_material(text: str, default: str) -> str:
    for key, words in _SEAT_HINTS:
        if any(w in text for w in words):
            return key
    return default


def params_for(family: Family, identity: dict, spec: Optional[dict] = None) -> dict:
    """Aileye verilecek ölçü ve malzeme parametrelerini metinden türetir."""
    spec = spec or {}
    text = identity_text(identity, spec)
    size_text = " ".join(str(v) for v in (
        identity.get("nominal_size"), identity.get("type_designation"),
        identity.get("product_name"), spec.get("identified_as")) if v)
    press_text = " ".join(str(v) for v in (
        identity.get("pressure_rating"), spec.get("identified_as"),
        " ".join(f"{s.get('label')} {s.get('value')}"
                 for s in (spec.get("specs") or []))) if v)

    dn = std.parse_dn(size_text, text, default=50)
    pn = std.parse_pn(press_text, text, default=16)
    end = std.parse_end(identity.get("end_connection"), text, default="threaded")
    actuation = std.parse_actuation(identity.get("actuation"), text, default="lever")
    body_mat = materials.from_text(identity.get("body_material"),
                                   spec.get("surface_finish"),
                                   identity.get("materials"), text,
                                   default="stainless_cast")

    params: dict = {
        "dn": dn, "pn": pn, "end": end, "actuation": actuation,
        "body_material": body_mat,
        "trim_material": "stainless_machined",
        "seal_material": _seat_material(text, "graphite"),
        "bolt_material": "stainless_machined" if "paslanmaz" in text or "stainless"
                         in text else "zinc_plated",
    }

    if family.id == "ball_valve":
        params.update({
            "pieces": std.parse_pieces(identity.get("type_designation"), text,
                                       default=3 if "3" in str(
                                           identity.get("piece_count", "")) else 2),
            "seat_material": _seat_material(text, "ptfe"),
            "seal_material": _seat_material(text, "ptfe"),
            "reduced_port": any(w in text for w in
                                ("daraltılmış", "daraltilmis", "reduced port",
                                 "standard port")),
        })
        if identity.get("piece_count"):
            try:
                params["pieces"] = max(1, min(3, int(identity["piece_count"])))
            except (TypeError, ValueError):
                pass
    elif family.id == "gate_valve":
        params.update({
            "kind": "globe" if any(w in text for w in ("globe", "glob vana"))
                    else "gate",
            "end": std.parse_end(identity.get("end_connection"), text,
                                 default="flanged"),
            "seat_material": _seat_material(text, "bronze"),
            "actuation": "handwheel",
        })
    elif family.id == "butterfly_valve":
        params.update({
            "body_material": materials.from_text(identity.get("body_material"), text,
                                                 default="ductile_epoxy"),
            "seat_material": _seat_material(text, "epdm"),
        })
    elif family.id in ("check_valve", "y_strainer"):
        params["end"] = std.parse_end(identity.get("end_connection"), text,
                                      default="flanged")
    elif family.id == "flange_joint":
        params["body_material"] = materials.from_text(
            identity.get("body_material"), text, default="carbon_steel")
    elif family.id == "ball_bearing":
        code = re.search(r"\b(6[0-9]{3})\b", text)
        params = {"code": code.group(1) if code else "6206",
                  "bore_mm": dn, "body_material": "carbon_steel",
                  "trim_material": "carbon_steel"}
    elif family.id == "generic_housing":
        params = {"size_mm": float(max(60, min(400, dn * 2.4))),
                  "label": identity.get("product_name") or "Ürün montajı",
                  "body_material": body_mat,
                  "trim_material": "stainless_machined",
                  "seal_material": _seat_material(text, "nbr"),
                  "bolt_material": params["bolt_material"]}
    return params


def build(identity: dict, spec: Optional[dict] = None) -> Tuple[Assembly, Match, dict]:
    """Tanınan ürün için montajı kurar. (Assembly, Match, kullanılan parametreler)."""
    found = match(identity, spec)
    params = params_for(found.family, identity, spec)
    assembly = found.family.builder(params)
    return assembly, found, params


def catalog() -> List[dict]:
    """Kütüphanedeki ailelerin listesi (panel ve belgeler için)."""
    return [{"id": f.id, "label": f.label, "category": f.category,
             "keywords": len(f.keywords)}
            for f in FAMILIES.values()]
