"""Komut satiri arayuzu: python main.py foto.jpg -o cikti.mp4"""

from __future__ import annotations

import argparse
import glob
import os
import sys

# HF Hub'in Windows symlink uyarisi pipeline ciktisini kirletiyor
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from .camera import MOTIONS
from .depth import MODEL_IDS
from .pipeline import ParallaxPipeline, PipelineConfig

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="parallax3d",
        description="2D fotograftan 2.5D parallax (3D foto) videosu uretir.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Fotograf, klasor veya glob deseni (*.jpg)")
    p.add_argument("-o", "--output", default=None, help="Cikti .mp4 (klasor girdisinde cikti klasoru)")

    g = p.add_argument_group("hareket")
    g.add_argument("-m", "--motion", default="orbit", choices=MOTIONS, help="Kamera hareketi")
    g.add_argument("-d", "--duration", type=float, default=4.0, help="Sure (saniye)")
    g.add_argument("--fps", type=int, default=30, help="Kare/saniye")
    g.add_argument("-s", "--strength", type=float, default=1.0, help="Parallax siddeti (0.3 - 2.0)")
    g.add_argument("--focus", type=float, default=0.5, help="Sabit kalan derinlik duzlemi (0 arka, 1 on)")

    g = p.add_argument_group("derinlik / segmentasyon")
    g.add_argument("--model", default="small", help=f"Derinlik modeli: {', '.join(MODEL_IDS)} veya HF id")
    g.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    g.add_argument("--segment", default="auto", choices=("auto", "rembg", "depth", "none"),
                   help="On plan ayirma yontemi")
    g.add_argument("--threshold", type=float, default=None, help="Derinlik esigi (0-1), bos = Otsu")
    g.add_argument("--refine", type=int, default=7, help="Derinlik yumusatma (0 = kapali)")

    g = p.add_argument_group("cikti")
    g.add_argument("--max-side", type=int, default=1280, help="Calisma cozunurlugu (uzun kenar)")
    g.add_argument("--engine", default="warp", choices=("warp", "layers"),
                   help="Render motoru: warp = piksel bazli (temiz), layers = katmanli")
    g.add_argument("--layers", type=int, default=16, help="Derinlik katmani sayisi (--engine layers)")
    g.add_argument("--overscan", type=float, default=0.07, help="Kenar kirpma payi")
    g.add_argument("--width", type=int, default=None, help="Cikti genisligi (bos = calisma cozunurlugu)")
    g.add_argument("--quality", type=int, default=8, help="mp4 kalitesi (1-10)")
    g.add_argument("--gif", action="store_true", help="Ayrica .gif uret")
    g.add_argument("--gif-fps", type=int, default=20)
    g.add_argument("--gif-size", type=int, default=480, help="GIF uzun kenari (piksel)")
    g.add_argument("--debug", action="store_true", help="Derinlik/maske/arka plan goruntulerini kaydet")
    return p


def collect_inputs(pattern: str) -> list[str]:
    if os.path.isdir(pattern):
        files = [os.path.join(pattern, f) for f in sorted(os.listdir(pattern))]
    elif any(ch in pattern for ch in "*?["):
        files = sorted(glob.glob(pattern))
    else:
        files = [pattern]
    return [f for f in files if f.lower().endswith(IMAGE_EXT) and os.path.isfile(f)]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    images = collect_inputs(args.input)
    if not images:
        print(f"HATA: '{args.input}' icinde islenebilir fotograf bulunamadi.", file=sys.stderr)
        return 1

    cfg = PipelineConfig(
        model=args.model, device=args.device, refine=args.refine,
        segment=args.segment, threshold=args.threshold,
        engine=args.engine, max_side=args.max_side, layers=args.layers, focus=args.focus,
        overscan=args.overscan, strength=args.strength,
        motion=args.motion, duration=args.duration, fps=args.fps, quality=args.quality,
        out_width=args.width, gif=args.gif, gif_fps=args.gif_fps, gif_size=args.gif_size,
        debug=args.debug,
    )

    # Cikti yolu: tek dosya -> .mp4, coklu -> klasor
    batch = len(images) > 1
    if batch:
        out_dir = args.output or "output"
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_dir = None

    pipeline = ParallaxPipeline(cfg)
    ok = 0
    for i, path in enumerate(images, 1):
        stem = os.path.splitext(os.path.basename(path))[0]
        if batch:
            out_path = os.path.join(out_dir, f"{stem}_{args.motion}.mp4")
            print(f"\n=== [{i}/{len(images)}] {stem} ===")
        else:
            out_path = args.output or os.path.join("output", f"{stem}_{args.motion}.mp4")
            if os.path.isdir(out_path):
                out_path = os.path.join(out_path, f"{stem}_{args.motion}.mp4")
        try:
            pipeline.run(path, out_path)
            ok += 1
        except Exception as exc:  # tek fotograf patlasa da seriyi bitir
            print(f"HATA ({path}): {exc}", file=sys.stderr)
            if not batch:
                raise

    if batch:
        print(f"\nBitti: {ok}/{len(images)} video uretildi -> {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
