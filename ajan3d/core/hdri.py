"""Stüdyo HDRI üretici: ürün çekimi aydınlatmasını dosyaya yazar.

Neden sentetik: metalik bir yüzeyin "çelik gibi" görünmesi dokudan değil
**yansıdığı ortamdan** gelir. Düşük dinamik aralıklı (JPEG/PNG) bir ortam
görseli metalde sönük, gri bir yansıma verir; parlaklık tepeleri ancak 1.0
üstü değer taşıyan gerçek bir HDR'de oluşur. Hazır HDRI dosyaları ise 5-50 MB
ve lisanslı; sentetik üretim hem ~200 KB hem de lisans sorunsuz, hem de
internet gerektirmiyor (teslim paketi çevrimdışı açılabiliyor).

Kurulan düzen klasik üç nokta ürün aydınlatması + tepe softbox:
  anahtar ışık (sağ üst, geniş ve yumuşak), dolgu (sol, zayıf), rim/kontur
  (arka, parlaklık tepesi için sert), tepe softbox (üst sheen), ve ufuk
  çizgisinde koyulaşan bir stüdyo fonu (cyclorama) + zemin sıçraması.

Format: Radiance .hdr (RGBE). Satırlar **yeni tip RLE** ile kodlanır; düz
(sıkıştırmasız) RGBE'yi bazı okuyucular reddediyor, RLE ise evrensel.
"""
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

MAGIC = b"#?RADIANCE\n"


@dataclass(frozen=True)
class Light:
    """Yuvarlak (gaussian) ışık — geriye dönük uyumluluk için duruyor."""
    azimuth: float          # derece, yatay açı
    elevation: float        # derece, ufuktan yukarı
    radius: float           # derece, açısal yarıçap (yumuşaklık)
    intensity: float        # doğrusal parlaklık (1.0 üstü = HDR)
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class Softbox:
    """Dikdörtgen softbox — gerçek ürün çekiminin ışık kaynağı.

    Neden dikdörtgen: silindirik bir gövde, kaynağın **şeklini** uzun bir
    parlaklık şeridi olarak yansıtır. Yuvarlak bir kaynak yuvarlak ve yumuşak
    bir leke bırakır; göz bunu "CG" olarak okur. Paslanmaz çeliğin fotoğraf
    gibi durmasının asıl sebebi bu şeritlerdir.
    """
    azimuth: float          # derece, yatay açı
    elevation: float        # derece, ufuktan yukarı
    width: float            # derece, açısal genişlik
    height: float           # derece, açısal yükseklik
    intensity: float        # doğrusal parlaklık (gerçek softbox: 40-300)
    softness: float = 5.0   # derece, kenar yumuşaması
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)


# Ürün çekimi düzeni. Ölçü birimi "gerçek stüdyo": kaynaklar KÜÇÜK ve ÇOK
# PARLAK, çevre ise KOYU. Metalin metal gibi görünmesi, parlak kaynakla koyu
# çevre arasındaki kontrasttan gelir — her yeri orta parlaklıkta bir ortam
# yansıtan metal, gri boyalı bir yüzeyden ayırt edilemez.
STUDIO: Tuple[Softbox, ...] = (
    # anahtar softbox: sağ üst ön, geniş — gövdenin ana aydınlığı
    Softbox(azimuth=42, elevation=30, width=38, height=54,
            intensity=52.0, softness=8.0, color=(1.00, 0.985, 0.962)),
    # dikey şerit (kicker): sol yan, dar ve uzun — gövdedeki dikey parlaklık şeridi
    Softbox(azimuth=-74, elevation=10, width=13, height=104,
            intensity=95.0, softness=3.5, color=(0.94, 0.965, 1.00)),
    # kontur şeridi: arka, dar ve sert — cıvata başlarındaki keskin parlama
    Softbox(azimuth=161, elevation=26, width=9, height=72,
            intensity=150.0, softness=2.5, color=(1.00, 0.993, 0.975)),
    # tepe şeridi: üstten uzun bant — yatay yüzeylerde sheen
    Softbox(azimuth=4, elevation=74, width=104, height=16,
            intensity=22.0, softness=6.0),
    # zayıf dolgu: sol alt ön, gölgeleri tamamen kapatmamak için
    # dolgu 1.0'ın ALTINDA: gölgeyi açar ama "ışık kaynağı" sayılmaz —
    # geniş ve parlak bir dolgu, metali yine gri boyaya çevirirdi
    Softbox(azimuth=-28, elevation=-12, width=90, height=46,
            intensity=0.55, softness=18.0, color=(0.90, 0.94, 1.00)),
)

