"""Genel gövde-kapak montajı — eşleşme bulunamadığında kullanılan yedek aile.

Tanınan ürün kütüphanedeki ailelerden hiçbirine oturmuyorsa sistem **sessizce
yanlış bir model üretmez**: ürünün kaba ölçülerinden kapaklı bir mahfaza
montajı kurar ve bunu `representative=True` ile işaretler. Sunum sayfası bu
durumda "temsili model" rozetini gösterir, teknik özellik tablosu ise yine
araştırmadan gelen gerçek verilerle dolar.

Neden yine de bir montaj üretiliyor: müşteriye gösterilecek bir şey olması,
hem de parçalara ayrılabilen ve içi dolu bir şey olması gerekiyor. Alternatif
(fotoğraftan kabuk üretmek) tam olarak kaçınılan şeydi.
"""
import math
from typing import Dict

from cad import primitives as P
from cad import standards as std
from cad.assembly import Assembly, Part, at, ring


def build(params: Dict[str, object]) -> Assembly:
    size = float(params.get("size_mm", 120.0))
    label = str(params.get("label", "Ürün montajı"))
    body_mat = str(params.get("body_material", "stainless_cast"))
    trim_mat = str(params.get("trim_material", "stainless_machined"))
    seal_mat = str(params.get("seal_material", "nbr"))
    bolt_mat = str(params.get("bolt_material", "zinc_plated"))

    P.clear_warnings()
    r = size / 2.0
    height = size * 0.72
    wall = max(4.0, size * 0.055)
    bolt_size = "M8" if size < 140 else ("M10" if size < 220 else "M12")
    bd = std.metric(bolt_size)[0]
    pcd = (r - bd * 0.95) * 2.0
    bolt_xy = P.bolt_circle(pcd, 6, 30)
    cover_t = max(7.0, bd * 1.1)
    gasket_t = 2.5
    shaft_d = max(10.0, size * 0.10)

    assembly = Assembly(
        family="generic_housing",
        label=label,
        representative=True,
        params={"size_mm": round(size, 1), "bolts": f"6×{bolt_size}"},
        notes=["Ürün kütüphanedeki parametrik ailelere eşleşmediği için temsili "
               "bir gövde-kapak montajı kuruldu. Ölçüler ve parça listesi "
               "gerçek ürünün birebir kopyası değildir; teknik özellik tablosu "
               "ise araştırmadan gelen doğrulanmış verilerdir."],
    )

    housing = P.union(
        P.cylinder(r, height, 0.0),
        P.disc(r + bd * 1.1, cover_t, height - cover_t,
               holes=[(x, y, bd / 2.0 + 0.3) for x, y in bolt_xy]))
    housing = P.cut(housing,
                    P.cylinder(r - wall, height - wall, wall),
                    P.cylinder(shaft_d / 2.0 + 0.3, wall * 3, -wall))
    assembly.add(Part(
        id="govde", name="Gövde", mesh=housing, material=body_mat, group="housing",
        note="Dökme gövde; üstte flanşlı kapak yüzeyi, altta mil geçişi.",
        placements=[at(stage=0, distance=0.0)]))

    cover = P.union(
        P.disc(r + bd * 1.1, cover_t, 0.0,
               holes=[(x, y, bd / 2.0 + 0.3) for x, y in bolt_xy]),
        P.cylinder(r - wall - 0.4, wall * 0.8, -wall * 0.8))
    cover = P.cut(cover, P.cylinder(shaft_d / 2.0 + 0.3, cover_t * 4, -cover_t * 2))
    assembly.add(Part(
        id="kapak", name="Kapak", mesh=P.translate(cover, 0, 0, height),
        material=body_mat, group="housing",
        note="Sökülebilir üst kapak; iç spigot'u gövdeye merkezlenir.",
        placements=[at(axis=(0, 0, 1), distance=0.70, stage=2)]))

    assembly.add(Part(
        id="conta", name="Conta",
        mesh=P.tube(r - wall - 0.4, r - 1.0, gasket_t, height - gasket_t),
        material=seal_mat, group="seal", note="Gövde-kapak contası.",
        placements=[at(axis=(0, 0, 1), distance=0.56, stage=3)]))

    shaft = P.union(
        P.cylinder(shaft_d / 2.0, height * 1.25, -wall * 1.5),
        P.cylinder(r * 0.52, height * 0.22, height * 0.30))
    assembly.add(Part(
        id="ic_gobek", name="İç göbek ve mil", mesh=shaft, material=trim_mat,
        group="internal",
        note="Gövde içindeki dönen göbek ve mil; X-Ray modunda görünür.",
        placements=[at(axis=(0, 0, -1), distance=0.62, stage=3)]))

    assembly.add(Part(
        id="oring", name="Mil O-ringi",
        mesh=P.torus(shaft_d / 2.0 + 1.6, 1.6), material="nbr", group="seal",
        note="Mil çevresini sızdırmaz yapan O-ring.",
        placements=[at(0, 0, wall * 0.5, axis=(0, 0, -1), distance=0.80, stage=3)]))

    bolt_len = math.ceil((cover_t * 2 + gasket_t + 6) / 5.0) * 5.0
    assembly.add(Part(
        id="civata", name="Kapak cıvatası",
        mesh=P.translate(P.rotate(P.hex_bolt(bolt_size, bolt_len, 0.0), 180, "x"),
                         0, 0, height + cover_t),
        material=bolt_mat, group="fastener",
        standard=f"DIN 933 {bolt_size}×{bolt_len:.0f}",
        note="Kapağı gövdeye sıkan cıvata.",
        placements=ring(bolt_xy, 0.0, axis=(0, 0, 1), distance=1.10, stage=1)))

    assembly.warnings.extend(P.warnings())
    return assembly
