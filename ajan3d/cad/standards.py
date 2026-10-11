"""Endüstriyel ölçü tabloları — parametrik CAD üreticisinin veri tabanı.

Buradaki sayılar *nominal* katalog değerleridir (EN 1092-1, ASME B16.5,
ISO 5211, ISO 724). Amaç imalat resmi üretmek değil; tanınan ürünü **doğru
oranlarda ve doğru bağlantı ölçüleriyle** modellemek. Bir DN50/PN40 flanşın
görselde 165 mm çapında, 125 mm delik dairesinde ve 4 adet M16 cıvatalı
çıkması, "yaklaşık bir silindir" çizmekten tamamen farklı bir sonuç verir.

Metin ayrıştırıcıları (`parse_dn`, `parse_pn`) Vision ve Araştırma ajanlarının
serbest metin çıktısını (DN50, 2 inç, 1000 WOG, PN 40) sayıya çevirir;
ajanların ölçü biçimini tahmin etmek yerine okunan her biçim kabul edilir.
"""
import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Boru / anma çapı
# --------------------------------------------------------------------------- #

# DN -> (boru dış çapı mm, NPS inç etiketi)
PIPE = {
    8: (13.7, '1/4"'), 10: (17.2, '3/8"'), 15: (21.3, '1/2"'), 20: (26.9, '3/4"'),
    25: (33.7, '1"'), 32: (42.4, '1 1/4"'), 40: (48.3, '1 1/2"'), 50: (60.3, '2"'),
    65: (76.1, '2 1/2"'), 80: (88.9, '3"'), 100: (114.3, '4"'), 125: (139.7, '5"'),
    150: (168.3, '6"'), 200: (219.1, '8"'), 250: (273.0, '10"'), 300: (323.9, '12"'),
}
DN_LIST = sorted(PIPE)

# İnç -> DN (metin ayrıştırma için)
INCH_TO_DN = {
    0.25: 8, 0.375: 10, 0.5: 15, 0.75: 20, 1.0: 25, 1.25: 32, 1.5: 40, 2.0: 50,
    2.5: 65, 3.0: 80, 4.0: 100, 5.0: 125, 6.0: 150, 8.0: 200, 10.0: 250, 12.0: 300,
}


def nearest_dn(dn: float) -> int:
    return min(DN_LIST, key=lambda d: abs(d - dn))


def pipe_od(dn: int) -> float:
    return PIPE[nearest_dn(dn)][0]


def nps_label(dn: int) -> str:
    return PIPE[nearest_dn(dn)][1]


# --------------------------------------------------------------------------- #
# Flanş ölçüleri — EN 1092-1 (nominal)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Flange:
    dn: int
    pn: int
    od: float            # D   flanş dış çapı
    bolt_circle: float   # k   delik dairesi çapı
    bolt_count: int      # n   delik sayısı
    bolt_hole: float     # d2  delik çapı
    bolt_size: str       # M12 ...
    thickness: float     # b   flanş kalınlığı
    raised_face: float   # d1  conta (çıkıntı) yüzeyi çapı
    hub: float           # göbek çapı (kaynak boyunlu gövde)

    @property
    def bolt_dia(self) -> float:
        return float(self.bolt_size[1:])


# DN -> (D, k, n, d2, Mxx, b, d1)
_PN16 = {
    15: (95, 65, 4, 14, "M12", 14, 45), 20: (105, 75, 4, 14, "M12", 16, 58),
    25: (115, 85, 4, 14, "M12", 16, 68), 32: (140, 100, 4, 18, "M16", 16, 78),
    40: (150, 110, 4, 18, "M16", 16, 88), 50: (165, 125, 4, 18, "M16", 18, 102),
    65: (185, 145, 8, 18, "M16", 18, 122), 80: (200, 160, 8, 18, "M16", 20, 138),
    100: (220, 180, 8, 18, "M16", 20, 158), 125: (250, 210, 8, 18, "M16", 22, 188),
    150: (285, 240, 8, 22, "M20", 22, 212), 200: (340, 295, 12, 22, "M20", 24, 268),
    250: (405, 355, 12, 26, "M24", 26, 320), 300: (460, 410, 12, 26, "M24", 28, 378),
}
_PN40 = {
    15: (95, 65, 4, 14, "M12", 16, 45), 20: (105, 75, 4, 14, "M12", 18, 58),
    25: (115, 85, 4, 14, "M12", 18, 68), 32: (140, 100, 4, 18, "M16", 18, 78),
    40: (150, 110, 4, 18, "M16", 18, 88), 50: (165, 125, 4, 18, "M16", 20, 102),
    65: (185, 145, 8, 18, "M16", 22, 122), 80: (200, 160, 8, 18, "M16", 24, 138),
    100: (235, 190, 8, 22, "M20", 24, 162), 125: (270, 220, 8, 26, "M24", 26, 188),
    150: (300, 250, 8, 26, "M24", 28, 218), 200: (375, 320, 12, 30, "M27", 34, 285),
    250: (450, 385, 12, 33, "M30", 38, 345), 300: (515, 450, 16, 33, "M30", 42, 410),
}
_TABLES = {10: _PN16, 16: _PN16, 25: _PN40, 40: _PN40, 63: _PN40, 100: _PN40}
PN_LIST = (6, 10, 16, 25, 40, 63, 100)


