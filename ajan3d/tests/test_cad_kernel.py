"""Katı modelleme çekirdeği: her parça kapalı bir katı mı, ölçüler doğru mu.

Bu dosyanın varlık sebebi projenin asıl kusurunun tekrarını engellemek. Önceki
mimaride model bir **kabuktu**: içi boştu, parçalandığında kâğıt gibi yırtılıyordu.
Buradaki testler tam bu özelliği kilitliyor — `is_watertight` ve pozitif hacim,
"içi dolu" olmanın ölçülebilir karşılığıdır. Hacim ölçülemezse kütle de
hesaplanamaz, yani sunum sayfasındaki kütle sütunu aynı zamanda bir doğrulamadır.
"""
import math

import pytest

from cad import materials, primitives as P, standards as std


# --------------------------------------------------------------------------- #
# İlkeller
# --------------------------------------------------------------------------- #

def test_revolve_is_solid_with_expected_volume():
    tube = P.tube(10, 20, 30)
    assert tube.is_watertight and tube.is_volume
    exact = math.pi * (20 ** 2 - 10 ** 2) * 30
    assert tube.volume == pytest.approx(exact, rel=0.01)   # çokgen yaklaşımı


def test_clockwise_profile_is_corrected_not_inverted():
    """Saat yönünde verilen profil sessizce içi dışına dönük katı üretiyordu."""
    ccw = P.revolve([(5, 0), (10, 0), (10, 8), (5, 8)])
    cw = P.revolve([(5, 0), (5, 8), (10, 8), (10, 0)])
    assert cw.is_watertight and cw.volume > 0
    assert cw.volume == pytest.approx(ccw.volume, rel=1e-6)


def test_plate_with_holes_is_solid_and_holes_remove_material():
    holes = [(x, y, 9.0) for x, y in P.bolt_circle(125, 4, 45)]
    plain = P.disc(82.5, 20, bore=50)
    drilled = P.disc(82.5, 20, bore=50, holes=holes)
    assert drilled.is_watertight and drilled.is_volume
    removed = plain.volume - drilled.volume
    assert removed == pytest.approx(4 * math.pi * 9 ** 2 * 20, rel=0.02)


@pytest.mark.parametrize("size", ["M5", "M6", "M8", "M10", "M12", "M16", "M20",
                                  "M24", "M27", "M30"])
def test_every_nut_is_a_closed_solid(size):
    nut = P.hex_nut(size)
    assert nut.is_watertight and nut.volume > 0


@pytest.mark.parametrize("length", [20, 25, 35, 39, 45, 65, 70, 95, 120])
def test_bolt_lengths_stay_solid(length):
    """M16x39 bir ara dişin profili geri dönüyor ve katıyı deliyordu."""
    bolt = P.hex_bolt("M16", float(length))
    assert bolt.is_watertight, f"{length} mm cıvata su geçirmez değil"
    assert bolt.volume > 0


def test_thread_profile_stays_inside_requested_length():
    profile = P.thread_profile(16, 2.0, 39.0, z0=5.0, external=True)
    zs = [z for _, z in profile]
    assert zs == sorted(zs)                       # geri dönüş yok
    assert min(zs) == pytest.approx(5.0)
    assert max(zs) == pytest.approx(44.0)
    radii = {round(r, 4) for r, _ in profile}
    assert len(radii) == 2                        # tepe ve dip


def test_boolean_difference_actually_removes_material():
    base = P.cylinder(20, 50)
    drilled = P.cut(base, P.cylinder(8, 60, -5))
    assert drilled.is_watertight
    assert drilled.volume < base.volume
    assert drilled.volume == pytest.approx(
        base.volume - math.pi * 8 ** 2 * 50, rel=0.02)


def test_boolean_failure_is_recorded_not_raised():
    """Boolean çökerse zincir durmamalı; uyarı kaydedilip yedek yol kullanılır."""
    P.clear_warnings()
    broken = P.box(10, 10, 10)
    broken.faces = broken.faces[:4]               # artık kapalı değil
    result = P.cut(P.cylinder(20, 20), broken)
    assert result is not None and len(result.faces) > 0
    assert P.warnings(), "boolean düşüşü sessizce yutulmamalı"
    P.clear_warnings()


def test_mirror_keeps_outward_normals():
    original = P.cone(20, 8, 30)
    flipped = P.mirror(original, "z")
    assert flipped.is_watertight
    assert flipped.volume == pytest.approx(original.volume, rel=1e-6)


# --------------------------------------------------------------------------- #
# Standart tablolar
# --------------------------------------------------------------------------- #

