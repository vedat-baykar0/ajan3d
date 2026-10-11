"""Kamera hareket yollari.

Tum yollar bir tam sinus/kosinus dongusu oldugu icin video kusursuz loop olur.
Donen diziler birim derinlik icin: dx, dy = piksel oteleme, dz = olcek degisimi.
"""

from __future__ import annotations

import numpy as np

MOTIONS = ("zoom", "horizontal", "vertical", "orbit", "dolly", "swing", "zigzag")


def camera_path(
    motion: str = "orbit",
    frames: int = 120,
    strength: float = 1.0,
    width: int = 1280,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(dx, dy, dz) dizilerini uret. dx/dy piksel, dz olcek carpani farki."""
    if motion not in MOTIONS:
        raise ValueError(f"Bilinmeyen hareket: {motion!r}. Secenekler: {', '.join(MOTIONS)}")

    amp = 0.055 * strength * width  # birim derinlik icin yatay parallax genligi
    zamp = 0.22 * strength          # birim derinlik icin zoom genligi
    t = np.linspace(0.0, 2.0 * np.pi, frames, endpoint=False)
    zero = np.zeros_like(t)
    ramp = (1.0 - np.cos(t)) * 0.5  # 0 -> 1 -> 0 yumusak gidis-donus

    if motion == "zoom":
        return zero, zero, zamp * ramp
    if motion == "horizontal":
        return amp * np.sin(t), zero, zero
    if motion == "vertical":
        return zero, amp * 0.8 * np.sin(t), zero
    if motion == "orbit":
        return amp * np.sin(t), amp * 0.55 * np.cos(t), zero
    if motion == "dolly":
        return amp * 0.45 * np.sin(t), zero, zamp * ramp
    if motion == "swing":
        return amp * np.sin(t), amp * 0.25 * np.sin(2 * t), zamp * 0.5 * ramp
    # zigzag
    return amp * np.sin(t), amp * 0.5 * np.sin(3 * t), zamp * 0.3 * ramp
