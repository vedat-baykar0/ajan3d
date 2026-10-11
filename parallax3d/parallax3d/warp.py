"""Piksel bazli ters warp render'i (varsayilan motor).

Katmanli yontemde her bant tek parca kaydigi icin nesne kenarlarinda hayalet/
basamak izi kalir. Burada her piksel kendi derinligi kadar kayar:

  ileri donusum :  X = cx + (x-cx)*(1+dz*p) + dx*p        (p = derinlik - focus)
  ters donusum  :  sabit nokta iterasyonu ile x'i cozeriz

Iterasyon yakinsamazsa o piksel "disocclusion" (ozne kayinca acilan bosluk)
demektir; orasi inpaint'li arka plan plakasindan doldurulur.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .render import inpaint_background


@dataclass
class Scene:
    rgb: np.ndarray        # uint8 HxWx3 orijinal
    depth: np.ndarray      # float32 HxW 0..1
    plate: np.ndarray      # uint8 HxWx3 inpaint'li arka plan
    depth_bg: np.ndarray   # float32 HxW arka planin derinligi


def build_scene(
    rgb: np.ndarray,
    depth: np.ndarray,
    fg_mask: np.ndarray | None = None,
    inpaint_radius: int = 7,
) -> Scene:
    """Arka plan plakasini ve arka plan derinligini bir kez hazirla."""
    import cv2

    if fg_mask is None:  # maske yoksa en yakin %25'i on plan say
        fg_mask = (depth > np.quantile(depth, 0.75)).astype(np.float32)

    plate = inpaint_background(rgb, fg_mask, radius=inpaint_radius)

    hard = (fg_mask > 0.35).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    hard = cv2.dilate(hard, k)
    d8 = (np.clip(depth, 0, 1) * 255).astype(np.uint8)
    depth_bg = cv2.inpaint(d8, hard, inpaint_radius, cv2.INPAINT_TELEA).astype(np.float32) / 255.0
    depth_bg = cv2.GaussianBlur(depth_bg, (0, 0), 4.0)
    # Arka plan hicbir yerde on plandan one gecmesin
    depth_bg = np.minimum(depth_bg, depth).astype(np.float32)
    return Scene(rgb=rgb, depth=depth.astype(np.float32), plate=plate, depth_bg=depth_bg)


def _grid(h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    return np.meshgrid(xs, ys)


def inverse_maps(
    depth: np.ndarray, dx: float, dy: float, dz: float, focus: float, iters: int = 4
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hedef -> kaynak koordinat haritalari ve yakinsama artigi (residual)."""
    import cv2

    h, w = depth.shape
    X, Y = _grid(h, w)
    cx, cy = (w - 1) * 0.5, (h - 1) * 0.5

    p = depth - focus  # ilk tahmin: hedef pikselin derinligi
    mx, my = X, Y
    for _ in range(max(1, iters)):
        s = 1.0 + dz * p
        mx = (cx + (X - cx - dx * p) / s).astype(np.float32)
        my = (cy + (Y - cy - dy * p) / s).astype(np.float32)
        p = cv2.remap(depth, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) - focus

    # Bulunan kaynagi ileri tasiyip hedefe donuyor mu diye bak
    s = 1.0 + dz * p
    fx = cx + (mx - cx) * s + dx * p
    fy = cy + (my - cy) * s + dy * p
    residual = np.abs(fx - X) + np.abs(fy - Y)
    return mx, my, residual.astype(np.float32)


def render_frame(
    scene: Scene,
    dx: float,
    dy: float,
    dz: float,
    focus: float = 0.5,
    overscan: float = 0.07,
    out_size: tuple[int, int] | None = None,
    hole_softness: float = 1.8,
) -> np.ndarray:
    import cv2

    h, w = scene.depth.shape
    mx, my, residual = inverse_maps(scene.depth, dx, dy, dz, focus)
    fg = cv2.remap(scene.rgb, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    bx, by, _ = inverse_maps(scene.depth_bg, dx, dy, dz, focus, iters=2)
    bg = cv2.remap(scene.plate, bx, by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    # residual buyukse ozne kaymis, arkasi acilmis -> plakadan doldur
    a = np.clip((residual - 0.6) / max(hole_softness, 1e-3), 0.0, 1.0)
    a = cv2.GaussianBlur(a, (0, 0), 1.5)[..., None]
    frame = bg.astype(np.float32) * a + fg.astype(np.float32) * (1.0 - a)

    if overscan > 0:
        mx_, my_ = int(w * overscan), int(h * overscan)
        frame = frame[my_ : h - my_, mx_ : w - mx_]
    frame = np.clip(frame, 0, 255).astype(np.uint8)
    if out_size is not None and (frame.shape[1], frame.shape[0]) != out_size:
        frame = cv2.resize(frame, out_size, interpolation=cv2.INTER_LANCZOS4)
    return frame