def nearest_pn(pn: float) -> int:
    return min(PN_LIST, key=lambda p: abs(p - pn))


def flange(dn: int, pn: int = 16) -> Flange:
    """DN/PN için flanş ölçüleri. Tablo dışı değerler en yakınına yuvarlanır.

    Flanş tabloları DN15'te başlar ama boru tablosu DN8'e iner; aradaki
    anma çapları en yakın flanş satırına bağlanır, yoksa DN8 bir flanşlı
    uç istendiğinde zincir KeyError ile düşüyordu.
    """
    pn = nearest_pn(pn)
    table = _TABLES.get(pn, _PN16)
    dn = min(table, key=lambda d: abs(d - nearest_dn(dn)))
    od, k, n, d2, size, b, d1 = table[dn]
    return Flange(dn=dn, pn=pn, od=float(od), bolt_circle=float(k), bolt_count=int(n),
                  bolt_hole=float(d2), bolt_size=size, thickness=float(b),
                  raised_face=float(d1), hub=pipe_od(dn) + max(6.0, dn * 0.10))


# --------------------------------------------------------------------------- #
# ISO 5211 aktüatör montaj flanşı
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MountPad:
    """ISO 5211 aktüatör montaj pabucu — **çift delik takımlı**.

    Gerçek vanalarda pabuç tek bir delik dairesi taşımaz. Üretici aynı gövdeye
    hem küçük hem bir boy büyük aktüatörün doğrudan oturmasını ister, bu yüzden
    plaka iki takım delikle (ör. F05 **ve** F07) delinir ve üzerine iki kod da
    damgalanır. Müşterinin fotoğrafında sayılan **8 delik** budur: dışta dört
    büyük (F07), içeride dört küçük (F05).

    Plaka da yuvarlak değil **kare**dir; iki karşılıklı kenarının ortasında
    döküm boşluğu (kanal) bulunur.
    """
    code: str           # birincil (küçük) takım: F03, F04, F05 ...
    pcd: float          # birincil delik dairesi
    bolt_size: str
    pad: float          # pad dış ölçüsü (kare kenar)
    second_code: str = ""        # ikincil (büyük) takım
    second_pcd: float = 0.0
    second_bolt_size: str = ""
    second_pad: float = 0.0

    @property
    def dual(self) -> bool:
        return bool(self.second_code)

    @property
    def label(self) -> str:
        """Şeritte ve etiketlerde gösterilen kod: 'F05/F07'."""
        return f"{self.code}/{self.second_code}" if self.dual else self.code

    @property
    def hole_count(self) -> int:
        return 8 if self.dual else 4

    @property
    def size(self) -> float:
        """Kare plakanın kenarı — büyük takım belirler."""
        return max(self.pad, self.second_pad)


# (en büyük DN, kod, PCD, cıvata, pad)
_ISO5211 = [(20, "F03", 36, "M5", 46), (32, "F04", 42, "M5", 54),
            (50, "F05", 50, "M6", 64), (80, "F07", 70, "M8", 86),
            (150, "F10", 102, "M10", 122), (300, "F12", 125, "M12", 148)]


def mount_pad(dn: int, dual: bool = True) -> MountPad:
    """DN'ye uyan pabuç. `dual` ise bir üst boy ikinci delik takımı eklenir."""
    index = len(_ISO5211) - 1
    for i, row in enumerate(_ISO5211):
        if dn <= row[0]:
            index = i
            break
    _, code, pcd, bolt, pad = _ISO5211[index]
    if not dual or index + 1 >= len(_ISO5211):
        return MountPad(code, float(pcd), bolt, float(pad))
    _, code2, pcd2, bolt2, pad2 = _ISO5211[index + 1]
    return MountPad(code, float(pcd), bolt, float(pad),
                    code2, float(pcd2), bolt2, float(pad2))


