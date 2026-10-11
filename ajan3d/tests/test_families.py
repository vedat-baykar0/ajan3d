"""Her CAD ailesi her ölçüde kapalı, patlatılabilir ve tutarlı bir montaj üretir.

Üç şey kilitleniyor:

* **Katılık.** Montajdaki her parça su geçirmez olmalı. Bu, "içi dolu model"
  vaadinin tek ölçülebilir karşılığı.
* **Patlatma yönleri DIŞA bakmalı.** İçe bakan bir eksen parçaları birbirinin
  içine sürüyor ve patlatılmış görünüm okunmaz hale geliyor.
* **Boolean düşüşü olmamalı.** Düşüş sessizce çalışmaya devam eder ama ortaya
  kesilmemiş delikli, birleşmemiş gövdeli bir model çıkar.
"""
import pytest

from cad import library
from cad.families import (ball_valve, bearing, butterfly_valve, check_valve,
                          flange_joint, gate_valve, generic, strainer)

CASES = [
    ("ball_valve_3pc_threaded", ball_valve,
     {"dn": 50, "pn": 40, "pieces": 3, "end": "threaded", "actuation": "lever"}),
    ("ball_valve_2pc_flanged", ball_valve,
     {"dn": 80, "pn": 16, "pieces": 2, "end": "flanged", "actuation": "handwheel"}),
    ("ball_valve_small", ball_valve, {"dn": 15, "pn": 16, "pieces": 3}),
    ("ball_valve_large", ball_valve, {"dn": 150, "pn": 16, "end": "flanged"}),
    ("ball_valve_welded", ball_valve, {"dn": 40, "pn": 40, "end": "welded"}),
    ("gate", gate_valve, {"dn": 50, "pn": 16, "end": "flanged"}),
    ("gate_threaded", gate_valve, {"dn": 25, "pn": 16, "end": "threaded"}),
    ("globe", gate_valve, {"dn": 65, "pn": 16, "kind": "globe"}),
    ("butterfly_lever", butterfly_valve, {"dn": 80, "pn": 16}),
    ("butterfly_gear", butterfly_valve, {"dn": 150, "pn": 16, "actuation": "gear"}),
    ("check", check_valve, {"dn": 50, "pn": 16, "end": "flanged"}),
    ("strainer", strainer, {"dn": 50, "pn": 16, "end": "flanged"}),
    ("flange_joint", flange_joint, {"dn": 100, "pn": 16}),
    ("bearing", bearing, {"code": "6206"}),
    ("generic", generic, {"size_mm": 140, "label": "Test"}),
]


@pytest.fixture(scope="module", params=CASES, ids=[c[0] for c in CASES])
def built(request):
    name, module, params = request.param
    return name, module.build(params)


def test_every_part_is_a_watertight_solid(built):
    name, assembly = built
    leaking = [p.id for p in assembly.parts if not p.watertight]
    assert not leaking, f"{name}: kapalı olmayan parçalar {leaking}"


def test_every_part_has_positive_mass(built):
    name, assembly = built
    zero = [p.id for p in assembly.parts if p.mass_g <= 0]
    assert not zero, f"{name}: kütlesi sıfır parçalar {zero}"
    assert assembly.mass_g > 0


def test_explode_axes_point_outward(built):
    name, assembly = built
    assert assembly.validate()["explode_outward"], f"{name}: içe bakan patlatma ekseni"


def test_no_boolean_fallbacks(built):
    name, assembly = built
    assert not assembly.warnings, f"{name}: geometri uyarısı {assembly.warnings}"


def test_assembly_has_more_than_one_part(built):
    name, assembly = built
    assert len(assembly.parts) >= 4, f"{name}: patlatmaya değecek parça yok"
    assert assembly.instance_count >= len(assembly.parts)


def test_axes_are_unit_vectors(built):
    name, assembly = built
    for part in assembly.parts:
        for place in part.placements:
            length = sum(v * v for v in place.axis) ** 0.5
            assert abs(length - 1.0) < 1e-6, f"{name}/{part.id}"


def test_stage_zero_part_stays_put(built):
    """Her montajda sabit kalan (aşama 0) tam bir parça olmalı — referans gövde."""
    name, assembly = built
    anchored = [p.id for p in assembly.parts
                if any(pl.stage == 0 and pl.distance == 0 for pl in p.placements)]
    assert anchored, f"{name}: patlatmada sabit kalan gövde yok"


