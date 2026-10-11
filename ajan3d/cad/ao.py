"""Ortam ışığı gölgelemesi (AO) — girinti ve dip kararmalarını geometriden pişirir.

**Neden gerekli.** Modelin "CG" durmasının en belirgin sebebi girintilerin
kararmamasıdır: flanş–gövde birleşimi, cıvata yuvası, altıgen başın dibi,
diş kökü... Gerçek nesnede oralar daha az ışık görür. Stüdyo HDRI her yönden
eşit ışık verdiği için bu kararma kendiliğinden oluşmaz, ayrıca hesaplanması
gerekir.

**Neden ışın izleme değil.** Kaba kuvvet AO her köşeden yarıküreye yüzlerce
ışın atar; 66.000 köşe × 24 ışın saf Python/numpy ışın motorunda dakikalar
sürer ve zincirin tamamı (CAD montajı 1 sn) bunun yanında kaybolur.

**Kullanılan yöntem — boşluk doluluk oranı.** Parça zaten **kapalı bir katı**
olduğu için voksel ızgarasına doldurulabiliyor. Bir yüzey noktasının çevresine
bakıldığında:

| yüzey | çevredeki katı oranı | AO |
|---|---|---|
| düzlem | 0,50 | 1,00 (kararma yok) |
| 90° iç köşe | 0,75 | 0,50 |
| dar oluk içi | → 1,00 | taban değer |
| dış kenar/pah | 0,25 | 1,00 (kırpılır) |

Yani **AO = 1 − 2·(doluluk − 0,5)**. Bu, ışın izlemenin analitik karşılığıdır
(kapalı yarıküre oranı) ve gauss bulanıklığı ile tek seferde bütün ızgaraya
uygulanır — maliyet köşe sayısından bağımsızdır.

**İki ölçek.** Tek yarıçap ya yalnız diş kökünü ya yalnız gövde dibini görür.
İnce yarıçap (parçanın %3,5'i) keskin temas kararmasını, geniş yarıçap (%9)
büyük boşlukların yumuşak gölgesini verir; ikisi ağırlıklı toplanır.

**Yalnızca parçanın KENDİ gölgesi.** Montajın tamamından pişirilseydi doku
örneklenmiş parçalarda (4 cıvata tek mesh'i paylaşıyor) yanlış olurdu ve
patlatma animasyonunda parçaların üzerinde komşusunun hayaleti kalırdı.
Kendi gölgesi hem örnekleme güvenli hem patlatmada doğru.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

import numpy as np

# Yarıçaplar parçanın KARAKTERİSTİK ölçüsünün (kutu hacminin küp kökü)
# oranıdır; ağırlıkları toplamı 1. En uzun kenara bağlamak uzun ince
# parçalarda yanlış: M16×96 cıvatada 0,035·96 = 3,4 mm yarıçap 2 mm'lik diş
# hatvesini bulanıklaştırıp yok ediyordu.
RADII: Tuple[float, ...] = (0.035, 0.090)
WEIGHTS: Tuple[float, ...] = (0.62, 0.38)
# Adım, en uzun kenardan DEĞİL hacimden seçilir. Uzun ince bir cıvatada
# "en uzun kenar / N" kuralı adımı 1,5 mm yapıyor ve 1 mm derinliğindeki diş
# ızgaranın altında kalıyordu; hücre sayısını sabitlemek ince parçalara
# hak ettikleri çözünürlüğü veriyor, maliyeti ise sabit tutuyor.
GRID = 220_000       # parça başına hedef voksel sayısı
# Analitik değer 1.0. Üstü "doğru" değil ama GEREKLİ: pişirilen AO yalnız
# parçanın KENDİ gölgesidir (bkz. modül başlığı), parçalar arası temas
# kararmasını hiç görmez. Gövde ile kapağın birleştiği çizgi, somunun
# oturduğu yüzey, pabucun altı — fotoğrafta en koyu yerler bunlar ve
# modelde hiç yoktu. Kendi gölgesini abartmak o eksiğin yerini tutuyor;
# ürün ışıkla buluştuğunda "ağır çelik" hissi oradan geliyor.
STRENGTH = 1.48
FLOOR = 0.22         # en karanlık AO; 0 yapmak dipleri simsiyah bırakır


def _planar_level(sigma_voxels: float) -> float:
    """Düz bir yüzeyde ölçülen doluluk oranı (0,5 değil!).

    Vokselleştirme yüzeyi KESEN hücreleri de dolu sayıyor; katı bu yüzden
    yarım voksel kadar şişiyor ve düz bir yüzeyde bile oran 0,5'in üstüne
    çıkıyor (ölçüldü: 60 mm küpün düz yüzünde AO 0,855 — oysa düzlemde hiç
    kararma olmamalı). Kaymanın büyüklüğü analitik olarak bilinebiliyor:
    yarım vokselin, bulanıklığın standart sapmasına oranı. Referans değer
    0,5 yerine bu alınıyor, böylece düz yüzey tam olarak 1,0'a oturuyor ve
    dik iç köşe yine analitik 0,5 değerini veriyor.
    """
    return 0.5 * (1.0 + math.erf(0.5 / (max(sigma_voxels, 1e-6) * math.sqrt(2.0))))


def _occupancy(mesh, grid: int):
    """(doluluk, yerel->indis dönüşümü, adım, yerel orijin). Olmazsa None."""
    extents = np.asarray(mesh.extents, dtype=np.float64)
    longest = float(extents.max()) if extents.size else 0.0
    if longest <= 0.0:
        return None
    volume = float(np.prod(np.maximum(extents, longest * 1e-3)))
    pitch = (volume / max(8_000, int(grid))) ** (1.0 / 3.0)
    # Alt sınır maliyeti, üst sınır kaliteyi korur (yassı contada hacim
    # kuralı adımı parçadan büyük yapardı).
    pitch = min(max(pitch, longest / 160.0), longest / 12.0)
    # Izgara dünya orijinine göre kurulur (trimesh köşeleri `round(v/pitch)`
    # ile yerleştiriyor), yani parçanın montajdaki konumu ızgaranın FAZINI
    # kaydırıyor ve aynı parça başka yerde başka AO alıyordu. Parça kendi
    # sınır kutusunun köşesine taşınarak pişiriliyor: sonuç yalnız geometriye
    # bağlı, konuma değil. Örneklenen parçalarda (4 cıvata, tek mesh) bunun
    # tutması şart.
    origin = np.asarray(mesh.bounds[0], dtype=np.float64)
    try:
        local = mesh.copy()
        local.apply_translation(-origin)
        voxel = local.voxelized(pitch=pitch).fill()
        matrix = np.asarray(voxel.matrix, dtype=bool)
        transform = np.asarray(voxel.transform, dtype=np.float64)
    except Exception:
        return None
    if matrix.ndim != 3 or min(matrix.shape) < 2 or not matrix.any():
        return None
    try:
        inverse = np.linalg.inv(transform)
    except np.linalg.LinAlgError:
        return None
    return matrix, inverse, pitch, origin


def bake(mesh, points: Sequence[Sequence[float]], *,
         grid: Optional[int] = None, radii: Optional[Sequence[float]] = None,
         weights: Optional[Sequence[float]] = None,
         strength: Optional[float] = None,
         floor: Optional[float] = None) -> Optional[np.ndarray]:
    """`points` (parça yerel mm) için AO değerleri [floor..1]; hesaplanamazsa None.

    Dönen dizi `points` ile aynı uzunluktadır. Nokta kümesi serbesttir: glTF
    yazıcısı açı bölünmüş köşeleri verir, test kodu istediği noktayı sorar.

    Varsayılanlar `None` ve modül sabitlerinden ÇAĞRI ANINDA okunuyor; imzaya
    yazılsalardı tanım anında bağlanır ve `ao.GRID`'i sonradan değiştirmek
    hiçbir işe yaramazdı (test takımında yaşandı: ızgara küçültüldü, süre
    hiç değişmedi).
    """
    grid = GRID if grid is None else grid
    radii = RADII if radii is None else radii
    weights = WEIGHTS if weights is None else weights
    strength = STRENGTH if strength is None else strength
    floor = FLOOR if floor is None else floor

    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        return None
    occupancy = _occupancy(mesh, grid)
    if occupancy is None:
        return None
    matrix, inverse, pitch, origin = occupancy

    from scipy import ndimage

    # Dünya -> voksel indis koordinatı (ndimage (i, j, k) sırası bekler).
    homogeneous = np.hstack([points - origin, np.ones((len(points), 1))])
    index = (homogeneous @ inverse.T)[:, :3].T          # (3, N)

    solid = matrix.astype(np.float32)
    extents = np.maximum(np.asarray(mesh.extents, dtype=np.float64), 1e-9)
    scale = float(np.prod(extents) ** (1.0 / 3.0))
    occlusion = np.zeros(len(points), dtype=np.float64)
    total = 0.0
    for radius, weight in zip(radii, weights):
        sigma = (radius * scale) / pitch
        if sigma < 1.0:            # ızgara bu ölçeği çözemiyor, atla
            continue
        # mode="constant": ızgaranın DIŞI boşluktur. Varsayılan "reflect"
        # parçayı kendi aynasıyla çevreler ve dışbükey yüzeyleri karartır.
        blurred = ndimage.gaussian_filter(solid, sigma=sigma, mode="constant", cval=0.0)
        fraction = ndimage.map_coordinates(blurred, index, order=1, mode="nearest")
        occlusion += weight * np.clip((fraction - _planar_level(sigma)) * 2.0, 0.0, 1.0)
        total += weight
    if total <= 0.0:
        return None
    occlusion /= total
    return np.clip(1.0 - strength * occlusion, floor, 1.0).astype(np.float32)


def to_color_bytes(values: np.ndarray) -> np.ndarray:
    """AO -> glTF COLOR_0 (VEC4, normalize edilmiş ubyte).

    Neden COLOR_0: glTF'nin standart köşe niteliği budur, doğrulayıcıdan
    geçer, Draco sıkıştırır ve her yükleyici okur. Sayfa onu yükleyince
    kendi `ao` niteliğine çeviriyor (şiddeti ayarlanabilsin diye).
    VEC3/ubyte 3 bayt eder; glTF köşe niteliklerinde 4 bayt hizalama şartı
    olduğu için VEC4 yazılıyor (alfa 255, hiçbir şeyi değiştirmez).
    """
    gray = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    out = np.full((len(gray), 4), 255, dtype=np.uint8)
    out[:, :3] = np.round(gray * 255.0)[:, None]
    return out
