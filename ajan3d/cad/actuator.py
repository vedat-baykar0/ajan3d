"""Pnömatik aktüatör (yaylı/çift etkili, kremayer-pinyon) — ISO 5211 üstüne.

Müşterinin gönderdiği ürün fotoğrafından modellendi. Okunabilen biçim:

* **Gövde** ekstrüzyon alüminyum: yatay bir prizma, dikey kenarları pahlı,
  üstünde NAMUR arayüzü için yükseltilmiş bir plato ve iki saplama.
* **İki uç kapağı MAVİ** boyalı, köşelerinde dörder alyan cıvata. Yay odası
  ve piston bu kapakların arasındadır; dışarıdan görünen tek şey kapaklardır.
* Üstte **sarı taban + siyah kubbe** konum göstergesi, kubbenin üzerinde sarı
  ok. Vananın açık/kapalı olduğu uzaktan buradan okunur.
* Ön yüzde **iki kırmızı tapa** (A ve B hava portları, BSP dişli).
* Altta vananın pabucuna **oturan** bir bağlantı ayağı (yoke) ve onu pabuca
  çeken dört cıvata; milin kare ucu ayağın içinden geçip pinyona girer.
  Ayak ALÇAK ve pabuç kadar GENİŞ: montaj fotoğrafında aktüatörün gövdesi
  neredeyse vananın üstüne değiyor.

**Neden ayrı bir modül.** Aktüatör vananın parçası değil, ona monte edilen
bağımsız bir üründür: başka vana ailelerine de (kelebek, küresel) aynı ISO
5211 arayüzünden takılır. Ölçüler pabuç ölçüsünden türetilir, böylece DN
değiştiğinde aktüatör de birlikte büyür.
"""
from __future__ import annotations

import math
from typing import List

from cad import primitives as P
from cad.assembly import Part, at

# Gövde oranları — fotoğraftan ölçüldü (pabuç kenarı = 1 birim).
BODY_LENGTH = 2.55        # silindir ekseni boyunca (akış yönüne dik)
BODY_WIDTH = 1.08         # akış yönünde
BODY_HEIGHT = 0.95
CAP_LENGTH = 0.17         # tek uç kapağının boyu (toplam boyun oranı)

# Bağlantı ayağının yüksekliği. ÖNCEKİ DEĞER 0,42 İDİ (DN50'de 27 mm) ve
# aktüatörü vananın 27 mm üstünde, ince bir kule üzerinde bırakıyordu: her
# açıdan "havada duruyor" diye okunuyordu. Müşterinin montaj fotoğrafında
# aktüatörün gövdesi pabuca neredeyse değiyor — arada yalnız alçak bir ayak
# var. Ölçü oradan: pabuç kenarının ~%14'ü.
YOKE_HEIGHT = 0.14
# Ayak pabucun İÇİNE gömülür. Sebebi yalnız montaj değil, render: ayağın alt
# yüzü pabucun üst yüzüyle TAM AYNI düzlemde olursa iki yüzey z-savaşına
# girer ve kamera döndükçe sınır pırıldayıp "parça kayıyor" gibi görünür.
# Gömme payı o düzlem çakışmasını kaldırır.
YOKE_SINK = 0.035

# --- patlatma düzeni ------------------------------------------------------- #
# Mesafeler montaj KÖŞEGENİNİN oranıdır. Aktüatör bütün olarak YUKARI çıkar;
# kapakları, cıvataları ve portları gövdeyle AYNI KADAR yükselip bir yandan
# da yana açılır. Önceki sürümde kapaklar yalnız yana gidiyor, gövde ise
# yukarı çıkıyordu: kapaklar gövdenin eski yerinde, boşlukta kalıyordu —
# "parçalar havada mantıksız yerlere uçuyor" dedirten asıl davranış buydu.
RISE_BODY = 0.72          # aktüatör gövdesinin yükselişi
RISE_YOKE = 0.60
RISE_YOKE_BOLT = 0.54
OUT_CAP = 0.34            # uç kapağının yana açılması
OUT_CAP_BOLT = 0.50       # cıvata kapağın DIŞINDA kalmalı
OUT_PORT = 0.30
RISE_DIAL = 0.86
RISE_POINTER = 0.94


