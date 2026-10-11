"""Küresel vana (ball valve) — kütüphanenin referans ailesi.

Akış **Z**, mil **+Y**. Ölçüler DN/PN'den türetilir; uçlar dişli, flanşlı
(EN 1092-1), kaynak ağızlı veya clamp olabilir. 3 parçalı gövdede orta gövde
ile iki kapak dört uzun cıvatayla sıkılır; 2 parçalıda bir uç gövdeye
bütünleşiktir ve diğer uç vidalı kapaktır.

Eksenel düzenin çıkarılışı (DN50 için sayılarla):

* Top dışı küre, içi deliktir: küre yarıçapı `ball_r = 1.44·bore/2 ≈ 36 mm`.
  Delik Z ekseninde açıldığı için topun **eksenel** uzanımı küre yarıçapı
  değil `h = sqrt(ball_r² − (bore/2)²) ≈ 25.9 mm` kadardır — kutuplar zaten
  delinmiştir. Gövde boyu bu sayıdan çıkar; küre çapından hesaplanırsa gövde
  gereğinden 20 mm uzun olur.
* Oturmalar gövdenin silindirik iç boşluğunu iki uçtan doldurur. Ön yüzleri
  top küresiyle **Boolean çıkarma** ile kesilir: oturma yüzeyi gerçekten
  küreseldir ve topa tam oturur. `penetration` temas bandının genişliğini verir.
* Kapak spigot'u oturmanın arkasını destekler, conta spigot çevresini
  sızdırmaz yapar, cıvatalar bütün yığını ön yükler.

X-Ray modunda görülen zincir budur: delik → oturma → top → oturma → delik.
"""
import math
from typing import Dict, Optional

from cad import materials as mat
from cad import primitives as P
from cad import standards as std
from cad.assembly import Assembly, Part, at, ring


ACTUATION_LABEL = {"pneumatic": "pnömatik aktüatör", "electric": "elektrikli aktüatör",
                   "gear": "redüktör", "handwheel": "volan", "lever": "kol"}


def _body_bolt(dn: int) -> str:
    for limit, size in ((25, "M8"), (50, "M10"), (80, "M12"), (150, "M16")):
        if dn <= limit:
            return size
    return "M20"


def _pipe_thread_pitch(dn: int) -> float:
    """Boru dişi hatvesi (NPT / BSP yaklaşık karşılığı)."""
    if dn <= 15:
        return 1.41
    if dn <= 25:
        return 1.81
    if dn <= 50:
        return 2.21
    return 2.31


# --------------------------------------------------------------------------- #
# Patlatma düzeni
# --------------------------------------------------------------------------- #
# Mesafeler montaj KÖŞEGENİNİN oranıdır ve TEK BİR MERDİVEN oluşturur: aynı
# yönde açılan parçalar sökülme sırasına göre artan mesafelerde durur, hiçbiri
# bir diğerinin üstüne binmez.
#
# Önceki sürümde değerler parça parça serpiştirilmişti; sonuç "havada
# mantıksız yerlere uçan" bir dağılımdı. Ölçülen iki somut kusur:
#   * Küre 0,58 köşegen AŞAĞI gidiyordu (DN50'de 181 mm) ve zeminin altına,
#     kadrajın dışına iniyordu.
#   * Uç kapakları 0,72, gövde cıvataları 1,20 ile açılıyordu; patlamış
#     montaj birleşiğinin 3,5 katına çıkıyor ve kamera odanın dışına
#     çekilmek zorunda kalıyordu.
#
# Eksen boyunca (±Z), gövdeden dışarı doğru sökülme sırası:
EX_SEAT = 0.20            # oturma halkası
EX_GASKET = 0.32          # gövde contası
EX_CAP = 0.48             # uç kapağı
EX_BODY_BOLT = 0.75       # saplama ve somunu (kapağın DIŞ çapında kalır)
# Mil ekseninde (+Y), gövdeden yukarı doğru:
EX_STEM = 0.16
EX_PACKING = 0.22         # ikinci halka +0,04
EX_FOLLOWER = 0.30
EX_WASHER = 0.34
EX_GLAND_NUT = 0.38
EX_PAD = 0.46
# Küre AŞAĞI: milin yukarı çıktığı doğrunun devamı. Gövdenin içinden tek bir
# dikey hat hâlinde okunsun diye; yana savrulmuş bir küre hizayı bozuyordu.
# Değer gövdenin tabanını AŞMAK zorunda: 0,18'de küre hâlâ gövdenin içinde
# kalıyordu (ölçüldü: 6.454 mm³ ortak hacim, bkz. Assembly.explode_overlaps).
EX_BALL = 0.34
# Kumanda organı (kol/volan) milin üstünde.
EX_HANDLE = 0.62


