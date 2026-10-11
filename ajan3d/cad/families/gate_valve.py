"""Sürgülü vana (gate valve) ve yükselen milli benzerleri.

Akış **Z**, mil **+Y**. Gövde iki uçtan boruya bağlanır, ortadaki hazneden
yukarı çıkan boyun kapak (bonnet) ile kapatılır; kapak dört cıvatayla gövdeye
sıkılır. Sürgü (wedge) iki oturma halkası arasında yükselip iner, yükselen mil
volanla döndürülür.

`kind="globe"` verildiğinde aynı yığın globe vana olarak kurulur: sürgü yerine
tabla, iki oturma yerine tek oturma. **Globe vananın gerçek Z biçimli akış
yolu modellenmez** (giriş-çıkış düz geçer); montaj ve parça listesi doğru,
iç kanal temsilidir — montaj bu yüzden `representative` işaretlenir.
"""
import math
from typing import Dict

from cad import primitives as P
from cad import standards as std
from cad.assembly import Assembly, Part, at, ring


def build(params: Dict[str, object]) -> Assembly:
    dn = int(params.get("dn", 50))
    pn = int(params.get("pn", 16))
    end = str(params.get("end", "flanged"))
    kind = str(params.get("kind", "gate"))
    body_mat = str(params.get("body_material", "stainless_cast"))
    trim_mat = str(params.get("trim_material", "stainless_machined"))
    seat_mat = str(params.get("seat_material", "bronze"))
    seal_mat = str(params.get("seal_material", "graphite"))
    bolt_mat = str(params.get("bolt_material", "zinc_plated"))

    P.clear_warnings()
    flange = std.flange(dn, pn)
    bore = float(dn)
    br = bore / 2.0
    wall = max(5.0, bore * 0.15)
    chamber_r = br * 1.42
    body_r = chamber_r + wall
    length = max(dn * 1.7, 110.0)              # uçtan uca gövde boyu
    disc_t = max(7.0, bore * 0.20)
    seat_t = max(4.0, bore * 0.10)

    bonnet_bolt = "M10" if dn <= 50 else ("M12" if dn <= 80 else "M16")
    bb_d = std.metric(bonnet_bolt)[0]
    bonnet_pcd = (chamber_r + bb_d * 1.15) * 2.0
    bonnet_r = bonnet_pcd / 2.0 + bb_d * 1.05
    bonnet_t = max(10.0, bb_d * 1.2)
    bonnet_y = body_r + max(8.0, bore * 0.18)  # kapak oturma düzlemi
    gasket_t = 2.0

    stem_d = max(10.0, bore * 0.30)
    pack_d = stem_d * 1.5
    pack_h = max(10.0, stem_d * 1.3)
    neck_r = pack_d / 2.0 + max(4.5, stem_d * 0.5)
    neck_top = bonnet_y + bonnet_t + max(26.0, bore * 0.55)
    travel = bore * 1.05                       # sürgü stroku
    yoke_nut = f"M{int(round(max(10.0, stem_d * 1.25)))}"

    assembly = Assembly(
        family="gate_valve",
        label=f"{std.nps_label(dn)} / DN{dn} "
              + ("sürgülü vana" if kind == "gate" else "globe vana"),
        representative=kind != "gate",
        params={"dn": dn, "pn": pn, "end": end, "kind": kind,
                "bore_mm": bore, "face_to_face_mm": round(length, 1),
                "bonnet_bolts": bonnet_bolt, "stem_travel_mm": round(travel, 1)},
    )
    if kind != "gate":
        assembly.notes.append(
            "Globe vananın Z biçimli iç akış kanalı temsilidir; montaj sırası, "
            "parça listesi ve bağlantı ölçüleri gerçektir.")

    # --- gövde ------------------------------------------------------------- #
    body = P.cylinder(body_r, length, -length / 2.0)
    neck = P.to_axis(P.revolve([
        (0, body_r * 0.5), (neck_r + bb_d * 0.4, body_r * 0.5),
        (neck_r + bb_d * 0.4, bonnet_y - bonnet_t), (bonnet_r, bonnet_y - bonnet_t),
        (bonnet_r, bonnet_y), (0, bonnet_y),
    ], P.SECTIONS), "y")
    body = P.union(body, neck)
    body = P.union(body, _ends(end, dn, flange, length, body_r, bore))

    cuts = [
        P.cylinder(br, length + 4 * P.EPS, -length / 2.0 - P.EPS),
        P.cylinder(chamber_r, length * 0.42, -length * 0.21),
        P.to_axis(P.cylinder(chamber_r, bonnet_y + P.EPS, 0.0), "y"),
    ]
    for (x, y) in P.bolt_circle(bonnet_pcd, 4, 45):
        cuts.append(P.translate(P.to_axis(
            P.cylinder(bb_d / 2.0 + 0.3, bonnet_t * 1.4,
                       bonnet_y - bonnet_t * 1.4 + P.EPS, sections=20), "y"), x, 0, y))
    body = P.cut(body, *cuts)
    assembly.add(Part(
        id="govde", name="Gövde", mesh=body, material=body_mat, group="housing",
        standard="EN 1984 / ASME B16.34",
        note=f"Döküm gövde, iç hazne Ø{chamber_r * 2:.0f} mm; kapak düzlemi "
             f"{bonnet_bolt}×4 ile sıkılır.",
        placements=[at(stage=0, distance=0.0)]))

    # --- oturma halkaları --------------------------------------------------- #
    seat = P.revolve([(br, 0), (br + seat_t, 0), (br + seat_t * 0.55, seat_t),
                      (br, seat_t)], P.SECTIONS)
    seat_places = [at(0, 0, -(disc_t / 2.0 + seat_t), axis=(0, 0, -1), distance=0.42,
                      stage=3, suffix="1")]
    if kind == "gate":
        seat_places.append(at(0, 0, disc_t / 2.0 + seat_t, axis=(0, 0, 1),
                              distance=0.42, stage=3, suffix="2",
                              rotation=(180, "y")))
    assembly.add(Part(
        id="oturma_halkasi", name="Gövde oturma halkası", mesh=seat,
        material=seat_mat, group="seal",
        note="Konik yüzeyli oturma halkası; sürgü kapanırken buraya sıkışır.",
        placements=seat_places))

    # --- sürgü / tabla ------------------------------------------------------ #
    if kind == "gate":
        wedge = P.revolve([(0, -disc_t / 2.0), (br + seat_t * 0.9, -disc_t * 0.30),
                           (br + seat_t * 0.9, disc_t * 0.30), (0, disc_t / 2.0)],
                          P.SECTIONS)
        wedge = P.union(wedge, P.to_axis(P.cylinder(stem_d * 0.78, br * 0.7,
                                                    br * 0.55), "y"))
        wedge = P.cut(wedge, P.to_axis(P.box(stem_d * 1.25, stem_d * 0.60,
                                             br * 0.9,
                                             (0, 0, br * 0.9)), "y"))
        disc_name, disc_note = "Sürgü (wedge)", (
            "Esnek kama sürgü; iki oturma arasında sıkışarak çift yönlü "
            "sızdırmazlık sağlar. Üstte milin T başını alan yuva.")
    else:
        wedge = P.revolve([(0, -disc_t * 0.45), (br + seat_t * 0.8, -disc_t * 0.10),
                           (br + seat_t * 0.8, disc_t * 0.45), (0, disc_t * 0.45)],
                          P.SECTIONS)
        wedge = P.union(wedge, P.to_axis(P.cylinder(stem_d * 0.62, br * 0.6,
                                                    br * 0.3), "y"))
        disc_name, disc_note = "Tabla (disc)", (
            "Globe tablası; oturma halkasına eksenel bastırarak kapanır.")
    assembly.add(Part(
        id="surgu", name=disc_name, mesh=wedge, material=trim_mat, group="internal",
        note=disc_note,
        placements=[at(0, -travel * 0.05, 0, axis=(0, -1, 0), distance=0.42, stage=3)]))

    # --- kapak (bonnet) ----------------------------------------------------- #
    bonnet = P.to_axis(P.revolve([
        (0, 0), (bonnet_r, 0), (bonnet_r, bonnet_t),
        (neck_r, bonnet_t + (neck_top - bonnet_y - bonnet_t) * 0.35),
        (neck_r, neck_top - bonnet_y - pack_h * 0.9),
        (pack_d / 2.0 + 2.0, neck_top - bonnet_y - pack_h * 0.9),
        (pack_d / 2.0 + 2.0, neck_top - bonnet_y), (0, neck_top - bonnet_y),
    ], P.SECTIONS), "y")
    bonnet = P.translate(bonnet, 0, bonnet_y, 0)
    bcuts = [P.to_axis(P.cylinder(stem_d / 2.0 + 0.3, neck_top + P.EPS, 0.0), "y"),
             P.to_axis(P.cylinder(pack_d / 2.0, pack_h,
                                  neck_top - pack_h + P.EPS), "y"),
             P.to_axis(P.cylinder(chamber_r * 0.82, bonnet_t * 0.5,
                                  bonnet_y - P.EPS), "y")]
    for (x, y) in P.bolt_circle(bonnet_pcd, 4, 45):
        bcuts.append(P.translate(P.to_axis(
            P.cylinder(bb_d / 2.0 + 0.3, bonnet_t + 2 * P.EPS, bonnet_y - P.EPS,
                       sections=20), "y"), x, 0, y))
    bonnet = P.cut(bonnet, *bcuts)
    assembly.add(Part(
        id="kapak", name="Kapak (bonnet)", mesh=bonnet, material=body_mat,
        group="housing",
        note="Gövdeyi kapatan ve mil salmastrasını taşıyan kapak; dört cıvatayla "
             "sıkılır, altında düz conta vardır.",
        placements=[at(axis=(0, 1, 0), distance=0.60, stage=2)]))

    assembly.add(Part(
        id="kapak_contasi", name="Kapak contası",
        mesh=P.translate(P.to_axis(P.tube(chamber_r * 0.84, bonnet_pcd / 2.0 - bb_d,
                                          gasket_t, 0.0), "y"), 0, bonnet_y - gasket_t, 0),
        material=seal_mat, group="seal",
        note="Kapak ile gövde arasındaki düz conta.",
        placements=[at(axis=(0, 1, 0), distance=0.48, stage=3)]))

    # --- mil, salmastra, volan ---------------------------------------------- #
    stem_pitch = max(2.0, stem_d * 0.18)
    stem_len = neck_top + travel + stem_d * 2.2 - br * 0.9
    stem = P.union(
        P.cylinder(stem_d / 2.0, br * 1.5, br * 0.55),
        P.box(stem_d * 1.15, stem_d * 0.5, br * 0.75, (0, 0, br * 0.9)),
        P.threaded_rod(stem_d, stem_pitch, stem_len - br * 2.05, br * 2.05),
    )
    assembly.add(Part(
        id="mil", name="Mil (yükselen)", mesh=P.to_axis(stem, "y"), material=trim_mat,
        group="internal", standard=f"Trapez diş ~{stem_pitch:.1f} mm hatve",
        note=f"Yükselen mil; volan döndükçe sürgüyü {travel:.0f} mm kaldırır. "
             f"Alt ucundaki T başı sürgü yuvasına oturur.",
        placements=[at(axis=(0, 1, 0), distance=0.75, stage=4)]))

    assembly.add(Part(
        id="salmastra", name="Mil salmastrası",
        mesh=P.translate(P.to_axis(P.tube(stem_d / 2.0 + 0.2, pack_d / 2.0 - 0.2,
                                          pack_h * 0.38, 0.0), "y"),
                         0, neck_top - pack_h + 0.5, 0),
        material="graphite", group="seal",
        note="Grafit salmastra; mil çevresini sızdırmaz yapar.",
        placements=[at(axis=(0, 1, 0), distance=0.88, stage=4, suffix="1"),
                    at(0, pack_h * 0.40, 0, axis=(0, 1, 0), distance=0.94,
                       stage=4, suffix="2")]))

    gland_t = max(7.0, bb_d * 0.8)
    gland = P.to_axis(P.tube(stem_d / 2.0 + 0.4, pack_d / 2.0 + 5.0, gland_t, 0.0), "y")
    assembly.add(Part(
        id="salmastra_bilezigi", name="Salmastra bileziği",
        mesh=P.translate(gland, 0, neck_top - gland_t * 0.25, 0), material=trim_mat,
        group="internal", note="Salmastrayı bastıran bilezik.",
        placements=[at(axis=(0, 1, 0), distance=1.00, stage=4)]))

    wheel_d = max(110.0, dn * 2.6)
    wheel_y = neck_top + travel + stem_d * 0.9
    assembly.add(Part(
        id="volan", name="Volan",
        mesh=P.translate(P.to_axis(P.handwheel(wheel_d, stem_d * 1.05), "y"),
                         0, wheel_y, 0),
        material="cast_iron" if body_mat != "stainless_cast" else trim_mat,
        group="actuator", note=f"Ø{wheel_d:.0f} mm el çarkı.",
        placements=[at(axis=(0, 1, 0), distance=1.22, stage=5)]))

    yn_h = std.metric(yoke_nut)[4]
    assembly.add(Part(
        id="volan_somunu", name="Volan somunu",
        mesh=P.translate(P.to_axis(P.hex_nut(yoke_nut, 0.0), "y"),
                         0, wheel_y + stem_d * 0.55, 0),
        material=trim_mat, group="fastener", standard=f"DIN 934 {yoke_nut}",
        note="Volanı mile sabitleyen somun.",
        placements=[at(axis=(0, 1, 0), distance=1.40, stage=5)]))

    # --- kapak cıvataları ---------------------------------------------------- #
    bolt_len = math.ceil((bonnet_t * 2 + gasket_t + 6) / 5.0) * 5.0
    bolt_xy = P.bolt_circle(bonnet_pcd, 4, 45)
    # Govde delikleri kor (disli) oldugu icin civata asagi dogru girer, somun yok.
    assembly.add(Part(
        id="kapak_civatasi", name="Kapak cıvatası",
        mesh=_down_bolt(bonnet_bolt, bolt_len, bonnet_y + bonnet_t),
        material=bolt_mat, group="fastener",
        standard=f"DIN 933 {bonnet_bolt}×{bolt_len:.0f}",
        note="Kapağı gövdeye sıkan cıvata; gövdedeki dişli kör deliğe iner.",
        placements=[at(x, 0, y, axis=(0, 1, 0), distance=1.05, stage=1,
                       suffix=str(i)) for i, (x, y) in enumerate(bolt_xy, 1)]))

    assembly.warnings.extend(P.warnings())
    return assembly