# --------------------------------------------------------------------------- #
# Metrik vida (ISO 724 kaba hatve) ve altı köşe anahtar ağzı
# --------------------------------------------------------------------------- #

# M -> (hatve mm, anahtar ağzı mm, başlık yüksekliği mm, somun yüksekliği mm)
METRIC = {
    4: (0.70, 7, 2.8, 3.2), 5: (0.80, 8, 3.5, 4.7), 6: (1.00, 10, 4.0, 5.2),
    8: (1.25, 13, 5.3, 6.8), 10: (1.50, 16, 6.4, 8.4), 12: (1.75, 18, 7.5, 10.8),
    14: (2.00, 21, 8.8, 12.8), 16: (2.00, 24, 10.0, 14.8), 20: (2.50, 30, 12.5, 18.0),
    24: (3.00, 36, 15.0, 21.5), 27: (3.00, 41, 17.0, 23.8), 30: (3.50, 46, 18.7, 25.6),
}


def metric(size: str) -> tuple:
    """M16 -> (çap, hatve, anahtar ağzı, baş yüksekliği, somun yüksekliği)."""
    digits = re.sub(r"[^0-9]", "", str(size))
    d = int(digits) if digits else 10
    d = min(METRIC, key=lambda k: abs(k - d))
    pitch, af, head, nut = METRIC[d]
    return float(d), pitch, float(af), head, nut


# --------------------------------------------------------------------------- #
# Serbest metin ayrıştırma
# --------------------------------------------------------------------------- #

_IN = r'(?:"|″|’’|inch|inc\b|in\b)'
_DN_RE = re.compile(r"\bdn\s*[-_]?\s*(\d{1,3})\b", re.I)
_MM_RE = re.compile(r"\b(\d{2,3})\s*mm\b", re.I)
_INCH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*" + _IN, re.I)
_FRAC_RE = re.compile(r"\b(\d+)?\s*(\d)\s*/\s*(\d)\s*" + _IN, re.I)
_PN_RE = re.compile(r"\bpn\s*[-_]?\s*(\d{1,3})\b", re.I)
_CLASS_RE = re.compile(r"\b(?:class|cl|#)\s*[-_]?\s*(150|300|600|900|1500)\b", re.I)
_BAR_RE = re.compile(r"\b(\d{1,3})\s*bar\b", re.I)
_WOG_RE = re.compile(r"\b(\d{3,4})\s*(?:wog|psi)\b", re.I)

# ASME basınç sınıfı -> en yakın PN karşılığı
_CLASS_TO_PN = {150: 16, 300: 40, 600: 100, 900: 100, 1500: 100}


def parse_dn(*texts: str, default: int = 50) -> int:
    """Metinlerden anma çapını çıkarır. DN50, 2 inch, 1 1/2 inç, 50 mm kabul edilir."""
    for text in texts:
        if not text:
            continue
        t = str(text)
        m = _DN_RE.search(t)
        if m:
            return nearest_dn(int(m.group(1)))
        m = _FRAC_RE.search(t)
        if m:
            inch = float(m.group(1) or 0) + float(m.group(2)) / float(m.group(3))
            return INCH_TO_DN.get(round(inch, 3), nearest_dn(inch * 25.4))
        m = _INCH_RE.search(t)
        if m:
            inch = float(m.group(1).replace(",", "."))
            return INCH_TO_DN.get(round(inch, 3), nearest_dn(inch * 25.4))
        m = _MM_RE.search(t)
        if m:
            return nearest_dn(int(m.group(1)))
    return nearest_dn(default)


def parse_pn(*texts: str, default: int = 16) -> int:
    """Metinlerden basınç sınıfını PN olarak çıkarır. PN / Class / bar / WOG kabul."""
    for text in texts:
        if not text:
            continue
        t = str(text)
        m = _PN_RE.search(t)
        if m:
            return nearest_pn(int(m.group(1)))
        m = _CLASS_RE.search(t)
        if m:
            return _CLASS_TO_PN[int(m.group(1))]
        m = _WOG_RE.search(t)
        if m:
            return nearest_pn(int(m.group(1)) * 0.0689)   # psi -> bar
        m = _BAR_RE.search(t)
        if m:
            return nearest_pn(int(m.group(1)))
    return nearest_pn(default)


