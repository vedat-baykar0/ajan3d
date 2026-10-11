"""Katmanli derinlik render'i (layered depth image warping).

Mantik:
  1. Derinlik haritasi N bantta "sogan zari" gibi katmanlara ayrilir.
     Katman i = tum goruntu, alfa = derinligin edges[i] esigini gecme orani.
  2. En arkadaki katman, on plan maskesi inpaint edilerek deliksiz hale getirilir
     (ozne kayinca arkasinda siyah bosluk kalmasin).
  3. Her kare icin katmanlar kendi derinligi oraninda otelenir/olceklenir ve
     arkadan one dogru ust uste bindirilir.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Layer:
    rgb: np.ndarray    # uint8 HxWx3
    alpha: np.ndarray  # uint8 HxW (0 = seffaf)
    depth: float       # 0..1 temsili derinlik (1 = yakin)


def inpaint_background(rgb: np.ndarray, fg_mask: np.ndarray, radius: int = 7, dilate: int = 9) -> np.ndarray:
    """On plani silip arkasini doldurarak 'arka plan plakasi' uret."""
    import cv2

    hard = (fg_mask > 0.35).astype(np.uint8) * 255
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate))
        hard = cv2.dilate(hard, k)
    if hard.max() == 0:
        return rgb.copy()
    plate = cv2.inpaint(rgb, hard, radius, cv2.INPAINT_TELEA)
    # Inpaint izlerini yumusat; sadece doldurulan bolgede harmanla
    blurred = cv2.GaussianBlur(plate, (0, 0), 3)
    soft = cv2.GaussianBlur((hard > 0).astype(np.float32), (0, 0), 6)[..., None]
    return np.clip(plate * (1 - soft) + blurred * soft, 0, 255).astype(np.uint8)


def build_layers(
    rgb: np.ndarray,
    depth: np.ndarray,
    n_layers: int = 16,
    fg_mask: np.ndarray | None = None,
    feather: float = 0.006,
    inpaint_radius: int = 7,
) -> list[Layer]:
    """Goruntuyu derinlik bantlarina ayir; en arkaya inpaint edilmis plaka koy."""
    import cv2

    n_layers = max(2, int(n_layers))
    # Bantlari kantillere gore bol: her katmanda benzer miktarda piksel olsun.
    qs = np.linspace(0.0, 1.0, n_layers + 1)
    edges = np.quantile(depth, qs).astype(np.float32)
    # Ayni degerin tekrarlanmasini onle (duz zeminli fotograflar)
    for i in range(1, len(edges)):
        edges[i] = max(edges[i], edges[i - 1] + 1e-3)

    plate = inpaint_background(rgb, fg_mask if fg_mask is not None else depth, radius=inpaint_radius)
    layers = [Layer(rgb=plate, alpha=np.full(depth.shape, 255, np.uint8), depth=float(edges[0]))]

    for i in range(1, n_layers):
        e = float(edges[i])
        # Gecis genisligi bant genisligi kadar olsun: bantlar ust uste binerse
        # ayni kenar birkac kez farkli kaymayla cizilir ve hayalet olusur.
        band = max(float(edges[i + 1] - edges[i]), feather)
        a = np.clip((depth - e) / band, 0.0, 1.0)
        if a.max() < 0.02:
            continue
        layers.append(
            Layer(
                rgb=rgb,
                alpha=(a * 255).astype(np.uint8),
                depth=float((edges[i] + edges[i + 1]) * 0.5),
            )
        )
    # Hafif alfa yumusatmasi: bant gecislerindeki sert cizgileri kirar
    for L in layers[1:]:
        L.alpha = cv2.GaussianBlur(L.alpha, (0, 0), 1.2)
    return layers


def render_frame(
    layers: list[Layer],
    dx: float,
    dy: float,
    dz: float,
    focus: float = 0.5,
    overscan: float = 0.07,
    out_size: tuple[int, int] | None = None,
) -> np.ndarray:
    """Tek kare uret. focus = sabit kalacak derinlik duzlemi (0 arka, 1 on)."""
    import cv2

    h, w = layers[0].alpha.shape
    acc: np.ndarray | None = None

    for L in layers:
        p = L.depth - focus  # >0 on plan (cok hareket eder), <0 arka plan
        s = 1.0 + dz * p
        tx = dx * p + (1.0 - s) * w * 0.5
        ty = dy * p + (1.0 - s) * h * 0.5
        m = np.array([[s, 0.0, tx], [0.0, s, ty]], np.float32)

        if acc is None:
            acc = cv2.warpAffine(
                L.rgb, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
            ).astype(np.float32)
            continue

        a = cv2.warpAffine(
            L.alpha, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0
        )
        if a.max() == 0:  # bu katman kadrajin tamamen disina cikti
            continue
        warped = cv2.warpAffine(
            L.rgb, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        ).astype(np.float32)
        af = a.astype(np.float32)[..., None] * (1.0 / 255.0)
        # acc += a * (warped - acc)  -- yerinde islem, kare basina ~2 gecis tasarrufu
        warped -= acc
        warped *= af
        acc += warped

    frame = acc
    if overscan > 0:
        mx, my = int(w * overscan), int(h * overscan)
        frame = frame[my : h - my, mx : w - mx]
    frame = np.clip(frame, 0, 255).astype(np.uint8)
    if out_size is not None and (frame.shape[1], frame.shape[0]) != out_size:
        frame = cv2.resize(frame, out_size, interpolation=cv2.INTER_LANCZOS4)
    return frame