def build(params: Dict[str, object]) -> Assembly:
    dn = int(params.get("dn", 50))
    pn = int(params.get("pn", 40))
    pieces = max(1, min(3, int(params.get("pieces", 3))))
    end = str(params.get("end", "threaded"))
    actuation = str(params.get("actuation", "lever"))
    body_mat = str(params.get("body_material", "stainless_cast"))
    trim_mat = str(params.get("trim_material", "stainless_machined"))
    seat_mat = str(params.get("seat_material", "ptfe"))
    seal_mat = str(params.get("seal_material", "ptfe"))
    # Saplamalar çekme (parlak), somunlar işlenmiş: gerçekte de farklı
    # yüzeyler ve sayfada parçaları birbirinden ayıran en güçlü ipucu bu.
    bolt_mat = str(params.get("bolt_material", "stainless_bright"))
    nut_mat = str(params.get("nut_material", "stainless_machined"))
    grip_mat = str(params.get("grip_material", "vinyl_red"))
    reduced = bool(params.get("reduced_port", False))

    P.clear_warnings()
    flange = std.flange(dn, pn)
    iso = std.mount_pad(dn)
    bolted = pieces == 3

    # --- temel ölçüler ---------------------------------------------------- #
    bore = dn * (0.78 if reduced else 1.0)
    br = bore / 2.0
    ball_r = br * 1.44
    cav_r = ball_r + 0.6
    seat_or = cav_r - 0.25
    seat_t = max(4.5, bore * 0.12)
    penetration = max(1.4, seat_t * 0.30)
    h_axial = math.sqrt(max(1.0, ball_r ** 2 - br ** 2))
    length = 2.0 * (seat_t + h_axial - penetration)
    zc = length / 2.0
    wall = max(5.0, bore * 0.14)
    body_r = cav_r + wall

    bolt_size = _body_bolt(dn)
    bolt_d = std.metric(bolt_size)[0]
    pad_t = max(9.0, bolt_d * 1.15)
    bolt_pcd_r = body_r + bolt_d * 0.72
    pad_w = max(body_r, bolt_pcd_r / math.sqrt(2.0) + bolt_d * 0.95)
    bolt_xy = [(bolt_pcd_r * math.cos(math.radians(a)),
                bolt_pcd_r * math.sin(math.radians(a))) for a in (45, 135, 225, 315)]
    gasket_t = max(1.8, bore * 0.035)

    # --- mil / boyun ölçüleri --------------------------------------------- #
    stem_d = max(9.0, bore * 0.26)
    collar_d = stem_d * 1.52
    collar_t = stem_d * 0.38
    blade_w = min(bore * 0.64, stem_d * 1.18)
    blade_t = stem_d * 0.46
    blade_len = ball_r * 0.52
    pack_d = stem_d * 1.42
    pack_h = max(7.0, stem_d * 1.05)
    neck_r = pack_d / 2.0 + max(4.0, stem_d * 0.5)

    iso_bolt_d = std.metric(iso.bolt_size)[0]
    iso_bolt2_d = std.metric(iso.second_bolt_size)[0] if iso.dual else 0.0
    # Pabuç KARE ve çift delikli (bkz. std.MountPad). Kenar ölçüsü BİRİNCİL
    # pabucunkidir; ikincil (büyük) takımın delikleri aynı plakaya köşegen
    # üzerinde sığar — fotoğrafta da öyle: dört büyük delik köşelere yakın,
    # kenar payı dar.
    #
    # İkincil pabucun ölçüsünü taban almak (86 mm) plakayı gövdeden geniş
    # yapıyor ve 3/4 görünüşte vananın tamamını örtüyordu; ölçüldü: gerçek
    # üründe plaka gövde boyunun ~%60'ı, yani F05 pabucu kadar.
    pad_half = max(iso.pad / 2.0,
                   (max(iso.pcd, iso.second_pcd) / 2.0) / math.sqrt(2.0)
                   + max(iso_bolt_d, iso_bolt2_d) * 0.75)
    pad_r = pad_half * math.sqrt(2.0)          # köşeye kadar olan yarıçap
    iso_t = max(8.0, max(iso_bolt_d, iso_bolt2_d) * 1.6)
    # Dikey sıra fotoğraftan: konik boyun -> salmastra bosu + somunu ->
    # EN ÜSTTE kare pabuç. Önceki sürümde pabuç ortadaydı ve üstünde dişli
    # bir mil ucu + somun duruyordu; üründe orada hiçbir şey yok, pabuç
    # serbest kalır ve aktüatör doğrudan onun üstüne oturur.
    gland_y0 = body_r + max(6.0, stem_d * 0.55)
    pack_y0 = gland_y0
    neck_top = gland_y0 + pack_h
    # Pabuç bosun omzuna oturur; salmastra somunu pabucun merkez deliğinin
    # İÇİNDE kalır (fotoğrafta plakanın altından görünüyor).
    pad_y0 = neck_top - iso_t * 0.45
    pad_top = pad_y0 + iso_t

    gland_size = f"M{int(round(max(10.0, pack_d + 4.0)))}"
    gland_d, gland_pitch, _, _, gland_nut_h = std.metric(gland_size)
    gland_minor = gland_d / 2.0 - gland_pitch * 0.613
    stem_nut_size = f"M{int(round(max(6.0, stem_d * 0.68)))}"

    assembly = Assembly(
        family="ball_valve",
        label=f"{std.nps_label(dn)} / DN{dn} küresel vana",
        representative=pieces == 1,
        params={"dn": dn, "pn": pn, "pieces": pieces, "end": end,
                "actuation": actuation, "bore_mm": round(bore, 1),
                "ball_dia_mm": round(ball_r * 2, 1),
                "body_length_mm": round(length, 1),
                "body_bolts": bolt_size if bolted else "",
                "iso5211": iso.label, "iso5211_holes": iso.hole_count,
                "iso5211_pad_mm": round(pad_half * 2, 1),
                "reduced_port": reduced},
    )
    if pieces == 1:
        assembly.notes.append(
            "Tek parça gövde bildirildi; model iki parçalı eşdeğer olarak "
            "kuruldu (iç yığın ve ölçüler aynı, gövde ayrımı temsilidir).")

    # --- orta gövde -------------------------------------------------------- #
    body = P.cylinder(body_r, length, 0.0)
    if bolted:
        pads = P.plate(P.rounded_rect_pts(pad_w * 2, pad_w * 2, bolt_d * 1.3), pad_t,
                       0.0, holes=[P.circle_pts(bolt_d * 0.55 + 0.4, 24, x, y)
                                   for x, y in bolt_xy])
        body = P.union(body, pads, P.translate(pads, 0, 0, length - pad_t))

    # Boyun: konik kolon -> salmastra bosu. Pabuç buraya DAHİL DEĞİL;
    # ayrı, pres geçme bir parçadır (aşağıda eklenir).
    neck = P.to_axis(P.revolve([
        (0, body_r * 0.5), (neck_r, body_r * 0.5),
        (neck_r * 0.86, gland_y0 - pack_h * 0.35),
        (neck_r * 0.86, gland_y0),
        (gland_minor, gland_y0), (gland_minor, neck_top), (0, neck_top),
    ], P.SECTIONS), "y")
    body = P.union(body, P.translate(neck, 0, 0, zc))

    # 2 parçalı gövdede B ucu bütünleşik
    if not bolted:
        integral = _end_cap(style="integral", end=end, bore=bore, cav_r=cav_r,
                            body_r=body_r, pad_w=pad_w, pad_t=pad_t, bolt_d=bolt_d,
                            bolt_xy=bolt_xy, gasket_t=gasket_t, flange=flange, dn=dn)
        body = P.union(body, P.translate(integral, 0, 0, length))

    cuts = [
        P.cylinder(cav_r, length + 2 * P.EPS, -P.EPS),
        _y_cyl(collar_d / 2.0 + 0.3, ball_r + 2.0 + collar_t + 0.8, 0.0, zc),
        _y_cyl(stem_d / 2.0 + 0.25, neck_top + P.EPS, 0.0, zc),
        _y_cyl(pack_d / 2.0, pack_h + 2 * P.EPS, pack_y0 - P.EPS, zc),
    ]
    body = P.cut(body, *cuts)
    # Salmastra somununun oturduğu boyun dişi
    body = P.union(body, _y_part(P.threaded_rod(gland_d, gland_pitch, pack_h,
                                                gland_y0), zc))
    body = P.cut(body, _y_cyl(pack_d / 2.0, pack_h + 2 * P.EPS, pack_y0 - P.EPS, zc))

    assembly.add(Part(
        id="govde", name="Orta gövde" if bolted else "Gövde", mesh=body,
        material=body_mat, group="housing", standard="ASME B16.34 / EN 12516",
        note=f"Döküm gövde; iç boşluk Ø{cav_r * 2:.0f} mm, omuzlu mil yuvası "
             f"(blow-out proof); boynun üstünde salmastra bosu, onun da "
             f"üstünde ayrı bir ISO 5211 {iso.label} montaj pabucu oturur.",
        placements=[at(stage=0, distance=0.0)]))

    # --- ISO 5211 montaj pabucu (ayrı, pres geçme parça) ------------------- #
    # Üründe plaka gövdeye kaynaklı ya da cıvatalı değil; boynun omzuna
    # çekiçle geçirilmiş bağımsız bir parçadır. Ayrı parça olması aynı
    # zamanda doğru: patlatıldığında aktüatörle birlikte yukarı çıkar ve
    # parça listesinde kendi adıyla görünür.
    pad = _mount_pad(iso, pad_half, iso_t, pad_y0)
    pad_bore = max(pack_d / 2.0 + 1.2, neck_r * 0.52)
    pad = P.cut(pad, P.to_axis(
        P.cylinder(pad_bore, iso_t + 2 * P.EPS, pad_y0 - P.EPS), "y"))
    for pcd, hole_d in ((iso.pcd, iso_bolt_d), (iso.second_pcd, iso_bolt2_d)):
        if pcd <= 0 or hole_d <= 0:
            continue
        for (x, y) in P.bolt_circle(pcd, 4, 45):
            pad = P.cut(pad, P.translate(P.to_axis(
                P.cylinder(hole_d / 2.0, iso_t * 0.82,
                           pad_y0 + iso_t * 0.18 + P.EPS, sections=20), "y"),
                x, 0, y))
    assembly.add(Part(
        id="montaj_pabucu", name="ISO 5211 montaj pabucu",
        mesh=P.translate(pad, 0, 0, zc), material=trim_mat, group="housing",
        standard=f"ISO 5211 {iso.label}",
        note=f"Kare pabuç, {iso.hole_count} delik "
             f"({iso.bolt_size}@Ø{iso.pcd:.0f}" +
             (f" + {iso.second_bolt_size}@Ø{iso.second_pcd:.0f}"
              if iso.dual else "") + " mm). Boynun omzuna pres geçer; "
             "aktüatör doğrudan bunun üstüne bağlanır.",
        placements=[at(axis=(0, 1, 0), distance=EX_PAD, stage=5)]))

    # --- uç kapakları ------------------------------------------------------ #
    cap = _end_cap(style="bolted" if bolted else "screwed", end=end, bore=bore,
                   cav_r=cav_r, body_r=body_r, pad_w=pad_w, pad_t=pad_t,
                   bolt_d=bolt_d, bolt_xy=bolt_xy, gasket_t=gasket_t,
                   flange=flange, dn=dn)
    cap_note = {
        "threaded": f"İç dişli uç ({std.nps_label(dn)} boru dişi); oturma yuvası "
                    f"ve conta spigot'u ile birlikte tek parça.",
        "flanged": f"EN 1092-1 PN{pn} flanşlı uç: Ø{flange.od:.0f} mm, "
                   f"{flange.bolt_count}×{flange.bolt_size}, delik dairesi "
                   f"Ø{flange.bolt_circle:.0f} mm, conta yüzeyi Ø"
                   f"{flange.raised_face:.0f} mm.",
        "welded": "Kaynak ağızlı uç; boru et kalınlığına uygun 37.5° pah.",
        "clamp": "Clamp (ferrule) uç.",
    }.get(end, "Bağlantı kapağı")
    cap_places = [at(0, 0, -gasket_t, axis=(0, 0, -1), distance=EX_CAP, stage=7,
                     suffix="1" if bolted else "", rotation=(180, "y"))]
    if bolted:
        cap_places.append(at(0, 0, length + gasket_t, axis=(0, 0, 1), distance=EX_CAP,
                             stage=7, suffix="2"))
    assembly.add(Part(
        id="kapak", name="Uç kapağı", mesh=cap, material=body_mat, group="housing",
        standard="EN 1092-1" if end == "flanged" else "ASME B1.20.1",
        note=cap_note, placements=cap_places))

    # --- top --------------------------------------------------------------- #
    ball = P.cut(P.sphere(ball_r, 4),
                 P.cylinder(br, ball_r * 3.0, -ball_r * 1.5),
                 P.box(blade_w, blade_len * 2.0, blade_t, (0, ball_r, 0)))
    assembly.add(Part(
        id="top", name="Küre (top)", mesh=P.translate(ball, 0, 0, zc),
        material="stainless_polished", group="internal",
        note=f"{'Tam' if not reduced else 'Daraltılmış'} geçişli küre, delik "
             f"Ø{bore:.0f} mm, parlatılmış yüzey; üstte mil dili kanalı.",
        placements=[at(axis=(0, -1, 0), distance=EX_BALL, stage=8)]))

    # --- oturmalar ve contalar ---------------------------------------------- #
    seat = P.cut(P.tube(br, seat_or, seat_t, 0.0),
                 P.translate(P.sphere(ball_r, 4), 0, 0, zc))
    assembly.add(Part(
        id="oturma", name="Oturma halkası (seat)", mesh=seat, material=seat_mat,
        group="seal",
        note=f"{mat.get(seat_mat).label}; ön yüzü top küresiyle kesilmiş, "
             f"temas bandı {penetration:.1f} mm bastırma ile oluşuyor.",
        placements=[
            at(0, 0, 0, axis=(0, 0, -1), distance=EX_SEAT, stage=8, suffix="1"),
            at(0, 0, length, axis=(0, 0, 1), distance=EX_SEAT, stage=8, suffix="2",
               rotation=(180, "y")),
        ]))

    gasket_or = min(body_r - 1.5, cav_r + max(5.0, bore * 0.12))
    gasket = P.tube(cav_r + 0.4, gasket_or, gasket_t, 0.0)
    gasket_places = [at(0, 0, -gasket_t, axis=(0, 0, -1), distance=EX_GASKET, stage=8,
                        suffix="1" if bolted else "")]
    if bolted:
        gasket_places.append(at(0, 0, length, axis=(0, 0, 1), distance=EX_GASKET,
                                stage=8, suffix="2"))
    assembly.add(Part(
        id="govde_contasi", name="Gövde contası", mesh=gasket, material=seal_mat,
        group="seal",
        note="Kapak ile gövde arasındaki düz conta; spigot çevresini sızdırmaz yapar.",
        placements=gasket_places))

    # --- mil yığını --------------------------------------------------------- #
    gland_top = gland_y0 + gland_nut_h
    stack = _stem_stack(
        assembly, stem_d=stem_d, collar_d=collar_d, collar_t=collar_t,
        blade_w=blade_w, blade_t=blade_t, blade_len=blade_len, ball_r=ball_r,
        pack_d=pack_d, pack_h=pack_h, pack_y0=pack_y0, gland_y0=gland_y0,
        gland_size=gland_size, gland_top=gland_top, pad_top=pad_top,
        zc=zc, trim_mat=trim_mat)

    # --- kumanda ------------------------------------------------------------ #
    drive_y = stack["drive_y"]
    drive_len = stack["drive_len"]
    if actuation in std.NO_ACTUATOR:
        # Çıplak milli vana: kumanda organı çizilmez. Mil ucundaki
        # düzleştirilmiş yuva ve ISO 5211 pabucu arayüzü zaten anlatıyor.
        assembly.notes.append(
            "Vana çıplak milli olarak modellendi (kol/volan takılı değil); "
            f"kumanda ISO 5211 {iso.label} pabucundan bağlanır."
            if actuation == "none" else
            f"Kumanda {ACTUATION_LABEL.get(actuation, actuation)} olarak "
            f"bildirildi; aktüatör ayrı bir ürün olduğu için montaja dahil "
            f"edilmedi, bağlantı ISO 5211 {iso.label} pabucundan yapılır.")
    elif actuation == "pneumatic":
        # Aktüatör pabucun ÜSTÜNE oturur; ölçüleri pabuç kenarından türetilir
        # (bkz. cad/actuator.py). Vananın parçası değil, ona monte edilen
        # bağımsız bir ürün — bu yüzden ayrı bir modülde duruyor.
        from cad import actuator

        for part in actuator.build(pad_top=pad_top, pad_half=pad_half,
                                   stem_d=stem_d, zc=zc):
            assembly.add(part)
        assembly.notes.append(
            "Pnömatik aktüatör, ISO 5211 "
            f"{iso.label} pabucuna monte edilmiş olarak modellendi; "
            "yay geri dönüşlü/çift etkili kremayer-pinyon tipi.")
    elif actuation in ("handwheel", "gear"):
        wheel = _y_part(P.handwheel(max(90.0, dn * 2.6), stem_d * 0.96), zc,
                        y=drive_y)
        assembly.add(Part(
            id="volan", name="Volan", mesh=wheel, material=trim_mat,
            group="actuator", note="El çarkı; mil üstündeki düzleştirilmiş "
                                   "yuvaya oturur.",
            placements=[at(axis=(0, 1, 0), distance=EX_HANDLE, stage=9)]))
    else:
        arm, sleeve = P.lever(max(85.0, dn * 2.9), max(18.0, stem_d * 2.0),
                              max(4.5, stem_d * 0.42), stem_d * 1.28, stem_d * 0.96)
        assembly.add(Part(
            id="kol", name="Kumanda kolu", mesh=_y_part(arm, zc, y=drive_y),
            material=trim_mat, group="actuator",
            note="90° çeyrek tur kol; mil üstündeki düzleştirilmiş yuvaya oturur.",
            placements=[at(axis=(0, 1, 0), distance=EX_HANDLE, stage=9)]))
        assembly.add(Part(
            id="kol_kilifi", name="Kol kılıfı", mesh=_y_part(sleeve, zc, y=drive_y),
            material=grip_mat, group="actuator", note="Vinil kavrama kılıfı.",
            placements=[at(axis=(0, 1, 0), distance=EX_HANDLE + 0.10, stage=9)]))
        pin = _y_cyl(max(2.2, stem_d * 0.22), drive_len * 1.4, 0.0, zc,
                     sections=20)
        assembly.add(Part(
            id="durdurma_pimi", name="Durdurma pimi",
            mesh=P.translate(pin, pad_r * 0.68, gland_y0 - drive_len * 0.2, 0),
            material=trim_mat, group="actuator",
            note="Kolun 90°'den fazla dönmesini engelleyen pim.",
            placements=[at(axis=(0, 1, 0), distance=EX_HANDLE - 0.18, stage=9)]))

    # --- gövde cıvataları ---------------------------------------------------- #
    if bolted:
        span = 2.0 * (gasket_t + pad_t) + length
        bolt_len = math.ceil((span + 3.0) / 5.0) * 5.0
        assembly.add(Part(
            id="govde_civatasi", name="Gövde cıvatası",
            mesh=P.hex_bolt(bolt_size, bolt_len, -(gasket_t + pad_t)),
            material=bolt_mat, group="fastener",
            standard=f"DIN 931 {bolt_size}×{bolt_len:.0f}",
            note=f"{bolt_size}×{bolt_len:.0f} mm; iki kapağı ve orta gövdeyi "
                 f"birlikte sıkar, oturma ön yükünü verir.",
            placements=ring(bolt_xy, 0.0, axis=(0, 0, -1), distance=EX_BODY_BOLT, stage=6)))
        assembly.add(Part(
            id="govde_somunu", name="Gövde somunu",
            mesh=P.hex_nut(bolt_size, -(gasket_t + pad_t) + bolt_len),
            material=nut_mat, group="fastener", standard=f"DIN 934 {bolt_size}",
            note="Altı köşe somun; sıkma torku contayı ve oturmaları ön yükler.",
            placements=ring(bolt_xy, 0.0, axis=(0, 0, 1), distance=EX_BODY_BOLT, stage=6)))

    assembly.warnings.extend(P.warnings())
    assembly.notes.append(
        f"Gövde iç boyu {length:.1f} mm; topun eksenel uzanımı {h_axial * 2:.1f} mm "
        f"(küre Ø{ball_r * 2:.1f} mm, delik Ø{bore:.0f} mm).")
    return assembly


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #

