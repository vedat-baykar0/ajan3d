"""Ajanlar arası veri sözleşmeleri (Pydantic).

    Vision Ajanı     -> ProductIdentity   (metadata.json -> identity)
    Teknik Ajan      -> SpecSheet         (metadata.json -> spec)
    CAD Ajanı bu ikisini okuyup montajı kurar.

Mimari değişikliğin sözleşmedeki izi: eski `VisionResult` 3D üretimini beslemek
için **hotspot konumları** taşıyordu (parça şurada, şu kutunun üst %20'sinde).
Artık fotoğraftan geometri çıkarılmadığı için o alanlar yok. Yerine **teknik
kimlik** geldi: anma çapı, basınç sınıfı, gövde malzemesi, bağlantı tipi,
kumanda tipi, parça sayısı ve ürün üzerinde okunan damgalar. Bunlar hem CAD
kütüphanesindeki aileyi seçer hem de EN 1092-1 / ISO 5211 tablolarından gerçek
ölçüleri çeker.

`family_hint` kasıtlı olarak kapalı bir listedir: ajanın serbest metin yerine
kataloğdan seçim yapması, eşleştirmeyi ölçülebilir ve denetlenebilir kılıyor.
"""
from typing import List, Literal

from pydantic import BaseModel, Field

# cad/library.py içindeki HINTS ile aynı kümedir; biri değişirse diğeri de değişmeli.
FamilyHint = Literal[
    "ball_valve", "gate_valve", "globe_valve", "butterfly_valve", "check_valve",
    "y_strainer", "flange_joint", "ball_bearing", "other",
]


class Identification(BaseModel):
    """Tanımanın ne kadar güvenilir olduğu."""
    confident: bool = Field(
        description="Ürünün tipi fotoğraftan güvenle belirlenebildi mi")
    confidence: Literal["high", "medium", "low"]
    issues: List[str] = Field(
        description="Tanımayı zorlaştıran sorunlar (bulanıklık, parlama, kadraj, "
                    "birden fazla ürün); sorun yoksa boş liste")


class ProductIdentity(BaseModel):
    """Vision ajanının çıktısı: ürünün teknik kimliği. Geometri ÜRETİLMEZ."""
    product_name: str = Field(description="Müşteriye gösterilecek tam ürün adı")
    product_name_en: str = Field(description="İngilizce karşılığı (arama için)")
    category: str = Field(description="Kategori, ör: 'endüstriyel vana', 'rulman'")
    family_hint: FamilyHint = Field(
        description="CAD kütüphanesindeki en uygun ürün ailesi. Emin değilsen 'other'")
    type_designation: str = Field(
        description="Tam tip tanımı, ör: '3 parçalı tam geçişli küresel vana, "
                    "dişli uçlu, ISO 5211 montaj flanşlı'")
    nominal_size: str = Field(
        description="Anma ölçüsü; okunabiliyorsa damgadan, yoksa orandan tahmin. "
                    "Ör: 'DN50', '2 inç'. Bilinmiyorsa boş bırak")
    pressure_rating: str = Field(
        description="Basınç sınıfı, ör: 'PN40', '1000 WOG', 'Class 150'. "
                    "Bilinmiyorsa boş bırak")
    body_material: str = Field(
        description="Gövde malzemesi, ör: 'CF8M paslanmaz çelik (AISI 316)'")
    end_connection: str = Field(
        description="Bağlantı tipi: flanşlı | dişli | kaynaklı | wafer | clamp")
    actuation: str = Field(
        description="Kumanda: kol | volan | redüktör | pnömatik | elektrikli | yok")
    piece_count: int = Field(
        description="Gövde parça sayısı (küresel vanada 1/2/3). Geçerli değilse 0")
    summary: str = Field(description="Ürün sayfası için 2-3 cümlelik tanıtım")
    visible_features: List[str] = Field(
        description="Fotoğrafta açıkça görülen ayırt edici özellikler")
    markings: List[str] = Field(
        description="Ürün üzerinde okunabilen yazı/damga (döküm kodu, marka, ölçü)")
    materials: List[str] = Field(description="Görünen malzemeler")
    identification: Identification


class SpecItem(BaseModel):
    """Teknik özellikler tablosunun bir satırı."""
    label: str = Field(description="Özellik adı, ör: 'Çalışma basıncı'")
    value: str = Field(description="Değer, ör: 'PN40 (40 bar)'")


class SpecSheet(BaseModel):
    """Teknik Ajanın çıktısı: internetten doğrulanmış ürün verisi."""
    identified_as: str = Field(
        description="İnternetteki referanslara göre ürünün endüstri standardı adı")
    confidence: Literal["high", "medium", "low"]
    nominal_size: str = Field(
        description="Doğrulanmış anma ölçüsü (DN veya inç); bulunamazsa boş")
    pressure_rating: str = Field(
        description="Doğrulanmış basınç sınıfı; bulunamazsa boş")
    temperature_range: str = Field(
        description="Çalışma sıcaklığı aralığı, ör: '-20 °C … +180 °C'")
    specs: List[SpecItem] = Field(
        description="Kaynaklı 4-12 teknik özellik; bulunamazsa boş liste")
    standards: List[str] = Field(
        description="İlgili standartlar, ör: ['EN 1092-1', 'ISO 5211', 'API 608']")
    standard_parts: List[str] = Field(
        description="Bu ürün tipinde standart olarak bulunan parçalar; fotoğrafta "
                    "GÖRÜNMEYENLER dahil (yay, oturma, salmastra, antistatik eleman)")
    surface_finish: str = Field(
        description="Tipik yüzey işlemi, ör: 'kumlanmış paslanmaz çelik, mat'")
    applications: List[str] = Field(
        description="Tipik kullanım alanları (2-5 madde)")
    reference_urls: List[str] = Field(description="Kullanılan kaynak adresleri")