def _lift(out_x: float = 0.0, out_z: float = 0.0, rise: float = RISE_BODY):
    """Yukarı + yana BİLEŞİK patlatma yönü ve uzunluğu.

    `at(...)` parça başına tek bir yön alıyor. Kapağı yalnız yana açmak onu
    yükselen gövdeden koparıyordu; iki bileşeni tek vektörde birleştirmek
    alt montajı bir arada tutuyor.
    """
    length = math.sqrt(out_x * out_x + rise * rise + out_z * out_z)
    if length <= 0:
        return (0.0, 1.0, 0.0), 0.0
    return (out_x / length, rise / length, out_z / length), length


def _rounded_box(width: float, depth: float, height: float, radius: float,
                 z0: float = 0.0) -> "P.trimesh.Trimesh":
    """Dikey kenarları yuvarlatılmış prizma (ekstrüzyon profili)."""
    return P.plate(P.rounded_rect_pts(width, depth, radius), height, z0)


def build(*, pad_top: float, pad_half: float, stem_d: float, zc: float,
          body_material: str = "aluminium_anodised",
          cap_material: str = "actuator_blue",
          # Alyan cıvatalar MAT. Parlatılmış paslanmaz (roughness 0,15)
          # küçük ve düz bir cıvata başında aynaya dönüyor: ışığı dik
          # yakalayan baş yakın planda cıvata değil BEYAZ BİR DELİK gibi
          # okunuyordu. Kumlanmış yüzey dağınık yansıtır, her açıdan
          # cıvata gibi durur — gerçek ürün de boyalı kapağa mat soket
          # başlı cıvatayla bağlanır.
          bolt_material: str = "stainless_blasted",
          indicator_material: str = "plastic_black",
          dial_material: str = "indicator_yellow",
          port_material: str = "port_red") -> List[Part]:
    """Pabucun üstüne oturan aktüatör parçaları.

    Patlatma mesafeleri montaj KÖŞEGENİNİN oranıdır; aktüatör köşegeni
    büyüttüğü için burada küçük tutulurlar (0,3-0,9). Vananın kendi
    değerleriyle aynı ölçekte yazmak parçaları kadrajın dışına atıyordu.

    `pad_top` pabucun üst yüzeyinin Y'si, `pad_half` kare pabucun yarı kenarı,
    `zc` montajın akış ekseni üzerindeki orta noktası. Parçalar vananın
    koordinat sisteminde (akış Z, mil +Y) döner.
    """
    size = pad_half * 2.0
    length = size * BODY_LENGTH
    depth = size * BODY_WIDTH
    height = size * BODY_HEIGHT
    yoke_h = size * YOKE_HEIGHT
    sink = size * YOKE_SINK
    # Pinyon göbeği (gövdenin altındaki yuva) ile ayağın bileziği GEÇMELİ
    # olmalı: bilezik göbekten genişse gövdeyi kaldırır ve aradaki boşluk
    # geri gelir. Bu yüzden iki ölçü de tek yerden, göbekten türetiliyor.
    hub_r = size * BODY_WIDTH * 0.30
    cap_len = length * CAP_LENGTH
    body_len = length - 2.0 * cap_len

    base = pad_top - sink               # ayağın tabanı: pabucun İÇİNE gömülü
    body_y0 = pad_top + yoke_h          # gövdenin alt yüzü
    body_y1 = body_y0 + height
    parts: List[Part] = []

    # --- bağlantı ayağı (yoke) -------------------------------------------- #
    # Pabucun üstüne OTURAN alçak, pahlı bir blok — kule değil. Kenar ölçüsü
    # pabuçla aynı; böylece aktüatör pabucu tam kapatır ve iki parça arasında
    # "havada duruyor" diye okunan boşluk kalmaz. Mil ortadan geçer.
    yoke_half = pad_half * 0.96
    yoke = P.plate(P.rounded_rect_pts(yoke_half * 2, yoke_half * 2,
                                      yoke_half * 0.22),
                   yoke_h + sink, 0.0)
    # Üstte gövdenin göbeğinin oturduğu dairesel bir bilezik: ayak kare,
    # gövdenin göbeği yuvarlak; geçişi çizmezsek kare blok kesik duruyor.
    yoke = P.union(yoke, P.cylinder(hub_r * 0.86, yoke_h * 0.55,
                                    yoke_h + sink - P.EPS))
    yoke = P.cut(yoke, P.cylinder(stem_d * 0.78, (yoke_h + sink) * 2.4, -P.EPS))
    parts.append(Part(
        id="aktuator_baglanti", name="Aktüatör bağlantı ayağı",
        mesh=P.translate(P.to_axis(yoke, "y"), 0, base, zc),
        material=body_material, group="actuator", standard="ISO 5211 F05/F07",
        note="Aktüatörü ISO 5211 pabucuna oturtan ayak; milin kare ucu "
             "içinden geçip pinyona girer.",
        placements=[at(axis=(0, 1, 0), distance=RISE_YOKE, stage=4)]))

    # --- ayağı pabuca çeken cıvatalar -------------------------------------- #
    # Aktüatör pabuca "yaslanmaz", DÖRT CIVATAYLA ÇEKİLİR. Cıvatalar
    # olmadan montaj anlatılmış olmuyor: izleyici iki parçanın neyle bir
    # arada durduğunu göremiyor ve aktüatör yine konmuş gibi duruyor.
    yoke_bolt_d = max(4.0, size * 0.075)
    yoke_bolt_len = yoke_h + sink + size * 0.12
    yb_head = P.cylinder(yoke_bolt_d * 0.80, yoke_bolt_d * 0.62, 0.0, sections=16)
    yb_shank = P.cylinder(yoke_bolt_d * 0.44, yoke_bolt_len, -yoke_bolt_len,
                          sections=16)
    yoke_bolt = P.to_axis(P.union(yb_head, yb_shank), "y")
    yb_r = yoke_half * 0.66
    parts.append(Part(
        id="aktuator_ayak_civatasi", name="Aktüatör ayak cıvatası",
        mesh=P.translate(yoke_bolt, 0, pad_top + yoke_h, zc),
        material=bolt_material, group="fastener",
        standard=f"DIN 912 M{yoke_bolt_d:.0f}",
        note="Aktüatörün ayağını ISO 5211 pabucuna çeken alyan cıvata (4 adet).",
        placements=[at(dx * yb_r, 0.0, dz * yb_r, axis=(0, 1, 0),
                       distance=RISE_YOKE_BOLT, stage=4, suffix=f"{i + 1}")
                    for i, (dx, dz) in enumerate(((1, 1), (1, -1),
                                                  (-1, 1), (-1, -1)))]))

    # --- gövde (ekstrüzyon) ----------------------------------------------- #
    # Yerel kurulum: uzunluk X'te, derinlik Z'de, yükseklik Y'de. Profili XY
    # düzleminde kurup X eksenine çevirmek yerine doğrudan kutu + pah ile
    # kuruyoruz; ekstrüzyon profili dikey kenarlarda yuvarlak.
    # Profil XY düzleminde kurulup Z'de uzatılıyor; sonra bütün aktüatör
    # `to_axis(..., "y")` ile mil eksenine çevriliyor. Yani yerel Z = yükseklik.
    body = _rounded_box(body_len, depth, height, depth * 0.13)
    # NAMUR platosu: üstte dar bir çıkıntı
    plateau = P.box(body_len * 0.52, depth * 0.52, height * 0.10,
                    (0, 0, height + height * 0.05))
    body = P.union(body, plateau)
    # Pinyon kovanı: altta milin girdiği göbek. Eteği ayağın bileziğini
    # ÖRTER, pabuca kadar inmez — eskiden height*0.26 iniyor ve pabucun
    # içinden geçiyordu.
    hub_drop = yoke_h * 0.78
    hub = P.cylinder(hub_r, hub_drop, -hub_drop)
    body = P.union(body, hub)
    body = P.cut(body, P.cylinder(stem_d * 0.80, height * 1.6, -hub_drop - P.EPS))
    parts.append(Part(
        id="aktuator_govdesi", name="Aktüatör gövdesi",
        mesh=P.translate(P.to_axis(body, "y"), 0, body_y0, zc),
        material=body_material, group="actuator",
        standard="ISO 5211 / NAMUR VDI 3845",
        note="Ekstrüzyon alüminyum gövde; içinde kremayer-pinyon mekanizması "
             "ve pistonlar bulunur. Üstte NAMUR sinyal kutusu arayüzü.",
        placements=[at(axis=(0, 1, 0), distance=RISE_BODY, stage=3)]))

    # --- uç kapakları (mavi) ---------------------------------------------- #
    # İki kapak AYNI parçadır: tek mesh, iki yerleşim. Ayrı parça yazmak
    # dosyayı büyütür ve parça listesinde aynı ürünü iki kez gösterirdi.
    cap = _rounded_box(cap_len, depth * 1.02, height * 1.02, depth * 0.16)
    cap = P.translate(cap, 0, 0, -height * 0.01)
    cap_x = body_len * 0.5 + cap_len * 0.5
    parts.append(Part(
        id="aktuator_kapagi", name="Aktüatör uç kapağı",
        mesh=P.translate(P.to_axis(cap, "y"), -cap_x, body_y0, zc),
        material=cap_material, group="actuator",
        note="Boyalı alüminyum uç kapağı; yay odasını kapatır ve "
             "pistonun strokunu sınırlar.",
        placements=[at(axis=_lift(-OUT_CAP)[0], distance=_lift(-OUT_CAP)[1],
                       stage=2, suffix="1"),
                    at(2 * cap_x, 0, 0, axis=_lift(OUT_CAP)[0],
                       distance=_lift(OUT_CAP)[1], stage=2, suffix="2")]))

    # --- kapak cıvataları --------------------------------------------------- #
    # Sekiz kapak cıvatası tek mesh paylaşır; yerleşimler köşelere dağıtır.
    #
    # Mesh ORİJİNDE kuruluyor. Sebebi `at(...)`'in sözleşmesi: döndürme
    # montaj orijini etrafında yapılır, öteleme ondan SONRA eklenir. Mesh
    # kendi yerinde dururken 180° çevrilince karşı tarafa fırlıyor ve
    # öteleme onu bir kat daha uzağa taşıyordu (ölçüldü: montaj X boyu
    # 168 mm yerine 331 mm). Orijinde duran bir mesh dönmeden etkilenmez.
    bolt_d = max(4.0, size * 0.055)
    # Cıvatalar kapağın KÖŞELERİNDE. Tek bir `bolt_r` ile dört cıvatayı aynı
    # dairenin üstüne koymak onları kapağın ortasına topluyordu; referans
    # fotoğrafta dördü de köşelerde, kenardan bir cıvata payı içeride.
    bolt_margin = max(bolt_d * 1.35, size * 0.085)
    bolt_dy = height * 0.5 - bolt_margin
    bolt_dz = depth * 0.5 - bolt_margin
    bolt_len = cap_len + size * 0.10          # kapağı geçip gövdeye girer
    head_h = bolt_d * 0.55
    head = P.cylinder(bolt_d * 0.78, head_h, 0.0, sections=16)
    # ALYAN YUVASI. Düz bir silindir tepesi parlatılmış paslanmazda kameraya
    # dönük dümdüz bir ayna oluyor ve yakın planda cıvata değil BEYAZ BİR
    # DELİK gibi okunuyordu. Yuva hem kırıcı bir gölge verir hem de parçanın
    # ne olduğunu söyler.
    head = P.cut(head, P.hex_prism(bolt_d * 0.62, head_h * 0.62,
                                   head_h - head_h * 0.62 + P.EPS))
    shank = P.cylinder(bolt_d * 0.42, bolt_len, -bolt_len, sections=16)
    total_h = head_h + bolt_len
    bolt = P.translate(P.union(head, shank), 0, 0, (bolt_len - head_h) * 0.5)
    bolt = P.rotate(bolt, -90, "y")                      # başı -X'e bakar
    # Başın DIŞ yüzü kapağın dış yüzeyiyle aynı düzlemde olmalı; mesh
    # orijinde merkezli olduğu için merkez o kadar içeri çekiliyor.
    x_cap = length * 0.5 - total_h * 0.5
    bolt_places = []
    for sign in (-1, 1):
        for index, (dy, dz) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
            bolt_places.append(at(
                sign * x_cap, body_y0 + height * 0.5 + dy * bolt_dy,
                zc + dz * bolt_dz, axis=_lift(sign * OUT_CAP_BOLT)[0],
                distance=_lift(sign * OUT_CAP_BOLT)[1], stage=1,
                rotation=None if sign < 0 else (180.0, "y"),
                suffix=f"{'a' if sign < 0 else 'b'}{index + 1}"))
    parts.append(Part(
        id="aktuator_civatasi", name="Aktüatör kapak cıvatası", mesh=bolt,
        material=bolt_material, group="fastener",
        standard=f"DIN 912 M{bolt_d:.0f}",
        note="Uç kapağını gövdeye bağlayan alyan cıvata (kapak başına 4).",
        placements=bolt_places))

    # --- konum göstergesi --------------------------------------------------- #
    dial_r = depth * 0.30
    dial = P.revolve([
        (0, 0), (dial_r, 0), (dial_r, height * 0.07),
        (dial_r * 0.74, height * 0.10), (0, height * 0.10)], 48)
    parts.append(Part(
        id="aktuator_kadran", name="Gösterge kadranı",
        mesh=P.translate(P.to_axis(dial, "y"), 0, body_y1 + height * 0.05, zc),
        material=dial_material, group="actuator",
        note="Sarı gösterge kadranı; vananın açık/kapalı konumu buradan okunur.",
        placements=[at(axis=(0, 1, 0), distance=RISE_DIAL, stage=2)]))

    dome_r = dial_r * 0.72
    dome = P.revolve([
        (0, 0), (dome_r, 0), (dome_r * 0.95, dome_r * 0.55),
        (dome_r * 0.62, dome_r * 0.95), (0, dome_r * 1.02)], 48)
    pointer = P.box(dome_r * 0.26, dome_r * 1.70, dome_r * 0.22,
                    (0, 0, dome_r * 0.92))
    dome = P.union(dome, pointer)
    parts.append(Part(
        id="aktuator_gostergesi", name="Konum göstergesi",
        mesh=P.translate(P.to_axis(dome, "y"),
                         0, body_y1 + height * 0.14, zc),
        material=indicator_material, group="actuator",
        note="Siyah gösterge kubbesi ve üzerindeki ok; mille birlikte döner.",
        placements=[at(axis=(0, 1, 0), distance=RISE_POINTER, stage=1)]))

    # --- hava portları (kırmızı tapalar) ------------------------------------ #
    port_r = max(2.6, size * 0.052)
    plug = P.revolve([
        (0, 0), (port_r, 0), (port_r, port_r * 0.55),
        (port_r * 0.55, port_r * 0.80), (0, port_r * 0.80)], 24)
    parts.append(Part(
        id="aktuator_portu", name="Hava portu tapası",
        mesh=P.translate(P.to_axis(plug, "z"), -port_r * 2.1,
                         body_y0 + height * 0.40, zc + depth * 0.5),
        material=port_material, group="actuator", standard='G 1/4" BSP',
        note="Hava bağlantı portu (A/B); nakliye tapası takılı.",
        placements=[at(axis=_lift(out_z=OUT_PORT)[0],
                       distance=_lift(out_z=OUT_PORT)[1], stage=1, suffix="A"),
                    at(port_r * 4.2, 0, 0, axis=_lift(out_z=OUT_PORT)[0],
                       distance=_lift(out_z=OUT_PORT)[1], stage=1, suffix="B")]))

    return parts