# Endüstriyel rig: stüdyo rigi + tavandaki iki uzun armatür sırası. Armatürler
# hem ışık verir hem de fonda görünür — holü "gerçek bir yer" yapan şey onlar.
INDUSTRIAL: Tuple[Softbox, ...] = (
    # anahtar softbox: sağ üst ön
    Softbox(azimuth=42, elevation=30, width=34, height=50,
            intensity=52.0, softness=8.0, color=(1.00, 0.985, 0.962)),
    # dikey kicker: sol yan
    Softbox(azimuth=-74, elevation=10, width=12, height=96,
            intensity=95.0, softness=3.5, color=(0.94, 0.965, 1.00)),
    # kontur şeridi: arka, sert
    Softbox(azimuth=161, elevation=26, width=9, height=70,
            intensity=150.0, softness=2.5, color=(1.00, 0.993, 0.975)),
    # tavan armatür sıraları: DAR ve uzun. Stüdyodaki 104°'lik geniş tepe
    # bandı fon olarak bakıldığında kareyi baştan sona beyaza boyuyordu;
    # gerçek bir holde tavan karanlık, armatürler ise ince çizgilerdir.
    Softbox(azimuth=-55, elevation=56, width=104, height=3.2,
            intensity=42.0, softness=1.4, color=(1.00, 0.972, 0.925)),
    Softbox(azimuth=125, elevation=62, width=104, height=3.2,
            intensity=42.0, softness=1.4, color=(1.00, 0.972, 0.925)),
    # kapı/pencere: ufka yakın soğuk açıklık, derinlik hissi verir
    Softbox(azimuth=-150, elevation=5, width=20, height=18,
            intensity=5.0, softness=6.0, color=(0.86, 0.92, 1.00)),
    # zayıf dolgu (1.0 altında: "kaynak" sayılmaz)
    Softbox(azimuth=-28, elevation=-12, width=90, height=46,
            intensity=0.55, softness=18.0, color=(0.90, 0.94, 1.00)),
)

# Fon: koyu stüdyo. Üst yarıküre hafif soğuk, zemin daha koyu — ufuk çizgisi
# metalde görünür bir "parlak üst / koyu alt" ayrımı yaratır (gerçekçilik ipucu).
# Toplam ışınım hedefi. Fotogerçekçiliğin anahtarı parlaklık DEĞİL, KONTRAST:
# ortam ne kadar ışık verdiği bakımından eskisiyle aynı kalır, ama o ışık geniş
# gri bir kubbe yerine birkaç küçük ve keskin softbox'ta toplanır. Kaynakların
# yoğunluğu bu hedefi tutturacak şekilde otomatik ölçeklenir; rigi elle
# kurcalayınca parlaklık dengesi bozulmasın diye sayısal olarak çözülüyor.
#
# 0.45 gözle seçilmedi: gerçek tarayıcıda ölçüldü. Daha yükseğinde paslanmaz
# gövde beyaz seramiğe dönüyor (metalin yansıttığı ortalama parlaklık, gövde
# rengi F0≈0.56 ile çarpılınca doygunluğa gidiyor); daha düşüğünde parça
# okunmuyor. Bu değerde gövde orta-koyu kalıp parlaklık şeritleri patlıyor.
TARGET_MEAN_RADIANCE = 0.45

SKY_TOP = (0.021, 0.023, 0.029)
SKY_HORIZON = (0.010, 0.011, 0.014)
FLOOR_NEAR = (0.016, 0.016, 0.017)
FLOOR_FAR = (0.004, 0.004, 0.005)