def test_catalog_rows_match_parts(built):
    name, assembly = built
    rows = assembly.catalog()
    assert len(rows) == len(assembly.parts)
    assert all(r["name"] and r["material_label"] for r in rows)
    assert sum(r["total_mass_g"] for r in rows) == pytest.approx(
        assembly.mass_g, rel=1e-3)


def test_dimensions_are_plausible(built):
    """Ölçüler milimetre mertebesinde kalmalı; ölçek hatası burada yakalanır."""
    name, assembly = built
    size = assembly.size_mm
    assert 10 < max(size) < 2000, f"{name}: şüpheli ölçü {size}"
    assert min(size) > 1


# --------------------------------------------------------------------------- #
# Ölçü duyarlılığı
# --------------------------------------------------------------------------- #

def test_ball_valve_scales_with_dn():
    small = ball_valve.build({"dn": 25, "pn": 16})
    large = ball_valve.build({"dn": 100, "pn": 16})
    assert large.mass_g > small.mass_g * 4
    assert large.size_mm[2] > small.size_mm[2]


def test_three_piece_adds_body_bolts():
    two = ball_valve.build({"dn": 50, "pn": 16, "pieces": 2})
    three = ball_valve.build({"dn": 50, "pn": 16, "pieces": 3})
    ids2 = {p.id for p in two.parts}
    ids3 = {p.id for p in three.parts}
    assert "govde_civatasi" in ids3 and "govde_civatasi" not in ids2
    assert next(p for p in three.parts if p.id == "govde_civatasi").qty == 4


def test_ball_bore_matches_nominal_diameter():
    """Tam geçişli vanada top deliği anma çapına eşit olmalı."""
    assembly = ball_valve.build({"dn": 50, "pn": 16})
    assert assembly.params["bore_mm"] == pytest.approx(50.0)
    reduced = ball_valve.build({"dn": 50, "pn": 16, "reduced_port": True})
    assert reduced.params["bore_mm"] < 50.0


def test_flange_joint_uses_table_dimensions():
    assembly = flange_joint.build({"dn": 100, "pn": 16})
    assert assembly.params["flange_od_mm"] == 220.0
    assert assembly.params["bolts"] == "8×M16"
    bolts = next(p for p in assembly.parts if p.id == "civata")
    assert bolts.qty == 8


def test_only_generic_is_marked_representative():
    assert generic.build({"size_mm": 120}).representative
    assert not ball_valve.build({"dn": 50}).representative
    assert not flange_joint.build({"dn": 50}).representative


# --------------------------------------------------------------------------- #
# Kütüphane eşleştirmesi
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("identity,expected", [
    ({"product_name": "Paslanmaz 3 parçalı küresel vana", "family_hint": "ball_valve"},
     "ball_valve"),
    ({"product_name": "Kelebek vana wafer tip", "family_hint": "butterfly_valve"},
     "butterfly_valve"),
    ({"product_name": "Sürgülü vana", "family_hint": "gate_valve"}, "gate_valve"),
    ({"product_name": "Çek valf klapeli", "family_hint": "check_valve"}, "check_valve"),
    ({"product_name": "Y tipi pislik tutucu", "family_hint": "y_strainer"}, "y_strainer"),
    ({"product_name": "Kaynak boyunlu flanş", "family_hint": "flange_joint"},
     "flange_joint"),
    ({"product_name": "6206 rulman", "family_hint": "ball_bearing"}, "ball_bearing"),
])
def test_matcher_picks_expected_family(identity, expected):
    assert library.match(identity).family.id == expected


def test_keywords_can_overrule_a_wrong_hint():
    """Ajan yanılırsa metin düzeltebilmeli."""
    found = library.match({
        "product_name": "Kelebek vana, wafer gövdeli, elastomer gömlekli",
        "type_designation": "butterfly valve wafer",
        "family_hint": "ball_bearing"})
    assert found.family.id == "butterfly_valve"


def test_unknown_product_falls_back_to_representative_assembly():
    found = library.match({"product_name": "Mutfak robotu", "family_hint": "other"})
    assert found.family.id == "generic_housing"
    assert found.confidence == "low"
    assembly, _, _ = library.build({"product_name": "Mutfak robotu",
                                    "family_hint": "other"})
    assert assembly.representative


