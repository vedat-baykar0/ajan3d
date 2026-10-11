"""Derinlik haritasi cikarimi (Depth-Anything V2 / MiDaS-DPT)."""

from __future__ import annotations

import numpy as np
from PIL import Image

# Kisa ad -> HuggingFace model kimligi
MODEL_IDS = {
    "small": "depth-anything/Depth-Anything-V2-Small-hf",
    "base": "depth-anything/Depth-Anything-V2-Base-hf",
    "large": "depth-anything/Depth-Anything-V2-Large-hf",
    "midas": "Intel/dpt-hybrid-midas",
    "midas-large": "Intel/dpt-large",
}


def pick_device(requested: str | None = None) -> str:
    """Istenen cihazi dogrula; 'auto' ise CUDA varsa onu sec."""
    import torch

    if requested and requested != "auto":
        if requested.startswith("cuda") and not torch.cuda.is_available():
            print("[depth] CUDA bulunamadi, CPU'ya dusuluyor.")
            return "cpu"
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


def normalize(depth: np.ndarray, lo_pct: float = 1.0, hi_pct: float = 99.0) -> np.ndarray:
    """Derinligi 0..1 arasina tasi (1 = kameraya en yakin). Uc degerleri kirp."""
    d = depth.astype(np.float32)
    lo, hi = np.percentile(d, [lo_pct, hi_pct])
    if hi - lo < 1e-6:
        return np.zeros_like(d)
    return np.clip((d - lo) / (hi - lo), 0.0, 1.0)


def refine(depth: np.ndarray, strength: int = 7) -> np.ndarray:
    """Kenar koruyarak derinlik gurultusunu temizle (parallax halo'sunu azaltir)."""
    import cv2

    if strength <= 0:
        return depth
    d = np.ascontiguousarray(depth, dtype=np.float32)
    d = cv2.bilateralFilter(d, d=strength, sigmaColor=0.08, sigmaSpace=strength * 2)
    return np.clip(d, 0.0, 1.0)


class DepthEstimator:
    """Tek fotograf icin tek seferlik derinlik cikarimi yapar (model cache'lenir)."""

    def __init__(self, model: str = "small", device: str = "auto"):
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self.model_id = MODEL_IDS.get(model, model)
        self.device = pick_device(device)
        print(f"[depth] Model yukleniyor: {self.model_id} ({self.device})")
        self.processor = AutoImageProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForDepthEstimation.from_pretrained(self.model_id)
        self.model.to(self.device).eval()
        self._torch = torch

    def predict(self, image: Image.Image) -> np.ndarray:
        """RGB PIL goruntusu -> float32 derinlik haritasi (HxW, 0..1, 1 = yakin)."""
        torch = self._torch
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.inference_mode():
            out = self.model(**inputs)
        pred = out.predicted_depth
        if pred.ndim == 3:
            pred = pred.unsqueeze(1)
        pred = torch.nn.functional.interpolate(
            pred.float(), size=image.size[::-1], mode="bicubic", align_corners=False
        )
        return normalize(pred[0, 0].cpu().numpy())