def _down_bolt(size: str, length: float, top_y: float):
    """Başı üstte, gövdesi aşağı inen cıvata (kör dişli deliğe giren bağlantı)."""
    return P.translate(P.rotate(P.to_axis(P.hex_bolt(size, length, 0.0), "y"),
                                180, "x"), 0, top_y, 0)


def _ends(end: str, dn: int, flange: std.Flange, length: float, body_r: float,
          bore: float):
    """İki uçtaki bağlantı gövdeleri (flanş / dişli boss / kaynak ağzı)."""
    half = length / 2.0
    if end == "flanged":
        one = P.revolve([
            (0, half - flange.thickness - max(8.0, dn * 0.18)),
            (flange.hub / 2.0, half - flange.thickness - max(8.0, dn * 0.18)),
            (flange.hub / 2.0, half - flange.thickness),
            (flange.od / 2.0, half - flange.thickness),
            (flange.od / 2.0, half), (0, half)], P.SECTIONS)
        one = P.cut(one, *[P.translate(
            P.cylinder(flange.bolt_hole / 2.0, flange.thickness * 2 + 2 * P.EPS,
                       half - flange.thickness * 1.5, sections=24), x, y, 0)
            for x, y in P.bolt_circle(flange.bolt_circle, flange.bolt_count,
                                      180.0 / flange.bolt_count)])
    else:
        r = std.pipe_od(dn) / 2.0 + max(4.0, bore * 0.12)
        one = P.revolve([(0, half - max(16.0, bore * 0.45)),
                         (max(r, body_r * 0.8), half - max(16.0, bore * 0.45)),
                         (r, half - 2.0), (r - 1.6, half), (0, half)], P.SECTIONS)
    return P.union(one, P.mirror(one, "z"))