def test_params_are_derived_from_identity_and_spec():
    identity = {"product_name": "Küresel vana", "family_hint": "ball_valve",
                "type_designation": "3 parçalı tam geçişli küresel vana, dişli uçlu",
                "nominal_size": "DN50", "pressure_rating": "1000 WOG",
                "body_material": "CF8M paslanmaz çelik", "end_connection": "dişli",
                "actuation": "kol", "piece_count": 3}
    spec = {"identified_as": "3 parçalı CF8M küresel vana",
            "specs": [{"label": "Oturma", "value": "TFM 1600"}]}
    found = library.match(identity, spec)
    params = library.params_for(found.family, identity, spec)
    assert params["dn"] == 50
    assert params["pn"] == 63            # 1000 WOG ~ 69 bar
    assert params["end"] == "threaded"
    assert params["actuation"] == "lever"
    assert params["pieces"] == 3
    assert params["body_material"] == "stainless_cast"
    assert params["seat_material"] == "tfm"


def test_build_returns_assembly_match_and_params():
    assembly, found, params = library.build(
        {"product_name": "DN80 kelebek vana", "family_hint": "butterfly_valve"})
    assert assembly.family == "butterfly_valve"
    assert found.confidence in ("high", "medium", "low")
    assert params["dn"] == 80


# --------------------------------------------------------------------------- #
# Kumanda organı
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("text", ["yok", "kolsuz", "çıplak mil", "ciplak mil",
                                  "bare stem", "kol takılı değil"])
def test_bare_stem_is_not_read_as_a_lever(text):
    """'kolsuz' kelimesi 'kol' iceriyor; once lever kuralina takiliyordu."""
    from cad import standards as std
    assert std.parse_actuation(text) == "none"


def test_bare_stem_valve_gets_no_actuator():
    """Canli iste yasandi: vana 'ciplak milli' taninip modele volan takildi.

    Musterinin elindeki urunde kol/volan yoksa modelde de olmamali — bu,
    modeli gozle ayirt edilir bicimde yanlis yapan tek hata turu.
    """
    bare = ball_valve.build({"dn": 50, "pn": 63, "pieces": 3, "actuation": "none"})
    ids = {p.id for p in bare.parts}
    assert not ids & {"kol", "kol_kilifi", "durdurma_pimi", "volan"}
    assert any("çıplak mil" in n for n in bare.notes)
    assert bare.validate()["all_solid"]


def test_actuator_bought_separately_is_not_drawn():
    """Pnomatik/elektrik aktuator ayri bir urun; volan cizmek yaniltici."""
    for act in ("pneumatic", "electric"):
        assembly = ball_valve.build({"dn": 50, "pn": 16, "actuation": act})
        assert "volan" not in {p.id for p in assembly.parts}
        assert any("ISO 5211" in n for n in assembly.notes)


def test_lever_and_handwheel_are_still_drawn():
    lever = {p.id for p in ball_valve.build({"dn": 50, "actuation": "lever"}).parts}
    wheel = {p.id for p in ball_valve.build({"dn": 50, "actuation": "handwheel"}).parts}
    assert {"kol", "kol_kilifi"} <= lever
    assert "volan" in wheel


def test_bare_stem_assembly_still_explodes_cleanly():
    report = ball_valve.build({"dn": 80, "pn": 16, "actuation": "none"}).validate()
    assert report["all_solid"] and report["explode_outward"]
    assert report["explode_spread"] > 1.4


# --------------------------------------------------------------------------- #
# Musterinin fotografindan okunan ayrintilar
# --------------------------------------------------------------------------- #

def _slice_loops(mesh, y):
    """Mesh'in y yuksekligindeki yatay kesitinin kapali konturlari."""
    section = mesh.section(plane_origin=[0.0, float(y), 0.0],
                           plane_normal=[0.0, 1.0, 0.0])
    if section is None:
        return []
    planar, _ = section.to_2D()
    return planar.discrete


@pytest.fixture(scope="module")
def photo_valve():
    """Musterinin urunuyle ayni parametreler (DN50 PN63, 3 parcali, disli)."""
    return ball_valve.build({"dn": 50, "pn": 63, "pieces": 3,
                             "end": "threaded", "actuation": "pneumatic"})


