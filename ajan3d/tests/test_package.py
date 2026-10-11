"""Teslim paketi ve sunum sayfası.

Paket müşteriye giden şeydir: tek klasör, çift tıklanınca açılan bir sayfa,
WhatsApp'tan gönderilebilen bir link. Buradaki testler paketin **kendi kendine
yeter** olmasını (internet gerekmeden açılması), sayfanın 3B modelle aynı
sözleşmeyi konuşmasını ve müşteri metinlerinin HTML'e kaçışlanarak girmesini
kilitliyor.
"""
import json
import pathlib
import re
import tempfile

import pytest

from agents import cad_agent
from agents.packager_agent import PackagingError, build_package

IDENTITY = {
    "product_name": "Paslanmaz Çelik 3 Parçalı Küresel Vana",
    "product_name_en": "stainless 3-piece ball valve",
    "category": "endüstriyel vana",
    "family_hint": "ball_valve",
    "type_designation": "3 parçalı tam geçişli küresel vana, dişli uçlu",
    "nominal_size": "DN50",
    "pressure_rating": "PN40",
    "body_material": "CF8M paslanmaz çelik (AISI 316)",
    "end_connection": "dişli",
    "actuation": "kol",
    "piece_count": 3,
    "summary": "Üç parçalı gövdeli paslanmaz küresel vana.",
    "visible_features": ["ISO 5211 pabucu"],
    "markings": ["CF8M", "1000 WOG"],
    "materials": ["paslanmaz çelik"],
    "identification": {"confident": True, "confidence": "high", "issues": []},
}
SPEC = {
    "identified_as": "3 parçalı CF8M küresel vana",
    "confidence": "high",
    "nominal_size": "DN50",
    "pressure_rating": "PN40",
    "temperature_range": "-20 °C … +180 °C",
    "specs": [{"label": "Gövde", "value": "CF8M"},
              {"label": "Oturma", "value": "TFM 1600"}],
    "standards": ["ASME B16.34", "ISO 5211"],
    "standard_parts": ["Belleville yaylı rondela", "Antistatik eleman"],
    "surface_finish": "kumlanmış paslanmaz çelik",
    "applications": ["Proses hatları"],
    "reference_urls": ["https://example.com/katalog"],
}


