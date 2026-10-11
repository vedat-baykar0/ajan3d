"""Sabit bilyalı rulman (deep groove ball bearing) — DIN 625 / ISO 15.

Eksen **Z**. Oluklar bilye küresinin **Boolean çıkarılmasıyla** açılır, yani
bilyeler oluğa gerçekten oturur; ayrıca kafes bilyeleri eşit açıda tutar.
Rulman, vana dışı bir ürün geldiğinde kütüphanenin mekanik tarafını temsil eder.
"""
import math
from typing import Dict

from cad import primitives as P
from cad.assembly import Assembly, Part, at


# Yaygın 60xx serisi: kod -> (iç çap d, dış çap D, genişlik B, bilye sayısı)
SERIES = {
    "6000": (10, 26, 8, 8), "6002": (15, 32, 9, 9), "6004": (20, 42, 12, 9),
    "6006": (30, 55, 13, 10), "6008": (40, 68, 15, 11), "6010": (50, 80, 16, 12),
    "6204": (20, 47, 14, 9), "6206": (30, 62, 16, 9), "6208": (40, 80, 18, 10),
    "6305": (25, 62, 17, 8), "6308": (40, 90, 23, 8),
}


def build(params: Dict[str, object]) -> Assembly:
    code = str(params.get("code", "6206"))
    if code not in SERIES:
        code = _nearest(float(params.get("bore_mm", 30)))
    d, od, width, balls = SERIES[code]
    ring_mat = str(params.get("body_material", "carbon_steel"))
    ball_mat = "chrome"
    cage_mat = str(params.get("trim_material", "carbon_steel"))

    P.clear_warnings()
    pitch_r = (d + od) / 4.0
    ball_r = (od - d) * 0.145
    inner_or = pitch_r - ball_r * 0.62
    outer_ir = pitch_r + ball_r * 0.62

    assembly = Assembly(
        family="ball_bearing",
        label=f"{code} sabit bilyalı rulman",
        params={"code": code, "bore_mm": d, "outer_mm": od, "width_mm": width,
                "balls": balls, "ball_dia_mm": round(ball_r * 2, 2)},
    )

    groove = [P.translate(P.sphere(ball_r + 0.12, 3),
                          pitch_r * math.cos(2 * math.pi * i / 72),
                          pitch_r * math.sin(2 * math.pi * i / 72), 0)
              for i in range(72)]

    inner = P.cut(P.tube(d / 2.0, inner_or, width, -width / 2.0), *groove)
    assembly.add(Part(
        id="ic_bilezik", name="İç bilezik", mesh=inner, material=ring_mat,
        group="internal", standard=f"DIN 625 {code}",
        note=f"Ø{d} mm mil üzerine geçer; oluk bilye küresiyle açılmıştır.",
        placements=[at(axis=(0, 0, -1), distance=0.45, stage=3)]))

    outer = P.cut(P.tube(outer_ir, od / 2.0, width, -width / 2.0), *groove)
    assembly.add(Part(
        id="dis_bilezik", name="Dış bilezik", mesh=outer, material=ring_mat,
        group="housing", standard=f"DIN 625 {code}",
        note=f"Ø{od} mm yatak deliğine oturur.",
        placements=[at(stage=0, distance=0.0)]))

    assembly.add(Part(
        id="bilye", name="Bilye", mesh=P.sphere(ball_r, 3), material=ball_mat,
        group="internal", standard="100Cr6 rulman çeliği",
        note=f"Ø{ball_r * 2:.2f} mm taşlanmış bilye, {balls} adet.",
        placements=[at(pitch_r * math.cos(2 * math.pi * i / balls),
                       pitch_r * math.sin(2 * math.pi * i / balls), 0,
                       axis=(math.cos(2 * math.pi * i / balls),
                             math.sin(2 * math.pi * i / balls), 0),
                       distance=0.55, stage=2, suffix=str(i + 1))
                    for i in range(balls)]))

    cage_t = max(0.8, ball_r * 0.22)
    cage = P.tube(pitch_r - ball_r * 0.72, pitch_r + ball_r * 0.72, cage_t,
                  -cage_t / 2.0)
    cage = P.cut(cage, *[P.translate(P.cylinder(ball_r * 1.06, cage_t * 4,
                                                -cage_t * 2, sections=20),
                                     pitch_r * math.cos(2 * math.pi * i / balls),
                                     pitch_r * math.sin(2 * math.pi * i / balls), 0)
                         for i in range(balls)])
    assembly.add(Part(
        id="kafes", name="Kafes", mesh=cage, material=cage_mat, group="internal",
        note="Bilyeleri eşit açıda tutan sac kafes.",
        placements=[at(axis=(0, 0, 1), distance=0.60, stage=2)]))

    assembly.warnings.extend(P.warnings())
    return assembly


def _nearest(bore_mm: float) -> str:
    return min(SERIES, key=lambda k: abs(SERIES[k][0] - bore_mm))
