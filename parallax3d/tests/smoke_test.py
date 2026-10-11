"""Model indirmeden calisan hizli dogrulama testi.

    python tests/smoke_test.py

Sentetik bir sahne (yakin kutu + uzak zemin) uretip derinlik disindaki tum
adimlari (segmentasyon, katmanlama, warp, mp4/gif yazma) kontrol eder.
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parallax3d import camera, render, segment, video, warp  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  {'OK  ' if cond else 'HATA'}  {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def synthetic(h: int = 180, w: int = 240):
    """Gradyan zemin uzerinde yakin bir kutu: bilinen derinlikli sahte sahne."""
    depth = np.tile(np.linspace(0.0, 0.35, h, dtype=np.float32)[:, None], (1, w))
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[..., 2] = (depth / 0.35 * 180).astype(np.uint8)
    y0, y1, x0, x1 = 50, 130, 70, 170
    depth[y0:y1, x0:x1] = 0.9
    rgb[y0:y1, x0:x1] = (230, 160, 40)
    return rgb, depth


def main() -> int:
    rgb, depth = synthetic()
    h, w = depth.shape

    print("[kamera]")
    for m in camera.MOTIONS:
        dx, dy, dz = camera.camera_path(m, 24, 1.0, w)
        moves = max(np.abs(dx).max(), np.abs(dy).max(), np.abs(dz).max() * w)
        check(f"{m} yolu", len(dx) == 24 and moves > 0.5, f"maks {moves:.1f}")
    try:
        camera.camera_path("yok-boyle", 10)
        check("gecersiz hareket reddi", False)
    except ValueError:
        check("gecersiz hareket reddi", True)

    print("[segmentasyon]")
    mask, method = segment.foreground_mask(rgb, depth, method="depth")
    inside = mask[60:120, 80:160].mean()
    outside = mask[:40].mean()
    check("maske on plani buluyor", inside > 0.9 and outside < 0.1,
          f"ic {inside:.2f} / dis {outside:.2f}")
    check("maske 0..1 araliginda", float(mask.min()) >= 0 and float(mask.max()) <= 1)

    print("[katmanli render]")
    layers = render.build_layers(rgb, depth, n_layers=8, fg_mask=mask)
    check("katman sayisi", 2 <= len(layers) <= 8, f"{len(layers)} katman")
    check("arka plan plakasi deliksiz", layers[0].alpha.min() == 255)
    plate_box = layers[0].rgb[60:120, 80:160]
    check("plakada ozne silinmis", int(np.abs(plate_box.astype(int) - [230, 160, 40]).mean()) > 20)
    f0 = render.render_frame(layers, 40.0, 0.0, 0.0, focus=0.5)
    check("kare boyutu (overscan)", f0.shape[:2] == (h - 2 * int(h * 0.07), w - 2 * int(w * 0.07)),
          str(f0.shape))

    print("[warp render]")
    scene = warp.build_scene(rgb, depth, mask)
    check("arka plan derinligi one gecmiyor", bool((scene.depth_bg <= scene.depth + 1e-5).all()))
    mx, my, res = warp.inverse_maps(depth, 40.0, 0.0, 0.0, 0.5)
    check("ters harita yakinsiyor", float(np.median(res)) < 0.5, f"medyan artik {np.median(res):.3f}")
    # focus=0.5 duzlemi sabit kalir: on plan bir yone, arka plan ters yone kayar
    shift = mx - np.arange(w, dtype=np.float32)[None, :]
    fg_shift = float(np.median(shift[60:120, 80:160]))
    bg_shift = float(np.median(shift[:40]))
    check("on plan ve arka plan ters yone kayiyor", fg_shift * bg_shift < 0,
          f"on {fg_shift:+.1f}px / arka {bg_shift:+.1f}px")
    check("parallax ayrimi yeterli", abs(fg_shift - bg_shift) > 10,
          f"{abs(fg_shift - bg_shift):.1f}px")
    frames = [warp.render_frame(scene, float(dx), 0.0, 0.0) for dx in (0.0, 30.0, -30.0)]
    check("kareler gercekten degisiyor",
          int(np.abs(frames[1].astype(int) - frames[2].astype(int)).mean()) > 3)
    check("kare tipi uint8", all(f.dtype == np.uint8 for f in frames))

    print("[video]")
    with tempfile.TemporaryDirectory() as tmp:
        seq = [warp.render_frame(scene, float(d), 0.0, 0.0) for d in np.linspace(-20, 20, 12)]
        mp4 = video.write_mp4(seq, os.path.join(tmp, "t.mp4"), fps=12)
        check("mp4 yazildi", os.path.getsize(mp4) > 1000, f"{os.path.getsize(mp4)} bayt")
        gif = video.write_gif(seq, os.path.join(tmp, "t.gif"), fps=12, max_size=160,
                              src_mp4=mp4, src_fps=12)
        check("gif yazildi", os.path.getsize(gif) > 500, f"{os.path.getsize(gif)} bayt")

    print()
    if FAILS:
        print(f"{len(FAILS)} test BASARISIZ: {', '.join(FAILS)}")
        return 1
    print("Tum testler gecti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
