"""Pipeline: fotograf -> derinlik -> segmentasyon -> katmanli render -> video."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

from . import camera, depth as depth_mod, render, segment, video, warp


@dataclass
class PipelineConfig:
    # Derinlik modeli
    model: str = "small"          # small | base | large | midas | midas-large | HF id
    device: str = "auto"          # auto | cpu | cuda
    refine: int = 7               # derinlik yumusatma gucu (0 = kapali)
    # Segmentasyon
    segment: str = "auto"         # auto | rembg | depth | none
    threshold: float | None = None
    # Render
    engine: str = "warp"          # warp (piksel bazli) | layers (katmanli)
    max_side: int = 1280          # calisma cozunurlugu (uzun kenar)
    layers: int = 16
    focus: float = 0.5            # sabit kalan derinlik duzlemi
    overscan: float = 0.07        # kenar bosluklarini kirpma payi
    strength: float = 1.0         # parallax siddeti
    # Hareket / video
    motion: str = "orbit"
    duration: float = 4.0
    fps: int = 30
    quality: int = 8
    out_width: int | None = None  # None -> calisma cozunurlugu
    gif: bool = False
    gif_fps: int = 20
    gif_size: int = 480   # GIF uzun kenari
    debug: bool = False
    debug_dir: str | None = None


@dataclass
class PipelineResult:
    image_path: str
    video_path: str
    gif_path: str | None = None
    frames: int = 0
    segment_method: str = ""
    timings: dict = field(default_factory=dict)


class ParallaxPipeline:
    """Modeli bir kez yukler, ardindan istedigin kadar fotograf isler."""

    def __init__(self, config: PipelineConfig | None = None):
        self.cfg = config or PipelineConfig()
        self._estimator: depth_mod.DepthEstimator | None = None

    @property
    def estimator(self) -> depth_mod.DepthEstimator:
        if self._estimator is None:
            self._estimator = depth_mod.DepthEstimator(self.cfg.model, self.cfg.device)
        return self._estimator

    # ------------------------------------------------------------------ adimlar
    def load_image(self, path: str) -> Image.Image:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        w, h = img.size
        m = self.cfg.max_side
        if max(w, h) > m:
            scale = m / max(w, h)
            w, h = int(round(w * scale)), int(round(h * scale))
        # Cift sayi: hem x264 hem warp hizalamasi icin
        img = img.resize((w - w % 2, h - h % 2), Image.LANCZOS)
        return img

    def _dump_debug(self, out_dir: str, stem: str, rgb, dep, mask, plate):
        import cv2

        os.makedirs(out_dir, exist_ok=True)
        d8 = (np.clip(dep, 0, 1) * 255).astype(np.uint8)
        cv2.imwrite(os.path.join(out_dir, f"{stem}_depth.png"), d8)
        cv2.imwrite(
            os.path.join(out_dir, f"{stem}_depth_color.png"),
            cv2.applyColorMap(d8, cv2.COLORMAP_INFERNO),
        )
        if mask is not None:
            cv2.imwrite(os.path.join(out_dir, f"{stem}_mask.png"), (mask * 255).astype(np.uint8))
            cut = np.dstack([rgb[..., ::-1], (mask * 255).astype(np.uint8)])
            cv2.imwrite(os.path.join(out_dir, f"{stem}_foreground.png"), cut)
        cv2.imwrite(os.path.join(out_dir, f"{stem}_bg_plate.png"), plate[..., ::-1])
        print(f"[debug] Ara cikti: {out_dir}")

    # -------------------------------------------------------------------- calis
    def run(self, image_path: str, out_path: str) -> PipelineResult:
        cfg = self.cfg
        t = {}
        stem = os.path.splitext(os.path.basename(image_path))[0]

        t0 = time.time()
        img = self.load_image(image_path)
        rgb = np.asarray(img)
        t["yukleme"] = time.time() - t0
        print(f"[1/5] Fotograf: {image_path}  ({img.size[0]}x{img.size[1]})")

        est = self.estimator  # modeli olcum disinda yukle (ilk cagrida indirir)
        t0 = time.time()
        dep = est.predict(img)
        dep = depth_mod.refine(dep, cfg.refine)
        t["derinlik"] = time.time() - t0
        print(f"[2/5] Derinlik haritasi hazir ({t['derinlik']:.1f}s)")

        t0 = time.time()
        if cfg.segment == "none":
            mask, method = None, "none"
        else:
            mask, method = segment.foreground_mask(rgb, dep, cfg.segment, cfg.threshold)
        t["segmentasyon"] = time.time() - t0
        cover = f", on plan %{100 * float(mask.mean()):.0f}" if mask is not None else ""
        print(f"[3/5] Segmentasyon: {method}{cover} ({t['segmentasyon']:.1f}s)")

        t0 = time.time()
        if cfg.engine == "layers":
            scene = render.build_layers(rgb, dep, cfg.layers, mask)
            plate = scene[0].rgb
            detail = f"{len(scene)} derinlik katmani"
        else:
            scene = warp.build_scene(rgb, dep, mask)
            plate = scene.plate
            detail = "piksel bazli warp sahnesi"
        t["sahne"] = time.time() - t0
        print(f"[4/5] {detail} hazir ({t['sahne']:.1f}s)")

        if cfg.debug:
            self._dump_debug(
                cfg.debug_dir or os.path.join(os.path.dirname(os.path.abspath(out_path)), "debug"),
                stem, rgb, dep, mask, plate,
            )

        n_frames = max(2, int(round(cfg.duration * cfg.fps)))
        dx, dy, dz = camera.camera_path(cfg.motion, n_frames, cfg.strength, img.size[0])

        out_size = None
        if cfg.out_width:
            crop_w = img.size[0] - 2 * int(img.size[0] * cfg.overscan)
            crop_h = img.size[1] - 2 * int(img.size[1] * cfg.overscan)
            ow = cfg.out_width - cfg.out_width % 2
            oh = int(round(ow * crop_h / crop_w))
            out_size = (ow, oh - oh % 2)

        t0 = time.time()
        frames = []
        draw = render.render_frame if cfg.engine == "layers" else warp.render_frame
        for i in range(n_frames):
            frames.append(
                draw(
                    scene, float(dx[i]), float(dy[i]), float(dz[i]),
                    focus=cfg.focus, overscan=cfg.overscan, out_size=out_size,
                )
            )
            if (i + 1) % 15 == 0 or i + 1 == n_frames:
                print(f"      render {i + 1}/{n_frames}", end="\r", flush=True)
        t["render"] = time.time() - t0
        print(f"\n[5/5] {n_frames} kare render edildi ({t['render']:.1f}s)")

        t0 = time.time()
        video.write_mp4(frames, out_path, cfg.fps, cfg.quality)
        gif_path = None
        if cfg.gif:
            gif_path = os.path.splitext(out_path)[0] + ".gif"
            video.write_gif(
                frames, gif_path, fps=cfg.gif_fps, max_size=cfg.gif_size,
                src_mp4=out_path, src_fps=cfg.fps,
            )
        t["yazma"] = time.time() - t0

        print(f"  -> {out_path}" + (f"\n  -> {gif_path}" if gif_path else ""))
        print(f"  Toplam: {sum(t.values()):.1f}s")
        return PipelineResult(image_path, out_path, gif_path, n_frames, method, t)