def test_mount_pad_is_a_separate_press_fit_part(photo_valve):
    """Pabuç gövdeye kaynaklı/dökme değil, AYRI bir parça.

    Üründe plaka boynun omzuna çekiçle geçirilmiş bağımsız bir parçadır.
    Ayrı olması sunumda da doğru: patlatıldığında aktüatörle birlikte
    yukarı çıkar ve parça listesinde kendi adıyla görünür.
    """
    pad = next((p for p in photo_valve.parts if p.id == "montaj_pabucu"), None)
    assert pad is not None, "montaj pabucu ayrı bir parça değil"
    assert pad.watertight and pad.mass_g > 0
    assert "ISO 5211" in pad.standard


def test_mount_pad_is_square_with_eight_holes(photo_valve):
    """Pabuç YUVARLAK değil kare, ve 8 delikli.

    İlk sürümde pabuç bir devirme yüzeyiydi (yuvarlak) ve 4 delik
    taşıyordu; müşterinin fotoğrafında plaka açıkça kare ve iki takım
    delikli. Kesitte beklenen kontur sayısı: 1 dış kare + 8 delik = 9
    (mil deliği plakanın merkez boşluğudur, dış konturun içinde ayrı bir
    halka olarak görünür -> 10).
    """
    import numpy as np

    pad = next(p for p in photo_valve.parts if p.id == "montaj_pabucu").mesh
    low, high = float(pad.bounds[0][1]), float(pad.bounds[1][1])
    found = 0
    for y in np.linspace(low + 1.0, high - 1.0, 9):
        loops = _slice_loops(pad, y)
        if len(loops) >= 9:
            found += 1
    assert found >= 3, "8 delikli kesit bulunamadı"


def test_mount_pad_is_square_not_round(photo_valve):
    """Plakanın X ve Z genişliği eşit (kare), köşe yarıçapı kenardan büyük."""
    import numpy as np

    pad = next(p for p in photo_valve.parts if p.id == "montaj_pabucu").mesh
    size = photo_valve.params["iso5211_pad_mm"]
    span = pad.bounds[1] - pad.bounds[0]
    assert abs(float(span[0]) - size) < 1.0, span
    assert abs(float(span[2]) - size) < 1.0, span
    corner = float(np.hypot(pad.vertices[:, 0], pad.vertices[:, 2]).max())
    assert corner > size * 0.5 * 1.25, "köşe yok; plaka yuvarlak"


def test_nothing_sits_above_the_mount_pad(photo_valve):
    """Pabucun üstünde vida/somun YOK; yalnız milin kare ucu çıkar.

    Önceki sürümde orada dişli bir uzantı ve bir somun duruyordu. Üründe
    yoklar ve olsalardı aktüatörün kovanı mile geçemezdi.
    """
    pad = next(p for p in photo_valve.parts if p.id == "montaj_pabucu").mesh
    pad_top = float(pad.bounds[1][1])
    above = [p.id for p in photo_valve.parts
             if p.group in ("fastener", "internal")
             and float(p.mesh.bounds[0][1]) > pad_top - 0.5
             and not p.id.startswith("aktuator")]
    assert above == [], f"pabucun üstünde beklenmeyen parça: {above}"
    stem = next(p for p in photo_valve.parts if p.id == "mil").mesh
    assert float(stem.bounds[1][1]) > pad_top, "mil pabucun üstüne çıkmıyor"


def test_stem_drive_is_square(photo_valve):
    """Mil ucu KARE: ISO 5211 kovani iki yuzlu bir mile oturmaz."""
    import numpy as np

    stem = next(p for p in photo_valve.parts if p.id == "mil").mesh
    top = float(stem.bounds[1][1])
    loops = _slice_loops(stem, top - 3.0)
    assert loops, "mil ucunda kesit yok"
    pts = np.concatenate(loops)
    width = float(pts[:, 0].max() - pts[:, 0].min())
    depth = float(pts[:, 1].max() - pts[:, 1].min())
    assert abs(width - depth) < 0.3, (width, depth)
    # Kare ise kose yaricapi kenar yaricapinin ~1.41 kati olmali
    radius = float(np.hypot(pts[:, 0], pts[:, 1]).max())
    assert radius > width / 2.0 * 1.25, "kesit dairesel"


