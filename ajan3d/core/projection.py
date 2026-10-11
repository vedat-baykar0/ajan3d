"""Fotoğraf projeksiyonu: müşteri fotoğrafını 3B modelin dış kabuğuna oturtur.

**Neden bu mimari.** Model fotoğraftan ölçülmüş değil, standart tablolardan
kurulmuş parametrik bir yeniden inşadır. Dolayısıyla fotoğraf hiçbir zaman
piksel piksel oturmaz. Hizalamayı tahmin etmek yerine ÖLÇÜYORUZ: modelin
siluetiyle fotoğraftaki nesnenin siluetini çakıştıran 2B benzerlik dönüşümü
(dönme + ölçek + öteleme) sayısal olarak çözülüyor. Çıktı, sayfanın shader'ına
geçen birkaç sayıdır.

**Neden UV'ye pişirmiyoruz.** Parçalar örneklenmiş durumda (4 cıvata tek mesh'i
paylaşıyor); UV'yi mesh'e yazmak örneklemeyi bozar, dosyayı büyütür ve GLB
sözleşmesini değiştirir. Bunun yerine projeksiyon, sayfada SABİT bir projektör
matrisinden hesaplanır — kameradan değil. Kamera döndüğünde matris değişmediği
için doku yüzeye yapışık kalır; parça patladığında da düğümün DURAĞAN (rest)
dünya matrisi kullanıldığı için doku parçayla birlikte gider.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

# Sayfadaki varsayılan bakış yönü ve kadraj (templates/viewer.html.j2 `frame()`).
# Projektör bu kamerayla ÖZDEŞ kurulur: sayfa açıldığı anda fotoğraf oturur.
VIEW_DIR = (0.78, 0.46, 1.0)
VIEW_FOV = 34.0
VIEW_ZOOM = 1.06
VIEW_LIFT = 0.07          # bakış noktası yarıçapın %7'si kadar yukarıda
RASTER_WIDTH = 320        # son hizalamanın siluet çözünürlüğü
SEARCH_WIDTH = 160        # yön aramasının çözünürlüğü (dönüşüm uv uzayında,
                          # yani çözünürlükten bağımsız; arama 4 kat ucuzluyor)

# Hizalama SERBEST değil. Ürün fotoğrafı neredeyse her zaman düz tutulmuş
# çekilir; serbest bırakılan dönme, siluet örtüşmesini yükseltmek uğruna
# fotoğrafı 76° çevirip ürünün dişini gövdenin yanına yapıştırıyordu (ölçüldü).
# Sınırlı dönme + sınırlı anizotropi, "blob eşleşmesi" ile "yapı eşleşmesi"
# arasındaki farkı kapatır: ölçek serbest, ama ürünün duruşu korunur.
MAX_ROTATION = 20.0       # derece
MAX_ANISOTROPY = 1.35     # sx/sy oranının sınırı (parametrik modelin oranları
                          # gerçek üründen biraz farklı olabilir)
# Vektörleştirilmiş tarama kalıplarının kenarları (px). Kademeli: üçgenlerin
# %80'i ilk kalıba, geri kalanın çoğu ikinciye sığar.
_TILES = (4, 12, 40)

# Kademeli aramada sonraki kademeye geçen aday sayısı.
SCOUT_KEEP = 16           # moment taramasından optimizasyona
FINAL_KEEP = 6            # optimizasyondan tam çözünürlüğe
FINAL_PER_PHOTO = 2       # finalistlerde fotoğraf başına en çok kaç yön

# Kazanan yön aynı zamanda sayfanın AÇILIŞ KAMERASIDIR; yalnız doku uyumuna
# bakmak yetmiyor. Akış ekseni boyunca bakan bir kare, ürünü boru hattının
# ardına gizliyor (ölçüldü: vananın önüne gelen boru gövdeyi tamamen
# kapatıyordu). Eksene dik bakan yön tam puan alır, eksen boyunca bakan yön
# bu katsayıya iner. Yasak değil, sadece pahalı: fotoğraf uyumu yeterince
# iyiyse yine kazanabilir.
AXIS_PENALTY = 0.45

# Çok yönlü projeksiyon: en çok kaç projektör ve bir adayın kabul edilmesi
# için gereken en küçük YENİ kaplama katkısı. Her projektör sayfaya bir
# fotoğraf (~110 KB), bir maske ve bir derinlik haritası (1024², GPU) ekler;
# karşılığını vermeyen adayı almak paketi ve kare süresini boşuna şişirir.
MULTI_COUNT = 4
MULTI_MIN_GAIN = 0.035
FLOW_AXIS = (0.0, 0.0, 1.0)   # bütün ailelerin sözleşmesi: akış Z


@dataclass(frozen=True)
class Projector:
    """Sayfaya geçen projeksiyon tanımı (hepsi görüntüleyici dünya biriminde)."""
    position: Tuple[float, float, float]
    target: Tuple[float, float, float]
    fov: float
    aspect: float
    near: float
    far: float
    # Fotoğrafı modelin siluetine oturtan 2B afin dönüşüm (uv uzayında):
    #   uv_foto = fit_matrix * uv_projeksiyon + fit_offset
    # 2x2 matris (satır sıralı) genel haldir: dönme, ölçek ve en-boy
    # düzeltmesini tek parçada taşır, shader tarafında belirsizlik kalmaz.
    fit_matrix: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    fit_offset: Tuple[float, float] = (0.0, 0.0)
    photo: str = ""
    mask: str = ""
    iou: float = 0.0                          # hizalama kalitesi (0..1)
    # Açılış kamerası bu yöne kurulur: fotoğrafın çekildiği açı ile sayfanın
    # ilk karesi aynı olsun diye. Aksi halde doku yandan vurur ve esner.
    direction: Tuple[float, float, float] = VIEW_DIR
    # Modelin yüzey alanının kaçta kaçı fotoğraf giyiyor. Kalanı endüstriyel
    # PBR çeliğe düşer; sayfa bu oranı müşteriye dürüstçe gösterir.
    coverage: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Kamera
# --------------------------------------------------------------------------- #

def _normalize(v: Sequence[float]) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def view_matrix(position: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Sağ elli bakış matrisi (three.js / glTF ile aynı sözleşme)."""
    forward = _normalize(target - position)        # kamera -Z'ye bakar
    up_hint = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(forward, up_hint))) > 0.999:
        up_hint = np.array([0.0, 0.0, 1.0])
    right = _normalize(np.cross(forward, up_hint))
    up = np.cross(right, forward)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = right, up, -forward
    m[:3, 3] = -m[:3, :3] @ position
    return m