def make_job(tmp_path, identity=None, spec=None, photos=0):
    job = tmp_path / "is"
    job.mkdir(parents=True)
    source = tmp_path / "fotograflar"
    source.mkdir()
    for i in range(photos):
        from PIL import Image
        Image.new("RGB", (900, 700), (90 + i * 10, 100, 110)).save(
            source / f"foto-{i}.jpg")
    metadata = {"source_folder": str(source),
                "identity": identity or IDENTITY,
                "spec": spec if spec is not None else SPEC}
    (job / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False),
                                       encoding="utf-8")
    cad_agent.build(job, metadata, force=True)
    return job


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    job = make_job(tmp_path_factory.mktemp("job"), photos=3)
    out = build_package(job, lang="tr", make_zip=True)
    return out, (out / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Paket içeriği
# --------------------------------------------------------------------------- #

def test_package_is_self_contained(package):
    out, _ = package
    for name in ("index.html", "model.glb", "studio.hdr", "urun-1.jpg"):
        assert (out / name).exists(), name
    assert (out / "vendor" / "three" / "three.module.min.js").exists()
    assert (out / "vendor" / "three" / "addons" / "loaders" / "GLTFLoader.js").exists()
    assert out.with_suffix(".zip").exists()


def test_package_stays_small_enough_for_mobile(package):
    """11 MB'lik eski paketler telefonda yavaş açılıyordu; sınır 6 MB."""
    out, _ = package
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    assert total < 6 * 1024 * 1024, f"{total / 1_048_576:.1f} MB"


def test_customer_photos_are_copied_but_not_shown_twice(package):
    """Fotograflar pakete girer ama yan panelde GOSTERILMEZ.

    Dosyalar sart: fotograf projeksiyonunun dokusu onlardan okunuyor. Ama
    ayni gorseli bir de galeri olarak gostermek paneli sisiriyor ve gozu
    asil urunden (3B modelden) aliyordu; model zaten o fotografi giyiyor.
    """
    out, html = package
    photos = sorted(out.glob("urun-*.jpg"))
    # Adaylarin tamami hizalama aramasina girer, pakete yalniz KAZANAN kalir.
    assert len(photos) == 1
    from PIL import Image
    with Image.open(photos[0]) as img:
        assert max(img.size) <= 1100
    assert 'id="bigphoto"' not in html
    assert 'id="thumbs"' not in html


def test_every_photo_is_a_projection_candidate(tmp_path, monkeypatch):
    """Sekiz fotograf yuklendiginde sekizi de aranmali.

    Onceki surumde yalnizca uc "temsilci" kopyalaniyordu; modele en iyi
    oturan kare o ucunun arasinda olmayabilir. Arama butun adaylari gorur,
    paket yine tek fotografla cikar.
    """
    from agents import packager_agent as pkg

    source = tmp_path / "fotograflar"
    source.mkdir()
    from PIL import Image
    for i in range(8):
        Image.new("RGB", (800, 600), (40 + i * 12, 70, 90)).save(source / f"f{i}.jpg")
    out = tmp_path / "paket"
    out.mkdir()
    names = pkg._copy_photos(source, out)
    assert len(names) == 8, names

    kept = pkg._keep_only(out, names, "urun-5.jpg")
    assert kept == ["urun-5.jpg"]
    assert sorted(p.name for p in out.glob("urun-*.jpg")) == ["urun-5.jpg"]


def test_page_loads_three_from_the_local_copy(package):
    _, html = package
    importmap = json.loads(re.search(
        r'<script type="importmap">(.*?)</script>', html, re.S).group(1))
    assert importmap["imports"]["three"] == "./vendor/three/three.module.min.js"
    assert importmap["imports"]["three/addons/"] == "./vendor/three/addons/"


# --------------------------------------------------------------------------- #
# Sayfa içeriği
# --------------------------------------------------------------------------- #

def _data(html: str) -> dict:
    return json.loads(re.search(
        r'<script type="application/json" id="data">(.*?)</script>',
        html, re.S).group(1))


def test_embedded_data_matches_the_cad_report(package):
    out, html = package
    report = json.loads((out.parent / "cad.json").read_text(encoding="utf-8"))
    data = _data(html)
    assert len(data["parts"]) == len(report["parts"])
    assert data["model"] == "model.glb"
    assert data["hdri"] == "studio.hdr"
    assert data["diagonal"] == pytest.approx(report["diagonal_mm"])


def test_every_part_group_has_a_turkish_label(package):
    _, html = package
    data = _data(html)
    assert {p["group"] for p in data["parts"]} <= set(data["groups"])
    assert data["groups"]["housing"] == "Gövde"


def test_every_part_material_has_a_colour_swatch(package):
    _, html = package
    swatches = json.loads(re.search(r"const SWATCH = (\{.*?\});", html, re.S).group(1))
    for part in _data(html)["parts"]:
        assert part["material"] in swatches
        assert re.fullmatch(r"#[0-9a-f]{6}", swatches[part["material"]])


def test_technical_chips_come_from_the_cad_parameters(package):
    _, html = package
    header = html[html.index("<header>"):html.index("</header>")]
    assert "CF8M / 316" in header
    assert "DN50" in header
    assert "PN40" in header
    assert "ISO 5211 F05" in header
    assert "3 parçalı" in header


def test_specs_standard_parts_and_sources_are_rendered(package):
    _, html = package
    assert "TFM 1600" in html
    assert "Belleville yaylı rondela" in html
    assert "ASME B16.34" in html
    assert "-20 °C" in html


def test_reference_links_are_not_published(package):
    """Kaynak linkleri musteriye giden sayfada yer almaz.

    Katalog/tedarikci adresleri musteriye bir sey anlatmiyor, ustelik
    sunumdan disari acilan bir kapi. Veri `metadata.json` icinde duruyor.
    """
    _, html = package
    assert "https://example.com/katalog" not in html
    assert "Kaynaklar" not in html


def test_model_validation_block_reports_solidity(package):
    _, html = package
    assert "su geçirmez katı" in html
    assert re.search(r"1[0-9]/1[0-9] su geçirmez katı", html)


def test_control_dock_has_every_requested_tool(package):
    _, html = package
    dock = html[html.index('id="dock"'):html.index("</aside>")]
    for tool in ("t-explode", "t-xray", "t-labels", "t-spin", "t-reset",
                 "t-share", "t-full", "slider"):
        assert f'id="{tool}"' in dock, tool
    # "Goruntu al" kaldirildi: tarayicinin kendi ekran goruntusu ayni isi
    # yapiyor ve serit mobilde tasiyordu.
    assert "t-shot" not in dock


# --------------------------------------------------------------------------- #
# Güvenlik ve dayanıklılık
# --------------------------------------------------------------------------- #

def test_customer_text_is_escaped(tmp_path):
    """Ürün adı müşteriden gelir; doğrudan HTML'e yazılamaz."""
    evil = dict(IDENTITY)
    evil["product_name"] = '<script>alert("xss")</script>'
    evil["summary"] = "<img src=x onerror=alert(1)>"
    job = make_job(tmp_path, identity=evil)
    html = (build_package(job, make_zip=False) / "index.html").read_text(
        encoding="utf-8")
    # Kacislanmis metin icinde "onerror=alert" dizgesi gorunur ama etiket
    # olarak ayristirilmaz; onemli olan < ve > karakterlerinin gecmemesi.
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_page_is_built_without_any_spec_data(tmp_path):
    """Ücretli araştırma adımı atlanmış olabilir; sayfa yine çıkmalı."""
    job = make_job(tmp_path, spec={})
    out = build_package(job, make_zip=False)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Paslanmaz" in html
    assert _data(html)["parts"], "parça listesi yine dolmalı"
    assert "Kaynaklar" not in html          # boş bölüm gösterilmez


def test_representative_badge_only_when_representative(tmp_path):
    normal = build_package(make_job(tmp_path / "a"), make_zip=False)
    assert "Temsili model" not in (normal / "index.html").read_text(encoding="utf-8")

    odd = dict(IDENTITY, product_name="Mutfak robotu", family_hint="other",
               type_designation="bilinmeyen ürün", nominal_size="",
               pressure_rating="", end_connection="", actuation="", piece_count=0)
    other = build_package(make_job(tmp_path / "b", identity=odd, spec={}),
                          make_zip=False)
    html = (other / "index.html").read_text(encoding="utf-8")
    assert "Temsili model" in html
    assert "eşleşmedi" in html


def test_missing_model_is_a_clear_error(tmp_path):
    job = tmp_path / "bos"
    job.mkdir()
    (job / "metadata.json").write_text(json.dumps({"identity": IDENTITY}),
                                       encoding="utf-8")
    with pytest.raises(PackagingError, match="model.glb"):
        build_package(job, make_zip=False)


def test_missing_metadata_is_a_clear_error(tmp_path):
    with pytest.raises(PackagingError, match="metadata.json"):
        build_package(tmp_path, make_zip=False)


def test_english_package_uses_english_labels(tmp_path):
    out = build_package(make_job(tmp_path), lang="en", make_zip=False)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Explode" in html and "Parts list" in html
    assert _data(html)["groups"]["housing"] == "Housing"


# --------------------------------------------------------------------------- #
# Malzeme kodu ve kumanda etiketi
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("identity,spec,params,expected", [
    # Urunun uzerinde okunan damga her zaman once gelir
    ({"body_material": "CF8 paslanmaz çelik (AISI 304)",
      "markings": ["DN50 PN63", "CF8"]}, {}, {"body_material": "stainless_cast"},
     "CF8 / 304"),
    ({"body_material": "CF8M döküm (AISI 316)", "markings": ["CF8M"]}, {},
     {"body_material": "stainless_cast"}, "CF8M / 316"),
    # Damga yoksa ailenin genel koduna dusulur
    ({"body_material": "paslanmaz çelik", "markings": []}, {},
     {"body_material": "stainless_cast"}, "CF8M / 316"),
    # Damga yalnizca dokum kodu tasiyorsa kalite uydurulmaz
    ({"body_material": "GGG40 sfero", "markings": ["GGG-40"]}, {},
     {"body_material": "ductile_epoxy"}, "GGG40"),
    # Arastirmadan gelen kod da kabul edilir
    ({"body_material": "", "markings": []},
     {"identified_as": "WCB karbon çelik gövde"},
     {"body_material": "carbon_steel"}, "WCB"),
])
def test_material_code_prefers_what_is_stamped_on_the_product(identity, spec,
                                                              params, expected):
    """Canli iste yasandi: vanada CF8/304 yaziyordu, serit CF8M/316 diyordu.

    Malzeme ailesi dogru olsa da kalite farkli olabilir ve musteri bunu bilir;
    serit urunle celisen bir kalite ilan edemez.
    """
    from agents.packager_agent import _material_code
    assert _material_code(identity, spec, params) == expected


def test_bare_stem_chip_is_written_in_turkish(tmp_path):
    """Ham enum degeri ('none') arayuze sizmamali."""
    from agents.packager_agent import ACT_LABELS, _chips
    chips = _chips(IDENTITY, SPEC, {"params": {"dn": 50, "actuation": "none"}})
    kumanda = [c["value"] for c in chips if c["label"] == "Kumanda"]
    assert kumanda == ["Çıplak mil"]
    assert "none" not in {c["value"] for c in chips}
    assert set(ACT_LABELS) >= {"lever", "handwheel", "gear", "pneumatic",
                               "electric", "none"}


# --------------------------------------------------------------------------- #
# Sayfanin ACILABILIRLIGI — gercek tarayicida yasanan donmalar
# --------------------------------------------------------------------------- #

def test_import_map_targets_are_relative_urls(package):
    """Cıplak yazılan bir yol BUTUN import map'i iptal ettiriyor.

    Yaşandı: "three": "vendor/three/three.module.min.js" yazılmıştı. Tarayıcı
    bunu bare specifier sayıp haritayı tamamen yok sayıyor, modül "three"i
    çözemiyor, üst seviye kod hiç çalışmıyor ve kullanıcı sonsuza kadar
    "yükleniyor" ekranında kalıyor. Tek iz konsolda.
    """
    _, html = package
    imports = json.loads(re.search(
        r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    assert imports, "import map bos"
    for key, value in imports.items():
        assert value.startswith(("./", "../", "/", "http://", "https://")), \
            f"{key} -> {value} : goreli yol ./ ile baslamali"


def test_vendored_module_graph_is_complete(package):
    """Bir ES modulunun kendi import'u eksikse sayfa sessizce acilmaz.

    İki kez yaşandı: three r180 build'i three.module.min.js + three.core.min.js
    olarak ikiye bölünmüş (ikincisi kopyalanmamıştı) ve Draco yolu açıldığında
    DRACOLoader.js eksikti. İkisi de yalnızca konsolda 404 olarak görünüyordu.
    """
    from agents.packager_agent import missing_modules
    out, _ = package
    broken = missing_modules(out / "vendor")
    assert not broken, f"eksik modul: {broken}"


def test_page_survives_a_module_failure(package):
    """Modul hic calismazsa bile kullanici bir hata gormeli, donmamali."""
    _, html = package
    classic = html[:html.index('<script type="module">')]
    assert "__viewerFail" in classic
    assert "__viewerStarted" in html
    assert "unhandledrejection" in classic
    # Klasik betik modul betiginden ONCE gelmeli, yoksa koruma islemez
    assert classic.index("__viewerFail") < html.index('<script type="module">')


def test_webgl_is_checked_before_use(package):
    _, html = package
    assert "hasWebGL" in html
    assert html.index("hasWebGL") < html.index("new THREE.WebGLRenderer")


# --------------------------------------------------------------------------- #
# Yukleme gostergesi
# --------------------------------------------------------------------------- #

def test_real_file_sizes_are_embedded_for_the_progress_bar(package):
    """Tunel yanitlari parcali geliyor; Content-Length olmadan yuzde ilerlemez.

    Bu yüzden dosya boyutları paketleme sırasında ölçülüp sayfaya gömülüyor.
    """
    out, html = package
    data = _data(html)
    assert data["model_bytes"] == (out / "model.glb").stat().st_size
    assert data["hdri_bytes"] == (out / "studio.hdr").stat().st_size
    assert data["model_bytes"] > 0


def test_scene_is_revealed_only_when_ready(package):
    _, html = package
    assert "compileAsync" in html          # gölgeler/malzemeler derlensin
    assert "#view{opacity:0" in html.replace(" ", "")
    assert "classList.add('ready')" in html
    # Yukleme ekrani ancak reveal() icinde kalkar
    assert html.index("function reveal") < html.index("loaderEl.classList.add('gone')")


def test_loading_phases_are_localised(package):
    _, html = package
    assert "İndiriliyor" in html and "Sahne hazırlanıyor" in html
    assert 'id="fill"' in html and 'id="track"' in html


# --------------------------------------------------------------------------- #
# Draco
# --------------------------------------------------------------------------- #

def test_draco_flag_matches_the_actual_file(package):
    """Sayfa Draco der ama dosya sikistirilmamissa cozucu bosuna iner."""
    out, html = package
    data = _data(html)
    raw = (out / "model.glb").read_bytes()
    declared = b"KHR_draco_mesh_compression" in raw
    assert bool(data["draco"]) == declared


def test_decoder_ships_whenever_draco_is_used(package):
    out, html = package
    if not _data(html)["draco"]:
        pytest.skip("bu modelde Draco kullanilmadi")
    assert (out / "vendor" / "draco" / "draco_decoder.wasm").exists()
    assert (out / "vendor" / "draco" / "draco_wasm_wrapper.js").exists()
    assert _data(html)["draco_path"] == "vendor/draco/"
    # DRACOLoader dinamik import ediliyor; modulu de pakette olmali
    assert (out / "vendor" / "three" / "addons" / "loaders" / "DRACOLoader.js").exists()


def test_draco_decoder_is_not_shipped_when_unused(tmp_path, monkeypatch):
    import dataclasses
    from agents import packager_agent
    monkeypatch.setattr(packager_agent, "settings", dataclasses.replace(
        packager_agent.settings, draco_enabled=False))
    from core import optimize
    monkeypatch.setattr(optimize, "settings", dataclasses.replace(
        optimize.settings, draco_enabled=False))
    job = make_job(tmp_path)
    out = build_package(job, make_zip=False)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert _data(html)["draco"] is False
    assert not (out / "vendor" / "draco").exists()


# --------------------------------------------------------------------------- #
# Fotograf projeksiyonu ve AO
# --------------------------------------------------------------------------- #

def _force_projection_on(monkeypatch):
    """Projeksiyon ARTIK VARSAYILAN OLARAK KAPALI (bkz. core/config.py).

    Kapatma bir urun karari: cok gorusLu harmanlama paslanmaz govdeyi
    hardal lekelere ceviriyordu. Alt sistemin kendisi duruyor ve calisiyor;
    onu olcen testler acik konumda kosmali.
    """
    import dataclasses
    from agents import packager_agent as pkg
    monkeypatch.setattr(pkg, "settings", dataclasses.replace(
        pkg.settings, projection_enabled=True))


def _product_photo(path, width=360, height=480):
    """Koyu fonda, kenar bosluklu, acik renkli bir "urun" fotografi."""
    import numpy as np
    from PIL import Image
    image = np.full((height, width, 3), 22, dtype=np.uint8)
    image[int(height * 0.2):int(height * 0.8),
          int(width * 0.25):int(width * 0.75)] = (206, 205, 199)
    Image.fromarray(image).save(path)
    return path


def test_every_projector_gets_its_own_mask(tmp_path, monkeypatch):
    """Her projektorun KENDI maskesi yazilmali.

    Onbellek yalnizca SAYILARI tasir, dosyalari degil. Maske yazimi
    onbellek dalinin icinde kalmisti: ikinci paketlemede maske teslim
    klasorune hic girmiyor, sayfa onu 404 aliyor ve maske kapisi her
    pikseli kapattigi icin fotograf modelde HIC gorunmuyordu.
    """
    _force_projection_on(monkeypatch)
    from agents import packager_agent as pkg

    out = tmp_path / "delivery"
    out.mkdir()
    _product_photo(out / "urun-1.jpg")
    _product_photo(out / "urun-2.jpg")
    cached = [{"photo": "urun-1.jpg", "iou": 0.81, "coverage": 0.4, "mask": ""},
              {"photo": "urun-2.jpg", "iou": 0.74, "coverage": 0.3, "mask": ""}]
    monkeypatch.setattr(pkg, "_projection_search",
                        lambda m, o, p: [dict(c) for c in cached])

    data = pkg._build_projection(tmp_path / "model.glb", out,
                                 ["urun-1.jpg", "urun-2.jpg"])
    assert len(data) == 2
    assert [d["mask"] for d in data] == ["projection-mask-1.png",
                                         "projection-mask-2.png"]
    for item in data:
        assert (out / item["mask"]).exists()


def test_page_degrades_to_pure_pbr_without_a_mask(tmp_path, monkeypatch):
    """Maske uretilemezse projeksiyon yine calisir, yalniz kapisi kapanir."""
    _force_projection_on(monkeypatch)
    from agents import packager_agent as pkg

    out = tmp_path / "delivery"
    out.mkdir()                                   # fotograf dosyasi YOK
    monkeypatch.setattr(pkg, "_projection_search",
                        lambda m, o, p: [{"photo": "yok.jpg", "iou": 0.8}])
    data = pkg._build_projection(tmp_path / "model.glb", out, ["yok.jpg"])
    assert len(data) == 1 and data[0]["mask"] == ""
    assert not list(out.glob("projection-mask-*.png"))


def test_projection_can_be_switched_off(tmp_path, monkeypatch):
    import dataclasses
    from agents import packager_agent as pkg
    monkeypatch.setattr(pkg, "settings", dataclasses.replace(
        pkg.settings, projection_enabled=False))
    assert pkg._build_projection(tmp_path / "model.glb", tmp_path,
                                 ["urun-1.jpg"]) == []


def test_page_carries_the_multi_projector_shader(package):
    """Shader N projektoru ACARAK uretiyor ve agirliklari topluyor.

    GLSL ES 1.0'da sampler dizisini degiskenle indekslemek yasak; dongu
    elle acilmali. Agirliklar toplanip ortalandigi icin bir yuzey birden
    cok fotografta gorunuyorsa renkler karisir, hicbirinde gorunmuyorsa
    piksel endustriyel PBR'ye duser.
    """
    _, html = package
    assert "projUniformNames" in html and "projSampleCode" in html
    assert "gProjW" in html and "gProjRGB" in html
    assert "uFallbackMix" in html and "uFallbackTint" in html
    assert "uProjPart" in html


def test_actuator_is_excluded_from_projection(package):
    """Fotograflarda olmayan urune fotograf giydirmek uydurmadir.

    Musterinin 8 karesi ciplak milli vanayi gosteriyor; aktuator sonradan
    eklendi. Projeksiyon oraya da vurunca aktuatorun uzerine vananin
    govdesinden kopan lekeler dusuyordu.
    """
    _, html = package
    assert "grp !== 'actuator'" in html


def test_page_applies_baked_ao_to_indirect_light(package):
    """AO dolayli isiga ve ortam yansimasina uygulanmali.

    Metalde yayinim yoktur; AO yalnizca `indirectDiffuse`e uygulansaydi
    paslanmaz celikte hicbir sey degismezdi.
    """
    _, html = package
    assert "attribute float ao" in html
    assert "ambientOcclusion = mix(1.0, vAO" in html
    assert "reflectedLight.indirectSpecular *= computeSpecularOcclusion" in html
    assert "adoptAO" in html


def test_model_ships_with_baked_ao(package):
    """Teslim edilen GLB'de AO gercekten olmali (COLOR_0)."""
    out, html = package
    raw = (out / "model.glb").read_bytes()
    if _data(html)["draco"]:
        pytest.skip("sikistirilmis GLB; nitelik Draco icinde, test_ao kapsiyor")
    from cad.gltf import read_glb
    doc, _ = read_glb(raw)
    assert all("COLOR_0" in m["primitives"][0]["attributes"]
               for m in doc["meshes"])


# --------------------------------------------------------------------------- #
# Endustriyel baglam: boru hatti + fabrika fonu
# --------------------------------------------------------------------------- #

def test_pipeline_contract_reaches_the_page(package):
    """Sayfa boru hattini bu sozlesmeden kuruyor.

    Boru capi tahmin EDILMEZ: anma olcusunden (EN 10220 dis cap) gelir.
    Eksen butun ailelerin paylastigi sozlesmedir (akis Z).
    """
    _, html = package
    pipe = _data(html)["pipeline"]
    assert pipe is not None
    assert pipe["dn"] == 50
    assert pipe["od_mm"] > pipe["bore_mm"], "boru dis capi delikten buyuk olmali"
    assert pipe["axis"] == [0.0, 0.0, 1.0]


def test_pipeline_is_skipped_when_the_size_is_unknown():
    """Anma olcusu yoksa yanlis capta boru cizmektense hic cizme."""
    from agents import packager_agent as pkg
    assert pkg._pipeline({"params": {}}) is None
    assert pkg._pipeline({}) is None


def test_context_is_physical_geometry_not_a_backdrop_image(package):
    """Baglam FIZIKSEL: fon gorseli yok, diorama var.

    Bulanik bir arka plan ne golge alir ne verir, ne de urunle ayni
    perspektifte durur; goz onu "arkada bir resim var" diye okur. Sase
    ise urunle ayni isigi alir, zemine golge duserir ve borular onu
    DELIP gecer.
    """
    out, html = package
    assert not (out / "backdrop.jpg").exists()
    assert "buildDiorama" in html
    assert "ExtrudeGeometry" in html and "holes.push" in html
    assert "scene.background = new THREE.Color" in html


def test_page_builds_the_pipeline_and_two_stage_explode(package):
    """Parcalanma iki asamali: once hattan kopma, sonra eksenel ayrisma."""
    _, html = package
    assert "buildPipeline" in html
    assert "PULL_OUT" in html and "pullDirection" in html
    assert "state.pipeline" in html


def test_ground_is_a_real_floor_not_only_a_shadow_catcher(package):
    """Zemin gorunur olmali; aksi halde urun bosLukta suzuluyor."""
    _, html = package
    ground = html[html.index("const ground = new THREE.Mesh"):]
    ground = ground[:ground.index("scene.add(ground)")]
    assert "MeshStandardMaterial" in ground
    assert "ShadowMaterial" not in ground


def test_labels_are_laid_out_in_gutters_that_always_fit(package):
    """Etiketler oluga dizilir ve kadraja SIGAR.

    Parcanin yanina koymak patlatilmis goruntude ise yaramiyor: vananin ic
    parcalari ekranda birkac piksel arayla ust uste dusuyor, hepsi ayni yone
    itiliyor ve okunmaz tek bir sutun olusuyordu. Dogal yuksekligine
    yapismaya calisan acgozlu tarama da sondaki etiketleri alt sinirin
    DISINA itiyordu (telefonda son iki etiket arac cubugunun altinda
    kaliyordu). Esit arali sutun her zaman sigar.
    """
    _, html = package
    assert "layoutGutter" in html
    # Aralik sutun yuksekligine gore kisilir: tasma mumkun degil.
    assert "(BOT - TOP) / col.length" in html
    # Dar ekranda tek oluk; iki sutun 390 pikselde birbirinin icine girerdi.
    assert "const two = w >= 720" in html
    # Etiket kenara yaslanir, ortalanirsa yarisi ekran disinda kalir.
    assert "translate(0,-50%)" in html and "translate(-100%,-50%)" in html


# --------------------------------------------------------------------------- #
# Musteri geri bildirimi turu: kaplama, boru, kapali oda, patlatma
# --------------------------------------------------------------------------- #

def test_photo_projection_is_off_by_default(package):
    """Sayfa SAF PBR ile aciliyor; fotograf modele yansitilmiyor.

    Cok gorusLu harmanlama paslanmaz govdeyi hardal/haki lekelere
    ceviriyordu ("bir tarafi gumus, bir tarafi sari"). Kareler sicak ic
    mekan isiginda, koyu fon onunde ve kare basina farkli beyaz ayariyla
    cekilmis; dogru beyaz ayari olmadan ortalama almak camur uretiyor.
    """
    _, html = package
    data = _data(html)
    assert data["projectors"] == []
    assert data["projection"] is None


def test_hidden_tools_really_disappear(package):
    """`hidden` isaretli arac dugmesi GORUNMEZ olmali.

    `.tool{display:flex}` tarayicinin [hidden] kuralini eziyordu:
    projeksiyon kapaliyken gizlenmesi gereken "Foto doku" dugmesi yine de
    duruyor, basildiginda hicbir sey yapmiyordu.
    """
    _, html = package
    assert ".tool[hidden]{display:none}" in html


def test_pipeline_rides_the_flow_line_from_cad(package):
    """Boru hatti vananin DELIGINDEN gecer, sinir kutusundan degil."""
    out, html = package
    data = _data(html)
    pipe = data["pipeline"]
    cad = json.loads((out.parent / "cad.json").read_text(encoding="utf-8"))
    line = cad["flow_line"]
    assert pipe["origin_mm"] == line["origin"]
    assert pipe["ends_mm"] == line["ends_mm"]
    # Sayfa bu ucLari gercekten KULLANMALI.
    assert "info.ends_mm" in html and "faceA" in html and "faceB" in html


def test_pipes_are_plain_flanged_tubes(package):
    """Borunun uzerinde delik/kesik yok: duz silindir + YUVARLAK flans.

    Eski surumde her boruda ALTI KENARLI bir rakor bilezigi, bir aski
    kelepcesi ve bir ayak vardi; 48 dilimli borunun yaninda 6 dilimli
    bilezik yuzeyde "kesik" gibi okunuyordu.
    """
    _, html = package
    assert "CylinderGeometry(outer * 1.42, outer * 1.42, fl, 48)" in html
    # Kaldirilan parcalar geri gelmemeli.
    assert "clampAt" not in html
    assert "outer * 1.17" not in html, "alti kenarli rakor bilezigi geri gelmis"


def test_pipe_meets_the_valve_face_with_no_gap(package):
    """Boru vananin uc yuzeyine SIFIRA SIFIR dayanir, icine bir pay girer."""
    _, html = package
    assert "const bite = outer * 0.06;" in html
    assert "sign * (length * 0.5 - bite)" in html


def test_the_room_is_closed_on_every_side(package):
    """Tavan + dort duvar: hicbir aciden disarisi gorunmez.

    Onceki surum acik bir saseydi (zemin + iki uc bolmesi); kamera yana
    cevrildiginde aradan arka plandaki bosluk goruluyordu.
    """
    _, html = package
    assert "--- tavan ---" in html
    assert "--- yan duvarlar" in html
    # Boru UC DUVARLARI deler; deligin merkezi akis ekseninde olmali
    # (eskiden sinir kutusunun merkezindeydi, delik borunun epey ustunde
    # kaliyordu).
    assert "ExtrudeGeometry" in html and "holes.push" in html
    assert "hole.absarc(0, line.y" in html
    # Duvarlar yalniz ICERIDEN gorunur; disaridan urunu ortmezler.
    assert "THREE.BackSide" in html


def test_camera_cannot_leave_the_room(package):
    """Kamera odanin ICINDE kalir: hem yumusak sinir hem sert kelepce.

    `dolly` kamerayi dogrudan tasidigi icin OrbitControls'un maxDistance'i
    tek basina yetmiyor; patlatmada kamera duvarin arkasina dusuyordu.
    """
    _, html = package
    assert "controls.maxDistance =" in html
    assert "function confineCamera()" in html
    assert "confineCamera();" in html, "her karede cagrilmali"
    assert "Math.min(want, controls.maxDistance)" in html


def test_explode_direction_does_not_depend_on_the_camera(package):
    """Patlatma yonu SABIT yukari.

    Kameraya gore hesaplanan yon ayni urunu her acidan farkli diziyordu
    ve patlatma acikken sahne dondurulunce montaj eski yonde asili
    kaliyordu ("parcalar kendi kendine kayiyor").
    """
    _, html = package
    start = html.index("function pullDirection()")
    body = html[start:html.index("function applyExplode", start)]
    assert "camera" not in body, "yon hala kameraya bagli"
    assert "new THREE.Vector3(0, 1, 0)" in body


def test_explode_camera_frames_the_measured_spread(package):
    """Kamera patlatmada OLCULEN kutuya gore cekilir ve yukari kayar.

    Oranla geri cekilmek tahmindi: montaj yukari aciliyor, kamera ise
    birlesik halin merkezine bakmaya devam ediyordu; gosterge kadrajin
    ustunden tasiyordu.
    """
    _, html = package
    assert "state.explodedCenter" in html and "state.explodedRadius" in html
    assert "state.explodedDistance" in html


def test_the_page_script_actually_parses(package):
    """Sayfanin modulu SOZ DIZIMI olarak gecerli olmali.

    Butun oteki sayfa testleri HTML icinde metin ariyor; bozuk bir kacis
    karakteri yuzunden acilmayan bir sayfa hepsini gecebiliyor (gecti de:
    sablondaki bir shader dizesinde '\n' gercek satir sonuna donustu,
    432 test yesil kaldi, sayfa ise "Invalid or unexpected token" ile
    hic acilmadi). Bu test modulu ayiklayip `node --check` ile derletir.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node yok")
    _, html = package
    match = re.search(r'<script type="module">(.*?)</script>', html, re.S)
    assert match, "sayfada modul betigi yok"
    script = pathlib.Path(tempfile.mkdtemp()) / "page.mjs"
    script.write_text(match.group(1), encoding="utf-8")
    done = subprocess.run([node, "--check", str(script)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1500:]


# --------------------------------------------------------------------------- #
# LookDev, sahneleme ve etiket sadelestirmesi
# --------------------------------------------------------------------------- #

def test_only_main_parts_get_a_label(package):
    """Patlatmada etiket YALNIZ ana parcalarda.

    21 etiket birden aciliyordu; civata, somun, pul ve conta adlari urunu
    okunmaz bir ok yumagina ceviriyordu.
    """
    _, html = package
    parts = _data(html)["parts"]
    keyed = [p for p in parts if p.get("key")]
    assert 0 < len(keyed) < len(parts) / 2, [p["name"] for p in keyed]
    # Baglanti elemani ve sizdirmazlik ASLA etiketlenmez.
    for p in parts:
        if p["group"] in ("fastener", "seal"):
            assert not p["key"], p["name"]
    # Govde her zaman etiketlenir: urunun ana parcasi odur.
    assert next(p for p in parts if p["id"] == "govde")["key"]
    # Sayfa bu isareti gercekten kullanmali.
    assert "p.key === false" in html


def test_key_part_rule_is_mass_based_not_a_name_list():
    """Olcut aileden bagimsiz: kutle payi + grup. Ad listesi tutulmuyor."""
    from agents import packager_agent as pkg
    rows = [
        {"id": "govde", "group": "housing", "total_mass_g": 1000.0},
        {"id": "kucuk_ic", "group": "internal", "total_mass_g": 2.0},
        {"id": "civata", "group": "fastener", "total_mass_g": 500.0},
        {"id": "conta", "group": "seal", "total_mass_g": 300.0},
    ]
    pkg._mark_key_parts(rows)
    by_id = {r["id"]: r["key"] for r in rows}
    assert by_id["govde"] is True
    assert by_id["kucuk_ic"] is False, "kutle payi esigin altinda"
    assert by_id["civata"] is False and by_id["conta"] is False


def test_surface_has_three_roughness_bands(package):
    """Tek bir ince tane bandi yuzeyi "temiz ve tek tip" birakiyordu.

    Iri leke dokum karakterini, yonlu cizik islenmis yuzeyi anlatir; ince
    tane yalniz ikisini kirar. Ince bandin genligi DUSUK tutulur, yoksa
    yakin planda piksel olceginde titreyip zimpara gibi duruyor.
    """
    _, html = package
    assert "uBroadAmp" in html and "uScratchAmp" in html
    assert "mGrain" in html and "mBroad" in html and "mScratch" in html
    assert "Math.min(0.15, 0.52 * mat.roughness * mat.roughness)" in html


def test_ambient_occlusion_reaches_the_reflection(package):
    """AO yalniz taban rengi degil ORTAM YANSIMASI da kararmali.

    Metalde taban renk F0'dir; girinti etkisini asil veren yansimadaki
    kararmadir. AO, GLB'de COLOR_0 olarak geliyor ve sayfada tek bilesenli
    `ao` niteligine tasiniyor — yoksa GLTFLoader onu koseler rengi sanip
    yalnizca taban renge carpar ve siddeti ayarlanamaz.
    """
    _, html = package
    assert "function adoptAO" in html
    assert "reflectedLight.indirectSpecular *= computeSpecularOcclusion" in html
    assert "const AO_TINT = 0.90;" in html


def test_product_fills_the_frame(package):
    """Vana kutunun icinde oyuncak gibi kalmamali.

    Acilis kadraji 1,50 cevre payiyla kuruluyordu: hat kareye giriyor ama
    urun kuculuyordu. Oda da kameradan turedigi icin birlikte buyuyordu.
    """
    _, html = package
    assert "? 1.12 : 1.06" in html
    assert "const ROOM_CLEARANCE = 1.05;" in html