_END_WORDS = (
    ("flanged", ("flanş", "flans", "flange", "flanged", "en 1092", "b16.5")),
    ("wafer", ("wafer", "lug tip", "ara flanş", "ara flans")),
    ("clamp", ("clamp", "kelepçe", "kelepce", "triclamp")),
    ("welded", ("kaynak", "weld", "butt")),
    ("compression", ("sıkma", "sikma", "compression", "rakor")),
    ("threaded", ("diş", "dis", "vida", "thread", "npt", "bsp")),
)


def _first_match(table, texts, default: str) -> str:
    """Metinleri **sırayla** tarar; ilk eşleşen metnin sonucu kazanır.

    Hepsini tek torbaya atmak sessiz hatalara yol açıyordu: ürünün tanıtım
    cümlesinde geçen "ISO 5211 montaj flanşlı" ifadesi, bağlantı tipi alanı
    açıkça "dişli" dediği hâlde vanayı flanşlı kurduruyordu. Aynı şekilde
    "pnömatik aktüatör takılabilir" cümlesi kollu vanaya volan taktırıyordu.
    Bu yüzden önce açıkça verilen alan, sonra genel metin taranır.
    """
    for text in texts:
        if not text:
            continue
        low = str(text).lower()
        for kind, words in table:
            if any(w in low for w in words):
                return kind
    return default


def parse_end(*texts: str, default: str = "threaded") -> str:
    """Bağlantı tipi: flanged | threaded | welded | wafer | clamp | compression."""
    return _first_match(_END_WORDS, texts, default)


_ACTUATION = (
    # "none" MUTLAKA ilk sırada: "kolsuz" kelimesi "kol" içeriyor ve aşağıdaki
    # lever kuralına takılıyordu. Çıplak milli bir vanaya kol çizmek, modeli
    # müşterinin elindeki üründen gözle ayırt edilir biçimde yanlış yapar.
    ("none", ("kolsuz", "kol takılı değil", "kol takili degil", "çıplak mil",
              "ciplak mil", "bare stem", "bare shaft", "aktüatörsüz",
              "aktuatorsuz", "kumandasız", "kumandasiz", "yok", "none")),
    ("gear", ("redüktör", "reduktor", "gearbox", "worm", "salyangoz")),
    ("pneumatic", ("pnömatik", "pnomatik", "pneumatic", "aktüatör", "aktuator",
                   "actuator")),
    ("electric", ("elektrikli", "electric", "motorlu", "motorized")),
    ("handwheel", ("volan", "handwheel", "el çarkı", "el carki")),
    ("lever", ("kol", "lever", "handle")),
)

# Vananın gövdesine çizilecek kumanda organı olmayan tipler. Pnömatik ve
# elektrikli aktüatör ayrı satın alınan bir üründür; onu vana montajına dahil
# etmek yanıltıcı olur, ISO 5211 pabucu zaten arayüzü anlatıyor.
# Kumanda organı ÇİZİLMEYEN tipler. Pnömatik aktüatör bu listeden çıkarıldı:
# müşteri ürünü aktüatörüyle birlikte bir SET olarak satıyor ve sunumda da
# öyle görmek istiyor (ürün fotoğrafı da seti gösteriyor). Elektrikli
# aktüatör hâlâ çizilmiyor — ona ait bir referans görseli yok.
NO_ACTUATOR = ("none", "electric")


def parse_actuation(*texts: str, default: str = "lever") -> str:
    """Kumanda tipi: none | lever | handwheel | gear | pneumatic | electric."""
    return _first_match(_ACTUATION, texts, default)


_PIECE_WORDS = (
    (3, ("3 parça", "3 parca", "3-parça", "3-parca", "üç parça", "uc parca",
         "3 piece", "3-piece", "three piece", "three-piece")),
    (2, ("2 parça", "2 parca", "iki parça", "2 piece", "2-piece",
         "two piece", "two-piece")),
    (1, ("tek parça", "tek gövde", "tek govde", "1 piece", "1-piece", "one piece",
         "monoblok", "monobloc")),
)


def parse_pieces(*texts: str, default: int = 2) -> int:
    """Gövde parça sayısı (3 parçalı / 2 parçalı küresel vana)."""
    for text in texts:
        if not text:
            continue
        low = str(text).lower()
        for n, words in _PIECE_WORDS:
            if any(w in low for w in words):
                return n
    return default