def projection_matrix(fov_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_deg) * 0.5)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def direction_from(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Küresel açılardan bakış yönü (modelden kameraya doğru)."""
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return _normalize((math.sin(az) * math.cos(el), math.sin(el),
                       math.cos(az) * math.cos(el)))


def default_projector(center: np.ndarray, radius: float, aspect: float,
                      direction: Optional[Sequence[float]] = None) -> Projector:
    """Verilen yönden bakan projektör (varsayılan: sayfanın açılış kamerası)."""
    direction = _normalize(direction if direction is not None else VIEW_DIR)
    distance = radius / math.sin(math.radians(VIEW_FOV) * 0.5) * VIEW_ZOOM
    look = np.asarray(center, dtype=np.float64).copy()
    look[1] += radius * VIEW_LIFT
    position = look + direction * distance
    return Projector(
        position=tuple(float(v) for v in position),
        target=tuple(float(v) for v in look),
        fov=VIEW_FOV, aspect=float(aspect),
        # near/far nesneyi SARAR. Kullanıcı kamerasının geniş aralığını (d/120 ..
        # d*24) kopyalamak, projektörden alınan derinlik haritasında hassasiyeti
        # yok ediyor ve gövdede şerit şeklinde derinlik aknesi bırakıyordu.
        near=float(max(distance - radius * 1.6, distance * 0.02)),
        far=float(distance + radius * 1.6),
        direction=tuple(float(v) for v in direction),
    )


# --------------------------------------------------------------------------- #
# Siluet rasterleştirme
# --------------------------------------------------------------------------- #

def _fill_tiles(mask: np.ndarray, tri: np.ndarray, lo: np.ndarray, tile: int,
                width: int, height: int) -> None:
    """`tile`×`tile` kutuya sığan üçgenleri tek numpy çağrısında doldurur."""
    offset_x = np.tile(np.arange(tile), tile)
    offset_y = np.repeat(np.arange(tile), tile)
    # Bellek tavanı: tek seferde ~2 milyon aday piksel.
    chunk = max(1, 2_000_000 // (tile * tile))
    for begin in range(0, len(tri), chunk):
        t = tri[begin:begin + chunk]
        base = lo[begin:begin + chunk]
        gx = base[:, None, 0] + offset_x[None, :] + 0.5
        gy = base[:, None, 1] + offset_y[None, :] + 0.5
        ax, ay = t[:, 0, 0:1], t[:, 0, 1:2]
        bx, by = t[:, 1, 0:1], t[:, 1, 1:2]
        cx, cy = t[:, 2, 0:1], t[:, 2, 1:2]
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        d = np.where(np.abs(d) < 1e-12, 1e-12, d)
        l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / d
        l1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / d
        inside = (l0 >= 0) & (l1 >= 0) & (l0 + l1 <= 1)
        inside &= (gx < width) & (gy < height)
        if not inside.any():
            continue
        ys = np.clip(gy.astype(np.int32), 0, height - 1)
        xs = np.clip(gx.astype(np.int32), 0, width - 1)
        mask[ys[inside], xs[inside]] = True


def rasterize_silhouette(vertices: np.ndarray, faces: np.ndarray,
                         projector: Projector, width: int = RASTER_WIDTH) -> np.ndarray:
    """Modelin projektörden görünen siluetini ikili maske olarak üretir.

    Yalnız siluet gerektiği için derinlik tamponu yok: üçgenler sırasız
    doldurulur, birleşimleri zaten siluettir. Arkaya bakan üçgenler elenir
    (kapalı katılarda siluet değişmez, iş yarıya iner).
    """
    height = max(2, int(round(width / projector.aspect)))
    vp = projection_matrix(projector.fov, projector.aspect, projector.near,
                           projector.far) @ view_matrix(
        np.asarray(projector.position, dtype=np.float64),
        np.asarray(projector.target, dtype=np.float64))

    homo = np.hstack([vertices, np.ones((len(vertices), 1))])
    clip = homo @ vp.T
    w = clip[:, 3]
    valid = w > 1e-9
    ndc = np.zeros((len(vertices), 2))
    ndc[valid] = clip[valid, :2] / w[valid, None]
    # NDC -> piksel (y aşağı doğru)
    px = (ndc[:, 0] * 0.5 + 0.5) * width
    py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * height
    pts = np.stack([px, py], axis=1)

    tri = pts[faces]                                   # (F, 3, 2)
    ok = valid[faces].all(axis=1)
    # Saat yönü = arkaya bakan (y ekseni ters çevrildiği için işaret de döner)
    area2 = ((tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1]) -
             (tri[:, 2, 0] - tri[:, 0, 0]) * (tri[:, 1, 1] - tri[:, 0, 1]))
    ok &= area2 > 1e-9
    tri = tri[ok]
    if len(tri) == 0:
        return np.zeros((height, width), dtype=bool)

    mask = np.zeros((height, width), dtype=bool)
    lo = np.floor(tri.min(axis=1)).astype(np.int32)
    hi = np.ceil(tri.max(axis=1)).astype(np.int32)
    np.clip(lo[:, 0], 0, width - 1, out=lo[:, 0])
    np.clip(lo[:, 1], 0, height - 1, out=lo[:, 1])
    np.clip(hi[:, 0], 0, width, out=hi[:, 0])
    np.clip(hi[:, 1], 0, height, out=hi[:, 1])

    # CAD mesh'lerinin üçgenlerinin neredeyse tamamı bir kaç piksel boyundadır.
    # Üçgen başına Python döngüsü kurmak, 70.000 üçgenlik bir modelde tek
    # siluet için 0,8 sn yiyordu — yön araması bunu yüzlerce kez çağırıyor.
    # Üçgenler kutu boyutuna göre kademelere ayrılıp her kademe SABİT bir
    # kalıpla tek numpy çağrısında taranıyor; döngüye yalnızca birkaç yüz
    # büyük üçgen kalıyor. Sonuç birebir aynı (örnekleme değil, gerçek
    # kapsama testi), süre ~20 kat kısalıyor.
    span = hi - lo
    remaining = (span > 0).all(axis=1)
    for tile in _TILES:
        batch = remaining & (span[:, 0] <= tile) & (span[:, 1] <= tile)
        if not batch.any():
            continue
        remaining &= ~batch
        _fill_tiles(mask, tri[batch], lo[batch], tile, width, height)

    for t, (x0, y0), (x1, y1) in zip(tri[remaining], lo[remaining], hi[remaining]):
        if x1 <= x0 or y1 <= y0:
            continue
        xs = np.arange(x0, x1) + 0.5
        ys = np.arange(y0, y1) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        ax, ay = t[0]; bx, by = t[1]; cx, cy = t[2]
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            continue
        l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / d
        l1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / d
        inside = (l0 >= 0) & (l1 >= 0) & (l0 + l1 <= 1)
        if inside.any():
            mask[y0:y1, x0:x1] |= inside
    return mask


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0..255) -> CIE L*a*b*. Fon ayrımı parlaklık ve renk farkını birlikte
    görmeli; ham RGB uzaklığı gölgeyi ürün sanıyor."""
    c = np.clip(rgb.astype(np.float64) / 255.0, 0.0, 1.0)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    d = 6.0 / 29.0
    f = np.where(xyz > d ** 3, np.cbrt(np.clip(xyz, 1e-12, None)),
                 xyz / (3 * d * d) + 4.0 / 29.0)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def _otsu(values: np.ndarray) -> float:
    """Otsu eşiği (iki sınıf arası varyansı enbüyükleyen değer)."""
    hist, edges = np.histogram(values, bins=256)
    weight = hist.cumsum()
    total = weight[-1]
    if total == 0:
        return float(values.mean())
    centers = (edges[:-1] + edges[1:]) * 0.5
    mean = (hist * centers).cumsum()
    w0 = weight[:-1]
    w1 = total - w0
    ok = (w0 > 0) & (w1 > 0)
    if not ok.any():
        return float(values.mean())
    m0 = np.divide(mean[:-1], w0, out=np.zeros_like(mean[:-1]), where=w0 > 0)
    m1 = np.divide(mean[-1] - mean[:-1], w1, out=np.zeros_like(mean[:-1]), where=w1 > 0)
    between = np.where(ok, w0 * w1 * (m0 - m1) ** 2, 0.0)
    return float(centers[int(np.argmax(between))])


def _disk(radius: int) -> np.ndarray:
    g = np.arange(-radius, radius + 1)
    return (g[:, None] ** 2 + g[None, :] ** 2) <= radius * radius


_REMBG_SESSION = None
_REMBG_STATE = "untried"          # untried | ready | unavailable
_MASK_CACHE: dict = {}


def _rembg_session():
    """U²-Net oturumu (tek sefer kurulur); kurulamıyorsa None.

    `u2netp` modeli **4,5 MB**'tır ve ilk çalıştırmada indirilip kullanıcı
    profiline önbelleklenir; çıkarım 0,16 sn sürüyor. Büyük kardeşi `u2net`
    (176 MB) bu iş için gereksiz: ürün fotoğrafında nesne büyük ve merkezde.
    """
    global _REMBG_SESSION, _REMBG_STATE
    if _REMBG_STATE != "untried":
        return _REMBG_SESSION
    try:
        from rembg import new_session
        _REMBG_SESSION = new_session("u2netp")
        _REMBG_STATE = "ready"
    except Exception:
        _REMBG_SESSION, _REMBG_STATE = None, "unavailable"
    return _REMBG_SESSION


def _rembg_mask(path: Path, size: Tuple[int, int]) -> Optional[np.ndarray]:
    """Öğrenilmiş ürün kesimi (arka plan kaldırma). Yoksa None.

    **Neden klasik yöntemin önünde.** Fon düz değil: arkada duvar, altta deri
    koltuk var ve ikisinin birleştiği yerde parlak bir dikiş şeridi uzanıyor.
    Renk tabanlı her ayrım o şeridi de "ürün" sayıyor, üstelik sonuç
    çözünürlüğe göre değişiyordu (320 px'te vana, 512 px'te duvar kazanıyordu).
    U²-Net şeridi görmez; ürünü görür.

    Yine de ZORUNLU değil: paket yoksa ya da model indirilemiyorsa klasik
    yönteme düşülür ve zincir çalışmaya devam eder.
    """
    session = _rembg_session()
    if session is None:
        return None
    try:
        from PIL import Image
        from rembg import remove

        with Image.open(path) as image:
            alpha = remove(image.convert("RGB"), session=session, only_mask=True)
        mask = np.asarray(alpha.resize(size, Image.LANCZOS)) > 127
    except Exception:
        return None
    return mask if mask.any() else None


def _largest_central(binary: np.ndarray) -> Optional[np.ndarray]:
    """Alan × merkeze yakınlık en yüksek bağlı bileşen, delikleri doldurulmuş.

    Ürün fotoğrafı ürünü ortalar; masa kenarı, gölge ve arkadaki nesneler ya
    küçüktür ya kenardadır. "En büyüğü al" kuralı tek başına yetmiyor:
    ölçüldü, kimi çözünürlükte duvar şeridi üründen geniş çıkıyor.
    """
    from scipy import ndimage

    labels, count = ndimage.label(binary)
    if count == 0:
        return None
    index = np.arange(1, count + 1)
    areas = ndimage.sum_labels(binary, labels, index=index)
    centroids = np.asarray(ndimage.center_of_mass(binary, labels, index=index))
    h, w = binary.shape
    offset = np.linalg.norm(centroids - np.array([h * 0.5, w * 0.5]), axis=1)
    score = areas * np.exp(-(offset / (0.45 * math.hypot(h, w))) ** 2)
    chosen = int(index[int(np.argmax(score))])
    return ndimage.binary_fill_holes(labels == chosen)


def _kmeans(samples: np.ndarray, clusters: int = 3, rounds: int = 12) -> np.ndarray:
    """Küçük, bağımlılıksız Lloyd kümelemesi (fon renklerini ayırmak için)."""
    if len(samples) <= clusters:
        return samples.copy()
    quantiles = np.linspace(0.1, 0.9, clusters)
    centers = np.quantile(samples, quantiles, axis=0)
    for _ in range(rounds):
        distance = np.linalg.norm(samples[:, None, :] - centers[None, :, :], axis=2)
        labels = np.argmin(distance, axis=1)
        moved = False
        for index in range(clusters):
            members = samples[labels == index]
            if len(members) == 0:
                continue
            mean = members.mean(axis=0)
            if not np.allclose(mean, centers[index], atol=1e-3):
                moved = True
            centers[index] = mean
        if not moved:
            break
    return centers


def photo_mask(path: Path, size: Tuple[int, int]) -> Optional[np.ndarray]:
    """Fotoğraftaki ürünün ikili maskesi; çıkarılamazsa None.

    Önce öğrenilmiş kesim (`_rembg_mask`) denenir; yoksa aşağıdaki klasik
    yola düşülür. Sonuç (yol, boyut, dosya zamanı) ile önbelleklenir —
    hizalama aynı maskeyi birkaç kez istiyor.

    Klasik yol, stüdyo/düz fon varsayımı: kenar şeridinden fon renkleri öğrenilir, hepsinden
    belirgin biçimde ayrılan pikseller ürün sayılır.

    **Fon tek renk değildir.** Gerçek müşteri fotoğrafında arkada duvar, altta
    masa var; ikisinin ortancası ikisine de uymayan bir "ortalama fon" üretiyor
    ve duvar ile masa da "ürün" sayılıyordu. Bu yüzden kenar pikselleri birkaç
    kümeye ayrılıyor ve uzaklık **en yakın kümeye** ölçülüyor.

    **En büyük bileşen de doğru bileşen değildir.** Ürün fotoğrafı ürünü
    ortalar; duvar şeridi ise kenara yapışır ve kimi çözünürlüklerde üründen
    geniş çıkar (ölçüldü: 512 px'te duvar kazanıyor, 320 px'te ürün — yani
    sonuç çözünürlüğe göre değişiyordu). Bileşenler alan × MERKEZE yakınlık
    ile puanlanıyor.
    """
    from PIL import Image
    from scipy import ndimage

    path = Path(path)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    key = (str(path), tuple(size), stamp)
    if key in _MASK_CACHE:
        return _MASK_CACHE[key]

    learned = _rembg_mask(path, size)
    if learned is not None:
        result = _largest_central(learned)
        if result is not None and result.any():
            _MASK_CACHE[key] = result
            return result

    try:
        img = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
    except Exception:
        return None
    lab = _srgb_to_lab(np.asarray(img))

    h, w = lab.shape[:2]
    band = max(2, min(h, w) // 12)
    edge = np.concatenate([lab[:band].reshape(-1, 3), lab[-band:].reshape(-1, 3),
                           lab[:, :band].reshape(-1, 3), lab[:, -band:].reshape(-1, 3)])
    centers = _kmeans(edge, clusters=3)
    distance = np.linalg.norm(lab[:, :, None, :] - centers[None, None, :, :],
                              axis=3).min(axis=2)

    binary = distance > _otsu(distance)
    binary = ndimage.binary_closing(binary, structure=_disk(3), iterations=2)
    binary = ndimage.binary_opening(binary, structure=_disk(2))

    result = _largest_central(binary)
    if result is not None:
        _MASK_CACHE[key] = result
    return result


# --------------------------------------------------------------------------- #
# 2B hizalama
# --------------------------------------------------------------------------- #

def _moments(mask: np.ndarray) -> Tuple[np.ndarray, float, float]:
    """Maskenin ağırlık merkezi, yarıçapı ve ana ekseninin açısı."""
    ys, xs = np.nonzero(mask)
    pts = np.stack([xs, ys], axis=1).astype(np.float64)
    center = pts.mean(axis=0)
    cov = np.cov((pts - center).T)
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, int(np.argmax(evals))]
    angle = math.atan2(major[1], major[0])
    radius = math.sqrt(len(pts) / math.pi)          # eşit alanlı dairenin yarıçapı
    return center, radius, angle


def _warp(mask: np.ndarray, m: np.ndarray, b: np.ndarray,
          shape: Tuple[int, int]) -> np.ndarray:
    """`mask`'i (M, b) dönüşümüyle hedef şekle taşır.

    ndimage (satır, sütun) sırasıyla çalışır; dönüşüm (x, y) sırasında
    kurulduğu için matris ve öteleme ters çevrilerek veriliyor.
    """
    from scipy import ndimage

    rc = np.array([[m[1, 1], m[1, 0]], [m[0, 1], m[0, 0]]])
    off = np.array([b[1], b[0]])
    out = ndimage.affine_transform(mask.astype(np.uint8), rc, offset=off,
                                   output_shape=shape, order=0, cval=0)
    return out.astype(bool)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.count_nonzero(a & b)
    union = np.count_nonzero(a | b)
    return inter / union if union else 0.0


def _transform(params: Sequence[float], pivot: np.ndarray
               ) -> Tuple[np.ndarray, np.ndarray]:
    """5 serbest parametreden sınırlı benzerlik dönüşümü.

    Parametreler `tanh` ile ezilerek sınırın içinde tutulur: optimize edici
    serbest çalışır, dönme ve anizotropi fiziksel olarak makul aralığı asla
    aşamaz. Kısıtı cezayla uygulamak yerine parametreleştirmeye gömmek,
    Nelder-Mead'in sınırda sıkışıp titremesini de önlüyor.
    """
    angle = math.radians(MAX_ROTATION) * math.tanh(params[0])
    aniso = math.log(MAX_ANISOTROPY) * math.tanh(params[1])
    scale = math.exp(params[2])
    sx, sy = scale * math.exp(aniso * 0.5), scale * math.exp(-aniso * 0.5)
    c, s = math.cos(angle), math.sin(angle)
    m = np.array([[c * sx, -s * sy], [s * sx, c * sy]])
    b = pivot + np.array([params[3], params[4]]) - m @ pivot
    return m, b


def _atanh(value: float) -> float:
    return math.atanh(max(-0.98, min(0.98, value)))


def initial_params(silhouette: np.ndarray, photo: np.ndarray
                   ) -> Tuple[np.ndarray, np.ndarray]:
    """Momentlerden başlangıç parametreleri (+ dönüşüm ekseni)."""
    c_s, r_s, a_s = _moments(silhouette)
    c_p, r_p, a_p = _moments(photo)
    # Ana eksen farkı ±90° belirsizdir; sınırın içine katlanır. Katlanamıyorsa
    # duruşlar gerçekten uyuşmuyor demektir ve 0 ile başlanır — IoU bunu
    # zaten düşük puanlayacak.
    delta = math.degrees(a_p - a_s)
    delta = (delta + 90.0) % 180.0 - 90.0
    if abs(delta) > MAX_ROTATION:
        delta = 0.0
    shift = c_p - c_s
    scale = (r_p / r_s) if r_s > 1e-6 else 1.0
    return np.array([_atanh(delta / MAX_ROTATION), 0.0, math.log(max(scale, 1e-3)),
                     shift[0], shift[1]]), c_s


def fit_photo(silhouette: np.ndarray, photo: np.ndarray, refine: bool = True,
              start: Optional[Sequence[float]] = None
              ) -> Tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """Fotoğraf maskesini siluete oturtur: (M, b, IoU, parametreler).

    Önce momentlerden (merkez, alan, ana eksen) kapalı formda bir başlangıç
    bulunur; ardından örtüşme (IoU) doğrudan enbüyüklenerek rötuş yapılır.
    "Gözle ayarlama" yok: hizalamanın kalitesi döndürülen IoU ile ölçülebilir.

    Dönme ve anizotropi **sınırlıdır** (bkz. MAX_ROTATION). Serbest bırakılan
    bir benzerlik dönüşümü, siluet örtüşmesini birkaç puan artırmak uğruna
    fotoğrafı çeyrek tur çevirmeye hazırdır; ortaya çıkan görüntüde ürünün
    dişi gövdenin yanına yapışır. Örtüşme yüksek çıkar, sonuç yanlıştır.
    """
    if not silhouette.any() or not photo.any():
        return np.eye(2), np.zeros(2), 0.0, np.zeros(5)
    moments, pivot = initial_params(silhouette, photo)
    params = np.asarray(start, dtype=np.float64) if start is not None else moments
    shape = silhouette.shape

    def score(values) -> float:
        m, b = _transform(values, pivot)
        return -_iou(silhouette, _warp(photo, m, b, shape))

    best = (score(params), params)
    if start is not None:
        value = score(moments)
        if value < best[0]:
            best = (value, moments)
    if refine:
        try:
            from scipy.optimize import minimize

            # Başlangıç simpleksi ELLE kuruluyor. Nelder-Mead varsayılanı her
            # parametreyi kendi değerinin %5'i kadar oynatır; dönme parametresi
            # moment tahmininden sıfıra yakın geldiğinde (neredeyse her zaman,
            # çünkü vana silueti ana eksen bakımından belirsizdir) adım 0.03°
            # oluyor ve dönme PRATİKTE HİÇ aranmıyordu. Ölçüldü: 9° çevrilmiş
            # bir maske 0,80 IoU'da takılı kalıyor, doğru adımla 0,97'ye
            # çıkıyor. Adımlar parametrelerin fiziksel ölçeğinden geliyor:
            # ~7° dönme, ~%9 ölçek, karenin %5'i kadar kayma.
            steps = np.array([0.35, 0.30, 0.09,
                              shape[1] * 0.05, shape[0] * 0.05])
            simplex = np.vstack([best[1]] + [best[1] + np.eye(5)[i] * steps[i]
                                             for i in range(5)])
            res = minimize(score, best[1], method="Nelder-Mead",
                           options={"initial_simplex": simplex, "maxiter": 600,
                                    "xatol": 1e-3, "fatol": 1e-4})
            if res.fun < best[0]:
                best = (float(res.fun), np.asarray(res.x, dtype=np.float64))
        except Exception:                                # scipy yoksa moment yeter
            pass
    m, b = _transform(best[1], pivot)
    return m, b, -best[0], best[1]


def to_uv_transform(m: np.ndarray, b: np.ndarray, width: int, height: int
                    ) -> Tuple[Tuple[float, float, float, float], Tuple[float, float]]:
    """Piksel uzayı dönüşümünü shader'ın kullandığı uv uzayına çevirir."""
    s = np.diag([float(width), float(height)])
    s_inv = np.diag([1.0 / width, 1.0 / height])
    a = s_inv @ m @ s
    off = s_inv @ (b + 0.5 - m @ np.array([0.5, 0.5]))
    return (float(a[0, 0]), float(a[0, 1]), float(a[1, 0]), float(a[1, 1])), \
           (float(off[0]), float(off[1]))


def export_mask(photo_path: Path, out_path: Path, width: int = RASTER_WIDTH,
                feather: float = 2.5) -> Optional[Path]:
    """Fotoğraftaki ürünün maskesini gri tonlu PNG olarak yazar.

    Shader'ın dördüncü kapısı budur: model fotoğraftaki vananın dışına taştığı
    yerde, örneklenen piksel ürünün değil ARKA PLANIN rengidir ve gövdeye gri
    bir bant olarak düşer. Maske o pikselleri PBR'ye geri bırakır. Kenarlar
    yumuşatılıyor ki geçiş sert bir kesik olarak görünmesin.

    Çözünürlük hizalamanınkiyle (RASTER_WIDTH) AYNIDIR ve değiştirilmemelidir:
    segmentasyon çözünürlüğe duyarlıdır, farklı bir değerde başka bir bölge
    seçilebiliyor — sayfaya giden maske ile hizalamanın kullandığı maske
    ayrışırsa fotoğraf modelin üzerinde hiç görünmez (yaşandı).
    """
    from PIL import Image
    from scipy import ndimage

    try:
        with Image.open(photo_path) as image:
            aspect = image.width / image.height
    except Exception:
        return None
    height = max(2, int(round(width / aspect)))
    mask = photo_mask(Path(photo_path), (width, height))
    if mask is None or not mask.any():
        return None
    soft = ndimage.gaussian_filter(mask.astype(np.float32), feather)
    soft = np.clip((soft - 0.35) / 0.3, 0.0, 1.0)      # kenarı daralt + yumuşat
    Image.fromarray((soft * 255).astype(np.uint8), mode="L").save(out_path, optimize=True)
    return out_path


# --------------------------------------------------------------------------- #
# Üst seviye
# --------------------------------------------------------------------------- #

def load_world_mesh(glb_path: Path):
    """GLB'yi görüntüleyicinin dünya koordinatlarında tek mesh olarak okur.

    Kök düğümdeki mm->m ölçeği, merkeze alma ve her örneğin kendi matrisi
    trimesh tarafından uygulanır; yani buradaki köşeler sayfadakilerle aynı
    uzaydadır. Hizalamanın doğru olması buna bağlı.
    """
    import trimesh

    scene = trimesh.load(str(glb_path), force="scene")
    parts = [g for g in scene.dump() if getattr(g, "faces", None) is not None]
    if not parts:
        raise ValueError(f"{glb_path}: geometri yok")
    return trimesh.util.concatenate(parts)


def _photo_aspect(path: Path) -> Optional[float]:
    from PIL import Image
    try:
        with Image.open(path) as image:
            return image.width / image.height
    except Exception:
        return None


def coverage_mask(vertices: np.ndarray, faces: np.ndarray, projector: Projector,
                  matrix: np.ndarray, offset: np.ndarray, mask: np.ndarray):
    """(yüz başına giyinik mi, yüz alanları) — `coverage` bunun oranıdır.

    Çok yönlü projeksiyonda hangi yüzün HANGİ fotoğrafça giydirildiğini
    bilmek gerekiyor: ikinci projektör, birincinin bıraktığı boşluğu
    kapattığı ölçüde değerli.
    """
    triangle = vertices[faces]
    centroid = triangle.mean(axis=1)
    cross = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
    length = np.linalg.norm(cross, axis=1)
    area = 0.5 * length
    normal = cross / np.where(length > 1e-12, length, 1.0)[:, None]

    to_projector = np.asarray(projector.position, dtype=np.float64) - centroid
    to_projector /= np.maximum(np.linalg.norm(to_projector, axis=1), 1e-12)[:, None]
    ok = (normal * to_projector).sum(axis=1) > 0.25      # shader ile aynı eşik

    vp = projection_matrix(projector.fov, projector.aspect, projector.near,
                           projector.far) @ view_matrix(
        np.asarray(projector.position, dtype=np.float64),
        np.asarray(projector.target, dtype=np.float64))
    homo = np.hstack([centroid, np.ones((len(centroid), 1))])
    clip = homo @ vp.T
    w = clip[:, 3]
    ok &= w > 1e-9
    if not ok.any():
        return ok, area
    base = np.zeros((len(centroid), 2))
    base[ok] = clip[ok, :2] / w[ok, None] * 0.5 + 0.5        # uv (y yukarı)
    uv = base @ matrix.T + offset
    ok &= (uv >= 0.0).all(axis=1) & (uv <= 1.0).all(axis=1)
    if not ok.any():
        return ok, area
    height, width = mask.shape
    column = np.clip((uv[:, 0] * width).astype(np.int32), 0, width - 1)
    row = np.clip((uv[:, 1] * height).astype(np.int32), 0, height - 1)
    ok &= mask[row, column]                                  # maske de y yukarı
    return ok, area


def coverage(vertices: np.ndarray, faces: np.ndarray, projector: Projector,
             matrix: np.ndarray, offset: np.ndarray, mask: np.ndarray) -> float:
    """Modelin yüzey alanının ne kadarı gerçekten fotoğraf giyiyor (0..1).

    Örtüşme (IoU) tek başına yeterli bir ölçüt değil: vananın **ucundan**
    çekilmiş bir fotoğrafın silueti de modelin ön görünüşüne iyi oturur, ama
    o fotoğraf ürünün yalnızca kapak yüzünü taşır; gövdenin tamamı PBR'ye
    düşer. Yandan çekilmiş bir fotoğraf aynı örtüşmeyle üç kat yüzey giydirir.
    Seçimi bu sayı belirliyor.

    Yaklaşıklık: derinlik testi yapılmıyor, yalnız projektöre BAKAN yüzler
    sayılıyor. Kapalı bir katıda arkada kalıp yine de projektöre bakan yüzler
    azınlıktır ve bütün adaylar aynı yanlılığı taşıdığı için sıralama bozulmaz.
    """
    worn, area = coverage_mask(vertices, faces, projector, matrix, offset, mask)
    total = float(area.sum())
    return float(area[worn].sum() / total) if total > 0.0 else 0.0


def axis_factor(direction: Sequence[float],
                flow_axis: Sequence[float] = FLOW_AXIS) -> float:
    """Yönün akış eksenine DİKLİĞİ (AXIS_PENALTY..1).

    1.0 = hatta tam karşıdan bakılıyor (vana boydan boyu görünür),
    AXIS_PENALTY = hattın içinden bakılıyor (boru vanayı örter).
    """
    d = _normalize(direction)
    a = _normalize(flow_axis)
    across = math.sqrt(max(0.0, 1.0 - float(np.dot(d, a)) ** 2))
    return AXIS_PENALTY + (1.0 - AXIS_PENALTY) * across


def _shortlist(refined: Sequence[tuple], keep: int = FINAL_KEEP,
               per_photo: int = FINAL_PER_PHOTO) -> List[tuple]:
    """Finalistleri seçerken her fotoğrafa yer ayırır.

    Kısa liste yalnız örtüşmeye göre kesildiğinde, iyi hizalanan ama ürünün
    az bir kısmını taşıyan bir kare (ör. tepeden çekilmiş pabuç fotoğrafı)
    bütün yerleri kapatıyor ve **kaplama hiç hesaplanamadan** kazanıyordu:
    kaplama yalnızca finalistler için ölçülüyor. Fotoğraf başına en iyi
    birkaç yönü garantilemek, her adayın kaplamayla sınanmasını sağlar.
    """
    taken: dict = {}
    out: List[tuple] = []
    for item in refined:
        index = item[1]
        if taken.get(index, 0) >= per_photo:
            continue
        taken[index] = taken.get(index, 0) + 1
        out.append(item)
        if len(out) >= keep:
            break
    return out



def _decide(scored: Sequence[tuple]) -> Optional[Projector]:
    """Finalistlerden kazananı seçer: önce FOTOĞRAF, sonra YÖN.

    İki ayrı soru tek puana sıkıştırıldığında ikisi de yanlış cevaplanıyordu:

    * **Hangi fotoğraf?** Bu bir *işe yararlık* sorusu. Tepeden çekilmiş bir
      kare siluet örtüşmesinde öne geçebilir ama ürünün yalnız üst yüzünü
      taşır; cevabı **kaplama** verir (örtüşme × kaplama × diklik).
    * **Hangi yön?** Fotoğraf seçildikten sonra bu bir *hizalama* sorusu —
      o kare hangi açıdan çekilmişse o. Cevabı **örtüşme** verir; kaplamanın
      burada söz hakkı olmamalı, çünkü derinlik testi olmayan yaklaşık bir
      ölçüt, ölçülmüş %5'lik bir hizalama farkını çevirebiliyordu (sentetik
      veride 37° sapma olarak ölçüldü).

    Yönelim çarpanı (`across`) her iki adımda da var: hattın içinden bakmak
    hem kötü bir fotoğraf tercihi hem kötü bir açılış karesidir.
    """
    if not scored:
        return None
    winner = max(scored, key=lambda item: item[0])[2]
    same_photo = [item for item in scored if item[2].photo == winner.photo]
    return max(same_photo, key=lambda item: item[1])[2]



def _finalists(glb_path: Path, photo_paths: Sequence[Path], width: int,
               search_width: int, azimuth_step: float,
               elevations: Sequence[float], flow_axis: Sequence[float],
               scout_keep: int = SCOUT_KEEP, final_keep: int = FINAL_KEEP,
               per_photo: int = FINAL_PER_PHOTO):
    """Üç kademeli aramanın sonucu: puanlanmış finalist projektörler.

    Dönen her kayıt: (puan, hizalama, Projector, giyinik yüz maskesi).
    `build` bunlardan birini, `build_multi` birkaçını seçer.
    """
    mesh = load_world_mesh(Path(glb_path))
    sphere = mesh.bounding_sphere.primitive
    center, radius = np.asarray(sphere.center, dtype=np.float64), float(sphere.radius)
    vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)

    photos: List[dict] = []
    for photo_path in photo_paths:
        photo_path = Path(photo_path)
        aspect = _photo_aspect(photo_path)
        if aspect is None:
            continue
        height = max(2, int(round(search_width / aspect)))
        mask = photo_mask(photo_path, (search_width, height))
        if mask is None or not mask.any():
            continue
        photos.append({"path": photo_path, "aspect": aspect,
                       "mask": np.flipud(mask)})            # y yukarı
    info: dict = {"candidates": [], "radius": radius, "photos": len(photos)}
    if not photos:
        return [], info, (vertices, faces)

    angles = [(float(a), float(e))
              for a in np.arange(-180.0, 180.0, azimuth_step)
              for e in elevations]

    # --- 1. kademe: moment hizalaması ------------------------------------- #
    silhouettes: dict = {}
    scouted: List[tuple] = []
    for index, photo in enumerate(photos):
        for angle in angles:
            key = (round(photo["aspect"], 4), angle)
            if key not in silhouettes:
                projector = default_projector(center, radius, photo["aspect"],
                                              direction_from(*angle))
                raster = rasterize_silhouette(vertices, faces, projector, search_width)
                silhouettes[key] = (projector, np.flipud(raster))
            projector, silhouette = silhouettes[key]
            if not silhouette.any():
                continue
            _, _, iou, params = fit_photo(silhouette, photo["mask"], refine=False)
            scouted.append((iou, index, angle, params))

    scouted.sort(key=lambda item: -item[0])
    if not scouted:
        return [], info, (vertices, faces)

    # Tarama listesi de FOTOĞRAF BAŞINA kısıtlanıyor. Düz kesilince iyi
    # hizalanan tek bir kare 36 sıranın tamamını kapatıyor ve geri kalan
    # fotoğraflar hiç optimize edilmeden eleniyordu — çok yönlü kaplama
    # tam da onlara muhtaç.
    scouted = _shortlist(scouted, scout_keep,
                         max(2, scout_keep // max(1, len(photos))))

    # --- 2. kademe: optimizasyon ------------------------------------------ #
    refined: List[tuple] = []
    for iou, index, angle, params in scouted[:scout_keep]:
        photo = photos[index]
        _, silhouette = silhouettes[(round(photo["aspect"], 4), angle)]
        _, _, iou, params = fit_photo(silhouette, photo["mask"], start=params)
        refined.append((iou, index, angle, params))
    refined.sort(key=lambda item: -item[0])
    refined = _shortlist(refined, final_keep, per_photo)

    # --- 3. kademe: tam çözünürlük + puan --------------------------------- #
    scored: List[tuple] = []
    for iou, index, angle, params in refined[:final_keep]:
        photo = photos[index]
        projector = default_projector(center, radius, photo["aspect"],
                                      direction_from(*angle))
        silhouette = np.flipud(rasterize_silhouette(vertices, faces, projector, width))
        height = max(2, int(round(width / photo["aspect"])))
        mask = photo_mask(photo["path"], (width, height))
        if mask is None or not mask.any():
            continue
        mask = np.flipud(mask)
        pixel_matrix, pixel_offset, iou, _ = fit_photo(silhouette, mask, start=params)
        matrix, offset = to_uv_transform(pixel_matrix, pixel_offset, width,
                                         silhouette.shape[0])
        worn_faces, areas = coverage_mask(
            vertices, faces, projector,
            np.array([[matrix[0], matrix[1]], [matrix[2], matrix[3]]]),
            np.asarray(offset), mask)
        total = float(areas.sum())
        worn = float(areas[worn_faces].sum() / total) if total > 0 else 0.0
        across = axis_factor(projector.direction, flow_axis)
        score = iou * worn * across
        info["candidates"].append({
            "photo": photo["path"].name, "iou": round(iou, 4),
            "coverage": round(worn, 4), "across": round(across, 3),
            "score": round(score, 4),
            "direction": [round(float(v), 3) for v in projector.direction]})
        scored.append((score, iou * across,
                       Projector(projector.position, projector.target,
                                 projector.fov, projector.aspect, projector.near,
                                 projector.far, matrix, offset,
                                 photo["path"].name, "", iou,
                                 projector.direction, worn),
                       worn_faces, areas))

    info["candidates"].sort(key=lambda item: -item["score"])
    return scored, info, (vertices, faces)


def build(glb_path: Path, photo_paths: Sequence[Path], width: int = RASTER_WIDTH,
          search_width: int = SEARCH_WIDTH, azimuth_step: float = 20.0,
          elevations: Sequence[float] = (-6.0, 4.0, 13.0, 22.0),
          flow_axis: Sequence[float] = FLOW_AXIS
          ) -> Tuple[Optional[Projector], dict]:
    """Model + aday fotoğraflar -> EN İYİ oturan tek projektör tanımı.

    Üç kademe. Her kademe bir öncekinin en iyi adaylarını alır; böylece pahalı
    iş (tam çözünürlüklü siluet + optimizasyon) yüzlerce yerine birkaç kez
    çalışır:

    1. **Tarama** — bütün yönler için siluet (ucuz çözünürlükte, bir kez
       hesaplanır ve aynı en-boy oranındaki bütün fotoğraflarda paylaşılır),
       her fotoğrafla yalnız MOMENT hizalaması. Optimizasyon yok.
    2. **Rötuş** — en iyi birkaç (fotoğraf, yön) çifti için tam optimizasyon.
    3. **Karar** — finalistler tam çözünürlükte yeniden hesaplanır ve
       puanlanır; karar iki adımlı (önce fotoğraf, sonra yön).

    **Bilinen belirsizlik:** eksenel simetriye yakın bir üründe siluet, 180°
    çevrilmiş yönden bakıldığında neredeyse aynıdır; siluet eşleştirmesi tek
    başına ön ile arkayı ayıramaz. Simetrik bir üründe bu görsel olarak fark
    etmez; asimetrik bir üründe kesin ayrım ancak fotoğrafın İÇERİĞİ
    karşılaştırılarak yapılabilir — siluetle değil.

    Kazanan yön sayfanın açılış kamerası olur.
    """
    scored, info, _ = _finalists(glb_path, photo_paths, width, search_width,
                                 azimuth_step, elevations, flow_axis)
    best = _decide([(s, a, p) for s, a, p, _m, _ar in scored])
    info["best"] = best.photo if best else None
    info["iou"] = best.iou if best else 0.0
    info["coverage"] = best.coverage if best else 0.0
    return best, info


def build_multi(glb_path: Path, photo_paths: Sequence[Path],
                count: int = MULTI_COUNT, min_iou: float = 0.0,
                min_gain: float = MULTI_MIN_GAIN,
                width: int = RASTER_WIDTH, search_width: int = SEARCH_WIDTH,
                azimuth_step: float = 20.0,
                elevations: Sequence[float] = (-6.0, 4.0, 13.0, 22.0),
                flow_axis: Sequence[float] = FLOW_AXIS
                ) -> Tuple[List[Projector], dict]:
    """Modeli ÇOK YÖNDEN giydiren projektör kümesi.

    Tek projektör ürünün yalnız bir yüzünü kaplar; ziyaretçi modeli çevirince
    arkası çıplak PBR olarak kalıyordu. Birden fazla fotoğraf farklı
    açılardan çekildiği için birlikte çok daha fazla yüzey giydirebilirler.

    Seçim **açgözlü küme kaplama**: önce en iyi puanlı projektör alınır,
    sonra her adımda HENÜZ GİYİNMEMİŞ yüzeyin en çoğunu ekleyen aday eklenir.
    Katkısı `min_gain`'in altına düşen aday alınmaz — fotoğraf başına bir
    doku ve bir derinlik haritası maliyeti var, karşılığını vermeyen
    projektörü eklemek paketi ve GPU'yu boşuna şişirir.

    İlk sıradaki projektör aynı zamanda sayfanın açılış kamerasıdır.
    """
    # Çok yönlü arama DAHA GENİŞ bir ağ atar: her fotoğrafın kendi en iyi
    # yönleri finale kalmalı, yoksa iyi hizalanan tek bir kare bütün yerleri
    # kapatıyor ve geri kalan yönler hiç denenmiyor. Fotoğraf başına İKİ yön
    # bırakılıyor ki açılış karesi tek yönlü aramanın seçtiğiyle aynı olsun
    # (tek yön bırakılınca ilk projektör biraz daha kötü hizalanıyordu).
    scored, info, (vertices, faces) = _finalists(
        glb_path, photo_paths, width, search_width, azimuth_step, elevations,
        flow_axis, scout_keep=max(SCOUT_KEEP, 4 * len(photo_paths)),
        final_keep=max(FINAL_KEEP, 2 * len(photo_paths)), per_photo=2)
    usable = [row for row in scored if row[2].iou >= min_iou]
    info["multi"] = []
    if not usable:
        info["best"], info["iou"], info["coverage"] = None, 0.0, 0.0
        return [], info

    first = _decide([(s, a, p) for s, a, p, _m, _ar in usable])
    order = [row for row in usable if row[2] is first] or [max(usable, key=lambda r: r[0])]
    chosen = [order[0]]
    remaining = [row for row in usable if row is not chosen[0]]

    areas = chosen[0][4]
    total = float(areas.sum()) or 1.0
    covered = chosen[0][3].copy()
    # Her FOTOĞRAFTAN en fazla bir projektör. Aynı kareyi iki karşıt yönden
    # yansıtmak kaplamayı yükseltir ama ürünün ARKASINA ÖNÜNÜN aynasını
    # boyar — uydurmadır. Farklı kareler gerçekten farklı yüzleri gösterir.
    #
    # "Aynı kare" DOSYA ADIYLA değil, İÇERİKLE belirlenir. Ad üzerinden
    # ayırmak aynı fotoğrafın iki kopyasını iki ayrı kare sayıyordu: arama
    # ikisine karşıt yönler veriyor, ikincisi "arka yüzü kaplıyor" diye
    # seçiliyor ve ürünün arkasına önünün aynası boyanıyordu — kaçınmak
    # için yazılan kuralın tam olarak deldiği durum.
    identity = {}
    for path in photo_paths:
        path = Path(path)
        try:
            identity[path.name] = hashlib.sha1(path.read_bytes()).hexdigest()
        except OSError:
            identity[path.name] = path.name
    same = lambda projector: identity.get(projector.photo, projector.photo)

    used = {same(chosen[0][2])}
    remaining = [row for row in remaining if same(row[2]) not in used]
    while len(chosen) < max(1, count) and remaining:
        gains = [(float(areas[row[3] & ~covered].sum() / total), row)
                 for row in remaining]
        gain, row = max(gains, key=lambda item: item[0])
        if gain < min_gain:
            break
        chosen.append(row)
        covered |= row[3]
        used.add(same(row[2]))
        remaining = [r for r in remaining if same(r[2]) not in used]

    projectors = [row[2] for row in chosen]
    info["multi"] = [{"photo": p.photo, "iou": round(p.iou, 4),
                      "coverage": round(p.coverage, 4),
                      "direction": [round(float(v), 3) for v in p.direction]}
                     for p in projectors]
    info["total_coverage"] = round(float(areas[covered].sum() / total), 4)
    info["best"] = projectors[0].photo
    info["iou"] = projectors[0].iou
    info["coverage"] = projectors[0].coverage
    return projectors, info
