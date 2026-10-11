"""Testlerin ortak kurulumu.

Buradaki üç fikstür de **hızla ilgili**, davranışla değil: pahalı üç adımı
(AO pişirme, öğrenilmiş ürün kesimi, çok yönlü projeksiyon araması) kendi
test dosyalarının dışında kısıyorlar. Her birinin gerçek davranışı kendi
dosyasında tam ayarla ölçülüyor; başka modüllerin onlardan beklentisi
yalnızca "çalıştı mı".
"""
import pytest

from cad import ao
from core import projection


@pytest.fixture(autouse=True)
def coarse_ao(request, monkeypatch):
    """AO pişirmeyi, kendi testleri DIŞINDA kaba ızgarayla çalıştırır.

    AO montaj başına ~18 sn alıyor (voksel ızgarası + gauss). Bu maliyet
    sonucun kalitesi için gerekli, ama diğer modüllerin AO'dan beklentisi
    yalnızca "nitelik yazılmış mı" — değerin inceliği değil. Tam çözünürlük
    `tests/test_ao.py` içinde ölçülüyor; başka her yerde ızgara küçültülüyor
    ve bütün takım dakikalarca kısalıyor.
    """
    if request.node.path.name == "test_ao.py":
        return
    monkeypatch.setattr(ao, "GRID", 25_000)


@pytest.fixture(autouse=True)
def no_learned_cutout(request, monkeypatch):
    """Öğrenilmiş ürün kesimini (rembg) kendi testleri dışında kapatır.

    İki sebep, ikisi de testin kendisiyle ilgili:

    * **Belirlenebilirlik.** U²-Net kurulu olan makinede başka, olmayan
      makinede başka sonuç verirdi. Testler makineye göre değişmemeli.
    * **Süre.** Test fotoğrafları düz renk karelerdir; ağ onlarda da bir maske
      "bulabiliyor" ve ardından tam yön araması çalışıyordu — paket testleri
      bu yüzden dakikalarca sürüyordu. Klasik yol düz karede hemen None döner.

    `tests/test_projection.py` zaten kendi fikstürüyle hem bunu kapatıyor hem
    de yedek yolu açıkça sınıyor.
    """
    if request.node.path.name == "test_projection.py":
        return
    monkeypatch.setattr(projection, "_rembg_mask", lambda path, size: None)
    projection._MASK_CACHE.clear()


@pytest.fixture(autouse=True)
def no_projection_search(request, monkeypatch):
    """Projeksiyon aramasını kendi testleri dışında kapatır.

    Arama, model başına 70+ siluet rasterleştirip her fotoğrafla hizalama
    optimizasyonu koşturuyor: gerçek işte bir kez çalışıp önbelleğe
    yazılıyor, ama testlerde her paketleme onu yeniden tetikliyordu ve
    `test_pipeline` tek başına dakikalarca sürüyordu.

    Düz renkli test kareleri zaten anlamlı bir hizalama üretmez; sayfanın
    projeksiyonsuz (saf PBR) yolu da böylece sınanmış oluyor.
    `tests/test_projection.py` motoru doğrudan çağırdığı için etkilenmez;
    `test_package.py`'deki projeksiyon testleri `_projection_search`'ü
    kendileri taklit eder ve bu fikstürü atlar.
    """
    if request.node.path.name == "test_projection.py":
        return
    monkeypatch.setattr(projection, "build_multi",
                        lambda *a, **k: ([], {"total_coverage": 0.0}))