# --------------------------------------------------------------------------- #
# Endüstriyel hol (fabrika) fonu
# --------------------------------------------------------------------------- #
# Ürün "karanlık uzayda süzülen bir obje" gibi durmasın diye ortam artık
# SAHNENİN FONU olarak da gösteriliyor. Buradaki zorluk: aydınlatma için iyi
# olan ortam (koyu, yüksek kontrast) fon olarak bakıldığında neredeyse siyahtır.
#
# Çözüm tek dosyada iki pozlama: three.js'in `backgroundIntensity`si fonu
# ayrıca parlatır, `environmentIntensity` ise aydınlatmayı olduğu yerde tutar.
# Yani ortam metal için hâlâ koyu ve kontrastlı, göz için ise okunur bir hol.
#
# Fonun TANINIR olması için yapıya ihtiyacı var; düz bir gradyan bulanınca
# yine "hiçbir yer" gibi görünür. Bu yüzden ufuk çizgisi, zemin, duvar bandı,
# düzenli aralıklı KOLONLAR ve tavanda armatür sıraları çiziliyor.
HALL_FLOOR = (0.0115, 0.0120, 0.0132)     # beton zemin
HALL_WALL = (0.0330, 0.0352, 0.0405)      # gövde duvar bandı
HALL_UPPER = (0.0145, 0.0158, 0.0192)     # üst duvar / çatı makası
HALL_CEILING = (0.0082, 0.0086, 0.0100)
HALL_COLUMN = (0.0062, 0.0066, 0.0080)    # kolonlar duvardan koyu
HALL_COLUMNS = 8                           # hol çevresinde kolon sayısı
HALL_COLUMN_WIDTH = 7.0                    # derece
HALL_WALL_TOP = 26.0                       # duvar bandının bittiği yükseklik
HALL_GLOW = (0.055, 0.058, 0.066)          # ufka yakın hafif puslu parlama


def _directions(width: int, height: int) -> np.ndarray:
    """Eş dikdörtgen (equirectangular) her piksel için birim yön vektörü."""
    u = (np.arange(width, dtype=np.float32) + 0.5) / width
    v = (np.arange(height, dtype=np.float32) + 0.5) / height
    theta = u * 2.0 * np.pi                   # yatay açı
    phi = v * np.pi                           # 0 = tepe (+Y), pi = dip (-Y)
    sin_phi, cos_phi = np.sin(phi), np.cos(phi)
    dirs = np.empty((height, width, 3), dtype=np.float32)
    dirs[..., 0] = sin_phi[:, None] * np.cos(theta)[None, :]
    dirs[..., 1] = cos_phi[:, None]
    dirs[..., 2] = sin_phi[:, None] * np.sin(theta)[None, :]
    return dirs


def _light_vector(light: Light) -> np.ndarray:
    az, el = np.radians(light.azimuth), np.radians(light.elevation)
    return np.array([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)],
                    dtype=np.float32)


def _frame(azimuth: float, elevation: float):
    """Softbox için (ileri, sağ, yukarı) ortonormal çerçeve."""
    forward = _light_vector(Light(azimuth, elevation, 0.0, 0.0))
    world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    right = np.cross(world_up, forward)
    if float(np.linalg.norm(right)) < 1e-4:      # tam tepe/dip: başka eksen seç
        right = np.cross(np.array([1.0, 0.0, 0.0], dtype=np.float32), forward)
    right = right / np.linalg.norm(right)
    up = np.cross(forward, right)
    return forward, right, up / np.linalg.norm(up)


def _softbox_mask(dirs: np.ndarray, box: "Softbox") -> np.ndarray:
    """Dikdörtgen kaynağın 0..1 kaplama maskesi (kenarlar `softness` kadar yumuşak)."""
    forward, right, up = _frame(box.azimuth, box.elevation)
    df = dirs @ forward
    safe = np.maximum(df, 1e-6)
    ax = np.degrees(np.arctan2(dirs @ right, safe))     # yatay sapma
    ay = np.degrees(np.arctan2(dirs @ up, safe))        # dikey sapma
    soft = max(box.softness, 1e-3)
    mask = _smoothstep((box.width * 0.5 - np.abs(ax)) / soft) *         _smoothstep((box.height * 0.5 - np.abs(ay)) / soft)
    return np.where(df > 1e-3, mask, 0.0).astype(np.float32)


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _mean_radiance(image: np.ndarray) -> float:
    """Katı açıya göre ağırlıklı ortalama parlaklık (kutup şişmesi düzeltilmiş)."""
    lum = image @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    weight = np.sin(np.linspace(0.0, np.pi, lum.shape[0], dtype=np.float32))[:, None]
    return float((lum * weight).sum() / (weight.sum() * lum.shape[1]))


