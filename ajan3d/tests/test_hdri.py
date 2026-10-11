"""Stüdyo HDRI'sinin fotogerçekçilik sözleşmesi.

Metalin "gri plastik" değil "çelik" görünmesi bir beğeni meselesi değil, ölçülebilir
bir ışık dağılımı meselesidir: kaynaklar KÜÇÜK ve PARLAK olmalı, çevre KOYU olmalı.
Bu dosya o sözleşmeyi kilitler — ortam rigi kurcalanınca sessizce gri kubbeye
geri dönülmesin diye.
"""
import numpy as np
import pytest

from core.hdri import (INDUSTRIAL, STUDIO, TARGET_MEAN_RADIANCE, Light, Softbox,
                       decode_hdr, encode_hdr, measure, render_environment,
                       write_studio_hdr)


@pytest.fixture(scope="module")
def env():
    return render_environment(512)


def test_rig_dikdortgen_softbox_kullaniyor():
    """Yuvarlak kaynak yuvarlak leke bırakır; şerit parlaklık dikdörtgenden gelir."""
    assert all(isinstance(s, Softbox) for s in STUDIO)
    assert len(STUDIO) >= 3


def test_kaynaklar_kucuk(env):
    """Gökyüzünün büyük kısmı ışık kaynağıysa metal her yerde eşit parlar."""
    m = measure(env)
    assert m["emitter_fraction"] < 0.15, "ortam fazla geniş bir alandan ışıyor"


def test_cevre_koyu(env):
    """Metal ne görürse odur: koyu çevre olmadan koyu gövde olmaz."""
    m = measure(env)
    assert m["dark_fraction"] > 0.70, "stüdyo fonu yeterince koyu değil"


def test_yuksek_kontrast(env):
    """Asıl ölçüt parlaklık değil kontrast: tepe / ortanca oranı."""
    m = measure(env)
    assert m["peak"] > 5.0, "gerçek bir parlaklık tepesi yok"
    assert m["peak"] / max(m["median"], 1e-6) > 300.0, "kontrast gri kubbe seviyesinde"


def test_toplam_isinim_hedefte(env):
    """Rig değişse bile sahne parlaklığı sabit kalmalı (pozlama kaymasın)."""
    assert measure(env)["mean"] == pytest.approx(TARGET_MEAN_RADIANCE, rel=0.02)


def test_rig_buyutulunce_parlaklik_kaymiyor():
    """Kaynak yoğunluğu 10 katına çıksa bile normalizasyon hedefi tutar."""
    buyuk = tuple(Softbox(s.azimuth, s.elevation, s.width, s.height,
                          s.intensity * 10.0, s.softness, s.color) for s in STUDIO)
    m = measure(render_environment(256, buyuk))
    assert m["mean"] == pytest.approx(TARGET_MEAN_RADIANCE, rel=0.02)


def test_softbox_yonunde_parlak_disinda_koyu():
    """Maske gerçekten kaynağın baktığı yöne düşüyor mu?"""
    tek = (Softbox(azimuth=90, elevation=0, width=20, height=20,
                   intensity=50.0, softness=2.0),)
    img = render_environment(256, tek, target_mean=None)
    h, w = img.shape[:2]
    # azimuth=90 -> +Z yönü; _directions'ta theta = u*2pi, z = sin(phi)*sin(theta)
    merkez = img[h // 2, w // 4].mean()      # u=0.25 -> theta=90°
    uzak = img[h // 2, 3 * w // 4].mean()    # tam ters yön
    assert merkez > uzak * 50, "softbox yanlış yöne düşüyor"


def test_eski_yuvarlak_isik_hala_calisiyor():
    """Geriye dönük uyumluluk: Light ile çağıran kod kırılmamalı."""
    img = render_environment(128, (Light(0, 30, 20, 8.0),), target_mean=None)
    assert float(img.max()) > 1.0


def test_hdr_yaz_oku_dongusu(tmp_path):
    """Dosyaya yazılan ortam, okunduğunda aynı ölçütleri vermeli."""
    p = write_studio_hdr(tmp_path / "studio.hdr", width=256, backdrop="studio",
                         lights=STUDIO)
    geri = decode_hdr(p.read_bytes())
    a, b = measure(render_environment(256)), measure(geri)
    assert b["mean"] == pytest.approx(a["mean"], rel=0.03)
    assert b["dark_fraction"] == pytest.approx(a["dark_fraction"], abs=0.02)


def test_kodlama_yuksek_degerleri_koruyor():
    """RGBE 1.0 üstünü saklayamazsa parlaklık tepeleri kaybolur."""
    img = render_environment(128)
    geri = decode_hdr(encode_hdr(img))
    assert float(geri.max()) > 5.0
    assert np.allclose(geri, img, rtol=0.02, atol=0.01)


# --------------------------------------------------------------------------- #
# Endustriyel hol fonu
# --------------------------------------------------------------------------- #

def test_endustriyel_fon_fotogercekcilik_sozlesmesini_bozmuyor():
    """Fon gorunur hale geldi diye aydinlatma gri kubbeye donmemeli.

    Sayfa ayni dokuyu iki pozlamayla kullaniyor: `environmentIntensity` ile
    aydinlatma (koyu, kontrastli), `backgroundIntensity` ile fon (parlak,
    okunur). Dolayisiyla fona yapi eklemek olcutleri bozmamali.
    """
    m = measure(render_environment(512, INDUSTRIAL, backdrop="industrial"))
    assert m["mean"] == pytest.approx(TARGET_MEAN_RADIANCE, rel=0.02)
    assert m["emitter_fraction"] < 0.15, m["emitter_fraction"]
    assert m["dark_fraction"] > 0.70, m["dark_fraction"]
    assert m["peak"] / m["median"] > 300


def test_endustriyel_fonun_ufku_ve_kolonlari_var():
    """Fon "bir yer" gibi okunmali: ufuk cizgisi + yatay kolon ritmi.

    Duz bir gradyan bulandirildiginda yine hicbir yer gibi gorunur. Olculen
    iki yapi: (1) ufkun hemen altiyla ustu arasinda belirgin bir fark,
    (2) duvar bandinda azimut boyunca tekrar eden parlaklik degisimi.
    """
    # Kaynaksiz render: olculen yalniz FON. Softbox'lar birakilsaydi duvar
    # bandindaki degisimin kolonlardan mi armaturlerden mi geldigi belirsiz
    # kalirdi.
    img = render_environment(512, (), target_mean=None, backdrop="industrial")
    h = img.shape[0]
    lum = img @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    ufuk = h // 2
    ust = float(lum[ufuk - h // 24:ufuk].mean())
    alt = float(lum[ufuk:ufuk + h // 24].mean())
    assert ust > alt * 1.5, (ust, alt)

    band = lum[int(h * 0.44):int(h * 0.49)].mean(axis=0)   # duvar bandi
    assert band.std() / max(band.mean(), 1e-9) > 0.10, "kolon ritmi yok"


def test_studyo_fonunda_kolon_yok():
    """Eski stüdyo fonu degismeden duruyor (geriye donuk uyumluluk)."""
    img = render_environment(256, (), target_mean=None, backdrop="studio")
    h = img.shape[0]
    lum = img @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    band = lum[int(h * 0.44):int(h * 0.49)].mean(axis=0)
    assert band.std() / max(band.mean(), 1e-9) < 0.02