def test_threaded_end_really_has_a_thread(photo_valve):
    """Boruya baglanan uclarda IC DIS olmali.

    Kesit yaricapini uc boyunca tarayinca disli bolumde testere disi gibi
    bir salinim gorulur; dissiz bir delikte yaricap sabittir.
    """
    import numpy as np

    cap = next(p for p in photo_valve.parts if p.id == "kapak").mesh
    z0, z1 = float(cap.bounds[0][2]), float(cap.bounds[1][2])
    radii = []
    for z in np.linspace(z1 - (z1 - z0) * 0.28, z1 - 1.0, 40):
        section = cap.section(plane_origin=[0, 0, float(z)],
                              plane_normal=[0, 0, 1])
        if section is None:
            continue
        planar, _ = section.to_2D()
        pts = np.concatenate(planar.discrete)
        inner = np.hypot(pts[:, 0], pts[:, 1])
        radii.append(float(inner.min()))
    assert len(radii) > 10
    swing = max(radii) - min(radii)
    assert swing > 0.6, f"ic dis yok (yaricap salinimi {swing:.2f} mm)"


def test_studs_and_nuts_are_different_materials(photo_valve):
    """Cekme saplama ile islenmis somun ayni yuzey degildir.

    Hepsini tek malzemeye baglamak modeli "tek parca gumus blok" gibi
    gosteriyordu; ayrim hem gercek hem de parcalari gozle ayirmanin en
    guclu ipucu.
    """
    stud = next(p for p in photo_valve.parts if p.id == "govde_civatasi")
    nut = next(p for p in photo_valve.parts if p.id == "govde_somunu")
    assert stud.material != nut.material
    from cad import materials as mat
    assert mat.get(stud.material).roughness < mat.get(nut.material).roughness


# --------------------------------------------------------------------------- #
# Pnomatik aktuator (musterinin set fotografindan)
# --------------------------------------------------------------------------- #

def test_pneumatic_actuator_is_modelled(photo_valve):
    """Urun ARTIK bir set: vana + aktuator.

    Onceki surumlerde aktuator "ayri satin alinan urun" diye cizilmiyordu.
    Musteri seti bir butun olarak satiyor ve sunumda da oyle gormek
    istiyor; referans fotografi da seti gosteriyor.
    """
    ids = {p.id for p in photo_valve.parts}
    assert {"aktuator_govdesi", "aktuator_kapagi", "aktuator_baglanti",
            "aktuator_gostergesi"} <= ids
    assert any("aktüatör" in n.lower() for n in photo_valve.notes)


def test_actuator_sits_on_top_of_the_mount_pad(photo_valve):
    """Aktuator pabuca OTURUR: ne havada durur ne de pabucun icinden gecer."""
    pad = next(p for p in photo_valve.parts if p.id == "montaj_pabucu").mesh
    pad_top = float(pad.bounds[1][1])
    pad_size = float(photo_valve.params["iso5211_pad_mm"])
    bracket = next(p for p in photo_valve.parts
                   if p.id == "aktuator_baglanti").mesh
    base = float(bracket.bounds[0][1])

    # Ayak pabucun ICINE gomulu: tam cakisik iki yuzey z-savasina girer ve
    # kamera dondukce sinir pirildar ("parca kayiyor" diye okunuyordu).
    assert base < pad_top - 0.3, "ayagin tabani pabukla ayni duzlemde"
    # Ama GECIP gitmez: gomme pay kadar, pabucun kalinligindan az.
    assert base > pad_top - pad_size * 0.08

    # Govde pabuca YAKIN. Onceki surumde arada pabuc kenarinin %42'si
    # kadar (DN50'de 27 mm) ince bir kule vardi ve aktuator havada
    # duruyordu.
    body = next(p for p in photo_valve.parts if p.id == "aktuator_govdesi").mesh
    lift = float(body.bounds[0][1]) - pad_top
    assert 0 < lift < pad_size * 0.25, f"aktuator pabucun {lift:.1f} mm ustunde"


def test_square_drive_reaches_into_the_actuator(photo_valve):
    """Milin KARE ucu aktuatorun govdesine girer.

    Kare ucun pabucun biraz ustunde bitmesi yetmiyor: pinyonu cevirecekse
    bagLanti ayagini asip govdenin gobegine ULASMALI. Olculdu: eski deger
    (0,62 x mil capi) ucu ayagin icinde birakiyordu.
    """
    stem = next(p for p in photo_valve.parts if p.id == "mil").mesh
    body = next(p for p in photo_valve.parts if p.id == "aktuator_govdesi").mesh
    assert float(stem.bounds[1][1]) > float(body.bounds[0][1])