def _mix(a, b, t: np.ndarray) -> np.ndarray:
    """İki rengi (3'lü demet) t ağırlığıyla karıştırır; t şekli (h, w)."""
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    return a + (b - a) * t[..., None]


def _backdrop_studio(dirs: np.ndarray) -> np.ndarray:
    """Koyu cyclorama: ufukta koyulaşan stüdyo fonu."""
    y = dirs[..., 1]
    above = _smoothstep(np.clip(y, 0.0, 1.0) * 1.6)
    sky = _mix(SKY_HORIZON, SKY_TOP, above)
    below = _smoothstep(np.clip(-y, 0.0, 1.0) * 1.9)
    floor = _mix(FLOOR_NEAR, FLOOR_FAR, below)
    return np.where((y >= 0.0)[..., None], sky, floor).astype(np.float32)


def _backdrop_industrial(dirs: np.ndarray, floor_gain: float = 1.0) -> np.ndarray:
    """Fabrika holü: zemin, ufuk, duvar bandı, kolonlar, çatı.

    Yapı DÜŞEY katmanlardan (yükseklik açısına göre) ve kolonların yarattığı
    YATAY ritimden oluşuyor. Bulandırıldığında bile bu ritim ayakta kalıyor ve
    göz arkadaki boşluğu "bir hol" olarak okuyor — düz gradyanda okumuyor.
    """
    y = np.clip(dirs[..., 1], -1.0, 1.0)
    elevation = np.degrees(np.arcsin(y))
    azimuth = np.degrees(np.arctan2(dirs[..., 2], dirs[..., 0]))

    # zemin: ufka yakın hafif açılır (parlak beton), aşağı indikçe koyulaşır
    # Zemin duvardan belirgin koyu: ufuk çizgisi ancak böyle okunur. Yumuşak
    # bir geçiş bırakmak holü yine "hiçbir yer" yapıyordu.
    # `floor_gain`: zemini AYDINLATMADA koyu tutar. Sahnenin fonu artık
    # fiziksel diorama olduğu için bu ortamın tek işi aydınlatmak; zemin
    # parlatılırsa yansıyan ışık ürünü alttan yıkar ve kontrastı öldürür.
    depth = _smoothstep(np.clip(-elevation / 55.0, 0.0, 1.0))
    floor = _mix(HALL_WALL, HALL_FLOOR, depth) * 0.40 * floor_gain

    # duvar: ufuktan HALL_WALL_TOP'a kadar; üstünde çatı makası, sonra tavan
    wall_t = _smoothstep(np.clip(elevation / HALL_WALL_TOP, 0.0, 1.0))
    wall = _mix(HALL_WALL, HALL_UPPER, wall_t)
    roof_t = _smoothstep(np.clip((elevation - HALL_WALL_TOP) / 42.0, 0.0, 1.0))
    above = _mix(wall, HALL_CEILING, roof_t)

    # kolonlar: yalnızca duvar bandında, yukarı doğru silinir
    phase = np.cos(np.radians(azimuth * HALL_COLUMNS))
    edge = np.cos(np.radians(HALL_COLUMN_WIDTH * HALL_COLUMNS * 0.5))
    column = _smoothstep((phase - edge) / max(1.0 - edge, 1e-3))
    column *= 1.0 - _smoothstep(np.clip((elevation - HALL_WALL_TOP * 0.8) / 18.0,
                                        0.0, 1.0))
    above = _mix(above, HALL_COLUMN, np.clip(column, 0.0, 1.0) * 0.85)

    image = np.where((elevation >= 0.0)[..., None], above, floor)

    # ufuk pusu: zeminle duvarın birleştiği çizgide ince bir parlama. Gerçek
    # hollerde zemin ıslak/parlak olduğu için orada bir yansıma bandı olur;
    # modelin "bir yere oturduğu" hissi büyük ölçüde bu çizgiden geliyor.
    haze = np.exp(-(elevation / 3.0) ** 2)
    return (image + np.array(HALL_GLOW, dtype=np.float32) * haze[..., None] * 0.32
            ).astype(np.float32)


