"""Y tipi pislik tutucu (Y-strainer) — süzgeç sepetli hat filtresi.

Akış **Z**, süzgeç kolu ana hattan 45° aşağı sarkar. Akış ana gövdeden geçerken
delikli süzgeç silindiri katı parçacıkları tutar; temizlik için alt kapak
sökülür ve süzgeç çıkarılır. Delikler gerçekten delinir (Boolean), bu yüzden
X-Ray modunda süzgecin içi ve dışı birbirinden ayırt edilebilir.
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
    seal_mat = str(params.get("seal_material", "graphite"))
    bolt_mat = str(params.get("bolt_material", "zinc_plated"))

    P.clear_warnings()
    flange = std.flange(dn, pn)
    bore = float(dn)
    br = bore / 2.0
    wall = max(5.0, bore * 0.15)
    body_r = br + wall
    length = max(dn * 2.0, 130.0)
    branch_r = br * 0.92 + wall
    branch_len = max(dn * 1.25, 80.0)
    angle = 45.0

    cap_bolt = "M10" if dn <= 50 else ("M12" if dn <= 100 else "M16")
    cb_d = std.metric(cap_bolt)[0]
    cap_pcd = (branch_r + cb_d * 1.1) * 2.0
    cap_r = cap_pcd / 2.0 + cb_d * 1.0
    cap_t = max(10.0, cb_d * 1.2)
    gasket_t = 2.0
    screen_or = br * 0.90
    screen_t = max(1.6, bore * 0.035)
    hole_d = max(1.4, bore * 0.030)

    assembly = Assembly(
        family="y_strainer",
        label=f"{std.nps_label(dn)} / DN{dn} Y tipi pislik tutucu",
        params={"dn": dn, "pn": pn, "end": end, "bore_mm": bore,
                "face_to_face_mm": round(length, 1), "branch_angle_deg": angle,
                "screen_hole_mm": round(hole_d, 1), "cap_bolts": cap_bolt},
    )

    # --- gövde: ana hat + 45° kol --------------------------------------------- #
    main = P.cylinder(body_r, length, -length / 2.0)
    branch = P.rotate(P.cylinder(branch_r, branch_len, 0.0), 180 - angle, "x")
    branch = P.translate(branch, 0, 0, -body_r * 0.25)
    cap_seat = P.rotate(P.cylinder(cap_r, cap_t, branch_len - cap_t), 180 - angle, "x")
    cap_seat = P.translate(cap_seat, 0, 0, -body_r * 0.25)
    body = P.union(main, branch, cap_seat,
                   _ends(end, dn, flange, length, body_r, bore))

    bore_cut = P.cylinder(br, length + 4 * P.EPS, -length / 2.0 - P.EPS)
    branch_cut = P.translate(P.rotate(
        P.cylinder(branch_r - wall, branch_len + 2 * P.EPS, -body_r * 0.6),
        180 - angle, "x"), 0, 0, -body_r * 0.25)
    bolt_xy = P.bolt_circle(cap_pcd, 4, 45)
    cuts = [bore_cut, branch_cut]
    for i, (x, y) in enumerate(bolt_xy):
        hole = P.rotate(P.cylinder(cb_d / 2.0 + 0.3, cap_t * 1.4,
                                   branch_len - cap_t * 1.4 + P.EPS, sections=20),
                        180 - angle, "x")
        cuts.append(P.translate(P.translate(hole, x, y, 0), 0, 0, -body_r * 0.25))
    body = P.cut(body, *cuts)
    assembly.add(Part(
        id="govde", name="Gövde", mesh=body, material=body_mat, group="housing",
        standard="EN 13445 / ASME B16.34",
        note=f"Döküm Y gövde; süzgeç kolu ana hattan {angle:.0f}° açıyla ayrılır, "
             f"ucunda sökülebilir temizlik kapağı vardır.",
        placements=[at(stage=0, distance=0.0)]))

    # --- süzgeç silindiri ------------------------------------------------------ #
    screen_len = branch_len * 0.78
    screen = P.tube(screen_or - screen_t, screen_or, screen_len, 0.0)
    screen = P.union(screen, P.tube(screen_or - screen_t, screen_or + screen_t * 1.6,
                                    screen_t * 2.2, screen_len - screen_t * 2.2))
    holes = []
    rows = max(4, int(screen_len / (hole_d * 3.4)))
    per_row = max(8, int(2 * math.pi * screen_or / (hole_d * 3.2)))
    per_row = min(per_row, 28)
    for r in range(rows):
        z = screen_len * (r + 0.6) / (rows + 1.0)
        for c in range(per_row):
            a = math.radians(360.0 * c / per_row + (18.0 if r % 2 else 0.0))
            cut = P.rotate(P.cylinder(hole_d / 2.0, screen_t * 4.0, -screen_t * 2.0,
                                      sections=10), 90, "y")
            cut = P.rotate(cut, math.degrees(a), "z")
            holes.append(P.translate(cut, screen_or * math.cos(a),
                                     screen_or * math.sin(a), z))
    screen = P.cut(screen, *holes)
    screen = P.translate(P.rotate(screen, 180 - angle, "x"), 0, 0, -body_r * 0.25)
    assembly.add(Part(
        id="suzgec", name="Süzgeç sepeti", mesh=screen, material=trim_mat,
        group="internal",
        note=f"Paslanmaz delikli süzgeç; Ø{hole_d:.1f} mm delik, "
             f"{rows * per_row} adet. Üst bileziği kapak tarafından bastırılır.",
        placements=[at(axis=_branch_axis(angle), distance=0.62, stage=3)]))

    # --- temizlik kapağı ------------------------------------------------------- #
    cap = P.cylinder(cap_r, cap_t, 0.0)
    cap = P.union(cap, P.cylinder(branch_r - wall - 0.3, cap_t * 0.5, -cap_t * 0.5))
    cap = P.cut(cap, *[P.translate(P.cylinder(cb_d / 2.0 + 0.3, cap_t * 3,
                                              -cap_t, sections=20), x, y, 0)
                       for x, y in bolt_xy])
    cap = P.translate(P.rotate(P.translate(cap, 0, 0, branch_len), 180 - angle, "x"),
                      0, 0, -body_r * 0.25)
    assembly.add(Part(
        id="temizlik_kapagi", name="Temizlik kapağı", mesh=cap, material=body_mat,
        group="housing",
        note="Süzgeci çıkarmak için sökülen kapak; iç spigot'u süzgeci yerinde tutar.",
        placements=[at(axis=_branch_axis(angle), distance=0.90, stage=2)]))

    gasket = P.tube(branch_r - wall, cap_pcd / 2.0 - cb_d, gasket_t, 0.0)
    gasket = P.translate(P.rotate(P.translate(gasket, 0, 0, branch_len - gasket_t),
                                  180 - angle, "x"), 0, 0, -body_r * 0.25)
    assembly.add(Part(
        id="kapak_contasi", name="Kapak contası", mesh=gasket, material=seal_mat,
        group="seal", note="Temizlik kapağı contası.",
        placements=[at(axis=_branch_axis(angle), distance=0.76, stage=3)]))

    bolt_len = math.ceil((cap_t * 2 + gasket_t + 6) / 5.0) * 5.0
    bolt = P.translate(P.rotate(P.hex_bolt(cap_bolt, bolt_len, 0.0), 180, "x"),
                       0, 0, branch_len + cap_t)
    bolt = P.translate(P.rotate(bolt, 180 - angle, "x"), 0, 0, -body_r * 0.25)
    places = []
    for i, (x, y) in enumerate(bolt_xy, 1):
        ox, oy, oz = _rot_x((x, y, 0.0), 180 - angle)
        places.append(at(ox, oy, oz, axis=_branch_axis(angle), distance=1.15,
                         stage=1, suffix=str(i)))
    assembly.add(Part(
        id="kapak_civatasi", name="Kapak cıvatası", mesh=bolt, material=bolt_mat,
        group="fastener", standard=f"DIN 933 {cap_bolt}×{bolt_len:.0f}",
        note="Temizlik kapağını sıkan cıvata.", placements=places))

    assembly.warnings.extend(P.warnings())
    return assembly


def _rot_x(point, degrees: float):
    """Noktayı X ekseni etrafında döndürür (kol üzerindeki cıvata konumları için)."""
    a = math.radians(degrees)
    x, y, z = point
    return x, y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)


def _branch_axis(angle: float):
    """45° kolun dışa bakan birim ekseni (patlatma yönü)."""
    a = math.radians(180 - angle)
    return (0.0, -math.sin(a), math.cos(a))


def _ends(end: str, dn: int, flange: std.Flange, length: float, body_r: float,
          bore: float):
    from cad.families.gate_valve import _ends as shared
    return shared(end, dn, flange, length, body_r, bore)
