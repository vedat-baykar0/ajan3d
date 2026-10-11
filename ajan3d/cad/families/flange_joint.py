"""Flanşlı boru birleşimi — iki kaynak boyunlu flanş, conta, cıvata ve somunlar.

Akış **Z**. Kütüphanenin en doğrudan standart ailesi: bütün ölçüler EN 1092-1
tablosundan gelir, uydurulan tek şey yoktur. Boru bağlantı parçaları (flanş,
adaptör, rakor) tanındığında da bu aile kullanılır, çünkü bu ürünlerin anlamlı
patlatılmış görünümü tam olarak budur: iki yarım, arada conta, çevrede cıvatalar.
"""
import math
from typing import Dict

from cad import primitives as P
from cad import standards as std
from cad.assembly import Assembly, Part, at, ring


def build(params: Dict[str, object]) -> Assembly:
    dn = int(params.get("dn", 50))
    pn = int(params.get("pn", 16))
    body_mat = str(params.get("body_material", "carbon_steel"))
    seal_mat = str(params.get("seal_material", "graphite"))
    bolt_mat = str(params.get("bolt_material", "zinc_plated"))

    P.clear_warnings()
    f = std.flange(dn, pn)
    pipe_od = std.pipe_od(dn)
    wall = max(2.6, pipe_od * 0.045)
    br = pipe_od / 2.0 - wall
    neck_len = max(28.0, dn * 0.55)
    rf_h = 2.0
    gasket_t = 2.0
    bolt_size = f.bolt_size
    bd, _, _, head_h, nut_h = std.metric(bolt_size)

    assembly = Assembly(
        family="flange_joint",
        label=f"DN{dn} / PN{pn} flanşlı boru birleşimi",
        params={"dn": dn, "pn": pn, "end": "flanged",
                "flange_od_mm": f.od, "bolt_circle_mm": f.bolt_circle,
                "bolts": f"{f.bolt_count}×{bolt_size}",
                "flange_thickness_mm": f.thickness, "pipe_od_mm": pipe_od},
    )

    # Kaynak boyunlu flanş: boyun -> göbek konisi -> flanş tablası -> conta yüzeyi
    flange = P.revolve([
        (br, 0), (pipe_od / 2.0, 0),
        (f.hub / 2.0, neck_len * 0.62), (f.hub / 2.0, neck_len),
        (f.od / 2.0, neck_len), (f.od / 2.0, neck_len + f.thickness),
        (f.raised_face / 2.0, neck_len + f.thickness),
        (f.raised_face / 2.0, neck_len + f.thickness + rf_h),
        (br, neck_len + f.thickness + rf_h),
    ], P.SECTIONS)
    bolt_xy = P.bolt_circle(f.bolt_circle, f.bolt_count, 180.0 / f.bolt_count)
    flange = P.cut(flange, *[P.translate(
        P.cylinder(f.bolt_hole / 2.0, f.thickness + 2 * P.EPS, neck_len - P.EPS,
                   sections=24), x, y, 0) for x, y in bolt_xy])
    total = neck_len + f.thickness + rf_h

    assembly.add(Part(
        id="flans", name="Kaynak boyunlu flanş", mesh=flange, material=body_mat,
        group="housing", standard=f"EN 1092-1 Tip 11 DN{dn} PN{pn}",
        note=f"Ø{f.od:.0f} mm tabla, {f.thickness:.0f} mm kalınlık, delik dairesi "
             f"Ø{f.bolt_circle:.0f} mm, {f.bolt_count}×Ø{f.bolt_hole:.0f} mm delik, "
             f"conta yüzeyi Ø{f.raised_face:.0f} mm.",
        placements=[
            at(0, 0, -gasket_t / 2.0, axis=(0, 0, -1), distance=0.55, stage=2,
               suffix="1", rotation=(180, "y")),
            at(0, 0, gasket_t / 2.0, axis=(0, 0, 1), distance=0.55, stage=2,
               suffix="2"),
        ]))

    # Conta birleşimin referans düzlemidir: patlatmada yerinde kalır, iki flanş
    # onun iki yanına açılır. Sabit bir parça olmadan montaj görsel olarak
    # dayanağını kaybediyor.
    assembly.add(Part(
        id="conta", name="Conta",
        mesh=P.tube(br, f.raised_face / 2.0, gasket_t, -gasket_t / 2.0),
        material=seal_mat, group="seal", standard="EN 1514-1",
        note=f"Ø{f.raised_face:.0f} mm conta; iki çıkıntı yüzeyi arasında sıkışır. "
             f"Patlatmada birleşim düzlemi olarak yerinde kalır.",
        placements=[at(stage=0, distance=0.0)]))

    bolt_len = math.ceil((2 * (f.thickness + rf_h) + gasket_t + nut_h + 6) / 5.0) * 5.0
    bolt_z0 = -(gasket_t / 2.0 + rf_h + f.thickness)
    assembly.add(Part(
        id="civata", name="Cıvata",
        mesh=P.hex_bolt(bolt_size, bolt_len, bolt_z0), material=bolt_mat,
        group="fastener", standard=f"DIN 931 {bolt_size}×{bolt_len:.0f}",
        note=f"{f.bolt_count} adet {bolt_size}; conta ön yükünü veren bağlantı.",
        placements=ring(bolt_xy, 0.0, axis=(0, 0, -1), distance=1.15, stage=1)))
    assembly.add(Part(
        id="somun", name="Somun", mesh=P.hex_nut(bolt_size, bolt_z0 + bolt_len),
        material=bolt_mat, group="fastener", standard=f"DIN 934 {bolt_size}",
        note="Altı köşe somun.",
        placements=ring(bolt_xy, 0.0, axis=(0, 0, 1), distance=1.15, stage=1)))
    assembly.add(Part(
        id="rondela", name="Rondela", mesh=P.washer(bolt_size, bolt_z0 + bolt_len
                                                    - std.metric(bolt_size)[0] * 0.16),
        material=bolt_mat, group="fastener", standard=f"DIN 125 Ø{bd:.0f}",
        note="Somun altı düz rondela.",
        placements=ring(bolt_xy, 0.0, axis=(0, 0, 1), distance=0.95, stage=1)))

    assembly.notes.append(
        f"Toplam uzunluk {2 * total + gasket_t:.0f} mm; bütün ölçüler EN 1092-1 "
        f"DN{dn}/PN{pn} tablosundan alındı.")
    assembly.warnings.extend(P.warnings())
    return assembly
