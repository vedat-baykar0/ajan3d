"""Kelebek vana (wafer tip) — kısa gövde, elastomer gömlek, merkezden milli tabla.

Akış **Z**, mil **+Y**. Wafer gövde iki boru flanşı arasına sıkışır; cıvata
gövdenin kendisinden geçmez, bu yüzden gövdede delik yerine merkezleme
kulakları vardır. Sızdırmazlığı elastomer gömlek (liner) sağlar: tabla
kapandığında gömleğin iç yüzeyine bastırır, gömlek aynı zamanda flanş contası
görevi de görür — bu yüzden ayrı conta yoktur.
"""
from typing import Dict

from cad import materials as mat
from cad import primitives as P
from cad import standards as std
from cad.assembly import Assembly, Part, at


def build(params: Dict[str, object]) -> Assembly:
    dn = int(params.get("dn", 80))
    pn = int(params.get("pn", 16))
    actuation = str(params.get("actuation", "lever"))
    body_mat = str(params.get("body_material", "ductile_epoxy"))
    disc_mat = str(params.get("trim_material", "stainless_machined"))
    liner_mat = str(params.get("seat_material", "epdm"))
    grip_mat = str(params.get("grip_material", "plastic_black"))

    P.clear_warnings()
    flange = std.flange(dn, pn)
    iso = std.mount_pad(dn)
    bore = float(dn)
    br = bore / 2.0

    liner_t = max(4.0, bore * 0.075)
    body_ir = br + liner_t
    body_or = min(flange.bolt_circle / 2.0 - flange.bolt_hole / 2.0 - 2.0,
                  body_ir + max(9.0, bore * 0.16))
    width = max(33.0, bore * 0.30)             # wafer gövde kalınlığı
    disc_t = max(7.0, bore * 0.13)

    stem_d = max(12.0, bore * 0.22)
    iso_bolt_d = std.metric(iso.bolt_size)[0]
    pad_r = iso.pcd / 2.0 + iso_bolt_d * 1.25
    neck_r = stem_d * 1.25
    pad_y0 = body_or + max(18.0, bore * 0.28)
    iso_t = max(9.0, iso_bolt_d * 1.7)
    stem_top = pad_y0 + iso_t + stem_d * 2.0

    assembly = Assembly(
        family="butterfly_valve",
        label=f"{std.nps_label(dn)} / DN{dn} kelebek vana (wafer)",
        params={"dn": dn, "pn": pn, "end": "wafer", "actuation": actuation,
                "bore_mm": bore, "body_width_mm": round(width, 1),
                "iso5211": iso.code, "liner": liner_mat},
    )

    # --- gövde --------------------------------------------------------------- #
    body = P.cylinder(body_or, width, -width / 2.0)
    neck = P.to_axis(P.revolve([
        (0, body_or * 0.6), (neck_r + 4.0, body_or * 0.6),
        (neck_r + 4.0, pad_y0 - (pad_r - neck_r) * 0.5), (pad_r, pad_y0),
        (pad_r, pad_y0 + iso_t), (neck_r, pad_y0 + iso_t), (0, pad_y0 + iso_t),
    ], P.SECTIONS), "y")
    # Flanş arasına oturan merkezleme kulakları
    lugs = []
    for (x, y) in P.bolt_circle(flange.bolt_circle, 2, 0):
        lugs.append(P.translate(P.cylinder(flange.bolt_hole / 2.0 - 0.6, width,
                                           -width / 2.0, sections=24), x, y, 0))
    body = P.union(body, neck, *lugs)
    body = P.cut(
        body,
        P.cylinder(br + liner_t, width + 4 * P.EPS, -width / 2.0 - P.EPS),
        P.to_axis(P.cylinder(stem_d / 2.0 + 0.4, pad_y0 + iso_t + P.EPS, 0.0), "y"),
        P.to_axis(P.cylinder(stem_d / 2.0 + 0.4, body_or + P.EPS,
                             -body_or - P.EPS), "y"),
        *[P.translate(P.to_axis(P.cylinder(iso_bolt_d / 2.0, iso_t * 0.8,
                                           pad_y0 + iso_t * 0.2 + P.EPS,
                                           sections=20), "y"), x, 0, y)
          for x, y in P.bolt_circle(iso.pcd, 4, 45)])
    assembly.add(Part(
        id="govde", name="Wafer gövde", mesh=body, material=body_mat,
        group="housing", standard="EN 593",
        note=f"Sfero döküm wafer gövde, {width:.0f} mm kalınlık; iki boru flanşı "
             f"arasına merkezleme kulaklarıyla oturur, üstte ISO 5211 {iso.code}.",
        placements=[at(stage=0, distance=0.0)]))

    # --- gömlek -------------------------------------------------------------- #
    liner = P.tube(br, br + liner_t, width, -width / 2.0)
    liner = P.union(liner,
                    P.tube(br, br + liner_t * 2.1, liner_t * 0.55, -width / 2.0
                           - liner_t * 0.55),
                    P.tube(br, br + liner_t * 2.1, liner_t * 0.55, width / 2.0))
    liner = P.cut(liner, P.to_axis(P.cylinder(stem_d / 2.0 + 1.2, bore * 2.0,
                                              -bore), "y"))
    assembly.add(Part(
        id="gomlek", name="Elastomer gömlek (liner)", mesh=liner, material=liner_mat,
        group="seal", note=f"{mat.get(liner_mat).label}; hem tabla sızdırmazlığını "
                           f"hem flanş contasını sağlar, ayrı conta gerekmez.",
        placements=[at(axis=(0, 0, 1), distance=0.70, stage=2)]))

    # --- tabla --------------------------------------------------------------- #
    disc = P.revolve([(0, -disc_t / 2.0), (br * 0.62, -disc_t / 2.0),
                      (br - 0.4, -disc_t * 0.16), (br - 0.4, disc_t * 0.16),
                      (br * 0.62, disc_t / 2.0), (0, disc_t / 2.0)], P.SECTIONS)
    disc = P.rotate(disc, 90, "x")             # tabla düzlemi akışa dik, mil Y'de
    disc = P.union(disc, P.to_axis(P.cylinder(stem_d * 0.92, br * 1.7,
                                              -br * 0.85), "y"))
    disc = P.cut(disc, P.to_axis(P.cylinder(stem_d / 2.0 + 0.15, br * 2.2,
                                            -br * 1.1), "y"))
    assembly.add(Part(
        id="tabla", name="Tabla (disc)", mesh=disc, material=disc_mat,
        group="internal",
        note="Merkezden milli tabla; kenarı küresel profilli, gömleğe eşit "
             "bastırır. Mil deliği ve pim yuvası tabla göbeğindedir.",
        placements=[at(axis=(0, 0, 1), distance=0.40, stage=3)]))

    # --- mil ve burçlar ------------------------------------------------------- #
    stem = P.cylinder(stem_d / 2.0, stem_top + body_or, -body_or)
    flat = stem_d * 0.76
    stem = P.cut(stem,
                 P.box(stem_d * 3, stem_d * 3, stem_d * 2.0,
                       (stem_d * 1.5 + flat / 2.0, 0, stem_top - stem_d * 1.0)),
                 P.box(stem_d * 3, stem_d * 3, stem_d * 2.0,
                       (-(stem_d * 1.5 + flat / 2.0), 0, stem_top - stem_d * 1.0)))
    assembly.add(Part(
        id="mil", name="Mil (stem)", mesh=P.to_axis(stem, "y"), material=disc_mat,
        group="internal",
        note="Tek parça geçmeli mil; tablayı iki noktadan taşır, üst ucu "
             "kumanda için düzleştirilmiştir.",
        placements=[at(axis=(0, 1, 0), distance=0.70, stage=4)]))

    bush = P.tube(stem_d / 2.0 + 0.2, stem_d / 2.0 + 3.0, max(8.0, stem_d * 0.7), 0.0)
    assembly.add(Part(
        id="burc", name="Mil burcu", mesh=P.to_axis(bush, "y"), material="peek",
        group="internal", note="Mili merkezleyen kuru yataklı burç.",
        placements=[at(0, body_or - max(8.0, stem_d * 0.7) - 1.0, 0, axis=(0, 1, 0),
                       distance=0.52, stage=4, suffix="1"),
                    at(0, -body_or + 1.0, 0, axis=(0, -1, 0), distance=0.52,
                       stage=4, suffix="2")]))

    plug = P.to_axis(P.cylinder(stem_d / 2.0 + 2.6, max(6.0, stem_d * 0.5),
                                -body_or), "y")
    assembly.add(Part(
        id="alt_tapa", name="Alt kapak tapası", mesh=plug, material=disc_mat,
        group="housing", note="Milin alt ucunu kapatan tapa.",
        placements=[at(axis=(0, -1, 0), distance=0.95, stage=2)]))

    # --- kumanda --------------------------------------------------------------- #
    if actuation in std.NO_ACTUATOR:
        # Aktuator ayri satin alinan bir urun; ISO 5211 pabucu arayuzu anlatiyor.
        assembly.notes.append(
            f"Kumanda organi montaja dahil edilmedi; baglanti ISO 5211 "
            f"{iso.code} pabucundan yapilir.")
    elif actuation in ("gear", "handwheel"):
        gearbox = P.to_axis(P.revolve([
            (0, 0), (pad_r * 1.25, 0), (pad_r * 1.25, iso_t * 2.6),
            (pad_r * 0.75, iso_t * 3.2), (0, iso_t * 3.2)], P.SECTIONS), "y")
        assembly.add(Part(
            id="reduktor", name="Redüktör kutusu",
            mesh=P.translate(gearbox, 0, pad_y0 + iso_t, 0), material="cast_iron",
            group="actuator",
            note="Salyangoz redüktör; ISO 5211 pabucuna dört cıvatayla bağlanır.",
            placements=[at(axis=(0, 1, 0), distance=1.15, stage=5)]))
        assembly.add(Part(
            id="volan", name="Volan",
            mesh=P.translate(P.to_axis(P.handwheel(max(160.0, dn * 2.2),
                                                   stem_d * 0.9), "y"),
                             0, pad_y0 + iso_t * 3.9, 0),
            material="cast_iron", group="actuator", note="Redüktör el çarkı.",
            placements=[at(axis=(0, 1, 0), distance=1.45, stage=5)]))
    else:
        notch = P.to_axis(P.revolve([(stem_d * 0.9, 0), (pad_r * 1.05, 0),
                                     (pad_r * 1.05, max(5.0, bore * 0.06)),
                                     (stem_d * 0.9, max(5.0, bore * 0.06))],
                                    P.SECTIONS), "y")
        assembly.add(Part(
            id="kademe_plakasi", name="Kademe plakası",
            mesh=P.translate(notch, 0, pad_y0 + iso_t, 0), material=body_mat,
            group="actuator",
            note="Kolun ara açılarda kilitlenmesini sağlayan dişli plaka.",
            placements=[at(axis=(0, 1, 0), distance=1.05, stage=5)]))
        arm, sleeve = P.lever(max(140.0, dn * 2.4), max(22.0, stem_d * 1.9),
                              max(5.0, stem_d * 0.4), stem_d * 1.3, stem_d * 0.96)
        y_handle = pad_y0 + iso_t + max(7.0, bore * 0.08)
        assembly.add(Part(
            id="kol", name="Kumanda kolu",
            mesh=P.translate(P.to_axis(arm, "y"), 0, y_handle, 0), material=disc_mat,
            group="actuator", note="Çeyrek tur kol; kademe plakasına kilitlenir.",
            placements=[at(axis=(0, 1, 0), distance=1.30, stage=5)]))
        assembly.add(Part(
            id="kol_kilifi", name="Kol kılıfı",
            mesh=P.translate(P.to_axis(sleeve, "y"), 0, y_handle, 0),
            material=grip_mat, group="actuator", note="Kavrama kılıfı.",
            placements=[at(axis=(0, 1, 0), distance=1.48, stage=5)]))

    assembly.warnings.extend(P.warnings())
    return assembly
