# Yerel CAD kütüphanesi

Bu klasöre koyduğunuz **gerçek CAD dosyaları**, parametrik üretimden önce
denenir. Kütüphane büyüdükçe sistem "model üretme"den "model eşleştirme"ye
kayar — ve tedarikçiden gelen gerçek bir katalog modeli her zaman üretilmiş
modelden iyidir.

## Nasıl eklenir

Her ürün kendi klasöründe durur:

```
cad_library/
└─ dn50-3pc-kuresel-vana/
   ├─ model.glb
   └─ manifest.json
```

`model.glb` dosyasına **hiç dokunulmaz**. Sistem yalnızca `manifest.json`
içinde adı geçen düğümlere patlatma sözleşmesini (`extras`) ekler, böylece
kütüphane modeli de parametrik modelle aynı arayüzü besler: parçalama,
X-Ray, parça listesi ve etiketler çalışır.

### manifest.json

```json
{
  "label": "DN50 3 parçalı küresel vana (Tedarikçi A, kod 2103-50)",
  "family": "ball_valve",
  "keywords": ["küresel vana", "ball valve", "dn50", "3 parçalı", "cf8m"],
  "model": "model.glb",
  "representative": false,
  "diagonal_mm": 285,
  "specs": [
    {"label": "Katalog kodu", "value": "2103-50"},
    {"label": "Anma çapı", "value": "DN50"}
  ],
  "parts": [
    {
      "node": "Body",
      "id": "govde",
      "name": "Orta gövde",
      "group": "housing",
      "material": "stainless_cast",
      "axis": [0, 1, 0],
      "distance": 0,
      "stage": 0,
      "qty": 1,
      "standard": "ASME B16.34",
      "note": "Döküm gövde"
    },
    {
      "node": "EndCap_L",
      "id": "kapak",
      "name": "Uç kapağı",
      "group": "housing",
      "material": "stainless_cast",
      "axis": [0, 0, -1],
      "distance": 0.72,
      "stage": 2
    }
  ]
}
```

### Alanlar

| Alan | Anlamı |
|---|---|
| `keywords` | Eşleştirme bunlara bakar. Türkçe + İngilizce + ölçü yazın; uzun ifadeler daha ayırt edicidir. **2.0 puanın altında kalan eşleşme kabul edilmez.** |
| `node` | GLB içindeki düğümün adı. Listelemek için: `python run_cad.py --families` değil, kısa yol → `python -c "from cad import gltf; print(gltf.node_names(open('model.glb','rb').read()))"` |
| `group` | `housing` (X-Ray'de saydamlaşır) · `internal` · `seal` · `fastener` · `actuator` |
| `axis` | Parçanın **montaj ekseni** — söküldüğünde hangi yöne çıkar. Birim olması gerekmez, normalize edilir. |
| `distance` | Köşegene oranla açılma mesafesi. Dışta kalan parçalar daha büyük değer alır (cıvata 1.2, kapak 0.7, oturma 0.35). |
| `stage` | Sökme sırası. **En az bir parça `stage: 0` ve `distance: 0` olmalı** — montajın sabit gövdesi odur. |
| `material` | `cad/materials.py` içindeki anahtar. Parça listesindeki renk karesi buradan gelir. |
| `representative` | Model birebir bu ürün değilse `true` yapın; sayfada "Temsili model" rozeti çıkar. |

### Birim

Model **metre** cinsinden olmalı (glTF geleneği). `diagonal_mm` verilmezse
sayfa köşegeni geometriden ölçer, yani boş bırakılabilir.

### Kütle

Kütüphane modellerinde kütle **hesaplanmaz** (dosyanın su geçirmez katı olup
olmadığı bilinemez). Parça listesinde kütle sütunu boş kalır; teknik özellik
tablosu `specs` alanından dolar. Parametrik modellerde kütle hacimden
hesaplanır ve gösterilir.

## Eşleştirmeyi denemek

```powershell
python run_cad.py "jobs\<is-dizini>" --force
```

Çıktının ilk satırı hangi kaynağın kazandığını ve neden kazandığını yazar.
`cad.json` içindeki `match_reason` aynı bilgiyi kalıcı olarak tutar.

Kütüphaneyi tamamen devre dışı bırakmak için `.env` → `CAD_SOURCES=parametric`.