def _y_part(mesh, zc: float, y: float = 0.0):
    """Z ekseninde kurulmuş parçayı mil eksenine (+Y) çevirip yerine koyar."""
    return P.translate(P.to_axis(mesh, "y"), 0, y, zc)


def _y_cyl(radius: float, height: float, y0: float, zc: float,
           sections: int = P.SECTIONS):
    return _y_part(P.cylinder(radius, height, y0, sections=sections), zc)


def _mount_pad(iso: std.MountPad, half: float, thickness: float, y0: float):
    """Kare ISO 5211 pabucu (yerel eksen Z; çağıran "y" eksenine çevirir).

    Fotoğraftaki plakanın iki karşılıklı kenarının ortasında dökümden gelen
    birer kanal var; düz bir kare plaka o yüzden eksik duruyor. Kanallar
    plakanın konturuna işleniyor, sonradan kesilmiyor — kalıpla açılan delik
    gibi, tek Boolean'la.
    """
    notch_w = half * 0.42
    notch_d = half * 0.30
    outline = [
        (half, -half), (half, -notch_w / 2.0),
        (half - notch_d, -notch_w / 2.0), (half - notch_d, notch_w / 2.0),
        (half, notch_w / 2.0), (half, half),
        (-half, half), (-half, notch_w / 2.0),
        (-half + notch_d, notch_w / 2.0), (-half + notch_d, -notch_w / 2.0),
        (-half, -notch_w / 2.0), (-half, -half),
    ]
    pad = P.plate(outline, thickness, 0.0)
    return P.to_axis(P.translate(pad, 0, 0, y0), "y")


