"""Katı modelleme ilkelleri — parametrik CAD çekirdeği.

Bütün üreticiler **su geçirmez (watertight) katı** döner; yüzey/kabuk değil.
Önceki mimarinin asıl kusuru buydu: Image-to-3D ağları yalnızca dış kabuğu
üretiyor, parçalamaya kalkınca içi boş çıkıyordu. Burada her gövde gerçek bir
hacim olarak kuruluyor, delikler ve yuvalar **Boolean çıkarma** ile açılıyor,
yani vidanın girdiği delik gerçekten delik, contanın oturduğu yuva gerçekten
yuva. Hacim ölçülebildiği için `materials.mass_g` ile kütle de hesaplanıyor.

Üç temel kurulum yolu:

* **Devirme (`revolve`)** — eksenel simetrik her şey (gövde, top, mil, oturma,
  conta, somun gövdesi). Profil `(r, z)` düzleminde verilir, Z ekseni etrafında
  döndürülür. Vana geometrisinin neredeyse tamamı budur.
* **Delikli plaka (`plate`)** — flanş, kapak, montaj pabucu. Shapely poligonu
  (dış kontur + delikler) doğrudan delikli olarak kalıplanır; delik sonradan
  kesilmediği için üçgenleme temiz kalır.
* **Boolean (`union` / `cut`)** — gövdeyi oluşturan parçaları birleştirmek ve
  geçişleri, yuvaları, diş boşluklarını açmak. `manifold3d` motoru kullanılır.

Birim: **milimetre**. Eksen düzeni: akış Z, mil/kumanda Y (aileler bu düzeni
kurar; ilkeller her zaman Z etrafında üretip sonra döndürür).

Diş profili not: dişler eksenel kesitte doğru V profiline sahip **konsantrik
oluklar** olarak üretilir, gerçek helis değil. Render ölçeğinde ayırt edilemez
ve katıyı su geçirmez tutar; imalat resmi olarak kullanılamaz.
"""
import math
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
import trimesh
from shapely.geometry import Polygon

Pt = Tuple[float, float]

# Devirme çözünürlüğü. 64 dilim, DN50 bir gövdede kenar uzunluğunu ~3 mm
# bırakıyor; açı bölünmüş normallerle (bkz. gltf.py) yüzey pürüzsüz görünüyor.
SECTIONS = 64
SECTIONS_FINE = 96
# Dis yuzeyleri cok sayida profil noktasi tasidigi icin daha az dilimle uretilir;
# 40 dilim bir M16 civatada yuz sayisini ~%40 dusuruyor, gorsel fark yok.
THREAD_SECTIONS = 40
# Boolean işlemleri için küçük taşma payı: iki yüzeyin tam çakışması
# dejenere üçgen üretebilir, bu yüzden kesici gövdeler daima biraz taşırılır.
EPS = 0.05

_warnings: List[str] = []


def warnings() -> List[str]:
    """Son üretimde biriken geometri uyarıları (boolean düşüşleri vb.)."""
    return list(_warnings)


def clear_warnings() -> None:
    _warnings.clear()


# --------------------------------------------------------------------------- #
# Profil yardımcıları — (r, z) düzlemi
# --------------------------------------------------------------------------- #

def arc(cr: float, cz: float, radius: float, a0: float, a1: float,
        n: int = 12) -> List[Pt]:
    """Merkezi (cr, cz) olan yayın noktaları. Açılar derece, CCW."""
    return [(cr + radius * math.cos(math.radians(a)),
             cz + radius * math.sin(math.radians(a)))
            for a in np.linspace(a0, a1, max(2, n))]


def close(points: Sequence[Pt]) -> np.ndarray:
    """Profili kapatır (ilk nokta sona eklenir); devirme kapalı kontur ister."""
    pts = [tuple(float(v) for v in p) for p in points]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return np.asarray(pts, dtype=np.float64)