def test_nothing_threaded_stands_above_the_mount_pad(photo_valve):
    """Pabucun ustunde yalnizca milin KARE ucu var.

    Musterinin fotograflarinda kare flansin uzerinde yukari uzanan bir
    vida ya da somun YOK; orada milin kare tahrik ucu duruyor. Pabucun
    ustune ciKan her parca ya mil ya da aktuatorun kendisi olmali.
    """
    pad = next(p for p in photo_valve.parts if p.id == "montaj_pabucu").mesh
    pad_top = float(pad.bounds[1][1])
    allowed = {"mil", "aktuator_baglanti", "aktuator_govdesi",
               "aktuator_kapagi", "aktuator_civatasi", "aktuator_kadran",
               "aktuator_gostergesi", "aktuator_portu",
               "aktuator_ayak_civatasi"}
    above = [p.id for p in photo_valve.parts
             if float(p.mesh.bounds[1][1]) > pad_top + 0.5]
    assert set(above) <= allowed, f"pabucun ustunde fazladan parca: {above}"


def test_cap_bolts_sit_in_the_corners_of_the_blue_cap(photo_valve):
    """Mavi kapagin dort civatasi KOSELERDE.

    Referans fotografta dordu de kapagin koselerinde, kenardan bir civata
    payi iceride. Onceki surumde dordu de tek bir dairenin ustundeydi ve
    kapagin ortasina toplanmisti (olculdu: yari yuksekligin %59'u).
    """
    cap = next(p for p in photo_valve.parts if p.id == "aktuator_kapagi")
    bolt = next(p for p in photo_valve.parts if p.id == "aktuator_civatasi")
    cap_mid = cap.placements[0].matrix[:3, 3] + cap.mesh.bounds.mean(axis=0)
    half_y = float(cap.mesh.bounds[1][1] - cap.mesh.bounds[0][1]) * 0.5
    half_z = float(cap.mesh.bounds[1][2] - cap.mesh.bounds[0][2]) * 0.5
    for place in bolt.placements[:4]:
        offset = place.matrix[:3, 3] - cap_mid
        assert abs(offset[1]) > half_y * 0.68, "civata kapagin ortasina yakin"
        assert abs(offset[2]) > half_z * 0.68, "civata kapagin ortasina yakin"


def test_actuator_parts_are_instanced_not_duplicated(photo_valve):
    """Iki uc kapagi ve sekiz civata TEK mesh paylasir.

    Ayri parca yazmak dosyayi buyutur ve parca listesinde ayni urunu
    birkac kez gosterirdi.
    """
    caps = next(p for p in photo_valve.parts if p.id == "aktuator_kapagi")
    bolts = next(p for p in photo_valve.parts if p.id == "aktuator_civatasi")
    assert caps.qty == 2 and bolts.qty == 8


def test_actuator_keeps_its_own_colours(photo_valve):
    """Mavi kapak, anotlu govde, sari kadran, kirmizi tapa.

    Hepsini tek gumus renge baglamak aktuatoru vananin devami gibi
    gosteriyordu; fotografta dort ayri renk var ve urunu uzaktan tanitan
    sey bu.
    """
    by_id = {p.id: p.material for p in photo_valve.parts}
    assert by_id["aktuator_kapagi"] == "actuator_blue"
    assert by_id["aktuator_govdesi"] == "aluminium_anodised"
    assert by_id["aktuator_kadran"] == "indicator_yellow"
    assert by_id["aktuator_portu"] == "port_red"
    assert len({by_id[k] for k in by_id if k.startswith("aktuator")}) >= 4


def test_actuator_does_not_blow_up_the_assembly_extent(photo_valve):
    """Aktuator montaji X'te kendi boyundan fazla buyutmemeli.

    Aynalanan kapak/civata yerlesimleri `at(...)`'in donme sozlesmesi
    yanlis kullanilinca montaji iki katina cikariyordu (olculdu: 168 mm
    yerine 331 mm).
    """
    size = photo_valve.validate()["size_mm"]
    assert size[0] < 200.0, size