BACKDROPS = {"studio": _backdrop_studio, "industrial": _backdrop_industrial}


def render_environment(width: int = 1024, lights: Sequence[Light] = STUDIO,
                       target_mean: Optional[float] = TARGET_MEAN_RADIANCE,
                       backdrop: str = "studio") -> np.ndarray:
    """(height, width, 3) doğrusal RGB ışık alanı üretir. Değerler 1.0'ı aşar."""
    height = max(2, width // 2)
    dirs = _directions(width, height)

    # --- fon ---
    image = BACKDROPS.get(backdrop, _backdrop_studio)(dirs)

    # --- ışıklar (arka plandan ayrı toplanır: ölçeklenecek olan bu) ---
    emitters = np.zeros_like(image)
    for light in lights:
        if isinstance(light, Softbox):
            falloff = _softbox_mask(dirs, light)
        else:                                    # eski yuvarlak kaynak
            vector = _light_vector(light)
            angle = np.degrees(np.arccos(np.clip(dirs @ vector, -1.0, 1.0)))
            falloff = _smoothstep(1.0 - (angle - light.radius * 0.45) /
                                  max(light.radius, 1e-3))
        contribution = falloff[..., None] * np.array(light.color, dtype=np.float32)
        emitters += contribution * light.intensity

    if target_mean is not None:
        # Kaynakları, toplam ışınım hedefe oturacak şekilde ölçekle. Böylece
        # rigin ŞEKLİ (küçük, keskin, yüksek kontrast) korunurken sahnenin
        # genel parlaklığı sabit kalır — pozlama yeniden ayarlanmak zorunda
        # kalmaz ve metal yanmaz.
        mean_bg = _mean_radiance(image)
        mean_em = _mean_radiance(emitters)
        if mean_em > 1e-6:
            emitters *= max(0.0, (target_mean - mean_bg) / mean_em)

    return np.maximum(image + emitters, 0.0)


def measure(image: np.ndarray) -> dict:
    """Ortamın fotogerçekçilik ölçütleri.

    Metalin fotoğraf gibi durması için gereken: kaynaklar **küçük ve parlak**,
    çevre **koyu**. Bu sayılar o iddiayı ölçülebilir kılar ve testle kilitlenir.
    """
    lum = image @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    solid = np.sin(np.linspace(0.0, np.pi, lum.shape[0], dtype=np.float32))[:, None]
    weight = np.broadcast_to(solid, lum.shape)
    total = float(weight.sum())
    return {
        "mean": _mean_radiance(image),
        "peak": float(lum.max()),
        "median": float(np.median(lum)),
        # katı açıya göre ağırlıklı: kutuplardaki şişme sayıyı bozmasın
        "emitter_fraction": float((weight * (lum > 1.0)).sum() / total),
        "dark_fraction": float((weight * (lum < 0.05)).sum() / total),
    }


# --------------------------------------------------------------------------- #
# Radiance RGBE yazma
# --------------------------------------------------------------------------- #

def to_rgbe(rgb: np.ndarray) -> np.ndarray:
    """Doğrusal float RGB -> RGBE (paylaşılan üs) bayt dizisi."""
    peak = rgb.max(axis=2)
    mantissa, exponent = np.frexp(peak)        # peak = mantissa * 2**exponent
    scale = np.where(peak > 1e-32, mantissa * 256.0 / np.maximum(peak, 1e-32), 0.0)
    out = np.zeros(rgb.shape[:2] + (4,), dtype=np.uint8)
    out[..., :3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    out[..., 3] = np.where(peak > 1e-32, np.clip(exponent + 128, 0, 255), 0).astype(np.uint8)
    return out


def _rle_component(values: np.ndarray) -> bytes:
    """Bir tarama satırının tek bileşenini yeni tip Radiance RLE ile kodlar.

    Kural: sayaç > 128 ise sonraki baytın (sayaç-128) kez tekrarı (en çok 127);
    sayaç <= 128 ise sonraki `sayaç` bayt birebir kopyalanır (en çok 128).
    """
    out = bytearray()
    data = values.tobytes()
    n = len(data)
    i = 0
    while i < n:
        run = 1
        while i + run < n and data[i + run] == data[i] and run < 127:
            run += 1
        if run >= 4:
            out.append(128 + run)
            out.append(data[i])
            i += run
            continue
        # Birebir kopya: 4'lü bir tekrar başlayana ya da 128 bayta kadar topla
        start = i
        while i < n and (i - start) < 128:
            if i + 3 < n and data[i] == data[i + 1] == data[i + 2] == data[i + 3]:
                break
            i += 1
        length = i - start
        out.append(length)
        out += data[start:i]
    return bytes(out)


def encode_hdr(rgb: np.ndarray) -> bytes:
    """Doğrusal float RGB görüntüsünü Radiance .hdr baytlarına çevirir."""
    height, width = rgb.shape[:2]
    if not (8 <= width <= 0x7FFF):
        raise ValueError(f"RLE için satır genişliği 8..32767 olmalı (verilen {width})")
    rgbe = to_rgbe(np.asarray(rgb, dtype=np.float32))

    out = bytearray(MAGIC)
    out += b"SOFTWARE=ajan3d\n"
    out += b"FORMAT=32-bit_rle_rgbe\n\n"
    out += f"-Y {height} +X {width}\n".encode("ascii")
    for row in range(height):
        out += struct.pack(">BBH", 2, 2, width)        # yeni tip RLE satır başlığı
        for component in range(4):
            out += _rle_component(np.ascontiguousarray(rgbe[row, :, component]))
    return bytes(out)


def decode_hdr(data: bytes) -> np.ndarray:
    """Doğrulama için RGBE RLE çözücü. (height, width, 3) float döner."""
    if not data.startswith(b"#?"):
        raise ValueError("Radiance imzası yok")
    index = data.index(b"\n\n") + 2
    end = data.index(b"\n", index)
    parts = data[index:end].split()
    height, width = int(parts[1]), int(parts[3])
    pos = end + 1

    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    for row in range(height):
        marker, marker2, line_width = struct.unpack(">BBH", data[pos:pos + 4])
        if marker != 2 or marker2 != 2 or line_width != width:
            raise ValueError(f"satır {row}: RLE başlığı bozuk")
        pos += 4
        for component in range(4):
            col = 0
            while col < width:
                count = data[pos]
                pos += 1
                if count > 128:
                    rgbe[row, col:col + count - 128, component] = data[pos]
                    col += count - 128
                    pos += 1
                else:
                    rgbe[row, col:col + count, component] = np.frombuffer(
                        data[pos:pos + count], dtype=np.uint8)
                    col += count
                    pos += count
            if col != width:
                raise ValueError(f"satır {row} bileşen {component}: {col} != {width}")

    exponent = rgbe[..., 3].astype(np.int32) - 136      # 128 + 8 (mantis kaydırması)
    scale = np.where(rgbe[..., 3] > 0, np.ldexp(1.0, exponent), 0.0)
    return rgbe[..., :3].astype(np.float32) * scale[..., None]


def write_studio_hdr(path: Path, width: Optional[int] = None,
                     lights: Optional[Sequence[Light]] = None,
                     target_mean: Optional[float] = TARGET_MEAN_RADIANCE,
                     backdrop: str = "industrial") -> Path:
    """Ortam HDRI'sını `path` konumuna yazar ve yolu döner.

    Varsayılan artık **endüstriyel hol**: sayfa ortamı yalnız aydınlatma için
    değil, arka plan olarak da kullanıyor.
    """
    width = width or 1024
    if lights is None:
        lights = INDUSTRIAL if backdrop == "industrial" else STUDIO
    image = render_environment(width, lights, target_mean, backdrop)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_hdr(image))
    return path