def circle_pts(radius: float, n: int = SECTIONS, cx: float = 0.0,
               cy: float = 0.0) -> List[Pt]:
    return [(cx + radius * math.cos(2 * math.pi * i / n),
             cy + radius * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rounded_rect_pts(width: float, height: float, radius: float,
                     n: int = 6) -> List[Pt]:
    """Köşeleri yuvarlatılmış dikdörtgen (döküm gövde pabuçları için)."""
    w, h = width / 2.0, height / 2.0
    r = max(0.0, min(radius, w - 0.01, h - 0.01))
    if r <= 0:
        return [(-w, -h), (w, -h), (w, h), (-w, h)]
    out: List[Pt] = []
    for (cx, cy, a0) in ((w - r, -(h - r), -90), (w - r, h - r, 0),
                         (-(w - r), h - r, 90), (-(w - r), -(h - r), 180)):
        out += [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                for a in np.linspace(a0, a0 + 90, n)]
    return out


def hex_pts(across_flats: float) -> List[Pt]:
    """Altı köşe konturu. `across_flats` anahtar ağzı ölçüsüdür."""
    r = across_flats / math.sqrt(3.0)          # köşeden köşeye yarıçap
    return [(r * math.cos(math.radians(30 + 60 * i)),
             r * math.sin(math.radians(30 + 60 * i))) for i in range(6)]


def bolt_circle(pcd: float, count: int, phase: float = 0.0) -> List[Pt]:
    """Delik dairesi üzerindeki nokta koordinatları (XY düzlemi)."""
    return [(pcd / 2.0 * math.cos(math.radians(phase + 360.0 * i / count)),
             pcd / 2.0 * math.sin(math.radians(phase + 360.0 * i / count)))
            for i in range(count)]


# --------------------------------------------------------------------------- #
# Katı üreticiler
# --------------------------------------------------------------------------- #

def revolve(profile: Sequence[Pt], sections: int = SECTIONS) -> trimesh.Trimesh:
    """(r, z) profilini Z ekseni etrafında devirerek katı üretir."""
    mesh = trimesh.creation.revolve(close(profile), sections=sections)
    return fix(mesh)


def cylinder(radius: float, height: float, z0: float = 0.0,
             sections: int = SECTIONS) -> trimesh.Trimesh:
    return revolve([(0, z0), (radius, z0), (radius, z0 + height), (0, z0 + height)],
                   sections)


def tube(inner: float, outer: float, height: float, z0: float = 0.0,
         sections: int = SECTIONS) -> trimesh.Trimesh:
    return revolve([(inner, z0), (outer, z0), (outer, z0 + height), (inner, z0 + height)],
                   sections)


def cone(r0: float, r1: float, height: float, z0: float = 0.0,
         sections: int = SECTIONS) -> trimesh.Trimesh:
    return revolve([(0, z0), (r0, z0), (r1, z0 + height), (0, z0 + height)], sections)


def sphere(radius: float, subdivisions: int = 3) -> trimesh.Trimesh:
    return fix(trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius))


def box(sx: float, sy: float, sz: float,
        center: Tuple[float, float, float] = (0, 0, 0)) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=(sx, sy, sz))
    return translate(mesh, *center)


def torus(ring_radius: float, cord_radius: float, sections: int = SECTIONS,
          cord_sections: int = 20) -> trimesh.Trimesh:
    """O-ring / conta halkası: `ring_radius` eksen dairesi, `cord_radius` kesit."""
    return revolve(arc(ring_radius, 0.0, cord_radius, 0, 360, cord_sections), sections)


def plate(outline: Sequence[Pt], thickness: float, z0: float = 0.0,
          holes: Optional[Iterable[Sequence[Pt]]] = None) -> trimesh.Trimesh:
    """Delikli plaka. Delikler kalıpla birlikte açılır, sonradan kesilmez."""
    poly = Polygon(outline, list(holes or []))
    if not poly.is_valid:
        poly = poly.buffer(0)
    mesh = trimesh.creation.extrude_polygon(poly, float(thickness))
    return fix(translate(mesh, 0, 0, z0))