def test_disassembly_order_starts_at_the_actuator(photo_valve):
    """Sokme sirasi gercek bakim sirasi olmali: disaridan iceri.

    Asama numarasi buyudukce parca DAHA GEC acilir. Aktuator en ustte ve
    en disarida oldugu icin once o sokulur; govde en sonda, sabit kalir.
    """
    stage = {p.id: min(pl.stage for pl in p.placements)
             for p in photo_valve.parts}
    assert stage["govde"] == 0, "orta govde sabit kalmali"
    actuator = max(v for k, v in stage.items() if k.startswith("aktuator"))
    assert actuator < stage["montaj_pabucu"] < stage["govde_civatasi"]
    assert stage["govde_civatasi"] < stage["kapak"] < stage["top"]
    assert stage["top"] <= stage["mil"]


# --------------------------------------------------------------------------- #
# Patlatma duzeni ve akis hatti sozlesmesi
# --------------------------------------------------------------------------- #

def test_exploded_parts_do_not_overlap(photo_valve):
    """Tam patlamis halde hicbir parca bir digerinin ICINDE durmaz.

    Patlatmanin okunur olmasinin tek kosulu bu. Mesafeler olculmeden
    yazildiginda sessizce bozuluyordu: kure 0,18 kosegen asagi gidince
    govdenin tabaninin icinde kaliyor (olculdu: 6.454 mm3 ortak hacim),
    salmastra bilezigi ile yayli rondela ayni 5 mm'ye oturuyordu.
    """
    hits = photo_valve.explode_overlaps()
    assert hits == [], hits


def test_explode_distances_climb_in_disassembly_order(photo_valve):
    """Ayni yonde acilan parcalar SIRAYLA uzaklasir.

    Govdeden disari dogru: oturma < conta < uc kapagi < saplama. Siranin
    bozulmasi parcalarin birbirinin onune gecmesi demek.
    """
    from cad.families import ball_valve as bv
    assert (bv.EX_SEAT < bv.EX_GASKET < bv.EX_CAP < bv.EX_BODY_BOLT)
    assert (bv.EX_STEM < bv.EX_PACKING < bv.EX_FOLLOWER
            < bv.EX_WASHER < bv.EX_GLAND_NUT < bv.EX_PAD)


def test_actuator_explodes_as_one_sub_assembly(photo_valve):
    """Aktuatorun kapaklari govdesiyle AYNI KADAR yukselir.

    Kapagi yalnizca yana acmak onu yukselen govdeden koparip bosLukta
    birakiyordu — "parcalar havada mantiksiz yerlere uciyor" dedirten
    davranis buydu. Yonler bilesik: yukari + yana.
    """
    import numpy as np
    from cad import actuator as act
    body = next(p for p in photo_valve.parts if p.id == "aktuator_govdesi")
    cap = next(p for p in photo_valve.parts if p.id == "aktuator_kapagi")
    rise_body = body.placements[0].distance * body.placements[0].axis[1]
    for place in cap.placements:
        rise_cap = place.distance * place.axis[1]
        assert abs(rise_cap - rise_body) < 1e-6
        assert abs(place.axis[0]) > 0.2, "kapak yana da acilmali"
    assert act.RISE_BODY > act.RISE_YOKE > act.RISE_YOKE_BOLT


def test_flow_line_rides_the_bore_not_the_bounding_box(photo_valve):
    """Hat vananin DELIGINDEN gecer.

    Sayfa boruyu eskiden sinir kutusunun merkezine koyuyordu; aktuator
    kutuyu yukari cektigi icin borular gövdenin ustunden geciyordu
    (olculdu: delik ekseni y=0 iken kutu merkezi y=+59,8 mm). Eksen artik
    CAD'den geliyor.
    """
    line = photo_valve.flow_line()
    assert line["axis"] == [0.0, 0.0, 1.0]
    assert line["origin"] == [0.0, 0.0, 0.0]          # delik ekseni x=y=0
    box = photo_valve.bounds
    assert box.mean(axis=0)[1] > 40.0, "kutu merkezi zaten yukarida"

    # Uclar BASINC ZARFINDAN olculur: civatalar uclardan tasar, onlara
    # dayanan bir boru vananin icine girer ya da acikta kalir.
    low, high = line["ends_mm"]
    shell = photo_valve.group_bounds("housing", "seal")
    assert low == pytest.approx(float(shell[0][2]))
    assert high == pytest.approx(float(shell[1][2]))
    assert low > float(box[0][2]) - 1e-9 and high <= float(box[1][2]) + 1e-9