def test_flange_table_matches_en_1092_1():
    f = std.flange(50, 40)
    assert (f.od, f.bolt_circle, f.bolt_count, f.bolt_size) == (165.0, 125.0, 4, "M16")
    f100 = std.flange(100, 16)
    assert (f100.od, f100.bolt_circle, f100.bolt_count) == (220.0, 180.0, 8)


def test_flange_bolt_holes_fit_inside_the_plate():
    """Delik dairesi + delik yarıçapı flanşın dışına taşmamalı."""
    for dn in std.DN_LIST:
        for pn in (16, 40):
            f = std.flange(dn, pn)
            assert f.bolt_circle / 2 + f.bolt_hole / 2 < f.od / 2, f"DN{dn} PN{pn}"
            assert f.raised_face < f.bolt_circle - f.bolt_hole


@pytest.mark.parametrize("text,dn", [
    ("Paslanmaz 3 parçalı küresel vana DN50 PN40", 50),
    ('2" ball valve', 50),
    ('1 1/2" flanged', 40),
    ("3 inch butterfly", 80),
    ("80 mm hat", 80),
])
def test_dn_parsing(text, dn):
    assert std.parse_dn(text) == dn


@pytest.mark.parametrize("text,pn", [("PN 40", 40), ("Class 300", 40),
                                     ("1000 WOG", 63), ("16 bar", 16)])
def test_pn_parsing(text, pn):
    assert std.parse_pn(text) == pn


def test_explicit_field_beats_marketing_copy():
    """Tanıtım cümlesindeki kelimeler açık alanı ezmemeli.

    Ölçülen hata: "ISO 5211 montaj flanşlı" ifadesi, bağlantı tipi alanı
    açıkça "dişli" dediği hâlde vanayı flanşlı kurduruyordu; "pnömatik
    aktüatör takılabilir" cümlesi de kollu vanaya volan taktırıyordu.
    """
    blurb = ("Üst kısmındaki ISO montaj flanşı sayesinde pnömatik veya "
             "elektrikli aktüatör takılmaya hazırdır.")
    assert std.parse_end("dişli", blurb) == "threaded"
    assert std.parse_actuation("kol", blurb) == "lever"
    # Açık alan boşsa genel metin yine kullanılır
    assert std.parse_end("", blurb) == "flanged"


def test_metric_table_snaps_to_nearest_size():
    assert std.metric("M16")[0] == 16.0
    assert std.metric("M9")[0] in (8.0, 10.0)
    assert std.metric("")[0] == 10.0


def test_iso5211_pad_grows_with_size():
    pads = [std.mount_pad(dn).pcd for dn in (15, 25, 50, 80, 150)]
    assert pads == sorted(pads)


def test_iso5211_pad_carries_two_hole_patterns():
    """Gercek vanada pabuc tek delik dairesi tasimaz.

    Uretici ayni govdeye hem kucuk hem bir boy buyuk aktuatorun dogrudan
    oturmasini ister; plaka iki takim delikle delinir ve uzerine iki kod da
    damgalanir. Musterinin fotografinda sayilan 8 delik budur.
    """
    pad = std.mount_pad(50)
    assert pad.dual and pad.hole_count == 8
    assert pad.code == "F05" and pad.second_code == "F07"
    assert pad.second_pcd > pad.pcd
    assert pad.label == "F05/F07"


def test_iso5211_largest_size_has_no_second_pattern():
    """Tablonun en ustunde ust boy yok; sozlesme sessizce 4 delige doner."""
    pad = std.mount_pad(400)
    assert not pad.dual and pad.hole_count == 4
    assert pad.label == pad.code


def test_iso5211_dual_can_be_switched_off():
    pad = std.mount_pad(50, dual=False)
    assert pad.hole_count == 4 and pad.second_pcd == 0.0


# --------------------------------------------------------------------------- #
# Malzeme
# --------------------------------------------------------------------------- #

def test_mass_follows_volume_and_density():
    volume = 1_000_000.0                          # 1000 cm³
    assert materials.mass_g(volume, "stainless_cast") == pytest.approx(7980, rel=1e-6)
    assert materials.mass_g(volume, "ptfe") == pytest.approx(2200, rel=1e-6)


def test_material_lookup_from_free_text():
    assert materials.from_text("CF8M döküm gövde") == "stainless_cast"
    assert materials.from_text("AISI 316 paslanmaz") == "stainless_machined"
    assert materials.from_text("pirinç gövde") == "brass"
    assert materials.from_text("hiçbir şey") == materials.DEFAULT


def test_unknown_material_falls_back_without_raising():
    assert materials.get("yok-böyle-bir-şey").key == materials.DEFAULT