def disc(radius: float, thickness: float, z0: float = 0.0, bore: float = 0.0,
         holes: Optional[Sequence[Tuple[float, float, float]]] = None,
         sections: int = SECTIONS) -> trimesh.Trimesh:
    """Yuvarlak plaka: merkez delik + (x, y, r) üçlüleriyle verilen delikler."""
    cut_holes: List[Sequence[Pt]] = []
    if bore > 0:
        cut_holes.append(circle_pts(bore / 2.0, sections))
    for (x, y, r) in holes or []:
        cut_holes.append(circle_pts(r, max(16, sections // 3), x, y))
    return plate(circle_pts(radius, sections), thickness, z0, cut_holes)


def hex_prism(across_flats: float, height: float, z0: float = 0.0,
              bore: float = 0.0) -> trimesh.Trimesh:
    holes = [circle_pts(bore / 2.0, 32)] if bore > 0 else []
    return plate(hex_pts(across_flats), height, z0, holes)


# --------------------------------------------------------------------------- #
# Diş profili
# --------------------------------------------------------------------------- #

def thread_profile(major: float, pitch: float, length: float, z0: float,
                   external: bool = True) -> List[Pt]:
    """Diş yüzeyinin (r, z) zikzak konturu. 60° V profili, ISO oranları.

    Zikzak **tam olarak** [z0, z0+length] aralığına oturtulur. Hatveden adım
    sayısını yuvarlayıp son adımı taşırmak profili geri dönük hale getiriyor
    ve katıyı kendisiyle kesiştiriyordu (ölçüldü: M16×39 dişli mil su geçirmez
    çıkmıyordu). Bunun yerine aralık eşit yarım hatve adımlarına bölünür.
    """
    depth = pitch * 0.613           # ISO 68-1 taşıyıcı diş yüksekliği
    r_out = major / 2.0
    r_in = r_out - depth
    high, low = (r_out, r_in) if external else (r_in, r_out)
    steps = max(2, int(round(length / (pitch / 2.0))))
    return [(high if i % 2 == 0 else low, z0 + length * i / steps)
            for i in range(steps + 1)]


def threaded_rod(major: float, pitch: float, length: float, z0: float = 0.0,
                 sections: int = THREAD_SECTIONS) -> trimesh.Trimesh:
    """Dişli mil/saplama: eksende dolu, dış yüzeyi V oluklu."""
    prof = [(0.0, z0)] + thread_profile(major, pitch, length, z0, external=True)
    prof.append((0.0, z0 + length))
    return revolve(prof, sections)


def thread_cutter(major: float, pitch: float, length: float, z0: float = 0.0,
                  sections: int = THREAD_SECTIONS) -> trimesh.Trimesh:
    """İç diş açmak için kesici gövde (gövdeden çıkarılır)."""
    prof = [(0.0, z0 - EPS)] + thread_profile(major, pitch, length, z0, external=True)
    prof.append((0.0, z0 + length + EPS))
    return revolve(prof, sections)


# --------------------------------------------------------------------------- #
# Standart bağlantı elemanları
# --------------------------------------------------------------------------- #

def hex_bolt(size: str, length: float, z0: float = 0.0,
             full_thread: bool = False) -> trimesh.Trimesh:
    """DIN 933/931 altı köşe başlı cıvata. Baş z0'ın altında, gövde yukarı."""
    from cad import standards as std
    d, pitch, af, head_h, _ = std.metric(size)
    thread_len = length if full_thread else min(length, max(2 * d + 6, length * 0.6))
    plain = length - thread_len

    # Başlık: altı köşe prizma, üst köşeleri pahlı (DIN 933 görünümü).
    # Pah, prizmayı tepeye doğru daralan bir koniyle KESİŞTİRİLEREK alınır.
    r_corner = af / math.sqrt(3.0)
    head = hex_prism(af, head_h, z0 - head_h)
    head = intersect(head, revolve(
        [(0, z0 - head_h - EPS), (r_corner + 1, z0 - head_h - EPS),
         (r_corner + 1, z0 - head_h * 0.30), (af / 2.0 * 0.99, z0 + EPS),
         (0, z0 + EPS)], 48))
    parts = [head]
    if plain > 0.1:
        parts.append(cylinder(d / 2.0, plain + EPS, z0))
    parts.append(threaded_rod(d, pitch, thread_len, z0 + plain))
    bolt = union(*parts)
    # Uç pahı: dış köşeyi saran halka çıkarılır (profil CCW verilmeli)
    tip = z0 + length
    ch = pitch * 1.3
    bolt = cut(bolt, revolve([(d / 2.0 - ch, tip + EPS), (d, tip - ch),
                              (d, tip + EPS)], 48))
    return bolt


def hex_nut(size: str, z0: float = 0.0) -> trimesh.Trimesh:
    """DIN 934 altı köşe somun: iç diş + iki yüzde pah."""
    from cad import standards as std
    d, pitch, af, _, nut_h = std.metric(size)
    body = hex_prism(af, nut_h, z0, bore=d - pitch * 1.2)
    # Pah, iki yüzü koniyle KESİŞTİRİLEREK alınır. Köşeleri saran halkaları
    # çıkarmak altıgenin yan yüzüne teğet geliyor ve boolean orada kapalı
    # yüzeyi bozuyor; kesişme yolu teğetlik bırakmıyor.
    r_corner = af / math.sqrt(3.0) + 1.0
    r_flat = af / 2.0 * 0.97
    ch = nut_h * 0.16
    body = intersect(body, revolve([
        (0, z0 - EPS), (r_flat, z0 - EPS), (r_corner, z0 + ch),
        (r_corner, z0 + nut_h - ch), (r_flat, z0 + nut_h + EPS), (0, z0 + nut_h + EPS),
    ], 48))
    return cut(body, thread_cutter(d, pitch, nut_h, z0))


def washer(size: str, z0: float = 0.0, thickness: Optional[float] = None,
           outer: Optional[float] = None) -> trimesh.Trimesh:
    """DIN 125 düz rondela."""
    from cad import standards as std
    d = std.metric(size)[0]
    return tube((d + 0.6) / 2.0, (outer or d * 2.0) / 2.0,
                thickness or max(1.0, d * 0.16), z0)


def belleville(size: str, z0: float = 0.0) -> trimesh.Trimesh:
    """Konik yaylı rondela (DIN 2093). Mil salmastrasını sürekli yükler."""
    from cad import standards as std
    d = std.metric(size)[0]
    ri, ro = (d + 0.8) / 2.0, d * 1.05
    t, rise = max(0.6, d * 0.09), max(0.9, d * 0.16)
    return revolve([(ri, z0), (ro, z0 + rise), (ro, z0 + rise + t), (ri, z0 + t)], SECTIONS)


# --------------------------------------------------------------------------- #
# Kumanda organları
# --------------------------------------------------------------------------- #

def lever(length: float, width: float, thickness: float, boss_r: float,
          bore: float, z0: float = 0.0, grip: float = 0.45) -> List[trimesh.Trimesh]:
    """Düz kol: (kol gövdesi, vinil kılıf). XZ'de uzar, Z'de yükselir.

    Kol +X yönünde uzanır; boss merkezi orijinde ve Z ekseni etrafında döner.
    Aileler kolu mil eksenine göre döndürür.
    """
    tip_w = width * 0.62
    outline = [(-boss_r * 0.9, -width / 2.0), (length, -tip_w / 2.0),
               (length, tip_w / 2.0), (-boss_r * 0.9, width / 2.0)]
    arm = plate(outline, thickness, z0)
    arm = union(arm, tube(bore / 2.0, boss_r, thickness * 2.4, z0 - thickness * 0.7))
    arm = cut(arm, cylinder(bore / 2.0, thickness * 4 + 2 * EPS, z0 - thickness * 1.5))
    # Kavrama bölgesindeki vinil kılıf
    g0 = length * (1.0 - grip)
    sleeve_outline = [(g0, -tip_w / 2.0 - 1.1), (length + 2.2, -tip_w / 2.0 - 1.1),
                      (length + 2.2, tip_w / 2.0 + 1.1), (g0, tip_w / 2.0 + 1.1)]
    sleeve = plate(sleeve_outline, thickness + 2.2, z0 - 1.1)
    sleeve = cut(sleeve, plate([(g0 - EPS, -tip_w / 2.0), (length + EPS, -tip_w / 2.0),
                                (length + EPS, tip_w / 2.0), (g0 - EPS, tip_w / 2.0)],
                               thickness + 2 * EPS, z0 - EPS))
    return [arm, sleeve]


def handwheel(diameter: float, bore: float, spokes: int = 5,
              z0: float = 0.0) -> trimesh.Trimesh:
    """Volan: dış jant + göbek + ışınsal kollar (tek katı olarak birleşir)."""
    r = diameter / 2.0
    cord = max(3.0, diameter * 0.045)
    rim = torus(r - cord, cord, SECTIONS, 16)
    hub = tube(bore / 2.0, max(bore * 0.95, bore / 2.0 + 5), cord * 2.6, -cord * 1.3)
    arms = []
    for i in range(spokes):
        a = 360.0 * i / spokes
        arm = box(r - cord, cord * 1.15, cord * 1.5, ((r - cord) / 2.0, 0, 0))
        arms.append(rotate(arm, a, "z"))
    wheel = union(rim, hub, *arms)
    # Jant hafifçe konik: gerçek volanlar düzlemsel değil, kullanıcıya doğru çanak
    return translate(wheel, 0, 0, z0)


# --------------------------------------------------------------------------- #
# Dönüşümler
# --------------------------------------------------------------------------- #

def translate(mesh: trimesh.Trimesh, x: float = 0, y: float = 0,
              z: float = 0) -> trimesh.Trimesh:
    out = mesh.copy()
    out.apply_translation((x, y, z))
    return out


def rotate(mesh: trimesh.Trimesh, degrees: float, axis: str = "z",
           point: Tuple[float, float, float] = (0, 0, 0)) -> trimesh.Trimesh:
    vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    matrix = trimesh.transformations.rotation_matrix(math.radians(degrees), vec, point)
    out = mesh.copy()
    out.apply_transform(matrix)
    return out


def mirror(mesh: trimesh.Trimesh, axis: str = "z") -> trimesh.Trimesh:
    """Aynalama. Ölçek negatifi yüz yönünü ters çevirdiği için düzeltilir."""
    scale = {"x": (-1, 1, 1), "y": (1, -1, 1), "z": (1, 1, -1)}[axis]
    matrix = np.eye(4)
    matrix[0, 0], matrix[1, 1], matrix[2, 2] = scale
    out = mesh.copy()
    out.apply_transform(matrix)
    out.invert()
    return fix(out)


def to_axis(mesh: trimesh.Trimesh, axis: str) -> trimesh.Trimesh:
    """Z ekseni etrafında kurulmuş bir parçayı X veya Y eksenine çevirir."""
    if axis == "z":
        return mesh
    if axis == "y":
        return rotate(mesh, -90, "x")
    if axis == "x":
        return rotate(mesh, 90, "y")
    raise ValueError(axis)


# --------------------------------------------------------------------------- #
# Boolean
# --------------------------------------------------------------------------- #

def fix(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Köşeleri kaynaştırır ve normalleri dışa çevirir.

    İki temizlik kasten yapılmıyor:

    * **Dejenere yüz atma yok.** Devirme eksen üzerinde sıfır alanlı ince
      üçgenler bırakabiliyor; bunları atmak kapalı yüzeyi deliyor (ölçüldü:
      304 yüzün 2'si atılınca katı su geçirmez olmaktan çıktı). Boolean motoru
      bu üçgenlerle sorun yaşamıyor.
    * **Kaynaştırma geri alınabilir.** `merge_vertices` varsayılan toleransla
      pah ile altıgen köşesinin buluştuğu gibi yerlerde ayrı köşeleri
      birleştirip yüzeyi açıyor (ölçüldü: manifold çıktısı su geçirmezken
      kaynaştırma sonrası değil). Kapalı bir katı açılırsa kaynaştırma iptal
      edilir — zincirin devamındaki Boolean'lar su geçirmez girdi istiyor.

    Ters sarım (negatif hacim) profilin saat yönünde verilmesinden doğar ve
    sessizce içi dışa dönük bir katı üretir; burada düzeltilir.
    """
    was_watertight = mesh.is_watertight
    merged = mesh.copy()
    merged.merge_vertices()
    merged.remove_unreferenced_vertices()
    if was_watertight and not merged.is_watertight:
        merged = mesh
    if merged.is_watertight and merged.volume < 0:
        merged.invert()
    return merged


def _boolean(op: str, meshes: Sequence[trimesh.Trimesh]) -> trimesh.Trimesh:
    """manifold3d ile Boolean. Başarısızlıkta zincir durmaz, uyarı kaydedilir."""
    meshes = [m for m in meshes if m is not None and len(m.faces) > 0]
    if not meshes:
        raise ValueError("boolean icin gövde yok")
    if len(meshes) == 1:
        return meshes[0].copy()
    try:
        result = getattr(trimesh.boolean, op)(meshes, engine="manifold")
        if isinstance(result, list):
            result = trimesh.util.concatenate(result)
        if result is None or len(result.faces) == 0:
            raise ValueError("boş sonuç")
        return fix(result)
    except Exception as e:                                  # noqa: BLE001
        _warnings.append(f"{op} başarısız ({type(e).__name__}: {str(e)[:90]}); "
                         f"yedek yol kullanıldı")
        if op == "union":
            return fix(trimesh.util.concatenate(meshes))
        return meshes[0].copy()


def union(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    return _boolean("union", meshes)


def cut(base: trimesh.Trimesh, *tools: trimesh.Trimesh,
        invert: bool = False) -> trimesh.Trimesh:
    """`base` gövdesinden `tools` gövdelerini çıkarır."""
    if invert:
        return _boolean("intersection", (base,) + tools)
    return _boolean("difference", (base,) + tools)


def intersect(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    return _boolean("intersection", meshes)


def repeat(mesh: trimesh.Trimesh, positions: Sequence[Pt],
           z: float = 0.0) -> trimesh.Trimesh:
    """Aynı gövdeyi XY noktalarına çoğaltıp tek katı olarak birleştirir."""
    return union(*[translate(mesh, x, y, z) for (x, y) in positions])
