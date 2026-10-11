"""On plan / arka plan ayrimi (segmentation).

Iki yol var:
  * rembg  : kurulu ise U2-Net ile kesin nesne maskesi (en temiz sonuc)
  * depth  : derinlik haritasi uzerinde Otsu esigi (ek bagimlilik gerektirmez)
"""

from __future__ import annotations

import numpy as np


def _largest_components(binary: np.ndarray, keep_ratio: float = 0.15) -> np.ndarray:
    """Kucuk gurultu adalarini at; en buyuk parcanin %15'inden kucukleri sil."""
    import cv2

    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    areas = stats[1:, cv2.CC_STAT_AREA]
    biggest = areas.max()
    out = np.zeros_like(binary)
    for i, area in enumerate(areas, start=1):
        if area >= biggest * keep_ratio:
            out[labels == i] = 255
    return out


def depth_mask(depth: np.ndarray, threshold: float | None = None, feather: int = 11) -> np.ndarray:
    """Derinlik haritasindan on plan maskesi (float32 0..1, yumusak kenar)."""
    import cv2

    d8 = (np.clip(depth, 0, 1) * 255).astype(np.uint8)
    if threshold is None:
        _, binary = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(d8, int(threshold * 255), 255, cv2.THRESH_BINARY)

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)
    binary = _largest_components(binary)

    if feather > 0:
        f = feather | 1  # tek sayi olmali
        soft = cv2.GaussianBlur(binary.astype(np.float32) / 255.0, (f, f), 0)
    else:
        soft = binary.astype(np.float32) / 255.0
    return np.clip(soft, 0.0, 1.0)


def rembg_mask(image_rgb: np.ndarray, feather: int = 5) -> np.ndarray | None:
    """rembg kuruluysa alfa maskesi dondurur, degilse None."""
    try:
        from rembg import remove
    except Exception:
        return None

    import cv2
    from PIL import Image

    cut = remove(Image.fromarray(image_rgb))
    alpha = np.array(cut.convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    if feather > 0:
        f = feather | 1
        alpha = cv2.GaussianBlur(alpha, (f, f), 0)
    return np.clip(alpha, 0.0, 1.0)


def foreground_mask(
    image_rgb: np.ndarray,
    depth: np.ndarray,
    method: str = "auto",
    threshold: float | None = None,
) -> tuple[np.ndarray, str]:
    """On plan maskesi uret. Donen: (maske 0..1, kullanilan yontem)."""
    if method in ("auto", "rembg"):
        m = rembg_mask(image_rgb)
        if m is not None:
            return m, "rembg"
        if method == "rembg":
            print("[segment] rembg kurulu degil, derinlik esigine dusuluyor.")
    return depth_mask(depth, threshold=threshold), "depth"
