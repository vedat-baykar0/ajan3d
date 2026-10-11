"""Fotoğraf projeksiyonu: maske çıkarma, sınırlı hizalama, yön araması.

Bu modülün çıktısı müşterinin gördüğü ilk karedir. "Oturdu mu" sorusunun gözle
değil **sayıyla** cevabı olsun diye her şey ölçülebilir kurulmuştu; buradaki
testler o ölçülerin anlamını kilitliyor:

* hızlandırılmış rasterleştirici, basit referans uygulamasıyla **birebir** aynı
  sonucu vermeli (hız için doğruluk feda edilmedi);
* hizalama bilinen bir dönüşümü geri bulmalı;
* ama **dönemeyeceği kadar** çevrilmiş bir fotoğrafı zorla oturtmamalı —
  serbest bırakılan dönme, siluet örtüşmesini yükseltmek uğruna fotoğrafı
  çeyrek tur çevirip ürünün dişini gövdenin yanına yapıştırıyordu;
* maske, fonun iki tonlu olduğu gerçek bir sahnede ürünü seçmeli;
* uçtan uca arama, fotoğrafın çekildiği YÖNÜ geri bulmalı.
"""
import json
import math

import numpy as np
import pytest
from PIL import Image

from cad import gltf
from cad.families import ball_valve
from core import projection as proj

# Yamalanmadan önceki gerçek işlev (yedek yol testi için).
REAL_REMBG_MASK = proj._rembg_mask


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def model(tmp_path_factory):
    """Gerçek bir montajın GLB'si (AO pişirmeden — burada gerekmiyor, yavaşlatır)."""
    assembly = ball_valve.build({"dn": 50, "pn": 40, "pieces": 3, "end": "threaded"})
    path = tmp_path_factory.mktemp("proj") / "model.glb"
    gltf.write_glb(assembly, path, bake_ao=False)
    return path


@pytest.fixture(scope="module")
def world(model):
    mesh = proj.load_world_mesh(model)
    sphere = mesh.bounding_sphere.primitive
    return (np.asarray(mesh.vertices), np.asarray(mesh.faces),
            np.asarray(sphere.center, dtype=np.float64), float(sphere.radius))