def _end_cap(*, style: str, end: str, bore: float, cav_r: float, body_r: float,
             pad_w: float, pad_t: float, bolt_d: float, bolt_xy, gasket_t: float,
             flange: std.Flange, dn: int):
    """Uç kapağı. Yerel eksen: gövdeye bakan yüz z=0, kapak +z yönünde uzar.

    `style`: bolted (3 parçalı, kare pabuç + 4 delik) | screwed (yuvarlak,
    gövdeye vidalanan) | integral (gövdeye kaynaşan, pabuçsuz).
    """
    br = bore / 2.0
    spigot_len = gasket_t + 0.4

    if end == "flanged":
        boss_len = flange.thickness + max(10.0, dn * 0.22)
        outer = flange.od / 2.0
    elif end == "welded":
        boss_len = max(16.0, dn * 0.34)
        outer = std.pipe_od(dn) / 2.0 + max(3.5, bore * 0.09)
    elif end == "clamp":
        boss_len = max(14.0, dn * 0.30)
        outer = std.pipe_od(dn) / 2.0 + max(5.0, bore * 0.14)
    else:
        boss_len = max(18.0, bore * 0.52)
        outer = std.pipe_od(dn) / 2.0 + max(4.5, bore * 0.13)

    parts = []
    base_t = pad_t
    if style == "bolted":
        parts.append(P.plate(P.rounded_rect_pts(pad_w * 2, pad_w * 2, bolt_d * 1.3),
                             pad_t, 0.0,
                             holes=[P.circle_pts(bolt_d * 0.55 + 0.4, 24, x, y)
                                    for x, y in bolt_xy]))
    elif style == "screwed":
        parts.append(P.hex_prism(body_r * 1.98, pad_t, 0.0))
    else:
        base_t = 0.0
    if style != "integral":
        parts.append(P.cylinder(cav_r, spigot_len + P.EPS, -spigot_len))

    if end == "flanged":
        parts.append(P.revolve([
            (0, base_t - P.EPS), (max(outer * 0.52, flange.hub / 2.0), base_t - P.EPS),
            (flange.hub / 2.0, base_t + boss_len - flange.thickness),
            (outer, base_t + boss_len - flange.thickness),
            (outer, base_t + boss_len), (0, base_t + boss_len),
        ], P.SECTIONS))
        parts.append(P.tube(br, flange.raised_face / 2.0, 2.0, base_t + boss_len))
        cap = P.union(*parts)
        cap = P.cut(cap, *[P.translate(P.cylinder(flange.bolt_hole / 2.0,
                                                  boss_len + 2 * P.EPS,
                                                  base_t - P.EPS, sections=24), x, y, 0)
                           for x, y in P.bolt_circle(flange.bolt_circle,
                                                     flange.bolt_count,
                                                     180.0 / flange.bolt_count)])
        total = base_t + boss_len + 2.0
    else:
        parts.append(P.revolve([
            (0, base_t - P.EPS), (max(outer, body_r * 0.72), base_t - P.EPS),
            (outer, base_t + boss_len * 0.22), (outer, base_t + boss_len - 1.6),
            (outer - 1.6, base_t + boss_len), (0, base_t + boss_len),
        ], P.SECTIONS))
        cap = P.union(*parts)
        total = base_t + boss_len

    cap = P.cut(cap, P.cylinder(br, total + spigot_len + 4 * P.EPS,
                                -spigot_len - P.EPS))
    if end == "threaded":
        thread_len = boss_len * 0.78
        cap = P.cut(cap, P.thread_cutter(std.pipe_od(dn), _pipe_thread_pitch(dn),
                                         thread_len, total - thread_len))
    elif end == "welded":
        cap = P.cut(cap, P.revolve([
            (std.pipe_od(dn) / 2.0 - 1.0, total + P.EPS),
            (outer + 1.0, total - max(4.0, bore * 0.12)),
            (outer + 1.0, total + P.EPS)], 48))
    return cap


