"""Çek valf (swing type) — akışı tek yönde geçiren klapeli vana.

Akış **Z**, kapak (cover) **+Y**. Klape menteşe piminden sarkar; akış ileri
yönde klapeyi açar, ters yönde klape oturma halkasına kapanır. Bakım için üst
kapak dört cıvatayla sökülür.
"""
import math
from typing import Dict

from cad import primitives as P
from cad import standards as std
from cad.assembly import Assembly, Part, at


def build(params: Dict[str, object]) -> Assembly:
    dn = int(params.get("dn", 50))
    pn = int(params.get("pn", 16))
    end = str(params.get("end", "flanged"))
    body_mat = str(params.get("body_material", "stainless_cast"))
    trim_mat = str(params.get("trim_material", "stainless_machined"))
    seat_mat = str(params.get("seat_material", "ptfe"))
    seal_mat = str(params.get("seal_material", "graphite"))
    bolt_mat = str(params.get("bolt_material", "zinc_plated"))

    P.clear_warnings()
    flange = std.flange(dn, pn)
    bore = float(dn)
    br = bore / 2.0
    wall = max(5.0, bore * 0.15)
    chamber_r = br * 1.45
    body_r = chamber_r + wall
    length = max(dn * 1.8, 115.0)
    disc_t = max(6.0, bore * 0.16)
    seat_t = max(4.0, bore * 0.10)

    cb = "M10" if dn <= 50 else ("M12" if dn <= 100 else "M16")
    cb_d = std.metric(cb)[0]
    cover_pcd = (chamber_r + cb_d * 1.2) * 2.0
    cover_r = cover_pcd / 2.0 + cb_d * 1.05
    cover_t = max(10.0, cb_d * 1.25)
    cover_y = body_r + max(6.0, bore * 0.14)
    gasket_t = 2.0
    pin_d = max(8.0, bore * 0.16)
    hinge_y = cover_y - cover_t - max(6.0, bore * 0.12)

    assembly = Assembly(
        family="check_valve",
        label=f"{std.nps_label(dn)} / DN{dn} çek valf (klapeli)",
        params={"dn": dn, "pn": pn, "end": end, "bore_mm": bore,
                "face_to_face_mm": round(length, 1), "cover_bolts": cb},
    )

    body = P.cylinder(body_r, length, -length / 2.0)
    neck = P.to_axis(P.revolve([
        (0, body_r * 0.5), (cover_r, body_r * 0.5), (cover_r, cover_y), (0, cover_y),
    ], P.SECTIONS), "y")
    body = P.union(body, neck, _ends(end, dn, flange, length, body_r, bore))
    cuts = [P.cylinder(br, length + 4 * P.EPS, -length / 2.0 - P.EPS),
            P.cylinder(chamber_r, length * 0.46, -length * 0.20),
            P.to_axis(P.cylinder(chamber_r, cover_y + P.EPS, 0.0), "y")]
    for (x, y) in P.bolt_circle(cover_pcd, 4, 45):
        cuts.append(P.translate(P.to_axis(
            P.cylinder(cb_d / 2.0 + 0.3, cover_t * 1.5, cover_y - cover_t * 1.5
                       + P.EPS, sections=20), "y"), x, 0, y))
    # Menteşe pimi yuvası: X ekseninde, gövdenin iki yan duvarından geçer
    z_disc = -disc_t * 0.9
    pin_z = z_disc + disc_t + pin_d * 0.95
    cuts.append(P.translate(_x_cyl(pin_d / 2.0 + 0.2, chamber_r * 2.4), 0,
                            hinge_y, pin_z))
    body = P.cut(body, *cuts)
    assembly.add(Part(
        id="govde", name="Gövde", mesh=body, material=body_mat, group="housing",
        standard="EN 12334 / API 594",
        note="Döküm gövde; üstte bakım kapağı, içte menteşe pimi yuvası ve "
             "oturma halkası yatağı.",
        placements=[at(stage=0, distance=0.0)]))

    seat = P.revolve([(br, 0), (br + seat_t, 0), (br + seat_t * 0.5, seat_t),
                      (br, seat_t)], P.SECTIONS)
    assembly.add(Part(
        id="oturma_halkasi", name="Oturma halkası",
        mesh=P.translate(seat, 0, 0, z_disc - seat_t), material=seat_mat,
        group="seal", note="Klapenin kapandığı konik oturma halkası.",
        placements=[at(axis=(0, 0, -1), distance=0.55, stage=3)]))

    # Klape: tabla + menteşe kolu + pim gözü, hepsi tek katı
    lug_h = hinge_y - br * 0.80
    disc = P.union(
        P.revolve([(0, 0), (br * 1.18, 0), (br * 1.18, disc_t * 0.55),
                   (br * 0.45, disc_t), (0, disc_t)], P.SECTIONS),
        P.box(pin_d * 1.7, lug_h, pin_d * 1.9,
              (0, br * 0.80 + lug_h / 2.0, disc_t + pin_d * 0.95)),
        P.translate(_x_cyl(pin_d * 1.15, pin_d * 2.4), 0, hinge_y,
                    disc_t + pin_d * 0.95),
    )
    disc = P.cut(disc, P.translate(_x_cyl(pin_d / 2.0 + 0.15, pin_d * 4.0), 0,
                                   hinge_y, disc_t + pin_d * 0.95))
    assembly.add(Part(
        id="klape", name="Klape (disc)", mesh=P.translate(disc, 0, 0, z_disc),
        material=trim_mat, group="internal",
        note="Menteşe pimine asılan klape; ileri akışta açılır, ters akışta "
             "oturma halkasına kapanır.",
        placements=[at(axis=(0, 1, 0), distance=0.58, stage=3)]))

    assembly.add(Part(
        id="mentese_pimi", name="Menteşe pimi",
        mesh=P.translate(_x_cyl(pin_d / 2.0, chamber_r * 2.2), 0, hinge_y, pin_z),
        material=trim_mat, group="internal",
        note="Klapeyi taşıyan pim; gövde yan duvarlarına oturur.",
        placements=[at(axis=(1, 0, 0), distance=0.95, stage=4)]))

    cover = P.to_axis(P.revolve([
        (0, 0), (cover_r, 0), (cover_r, cover_t),
        (cover_r * 0.55, cover_t + max(6.0, bore * 0.10)),
        (0, cover_t + max(6.0, bore * 0.10))], P.SECTIONS), "y")
    cover = P.translate(cover, 0, cover_y, 0)
    cover = P.cut(cover, *[P.translate(P.to_axis(
        P.cylinder(cb_d / 2.0 + 0.3, cover_t + 2 * P.EPS, cover_y - P.EPS,
                   sections=20), "y"), x, 0, y)
        for x, y in P.bolt_circle(cover_pcd, 4, 45)])
    cover = P.union(cover, P.translate(P.to_axis(
        P.cylinder(chamber_r * 0.9, max(4.0, bore * 0.08),
                   cover_y - max(4.0, bore * 0.08)), "y"), 0, 0, 0))
    assembly.add(Part(
        id="kapak", name="Bakım kapağı", mesh=cover, material=body_mat,
        group="housing", note="Klapeye erişim için sökülebilen üst kapak.",
        placements=[at(axis=(0, 1, 0), distance=0.72, stage=2)]))

    assembly.add(Part(
        id="kapak_contasi", name="Kapak contası",
        mesh=P.translate(P.to_axis(P.tube(chamber_r * 0.92, cover_pcd / 2.0 - cb_d,
                                          gasket_t, 0.0), "y"),
                         0, cover_y - gasket_t, 0),
        material=seal_mat, group="seal", note="Kapak ile gövde arasındaki conta.",
        placements=[at(axis=(0, 1, 0), distance=0.62, stage=3)]))

    bolt_len = math.ceil((cover_t * 2 + gasket_t + 6) / 5.0) * 5.0
    bolt_xy = P.bolt_circle(cover_pcd, 4, 45)
    assembly.add(Part(
        id="kapak_civatasi", name="Kapak cıvatası",
        mesh=P.translate(P.rotate(P.to_axis(P.hex_bolt(cb, bolt_len, 0.0), "y"),
                                  180, "x"), 0, cover_y + cover_t, 0),
        material=bolt_mat, group="fastener", standard=f"DIN 933 {cb}×{bolt_len:.0f}",
        note="Bakım kapağını sıkan cıvata.",
        placements=[at(x, 0, y, axis=(0, 1, 0), distance=1.10, stage=1,
                       suffix=str(i)) for i, (x, y) in enumerate(bolt_xy, 1)]))

    assembly.warnings.extend(P.warnings())
    return assembly


def _x_cyl(radius: float, length: float, sections: int = 24):
    """X eksenine yatık silindir (menteşe pimi ve yuvası için)."""
    return P.rotate(P.cylinder(radius, length, -length / 2.0, sections=sections),
                    90, "y")


def _ends(end: str, dn: int, flange: std.Flange, length: float, body_r: float,
          bore: float):
    from cad.families.gate_valve import _ends as shared
    return shared(end, dn, flange, length, body_r, bore)