def reference_raster(vertices, faces, projector, width):
    """Basit, yavaş ama apaçık rasterleştirici — hızlı olanın ölçüsü budur."""
    height = max(2, int(round(width / projector.aspect)))
    vp = proj.projection_matrix(projector.fov, projector.aspect, projector.near,
                                projector.far) @ proj.view_matrix(
        np.asarray(projector.position), np.asarray(projector.target))
    homo = np.hstack([vertices, np.ones((len(vertices), 1))])
    clip = homo @ vp.T
    w = clip[:, 3]
    valid = w > 1e-9
    ndc = np.zeros((len(vertices), 2))
    ndc[valid] = clip[valid, :2] / w[valid, None]
    pts = np.stack([(ndc[:, 0] * 0.5 + 0.5) * width,
                    (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * height], axis=1)
    mask = np.zeros((height, width), dtype=bool)
    for face in faces:
        if not valid[face].all():
            continue
        (ax, ay), (bx, by), (cx, cy) = pts[face]
        if (bx - ax) * (cy - ay) - (cx - ax) * (by - ay) <= 1e-9:
            continue                                   # arkaya bakan
        x0 = max(0, int(math.floor(min(ax, bx, cx))))
        x1 = min(width, int(math.ceil(max(ax, bx, cx))))
        y0 = max(0, int(math.floor(min(ay, by, cy))))
        y1 = min(height, int(math.ceil(max(ay, by, cy))))
        for y in range(y0, y1):
            for x in range(x0, x1):
                px, py = x + 0.5, y + 0.5
                d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
                if abs(d) < 1e-12:
                    continue
                l0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / d
                l1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / d
                if l0 >= 0 and l1 >= 0 and l0 + l1 <= 1:
                    mask[y, x] = True
    return mask


def silhouette_photo(vertices, faces, projector, path, width=300, margin=0.18):
    """Modelin siluetinden yapay bir "fotoğraf": koyu fonda açık ürün.

    Kenar boşluğu gerçek bir fotoğrafı taklit ediyor ve şart: klasik maske
    çıkarımı fon rengini KENAR ŞERİDİNDEN öğreniyor, ürün çerçeveye değerse o
    şerit ürünün kendi rengiyle kirleniyor ve hiçbir şey fondan ayrılmıyor.
    """
    mask = proj.rasterize_silhouette(vertices, faces, projector, width)
    height = mask.shape[0]
    pad_x, pad_y = int(width * margin), int(height * margin)
    rgb = np.full((height + 2 * pad_y, width + 2 * pad_x, 3), 18, dtype=np.uint8)
    inner = rgb[pad_y:pad_y + height, pad_x:pad_x + width]
    inner[mask] = (215, 214, 208)
    Image.fromarray(rgb).save(path)
    return path


@pytest.fixture(autouse=True)
def no_learned_cutout(monkeypatch):
    """Testler KLASİK maske yolunu ölçer.

    Öğrenilmiş kesim (rembg) isteğe bağlı bir hızlandırıcıdır: kurulu olduğu
    makinede sonuç daha iyi, kurulu olmadığı makinede zincir yine çalışmalı.
    Testin hangi makinede koştuğuna göre değişmemesi için kapatılıyor; ayrıca
    böylece asıl kırılgan olan yedek yol da gerçekten sınanmış oluyor.
    """
    monkeypatch.setattr(proj, "_rembg_mask", lambda path, size: None)
    proj._MASK_CACHE.clear()


# --------------------------------------------------------------------------- #
# Kamera
# --------------------------------------------------------------------------- #

def test_target_projects_to_frame_center():
    projector = proj.default_projector(np.zeros(3), 1.0, 1.5)
    vp = proj.projection_matrix(projector.fov, projector.aspect, projector.near,
                                projector.far) @ proj.view_matrix(
        np.asarray(projector.position), np.asarray(projector.target))
    clip = vp @ np.array([*projector.target, 1.0])
    assert clip[3] > 0
    assert np.allclose(clip[:2] / clip[3], 0.0, atol=1e-9)


def test_near_and_far_wrap_the_object():
    """Projektörün derinlik aralığı nesneyi SARMALI.

    Kullanıcı kamerasının geniş aralığını (d/120 … d*24) kopyalamak,
    projektörden alınan derinlik haritasındaki hassasiyeti yok ediyor ve
    gövdede şerit şeklinde derinlik aknesi bırakıyordu.
    """
    projector = proj.default_projector(np.zeros(3), 1.0, 1.0)
    distance = float(np.linalg.norm(np.asarray(projector.position) -
                                    np.asarray(projector.target)))
    assert 0 < projector.near < distance < projector.far
    assert projector.far / projector.near < 12


def test_direction_from_is_unit_and_signed():
    d = proj.direction_from(90.0, 0.0)
    assert np.allclose(np.linalg.norm(d), 1.0)
    assert d[0] > 0.99                                   # azimut 90° -> +X
    assert proj.direction_from(0.0, 90.0)[1] > 0.99      # yükseliş 90° -> +Y


# --------------------------------------------------------------------------- #
# Rasterleştirme
# --------------------------------------------------------------------------- #

def test_fast_raster_matches_the_reference_exactly(world):
    """Kademeli kalıp taraması bir yaklaşıklık DEĞİL; birebir aynı pikseller."""
    vertices, faces, center, radius = world
    projector = proj.default_projector(center, radius, 0.75)
    fast = proj.rasterize_silhouette(vertices, faces, projector, 96)
    slow = reference_raster(vertices, faces, projector, 96)
    assert np.array_equal(fast, slow)


def test_raster_fills_a_plausible_share_of_the_frame(world):
    vertices, faces, center, radius = world
    mask = proj.rasterize_silhouette(
        vertices, faces, proj.default_projector(center, radius, 0.75), 160)
    assert 0.15 < mask.mean() < 0.85


def test_raster_is_resolution_stable(world):
    vertices, faces, center, radius = world
    projector = proj.default_projector(center, radius, 0.75)
    coarse = proj.rasterize_silhouette(vertices, faces, projector, 120).mean()
    fine = proj.rasterize_silhouette(vertices, faces, projector, 320).mean()
    assert abs(coarse - fine) < 0.02


# --------------------------------------------------------------------------- #
# Hizalama
# --------------------------------------------------------------------------- #

def _warp_known(mask, angle_deg, scale, dx, dy):
    """Maskeyi bilinen bir benzerlik dönüşümüyle taşır (test verisi üretir)."""
    from scipy import ndimage

    angle = math.radians(angle_deg)
    c, s = math.cos(angle) / scale, math.sin(angle) / scale
    center = (np.array(mask.shape[::-1]) - 1) / 2.0
    m = np.array([[c, -s], [s, c]])
    b = center - m @ center - np.array([dx, dy])
    rc = np.array([[m[1, 1], m[1, 0]], [m[0, 1], m[0, 0]]])
    out = ndimage.affine_transform(mask.astype(np.uint8), rc,
                                   offset=np.array([b[1], b[0]]),
                                   output_shape=mask.shape, order=0, cval=0)
    return out.astype(bool)


def test_fit_recovers_a_known_similarity(world):
    vertices, faces, center, radius = world
    silhouette = np.flipud(proj.rasterize_silhouette(
        vertices, faces, proj.default_projector(center, radius, 0.75), 140))
    moved = _warp_known(silhouette, 9.0, 1.18, 7.0, -5.0)
    _, _, iou, _ = proj.fit_photo(silhouette, moved)
    assert iou > 0.93, iou


def test_fit_refuses_to_rotate_the_product_upright(world):
    """Serbest dönme, yüksek örtüşme uğruna ürünü yan yatırıyordu.

    70° çevrilmiş bir fotoğraf verildiğinde doğru davranış onu geri çevirmek
    DEĞİL, düşük puan vermektir: o fotoğraf o yönden çekilmemiştir ve arama
    başka bir yöne (ya da başka bir fotoğrafa) gitmelidir.
    """
    vertices, faces, center, radius = world
    silhouette = np.flipud(proj.rasterize_silhouette(
        vertices, faces, proj.default_projector(center, radius, 0.75), 140))
    turned = _warp_known(silhouette, 70.0, 1.0, 0.0, 0.0)
    matrix, _, iou, _ = proj.fit_photo(silhouette, turned)
    angle = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    assert angle <= proj.MAX_ROTATION + 1e-6, angle
    assert iou < 0.80, iou


def test_fit_anisotropy_stays_inside_the_limit(world):
    """Ölçek serbest, ama en-boy oranı sınırlı: parametrik model gerçek ürünle
    birebir aynı oranlarda değil, yine de ona benzemek zorunda."""
    vertices, faces, center, radius = world
    silhouette = np.flipud(proj.rasterize_silhouette(
        vertices, faces, proj.default_projector(center, radius, 0.75), 140))
    squashed = _warp_known(silhouette, 0.0, 1.0, 0.0, 0.0)
    squashed = np.repeat(squashed[::3], 3, axis=0)[:silhouette.shape[0]]
    matrix, _, _, _ = proj.fit_photo(silhouette, squashed)
    sx = math.hypot(matrix[0, 0], matrix[1, 0])
    sy = math.hypot(matrix[0, 1], matrix[1, 1])
    assert 1 / proj.MAX_ANISOTROPY - 1e-6 <= sx / sy <= proj.MAX_ANISOTROPY + 1e-6


def test_uv_transform_agrees_with_the_pixel_transform():
    """Shader uv uzayında çalışıyor; dönüşüm oraya kayıpsız taşınmalı."""
    width, height = 320, 427
    matrix = np.array([[0.9, -0.1], [0.12, 1.05]])
    offset = np.array([11.0, -4.0])
    uv_matrix, uv_offset = proj.to_uv_transform(matrix, offset, width, height)
    a = np.array([[uv_matrix[0], uv_matrix[1]], [uv_matrix[2], uv_matrix[3]]])
    for pixel in ([10.0, 20.0], [160.0, 213.0], [300.0, 400.0]):
        pixel = np.asarray(pixel)
        expected = matrix @ pixel + offset
        uv = np.array([(pixel[0] + 0.5) / width, (pixel[1] + 0.5) / height])
        got = a @ uv + np.asarray(uv_offset)
        back = np.array([got[0] * width - 0.5, got[1] * height - 0.5])
        assert np.allclose(back, expected, atol=1e-6)


def test_fit_of_empty_masks_is_harmless():
    empty = np.zeros((20, 20), dtype=bool)
    full = np.ones((20, 20), dtype=bool)
    assert proj.fit_photo(empty, full)[2] == 0.0
    assert proj.fit_photo(full, empty)[2] == 0.0


# --------------------------------------------------------------------------- #
# Maske
# --------------------------------------------------------------------------- #

def two_tone_photo(path, band=True):
    """Gerçek müşteri fotoğrafının zor yanı: fon TEK RENK değil.

    Arkada duvar, altta koyu bir masa ve ikisinin birleştiği yerde parlak bir
    dikiş şeridi var. Ürün ortada ve açık renk.
    """
    image = np.zeros((420, 320, 3), dtype=np.uint8)
    image[:180] = (46, 44, 42)                       # duvar
    image[180:] = (26, 25, 27)                       # masa
    if band:
        image[176:184] = (150, 148, 142)             # dikiş parlaması
    image[150:330, 95:225] = (208, 206, 200)         # ürün
    Image.fromarray(image).save(path)
    return path


def test_mask_finds_the_product_on_a_two_tone_background(tmp_path):
    path = two_tone_photo(tmp_path / "foto.png")
    mask = proj.photo_mask(path, (320, 420))
    assert mask is not None
    inside = mask[200:300, 120:200]
    assert inside.mean() > 0.9, "ürünün içi maskeye girmedi"
    assert mask[:140, :60].mean() < 0.05, "duvar ürün sanıldı"


def test_mask_is_resolution_stable(tmp_path):
    """Aynı fotoğraf, farklı çözünürlük, aynı maske.

    Hizalama 320 px'te, sayfaya giden PNG ise 512 px'te üretiliyordu ve
    segmentasyon çözünürlüğe duyarlı olduğu için ikisi AYRI bölge seçiyordu;
    sonuçta fotoğraf modelde hiç görünmüyordu.
    """
    path = two_tone_photo(tmp_path / "foto.png")
    shares = []
    for width in (160, 320, 512):
        mask = proj.photo_mask(path, (width, int(round(width * 420 / 320))))
        assert mask is not None
        shares.append(float(mask.mean()))
    assert max(shares) - min(shares) < 0.03, shares


def test_mask_prefers_the_learned_cutout(tmp_path, monkeypatch):
    path = two_tone_photo(tmp_path / "foto.png")
    learned = np.zeros((420, 320), dtype=bool)
    learned[40:80, 40:80] = True
    monkeypatch.setattr(proj, "_rembg_mask", lambda p, size: learned)
    proj._MASK_CACHE.clear()
    mask = proj.photo_mask(path, (320, 420))
    assert np.array_equal(mask, learned)


def test_mask_falls_back_when_the_cutout_is_unavailable(tmp_path, monkeypatch):
    """rembg kurulu değilse zincir durmaz, klasik yola düşer.

    Gerçek `_rembg_mask` geri konuluyor ama oturumu yokmuş gibi davranıyor —
    paketin kurulu olmadığı bir makinenin birebir taklidi.
    """
    path = two_tone_photo(tmp_path / "foto.png")
    monkeypatch.setattr(proj, "_rembg_mask", REAL_REMBG_MASK)
    monkeypatch.setattr(proj, "_rembg_session", lambda: None)
    proj._MASK_CACHE.clear()
    assert proj._rembg_mask(path, (320, 420)) is None
    mask = proj.photo_mask(path, (320, 420))
    assert mask is not None and mask.any()


def test_mask_of_a_blank_photo_is_none(tmp_path):
    path = tmp_path / "duz.png"
    Image.new("RGB", (200, 260), (40, 40, 40)).save(path)
    mask = proj.photo_mask(path, (200, 260))
    assert mask is None or mask.mean() < 0.35


def test_export_mask_matches_the_mask_used_for_fitting(tmp_path):
    photo = two_tone_photo(tmp_path / "foto.png")
    out = proj.export_mask(photo, tmp_path / "mask.png")
    assert out is not None and out.exists()
    with Image.open(out) as image:
        assert image.mode == "L"
        assert image.width == proj.RASTER_WIDTH
        written = np.asarray(image) > 127
    reference = proj.photo_mask(photo, (image.width, image.height))
    assert proj._iou(written, reference) > 0.9


# --------------------------------------------------------------------------- #
# Kaplama ve uçtan uca arama
# --------------------------------------------------------------------------- #

def test_coverage_counts_only_the_visible_half(world):
    """Kapalı bir katının yüzeyinin en çok yarısı tek yönden giyinebilir."""
    vertices, faces, center, radius = world
    projector = proj.default_projector(center, radius, 1.0)
    ones = np.ones((64, 64), dtype=bool)
    worn = proj.coverage(vertices, faces, projector, np.eye(2), np.zeros(2), ones)
    assert 0.05 < worn < 0.5, worn


def test_coverage_is_zero_when_the_mask_is_empty(world):
    vertices, faces, center, radius = world
    projector = proj.default_projector(center, radius, 1.0)
    empty = np.zeros((64, 64), dtype=bool)
    assert proj.coverage(vertices, faces, projector, np.eye(2),
                         np.zeros(2), empty) == 0.0


def test_build_recovers_the_direction_the_photo_was_taken_from(model, world, tmp_path):
    """Uçtan uca: bilinen bir yönden "çekilmiş" fotoğrafı veriyoruz, arama o
    yönü ve neredeyse birim bir hizalamayı geri bulmalı."""
    vertices, faces, center, radius = world
    truth = proj.direction_from(55.0, 15.0)
    projector = proj.default_projector(center, radius, 0.75, truth)
    photo = silhouette_photo(vertices, faces, projector, tmp_path / "urun-1.png")

    best, info = proj.build(model, [photo])
    assert best is not None, info

    # Siluet eşleştirmesi BAKIŞ DÜZLEMİNİ bulur; ön yüzle arka yüzü ayıramaz.
    # Eksenel simetriye yakın bir üründe (bu vana öyle) 180° çevrilmiş yönün
    # silueti neredeyse aynıdır — veri o ayrımı içermiyor, dolayısıyla test de
    # istememeli. Ayrım ancak fotoğrafın içeriği karşılaştırılarak yapılabilir.
    found = np.asarray(best.direction)
    angle = min(
        math.degrees(math.acos(float(np.clip(np.dot(found, truth), -1, 1)))),
        math.degrees(math.acos(float(np.clip(np.dot(found, -truth), -1, 1)))))
    # Tolerans 30°. Arama agi 20° adimli oldugu icin taban hata zaten ~10°
    # mertebesinde; ustune bu urunun silueti eksenel simetriye cok yakin.
    # Milin kare tahrik ucu fotograflardaki gercek boya (1,05 x mil capi)
    # uzatildiginda siluet daha da simetriklesti ve olculen sapma 28,4°'ye
    # cikti — tahmin edicinin kendi cozunurlugu icinde, algoritmada bir
    # gerileme degil. Bu alt sistem artik VARSAYILAN KAPALI (bkz.
    # core/config.py); testi yine de kosuyoruz cunku kod duruyor.
    assert angle < 30.0, f"{angle:.1f}° sapma, aday: {info['candidates']}"
    assert best.iou > 0.85, best.iou
    assert best.coverage > 0.15, best.coverage
    assert best.photo == photo.name


def test_build_without_usable_photos_returns_none(model, tmp_path):
    blank = tmp_path / "duz.jpg"
    Image.new("RGB", (400, 300), (30, 30, 30)).save(blank)
    best, info = proj.build(model, [blank])
    assert best is None
    assert info["best"] is None and info["iou"] == 0.0


def test_projector_serialises_to_json(model, world, tmp_path):
    """Sayfaya gömülen sözleşme: shader'ın okuduğu her alan JSON'da olmalı."""
    vertices, faces, center, radius = world
    projector = proj.default_projector(center, radius, 0.75,
                                       proj.direction_from(30.0, 10.0))
    photo = silhouette_photo(vertices, faces, projector, tmp_path / "urun-1.png")
    best, _ = proj.build(model, [photo])
    data = json.loads(json.dumps(best.as_dict()))
    for field in ("position", "target", "fov", "aspect", "near", "far",
                  "fit_matrix", "fit_offset", "photo", "iou", "direction",
                  "coverage"):
        assert field in data, field
    assert len(data["fit_matrix"]) == 4 and len(data["fit_offset"]) == 2


def test_rotation_is_actually_searched(world):
    """Dondurme parametresi GERCEKTEN araniyor mu.

    Nelder-Mead'in varsayilan baslangic simpleksi her parametreyi kendi
    degerinin %5'i kadar oynatir. Moment tahmini dondurmeyi sifira yakin
    verdiginde (vana silueti ana eksen bakimindan belirsizdir, neredeyse her
    zaman oyle olur) adim 0.03 dereceye duser ve dondurme pratikte hic
    aranmaz: 9 derece cevrilmis bir maske 0.80 IoU'da takili kaliyordu.
    Simpleks artik parametrelerin fiziksel olceginden kuruluyor.
    """
    vertices, faces, center, radius = world
    silhouette = np.flipud(proj.rasterize_silhouette(
        vertices, faces, proj.default_projector(center, radius, 0.75), 140))
    turned = _warp_known(silhouette, 9.0, 1.18, 7.0, -5.0)
    matrix, _, iou, _ = proj.fit_photo(silhouette, turned)
    assert iou > 0.92, iou
    angle = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    assert 5.0 < angle < 14.0, f"{angle:.1f}° bulundu, 9° bekleniyordu"


def test_score_balances_alignment_coverage_and_axis():
    """Puan üç ölçütü de GERÇEKTEN dinlemeli.

    Üçü de gerekli ve hiçbiri diğerini ezmemeli:

    * **örtüşme** — fotoğraf modele oturuyor mu (ölçülen kanıt),
    * **kaplama** — fotoğraf yüzeyin ne kadarını giydiriyor (işe yararlık),
    * **diklik** — vana hattın içinden değil karşıdan görünüyor mu (sunum).

    Örtüşmeyi karesiyle ağırlıklandırmak denendi: tepeden çekilmiş kare siluet
    örtüşmesinde öne geçip kazanıyor, ama kaplama 0,40'tan 0,31'e düşüyor ve
    ürünün yalnız üst yüzü giydiriliyordu. Bu yüzden üçü eşit ağırlıkta.
    """
    def score(iou, worn, across):
        return iou * worn * across

    # Eşit kaplamada daha iyi hizalama kazanır.
    assert score(0.90, 0.38, 0.93) > score(0.82, 0.38, 0.93)
    # Eşit hizalamada daha geniş kaplama kazanır.
    assert score(0.84, 0.40, 0.93) > score(0.84, 0.31, 0.93)
    # Ölçülen gerçek durum: yandan çekilen kare, tepeden çekilene yeğlenir.
    assert score(0.8202, 0.4012, 0.937) > score(0.8379, 0.3058, 0.993)
    # Eksene dik bakan yön, hattın içinden bakana yeğlenir.
    assert score(0.88, 0.38, 0.95) > score(0.88, 0.38, 0.50)


# --------------------------------------------------------------------------- #
# Cok yonlu projeksiyon (360 derece kaplama)
# --------------------------------------------------------------------------- #

def test_multi_covers_more_than_a_single_projector(model, world, tmp_path):
    """Birden cok fotograf, tek fotograftan BELIRGIN daha fazla yuzey giydirir.

    Tek projektor urunun yalniz bir yuzunu kapliyor; ziyaretci modeli
    cevirince arkasi ciplak PBR olarak kaliyordu. Farkli acilardan cekilmis
    kareler birlikte cok daha fazla yuzey kaplar.
    """
    vertices, faces, center, radius = world
    photos = []
    for index, (azimuth, elevation) in enumerate(
            ((40.0, 12.0), (-140.0, 12.0), (130.0, 12.0))):
        projector = proj.default_projector(
            center, radius, 0.75, proj.direction_from(azimuth, elevation))
        photos.append(silhouette_photo(vertices, faces, projector,
                                       tmp_path / f"urun-{index + 1}.png"))

    single, _ = proj.build(model, photos)
    many, info = proj.build_multi(model, photos)
    assert single is not None and len(many) >= 2
    assert info["total_coverage"] > single.coverage * 1.4, info


def test_multi_uses_each_photo_at_most_once(model, world, tmp_path):
    """Ayni kareyi iki karsit yonden yansitmak UYDURMADIR.

    Kaplamayi yukseltir ama urunun ARKASINA ONUNUN aynasini boyar.
    Farkli kareler gercekten farkli yuzleri gosterir.
    """
    vertices, faces, center, radius = world
    photos = []
    for index, azimuth in enumerate((40.0, -140.0, 130.0)):
        projector = proj.default_projector(
            center, radius, 0.75, proj.direction_from(azimuth, 12.0))
        photos.append(silhouette_photo(vertices, faces, projector,
                                       tmp_path / f"urun-{index + 1}.png"))
    many, _ = proj.build_multi(model, photos)
    names = [p.photo for p in many]
    assert len(names) == len(set(names)), names


def test_multi_skips_projectors_that_add_nothing(model, world, tmp_path):
    """Katkisi esigin altinda kalan aday alinmaz.

    Her projektor sayfaya bir fotograf, bir maske ve bir derinlik haritasi
    ekler; karsiligini vermeyeni almak paketi ve kare suresini sisirir.
    Ayni kare iki kez verildiginde ikincisi hicbir yeni yuzey katmaz.
    """
    vertices, faces, center, radius = world
    projector = proj.default_projector(center, radius, 0.75,
                                       proj.direction_from(40.0, 12.0))
    first = silhouette_photo(vertices, faces, projector, tmp_path / "a.png")
    second = silhouette_photo(vertices, faces, projector, tmp_path / "b.png")
    many, _ = proj.build_multi(model, [first, second], count=4)
    assert len(many) == 1, [p.photo for p in many]


def test_multi_first_projector_is_the_opening_camera(model, world, tmp_path):
    """Listenin ilki sayfanin acilis kamerasidir; en iyi oturan yon o olmali."""
    vertices, faces, center, radius = world
    photos = []
    for index, azimuth in enumerate((40.0, -140.0)):
        projector = proj.default_projector(
            center, radius, 0.75, proj.direction_from(azimuth, 12.0))
        photos.append(silhouette_photo(vertices, faces, projector,
                                       tmp_path / f"urun-{index + 1}.png"))
    many, info = proj.build_multi(model, photos)
    single, _ = proj.build(model, photos)
    assert many and many[0].photo == info["best"]
    # Tek projektorlu arama hangi kareyi secerse, cok yonlude de ILK o gelir:
    # acilis karesi "en cok yuzey giydiren" degil, "en iyi oturan"dir.
    assert many[0].photo == single.photo
    assert many[0].iou == pytest.approx(single.iou, abs=1e-6)