def _stem_stack(assembly: Assembly, *, stem_d, collar_d, collar_t, blade_w, blade_t,
                blade_len, ball_r, pack_d, pack_h, pack_y0, gland_y0, gland_size,
                gland_top, pad_top, zc, trim_mat) -> dict:
    """Mil + salmastra + bilezik + salmastra somunu + yaylı rondela.

    **Pabucun üstünde hiçbir şey yok.** Önceki sürümde mil, pabucun üstüne
    dişli bir uzantı ve onun üzerine bir somun taşıyordu; üründe orada yalnız
    milin KARE ucu duruyor. Aktüatörün kovanı doğrudan o kareye geçer —
    araya somun girmesi montajı imkânsız kılardı.
    """
    y_blade0 = ball_r - blade_len
    y_collar0 = ball_r + 1.0
    y_collar1 = y_collar0 + collar_t
    # Kare tahrik pabucun İÇİNDEN geçip üstünde biter. Çıkıntı aktüatörün
    # bağlantı ayağını AŞMALI, yoksa kare uç ayağın içinde kalır ve pinyona
    # girmez (ölçüldü: 0.62 × mil çapı, ayak yüksekliğinin altında kalıyordu).
    # Çıplak milli vanada da doğru: fotoğrafta kare uç pabucun belirgin
    # biçimde üstünde duruyor.
    drive_len = stem_d * 1.55
    y_drive1 = pad_top + stem_d * 1.05
    drive_y = y_drive1 - drive_len

    stem = P.union(
        P.box(blade_w, blade_t, blade_len * 1.04, (0, 0, y_blade0 + blade_len * 0.52)),
        P.cylinder(stem_d / 2.0, y_collar0 - y_blade0 + 0.2, y_blade0),
        P.cylinder(collar_d / 2.0, collar_t, y_collar0),
        P.cylinder(stem_d / 2.0, y_drive1 - y_collar1, y_collar1),
    )
    # KARE tahrik: dört yüzden de kesilir. İki yüz (double-D) kesmek, ISO 5211
    # kovanının kare yuvasına oturmayan bir mil veriyordu; müşterinin
    # fotoğrafında uç açıkça karedir.
    flat = stem_d * 0.76
    far = stem_d * 1.5 + flat / 2.0
    mid = drive_y + drive_len / 2.0
    stem = P.cut(stem, *[
        P.box(stem_d * 3, stem_d * 3, drive_len + 2 * P.EPS, (dx * far, dy * far, mid))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))])

    assembly.add(Part(
        id="mil", name="Mil (stem)", mesh=_y_part(stem, zc), material=trim_mat,
        group="internal",
        note="Omuzlu blow-out proof mil: bilezik gövde omzunun altında kalır, "
             "basınç altında mil dışarı fırlayamaz. Altta topa giren dil, "
             "üstte aktüatör kovanının geçtiği kare uç.",
        placements=[at(axis=(0, 1, 0), distance=EX_STEM, stage=9)]))

    packing = P.tube(stem_d / 2.0 + 0.2, pack_d / 2.0 - 0.15, pack_h * 0.30,
                     pack_y0 + 0.4)
    assembly.add(Part(
        id="salmastra", name="Mil salmastrası", mesh=_y_part(packing, zc),
        material="graphite", group="seal",
        note="Grafit salmastra halkası; mil çevresini sızdırmaz yapar.",
        placements=[at(axis=(0, 1, 0), distance=EX_PACKING, stage=9, suffix="1"),
                    at(0, pack_h * 0.32, 0, axis=(0, 1, 0),
                       distance=EX_PACKING + 0.04, stage=9, suffix="2")]))

    follower = P.tube(stem_d / 2.0 + 0.25, pack_d / 2.0 - 0.2, pack_h * 0.34,
                      pack_y0 + pack_h * 0.68)
    assembly.add(Part(
        id="salmastra_bilezigi", name="Salmastra bileziği",
        mesh=_y_part(follower, zc), material=trim_mat, group="internal",
        note="Salmastrayı eksenel bastıran bilezik (gland follower).",
        placements=[at(axis=(0, 1, 0), distance=EX_FOLLOWER, stage=9)]))

    assembly.add(Part(
        id="salmastra_somunu", name="Salmastra somunu",
        mesh=_y_part(P.hex_nut(gland_size, gland_y0), zc), material=trim_mat,
        group="fastener", standard=f"{gland_size} boyun dişi",
        note="Boyun dişine oturur; sıkıldıkça salmastra ön yükü artar.",
        placements=[at(axis=(0, 1, 0), distance=EX_GLAND_NUT, stage=9)]))

    # Yaylı rondela salmastra somununun ALTINDA: görevi salmastrayı sürekli
    # yüklemek. Önceki sürümde milin tepesinde, somunun altındaydı — oradan
    # salmastraya hiçbir kuvvet aktaramazdı.
    washer = P.belleville(gland_size, gland_y0 - max(0.9, pack_d * 0.09) - 0.3)
    assembly.add(Part(
        id="yayli_rondela", name="Belleville yaylı rondela",
        mesh=_y_part(washer, zc),
        material=trim_mat, group="internal", standard="DIN 2093",
        note="Salmastra somununun altında; sıcaklık değişiminde salmastra ön "
             "yükünü sabit tutan konik yay.",
        placements=[at(axis=(0, 1, 0), distance=EX_WASHER, stage=9)]))

    return {"drive_y": drive_y, "drive_len": drive_len}
