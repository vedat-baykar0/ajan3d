"""Kare dizisini .mp4 / .gif olarak yaz."""

from __future__ import annotations

import os
import subprocess

import numpy as np


def _even(x: int) -> int:
    return x if x % 2 == 0 else x - 1


def _fit(w: int, h: int, max_size: int) -> tuple[int, int]:
    """Uzun kenari max_size'a sigdir (buyutme yok)."""
    if max(w, h) <= max_size:
        return w, h
    scale = max_size / max(w, h)
    return max(2, int(round(w * scale))), max(2, int(round(h * scale)))


def write_mp4(frames: list[np.ndarray], path: str, fps: int = 30, quality: int = 8) -> str:
    """H.264 mp4 yaz (her yerde oynar: yuv420p + faststart)."""
    import imageio.v2 as imageio

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    h, w = frames[0].shape[:2]
    ew, eh = _even(w), _even(h)
    writer = imageio.get_writer(
        path,
        fps=fps,
        codec="libx264",
        quality=quality,
        pixelformat="yuv420p",
        macro_block_size=2,
        ffmpeg_params=["-movflags", "+faststart"],
    )
    try:
        for f in frames:
            writer.append_data(f[:eh, :ew])
    finally:
        writer.close()
    return path


def _gif_via_ffmpeg(src_mp4: str, path: str, fps: int, size: tuple[int, int]) -> bool:
    """ffmpeg palettegen/paletteuse: PIL'e gore cok daha kucuk ve temiz GIF."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        exe = get_ffmpeg_exe()
    except Exception:
        return False

    w, h = size
    vf = (
        f"fps={fps},scale={w}:{h}:flags=lanczos,split[a][b];"
        f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3"
    )
    cmd = [exe, "-y", "-v", "error", "-i", src_mp4, "-filter_complex", vf, "-loop", "0", path]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return os.path.exists(path)
    except Exception as exc:
        print(f"[video] ffmpeg GIF uretemedi ({exc}), PIL'e dusuluyor.")
        return False


def _gif_via_pil(frames: list[np.ndarray], path: str, fps: int, size: tuple[int, int]) -> str:
    import cv2
    from PIL import Image

    frames = [cv2.resize(f, size, interpolation=cv2.INTER_AREA) for f in frames]
    pil = [Image.fromarray(f) for f in frames]
    palette = pil[0].convert("P", palette=Image.ADAPTIVE, colors=256)
    quantized = [im.quantize(palette=palette, dither=Image.FLOYDSTEINBERG) for im in pil]
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=int(round(1000.0 / fps)),
        loop=0,
        optimize=True,
        disposal=2,
    )
    return path


def write_gif(
    frames: list[np.ndarray],
    path: str,
    fps: int = 20,
    max_size: int = 480,
    src_mp4: str | None = None,
    src_fps: int = 30,
) -> str:
    """Sonsuz donen GIF yaz. mp4 varsa ffmpeg palette yolunu kullanir."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    h, w = frames[0].shape[:2]
    size = _fit(w, h, max_size)

    if src_mp4 and os.path.exists(src_mp4) and _gif_via_ffmpeg(src_mp4, path, fps, size):
        return path

    step = max(1, int(round(src_fps / max(1, fps))))
    return _gif_via_pil(frames[::step], path, max(1, src_fps // step), size)
