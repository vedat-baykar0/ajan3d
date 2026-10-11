# PROJECT_STATUS — ajan3d

_Son güncelleme: 2026-10-11 (LookDev turu: üç bantlı yüzey, derin AO, heybetli
kadraj, yalnız ana parça etiketleri)_

> **Bu sürümde ne değişti:** proje "fotoğraftan 3D mesh üretme" sisteminden
> **"akıllı ürün eşleştirme ve parametrik CAD sunumu"** sistemine dönüştü.
> Fotoğraf artık yalnızca **tanıma** girdisidir; geometri standart ölçü
> tablolarından ve bir parametrik CAD çekirdeğinden kurulur.

---

## 0. Neden değişti — eski mimarinin kusuru

TRELLIS/InstantMesh gibi Image-to-3D ağları ürünün **yalnızca dış kabuğunu**
üretir. İçinin dolu olduğunu, vidanın nereye girdiğini, contanın hangi yuvaya
oturduğunu bilemez — çünkü bu bilgi fotoğrafta yoktur. Kabuğu kodla
(mesh split / geodezik Voronoi) parçalamaya kalkınca kâğıt gibi yırtılıyor, içi
boş bir görüntü çıkıyordu.

Ölçülen durum (önceki oturum, gerçek vana modeli): 186.191 yüzlük tek bir
kabuk; köşeler kaynaştırıldıktan sonra **tek bileşen** (%99,8). Yani cıvatalar,
kol ve gövde geometrik olarak tek yüzeydi. Parçalama tahminden ibaretti.

**Yeni yaklaşım:** ürünün *ne olduğu* bilinirse geometri doğru kurulabilir.
Bir DN50/PN40 flanşın 165 mm çapında, 125 mm delik dairesinde, 4×M16 cıvatalı
olduğu EN 1092-1 tablosunda yazar. Parça **önce** vardır, montaj ondan kurulur.

---

## 1. Yeni zincir

```
inbox\<klasör>  (fotoğraflar)
   │
   ├─[1] Tanıma Ajanı (Claude Vision)    → metadata.json: identity
   │      ürünün TEKNİK KİMLİĞİ: tip, DN, PN, malzeme, bağlantı,
   │      kumanda, gövde parça sayısı, üzerindeki damgalar
   │
   ├─[2] Teknik Veri Ajanı (Claude+web)  → metadata.json: spec
   │      katalog verileri, standartlar, standart parça listesi
   │
   ├─[3] CAD Ajanı (yerel, ücretsiz)     → model.glb + cad.json
   │      kütüphane eşleştirme → parametrik montaj (Boolean katılar)
   │
   ├─[4] Teslimat Ajanı                  → delivery_<ürün>_<tarih>\ + .zip
   │      Three.js endüstriyel sunum sayfası
   │
   └─[5] Yayın Ajanı + tünel             → PUBLIC LINK (https://...)
```

**Kaldırılanlar:** `agents/generation_agent.py` (HF Space / TRELLIS),
`core/segment.py`, `core/explode.py`, `core/glb.py`, `core/hotspots.py`,
`core/preprocess.py` (rembg), `core/selector.py`. 3D üretim artık ağa,
GPU kotasına veya kuyruğa bağlı değil.

---

## 2. Dosyalar

```
ajan3d\
├─ baslat.ps1              ★ ANA KOMUT (değişmedi): -Durum -Durdur -Gunluk -Yeniden
├─ run_agency.py           Orkestratör: izleme + işçi + iki web sunucusu + tünel
├─ run_all.py              Tek seferlik üretim
├─ run_vision.py / run_cad.py / run_package.py   Tek adım çalıştırıcıları
│                          (run_cad.py --families kütüphaneyi listeler)
├─ cad\                    ★ YENİ — parametrik CAD çekirdeği
│  ├─ primitives.py        devirme, delikli plaka, diş, cıvata/somun, Boolean
│  ├─ standards.py         EN 1092-1 flanş, ISO 5211 pabuç, ISO 724 vida,
│  │                       DN/PN/bağlantı/kumanda metin ayrıştırıcıları
│  ├─ materials.py         PBR + YOĞUNLUK (kütle hesabı buradan)
│  ├─ ao.py               ★ pişirilmiş ortam gölgelemesi (voksel doluluk)
│  ├─ actuator.py         ★ pnömatik aktüatör (ISO 5211 üstüne monte)
│  ├─ assembly.py          Part/Placement/Assembly, doğrulama, kütle dökümü
│  ├─ gltf.py              GLB yazıcı: açı bölünmüş normaller, düğüm extras
│  ├─ library.py           aile kataloğu + eşleştirme + parametre türetme
│  ├─ retrieval.py         yerel kütüphane → uzak API → parametrik
│  └─ families\            ball_valve · gate_valve (gate/globe) ·
│                          butterfly_valve · check_valve · strainer ·
│                          flange_joint · bearing · generic
├─ agents\
│  ├─ vision_agent.py      ★ teknik kimlik çıkarır (geometri ÜRETMEZ)
│  ├─ spec_agent.py        ★ web_search ile katalog verisi
│  ├─ cad_agent.py         ★ montajı kurar → model.glb + cad.json
│  ├─ packager_agent.py    ★ Three.js sunum paketi
│  ├─ deployer_agent.py    public\ yayını (değişmedi)
│  └─ receiver_agent.py / notifier_agent.py (değişmedi)
├─ core\                   config · schemas · pipeline · agency · tunnel ·
│                          hdri · qr · images · jobs · optimize
│  └─ projection.py       ★ fotoğrafı modelin kabuğuna oturtan hizalama
│                         (hdri.py ayrıca fabrika holü fonunu üretir)
├─ templates\viewer.html.j2  ★ Three.js endüstriyel arayüz
├─ cad_library\            yerel .glb kütüphanesi (README.md kurulumu anlatır)
├─ vendor\three\           Three.js r180 modülleri (offline çalışsın diye)
└─ tests\                  332 test
```

---

## 3. Parametrik CAD çekirdeği

### 3a. Her parça kapalı bir KATI

`manifold3d` Boolean motoruyla gerçek katı modelleme: delikler **açılır**,
yuvalar **kesilir**, gövdeler **birleştirilir**. Ölçülen: DN50 3 parçalı
küresel vana → 16 parça, 26 örnek, **16/16 su geçirmez katı**, 0 Boolean
düşüşü, 0,35 sn.

Katı olmanın ölçülebilir karşılığı **kütle**: hacim × yoğunluk. DN50 vana
**4,62 kg** çıkıyor (gerçek katalog değeri 3–4,5 kg). Kabuk model üretilseydi
hacim hesaplanamaz, kütle sütunu boş kalırdı — yani kütle aynı zamanda bir
doğrulamadır.

### 3b. Üç kurulum yolu

| Yol | Ne için | Not |
|---|---|---|
| `revolve` | eksenel simetrik her şey (gövde, top, mil, oturma, conta) | profil `(r, z)` düzleminde |
| `plate` | flanş, kapak, montaj pabucu | shapely poligonu, delikler kalıpla açılır |
| `union`/`cut` | geçişler, yuvalar, diş boşlukları | manifold3d |

### 3c. Ölçülerin kaynağı

EN 1092-1 flanş tablosu (DN15–DN300, PN16/PN40), ISO 5211 pabuç (F03–F12),
ISO 724 metrik vida. Metin ayrıştırıcıları `DN50`, `2"`, `1 1/2"`, `PN40`,
`Class 300`, `1000 WOG`, `16 bar` biçimlerinin hepsini kabul eder.

### 3d. Küresel vana — eksenel düzenin çıkarılışı

Top dışı küre içi deliktir. Delik Z ekseninde açıldığı için topun **eksenel**
uzanımı küre yarıçapı değil `h = √(r² − (delik/2)²)` kadardır (DN50 için 36 mm
değil **25,9 mm**). Gövde boyu bu sayıdan çıkar; küre çapından hesaplanırsa
gövde 20 mm fazla uzun olur. Oturmaların ön yüzü top küresiyle **Boolean
çıkarma** ile kesilir — oturma yüzeyi gerçekten küreseldir.

---

## 4. Kütüphane ve eşleştirme

İki kademeli: **ajanın önerisi** (`family_hint`, kapalı liste) + **anahtar
kelime puanlaması**. Ajanın önerisi büyük puan katkısıdır ama metin başka bir
aileyi güçlü işaret ediyorsa metin kazanır. Eşik altında kalan her şey
`generic_housing`'e düşer ve montaj **temsili** işaretlenir — sistemin
"bilmiyorum" deme yolu.

Kaynak sırası (`CAD_SOURCES`, varsayılan `local,parametric`):

1. **Yerel kütüphane** (`cad_library/<klasör>/model.glb` + `manifest.json`) —
   elinizdeki gerçek CAD dosyaları. Düğüm adlarına patlatma sözleşmesi işlenir.
2. **Uzak API** (`CAD_API_URL`) — varsayılan kapalı.
3. **Parametrik** — her zaman çalışan taban yol.

> **Dürüst not — Thangs / GrabCAD:** GrabCAD'in açık indirme API'si **yoktur**
> (oturum ister, içerik yeniden dağıtılamaz). Thangs'in API'si **anahtarla
> kapalıdır** ve içeriği çoğunlukla STEP/SLDPRT'tir — `.glb` değildir ve
> parçaları adlandırılmış/ayrılmış gelmez. Bu yüzden belirli bir sağlayıcıya
> kod gömülmedi; yerine **genel bir sözleşme** var (arama adresi JSON döner,
> içinde `.glb` bağlantısı aranır). Anahtarınız olan herhangi bir servisi
> `.env` ile bağlayabilirsiniz.

---

## 5. Sunum sayfası (Three.js)

`templates/viewer.html.j2` tamamen yeniden yazıldı. model-viewer bırakıldı.

| Yetenek | Ayrıntı |
|---|---|
| **Birleştir / Parçala** | Kaydırıcı + düğme; her parça kendi **montaj ekseninde** açılır, aşamalı gecikme (`st`) sökme sırasını gösterir |
| **X-Ray** | `grp == "housing"` saydamlaşır (%12), iç mekanizma opak kalır, saydam gövdeye **kenar çizgileri** eklenir |
| **Etiketler** | Projeksiyonla konumlanan etiket + nokta + çeker çizgi; ekran merkezinden dışa itilir |
| **Parça seçimi** | 3B'de tıkla veya listeden seç → diğerleri hayalet olur, bilgi kartı açılır |
| **Üst etiket şeridi** | CF8M/316 · DN50 · PN63 · Sıcaklık · Bağlantı · Kumanda · ISO 5211 F05 |
| **Sağ panel** | Müşteri fotoğrafı (+ küçük resimler), teknik özellikler, parça listesi (adet/kütle/malzeme rengi), malzeme dökümü, model doğrulama, standart bileşenler, kullanım alanları, standartlar, kaynaklar |
| **Fotoğraf yansıtma** | Müşterinin fotoğrafı sabit bir projektörden modelin kabuğuna düşer; kamera dönerken doku YAPIŞIK kalır, patlatmada parçayla gider. Karışım şeritten ayarlanır (bkz. 9. bölüm) |
| **Fallback endüstriyel PBR** | Fotoğrafın görmediği yüzeyler (arka yüz, iç mekanizma, vidalar) koyu ve pürüzlü çeliğe kayar |
| **Pişirilmiş AO** | Girinti ve dip kararmaları `COLOR_0`'dan okunur; dolaylı ışığa ve ortam yansımasına uygulanır, çalışma zamanı maliyeti sıfır |
| **Stüdyo HDRI + PBR** | Sentetik `studio.hdr` (226 KB) → PMREM; ACES ton eşlemesi; üç nokta ışık + yumuşak gölge |
| **Ölçek çubuğu** | Kameraya göre canlı mm/m ölçeği |
| **Diğer** | Döndür, Sıfırla, Tam ekran, Görüntü al (PNG), Link paylaş; klavye `E X L R F Space 1-9` |

**Paket boyutu: 2,4 MB** (önceki mimaride 11–27 MB). Telefonda ilk açılış
doğrudan buna bağlı.

---

## 6. Doğrulama

### 332 test geçiyor (ağ/API/GPU gerektirmez)

| Dosya | Kapsam |
|---|---|
| `test_cad_kernel.py` (43) | devirme hacmi, ters sarım düzeltmesi, delikli plaka, her ölçüde somun/cıvata katılığı, diş profilinin aralıktan taşmaması, Boolean düşüşünün **kaydedilmesi**, EN 1092-1 tablo doğruluğu, cıvata deliklerinin flanşa sığması, metin ayrıştırma |
| `test_families.py` (156) | 15 montaj varyantı × her parçanın su geçirmez olması, pozitif kütle, patlatmanın gerçekten ayırması, **Boolean uyarısı olmaması**, sabit gövdenin bulunması, ölçek duyarlılığı, eşleştirici doğruluğu |
| `test_gltf.py` (22) | GLB kabı ve 4 bayt hizalama, min/max zorunluluğu, birim matrisin yazılmaması, **patlatma sözleşmesinin her düğümde olması**, örneklerin tek mesh paylaşması, normallerin birim olması, sRGB→lineer, hazır GLB'ye sözleşme ekleme, **ters eksenin yakalanması** |
| `test_retrieval.py` (15) | yerel kütüphanenin bulunması ve **tercih edilmesi**, bozuk manifestin çökertmemesi, hazır GLB'ye sözleşme eklenirken **geometrinin değişmemesi**, eksenlerin normalize edilmesi, bir kaynak patlarsa zincirin sonrakine geçmesi |
| `test_package.py` (33) | paketin kendi kendine yetmesi (vendor/three dahil), 6 MB sınırı, gömülü JSON'un cad.json ile uyuşması, her malzemenin renk karesi olması, **müşteri metninin kaçışlanması**, araştırma verisi olmadan da sayfa üretilmesi |
| `test_pipeline.py` (16) | **ücretli aramanın başarısız olmasının teslimi durdurmaması**, aynı aramanın ikinci kez yapılmaması, geçici/kalıcı hata ayrımı, düşük güvenin işi bloke etmesi, tamamlanmış adımların atlanması |
| `test_tunnel.py` (15) | adres ayıklama, süreç ölünce yeniden kurma, iş parçacığı güvenliği |
| `test_agency_web.py` (19) | yayın sunucusunun yönetim bilgisi sızdırmaması, aynı portun reddedilmesi, XSS |

### Dış araçlarla doğrulama (bu oturum)

| Kontrol | Sonuç |
|---|---|
| **Khronos glTF Validator** (`gltf-validator` npm) | ✅ **0 hata, 0 uyarı, 0 bilgi** |
| **Gerçek three.js r180 GLTFLoader** (node, `loader.parse`) | ✅ 26 mesh, 70.382 üçgen, 6 malzeme, **26/26 düğümde patlatma sözleşmesi**, bütün eksenler birim |
| Sayfa modül betiği sözdizimi (`vm.SourceTextModule`) | ✅ 477 satır, hatasız |
| `getElementById` kimlikleri ↔ HTML | ✅ 27 kullanılan / 30 tanımlı, eksik 0 |
| Gömülü JSON + importmap + vendor dosyaları | ✅ hepsi mevcut |
| Malzeme renk sözlüğü ↔ parça listesi | ✅ eşleşmeyen 0 |
| `run_agency.py --check` | ✅ tamam, cloudflared bulundu |

### Canlı uçtan uca çalıştırma (10 Ekim 2026, 12:58)

Gerçek fotoğraflar, gerçek API, gerçek public link. **66 saniyede** tamamlandı:

| Adım | Süre | Sonuç |
|---|---|---|
| Tanıma (Claude Vision) | 13 sn | DN50 · PN63 · CF8 (AISI 304) · dişli · 3 parçalı · **çıplak mil** · aile önerisi `ball_valve` |
| Okunan damgalar | — | `DN50 PN63`, `CF8`, `2311`, `SJ`, `A2-70` (cıvata kalitesi dahil) |
| Teknik veri (web_search) | 41 sn | 4 arama, 39 kaynak, 10 özellik, **19 standart parça**, $0.166 |
| CAD montajı | 1 sn | 13 parça / 23 örnek, **13/13 su geçirmez katı**, 4,42 kg, 0,97 MB |
| Paket + yayın | 2 sn | 2,29 MB |

İnternetten doğrulandı: `index.html` 200, `model.glb` 200 (`model/gltf-binary`),
`studio.hdr` 200, fotoğraflar 200, `vendor/three/*` 200, galeri 200 — ve
**`/api/jobs` 404** (yönetim paneli dışarıya sızmıyor).

Yayınlanan model Khronos doğrulayıcısından yine **0 hata / 0 uyarı / 0 bilgi**
ile geçti; gerçek three.js ile 23 mesh, 23/23 düğümde patlatma sözleşmesi.

**Canlı çalıştırmada yakalanan 3 hata** (hepsi düzeltildi ve testle kilitlendi):

1. **Takılmış işaret (claim).** Servis klasörü işaretledikten sonra, iş kaydını
   açmadan yeniden başlatılınca klasör bir daha hiç alınmıyordu — işaret
   "kuyrukta" diyor ama kuyrukta kimse yok. Gözetimsiz bir sistemde bu, sessizce
   kaybolan müşteri işi demek. Artık işaretin gösterdiği iş dizininde gerçek bir
   kayıt aranıyor; taze işaretler korunuyor.
2. **Çıplak milli vanaya volan takılması.** Vision ürünü doğru tanıdı
   ("kolsuz, çıplak mil") ama `parse_actuation` içinde **"kolsuz" kelimesi "kol"
   kuralına takılıyor**, ardından tanıtım metnindeki "aktüatör" kelimesi pnömatik
   sanılıp volan çiziliyordu. `none` kuralı eklendi ve en başa alındı;
   pnömatik/elektrikli aktüatör de artık çizilmiyor (ayrı satın alınan ürün).
3. **Şeritte yanlış malzeme kalitesi.** Vanada `CF8` (AISI 304) damgalı ama şerit
   malzeme ailesinin genel kodunu (`CF8M / 316`) gösteriyordu. Artık önce ürünün
   üzerinde okunan damga, sonra araştırmanın doğruladığı kalite, en son ailenin
   genel kodu kullanılıyor.

### Tarayıcı doğrulaması ve performans (10 Ekim 2026, 14:00)

**Bildirilen sorun:** sayfa "CAD montajı yükleniyor" ekranında donuyordu.
**Gerçek sebep boyut değildi** — model 35.070 üçgen / 994 KB, yani orta sınıf
bir telefonun rahatça çevirdiği bir dosya. Sorun iki eksik yüklemeydi ve ikisi
de yalnızca tarayıcı konsolunda iz bırakıyordu.

Bu oturumda ilk kez **gerçek Chrome** ile test edildi (`puppeteer-core` +
kurulu Chrome), sorun birebir yeniden üretildi ve düzeltildikten sonra
görsel olarak doğrulandı.

#### Donmanın iki sebebi

1. **Geçersiz import map.** `"three": "vendor/three/three.module.min.js"`
   yazılmıştı. Import map değerleri `./`, `../`, `/` ile ya da mutlak adresle
   başlamak zorunda; çıplak yazılan yol *bare specifier* sayılıyor ve tarayıcı
   **bütün haritayı iptal ediyor**. Modül `three`i çözemiyor, üst seviye kod
   hiç çalışmıyor, yükleme ekranı sonsuza kadar kalıyor.
2. **Eksik modül dosyaları.** three r180 build'i `three.module.min.js` +
   `three.core.min.js` olarak ikiye bölünmüş; yalnızca ilki kopyalanmıştı.
   Draco yolu açıldığında `DRACOLoader.js` de eksikti. Her ikisi de konsolda
   sessiz 404.

Artık paket, modül grafiği doğrulanmadan yazılmıyor
(`packager_agent.missing_modules`), ve sayfa modül hiç çalışmazsa bile
**klasik bir betikle** hatayı ekrana basıyor — sonsuz "yükleniyor" ekranı
mimari olarak imkânsız hale getirildi.

#### Eklenen performans ve yükleme zinciri

| Konu | Yapılan |
|---|---|
| **Draco sıkıştırma** | `tools/node/optimize_glb.mjs` (`@gltf-transform` + `draco3dgltf`). **994 KB → 121 KB (%88)**. Uzantı elle yazılmıyor; sıkıştırılmış dosya geri okunup düğüm sözleşmesi, mesh sayısı, üçgen sayısı ve sınır kutuları karşılaştırılmadan kabul edilmiyor. |
| **Eşik** | Çözücü (~250 KB wasm) sabit maliyet; `DRACO_MIN_BYTES` (400 KB) altındaki modeller sıkıştırılmıyor — küçük modelde sıkıştırmak toplam indirmeyi artırırdı. Çözücü yalnızca gerçekten Draco'lu modelde **dinamik import** ile iniyor. |
| **İsteğe bağlılık** | Node yoksa, paketler eksikse veya bütünlük düşerse adım sessizce atlanıyor; zincir sıkıştırılmamış modelle devam ediyor. |
| **Gerçek yüzde** | Dosya boyutları paketleme sırasında ölçülüp sayfaya gömülüyor. Gerekliydi: tünel yanıtları parçalı (chunked) geldiği için `Content-Length` yok ve tarayıcının bildirdiği `total` sıfır — eski sayfada yüzde hiç ilerlemiyordu. |
| **Aşamalı yükleme** | İndiriliyor → Sahne hazırlanıyor → `compileAsync` (gölge/malzeme derlemesi) → yumuşak giriş. Sahne **hiçbir şey eksik değilken** açılıyor. |
| **Hata ekranı** | WebGL yoksa, modül düşerse veya 12 sn'de hiçbir şey olmazsa okunur bir hata + "Yeniden dene". |

#### Görsel düzeltmeler (ekran görüntüsüyle doğrulandı)

- **Metal plastik gibi bembeyazdı.** Stüdyo HDRI her yönden ışık verirken yönlü
  ışıklar da tam güçteydi. Ortam katkısı 0.55'e, pozlama 0.86'ya indirildi,
  parlaklık yönlü ışığa bırakıldı — paslanmaz çelik artık koyu gövde + keskin
  parlaklık tepesi olarak okunuyor.
- **Model kadrajın altından taşıyordu.** Yarıçap en büyük kenardan
  hesaplanıyordu; eğik bakışta siluet köşegene yaklaştığı için %45 dar kadraj
  çıkıyordu. Artık sınır küresi kullanılıyor.
- **Patlatınca parçalar ekrandan çıkıyordu.** Patlatılmış yarıçap artık
  ölçülüyor (DN50 vanada dikey uzanım 3,5 katına çıkıyor) ve kamera
  kullanıcının açısını bozmadan tam o kadar geri çekiliyor.
- **Etiketler üst üste biniyordu.** Mil yığınının parçaları ekranda birkaç
  piksel arayla hizalanıyordu; dikey itme eklendi.

#### Tünel adresi hatası

Günlükte `PUBLIC LINK HAZIR: https://api.trycloudflare.com` satırları
bulundu. `api.trycloudflare.com` cloudflared'in **kayıt adresi**, tünel adresi
değil; kayıt birkaç kez başarısız olurken sistem bu ölü adresi public link
ilan ediyor ve `3D_SONUC.txt`'ye yazıyordu — müşteriye gidecek link hiçbir
yere gitmeyecekti. Desen artık `api.` alt alanını dışlıyor (ngrok'ta da aynı
tuzak vardı).

#### Ölçülen son durum

| | |
|---|---|
| Yükleme (masaüstü, yerel) | **2,7 sn** — 13 parça, 13 etiket |
| Yükleme (mobil 390×844) | **2,6 sn** |
| Paket boyutu | 2,07 MB (model 121 KB + HDRI 464 KB + three 790 KB + Draco çözücü 250 KB + 3 fotoğraf) |
| Konsol hatası | yok (yalnızca favicon 404) |
| Doğrulanan etkileşimler | Parçala %100, X-Ray, Etiketler, parça seçimi + bilgi kartı, mobil yerleşim |

### ⚠️ Bilinen sınır: ZIP paketini çift tıklayarak açmak

Sayfa ES modülleri kullanıyor; tarayıcılar `file://` üzerinden modül yüklemeyi
**CORS kuralıyla** engelliyor (Chrome'da doğrulandı). Yani teslim ZIP'ini açıp
`index.html`'e çift tıklamak çalışmaz — sayfa okunur bir hata verir, donmaz.

Doğru kullanım public link ya da herhangi bir web sunucusudur. Çift tıklamayı
desteklemek isterseniz tek yol, three.js'i klasik (IIFE) tek dosyaya paketleyip
model ve HDRI'yi base64 olarak gömmektir — eski `model-viewer` mimarisinin
yaptığı buydu. Yapılmadı; paket boyutunu ~%35 büyütür ve asıl teslim yolu link.

---

## 8. Fotogerçekçilik oturumu (10 Ekim 2026, 15:00)

**Bildirilen sorun:** model "gri CAD çizimi / plastik" gibi duruyor; gerçek
çelik vananın fotoğrafı gibi durması isteniyor.

### Sebep: parlaklık değil, KONTRAST

Malzeme tanımları zaten doğruydu (`metalness 1.0`, paslanmaz `roughness`
0.26–0.46 — istenen aralık). Kusur ortamdaydı. Eski `studio.hdr` ölçüldüğünde:

| | eski | yeni |
|---|---|---|
| ortalama ışınım | 1.659 | 0.450 |
| tepe parlaklık | 16.4 | 11.8 |
| **ışık kaynağı oranı** (>1.0) | **%29,2** | %9,3 |
| **koyu alan oranı** (<0.05) | %28,1 | **%86,4** |
| **kontrast** (tepe/ortanca) | **49:1** | **1461:1** |

Gökyüzünün **üçte biri ışık kaynağıydı** ve üst yarıküre baştan sona açık
griydi (`SKY_TOP = 0.46`). Metalik bir yüzey ne görürse odur: her yönden orta
parlaklıkta bir ortamı yansıtan metal, gri boyalı yüzeyden ayırt edilemez.
Önceki oturumda bu, ortam katkısı 0.55'e kısılarak çözülmeye çalışılmıştı —
ama bu kontrastı daha da düşürdü, çünkü sorun miktar değil dağılımdı.

### Yapılanlar

1. **Dikdörtgen softbox'lar** (`core/hdri.Softbox`). Yuvarlak gaussian kaynak
   yuvarlak yumuşak leke bırakır; silindirik bir gövde kaynağın **şeklini**
   yansıttığı için uzun parlaklık şeridini ancak dikdörtgen kaynak verir.
   Rig: anahtar softbox + dikey kicker şeridi + sert kontur şeridi + tepe bandı
   + 1.0 altında bir dolgu (dolgu "kaynak" sayılmamalı, yoksa gri kubbeye dönülür).
2. **Koyu cyclorama.** `SKY_TOP` 0.46 → 0.021.
3. **Işınım normalizasyonu** (`TARGET_MEAN_RADIANCE = 0.45`). Kaynaklar hedefi
   tutturacak şekilde otomatik ölçeklenir: rig kurcalanınca sahne parlaklığı
   kaymaz, pozlama yeniden ayarlanmak zorunda kalmaz. Değer gözle değil
   tarayıcıda ölçülerek seçildi — yükseğinde gövde beyaz seramiğe dönüyor,
   düşüğünde parça okunmuyor.
4. **Yönlü ışıklar neredeyse kapatıldı** (key 1.45 → 0.55). A/B ile doğrulandı:
   ışıkları tamamen kapatınca görüntü neredeyse değişmiyor — yani aydınlatmayı
   artık ortam yapıyor, yönlü ışıklar pratikte yalnızca zemin gölgesi için.
5. **Prosedürel mikro yüzey** (`applyMicroSurface`, viewer). Tek tip pürüzlülük
   büyük döküm yüzeyini plastikleştiriyordu. CAD geometrisinde **UV yok**
   (`POSITION` + `NORMAL` yalnızca), bu yüzden doku haritası uygulanamıyor;
   pürüzlülük nesne uzayı konumundan 3B gürültüyle (`onBeforeCompile`)
   üretiliyor. Ek dosya inmez, UV gerekmez, parça patlarken doku parçayla gider.
   Genlik **pürüzlülüğün karesiyle** gider: pürüzlü yüzey düzensiz olduğu için
   pürüzlüdür, parlatılmış yüzey tanımı gereği düzgün parlatılmıştır. Doğrusal
   bağıntı küre gibi aynasal parçalarda görünür koyu lekeler bırakıyordu.
6. **`window.__viewer` kancası.** Sayfa ES modülü olduğu için sahneye dışarıdan
   ulaşılamıyordu; aydınlatma kararları artık gerçek tarayıcıda ölçülebiliyor.
7. **`tools/node/shoot.mjs`** — puppeteer-core + kurulu Chrome ile ekran
   görüntüsü (`--explode`, `--eval`, `--w/--h`). Fotogerçekçilik iddiası ancak
   gözle doğrulanabilir; bütün kararlar bununla A/B yapıldı.

### Yan kazanç: paket küçüldü

Koyu HDRI RLE ile daha iyi sıkışıyor: `studio.hdr` **464 KB → 226 KB**,
teslim paketi **2,07 MB → 1,9 MB**. Mobil açılış doğrudan buna bağlı.

### Doğrulama

- **342 test geçiyor** (332 + yeni `tests/test_hdri.py` 10 test). Yeni testler
  fotogerçekçilik sözleşmesini kilitliyor: kaynak oranı < %15, koyu alan > %70,
  kontrast > 300:1, ışınım hedefte, rig 10 katına çıkarılsa bile parlaklık kaymıyor.
- **Gerçek Chrome** ile montajlı, patlatılmış, etiketli ve küreye yakınlaşmış
  görünümler alındı. Patlatma 13 parçayı etiketleriyle açıyor; parlatılmış küre
  koyu stüdyoyu ve softbox şeritlerini aynasal yansıtıyor.
- **Canlı public link** üzerinden internetten doğrulandı: `index.html` 200,
  `model.glb` 200 (`model/gltf-binary`), `studio.hdr` 200 **225.610 bayt**
  (yani yeni koyu HDRI servis ediliyor), `vendor/three/*` 200, fotoğraflar 200.
  Konsolda yalnızca bilinen favicon 404'ü.

### Sıradaki iş: ortam ışığı gölgelemesi (AO) — **9. bölümde yapıldı**

---

## 9. Fotoğraf yansıtma oturumu (10 Ekim 2026, 18:30)

**İstenen:** model "prosedürel metal" olmaktan çıksın; müşterinin yüklediği
**kendi fotoğrafı** 3B geometrinin dışına ambalaj kâğıdı gibi otursun, kamera
dönerken üzerinde yapışık kalsın, fotoğrafın görmediği yerler akıllı bir
endüstriyel metale düşsün ve girintiler kararsın (AO).

### 9a. Mimari — neden UV'ye pişirilmedi

Parçalar **örneklenmiş** durumda: 4 cıvata tek mesh paylaşıyor. Mesh'e UV
yazmak örneklemeyi bozar, dosyayı büyütür ve GLB sözleşmesini değiştirir.
Bunun yerine projeksiyon sayfada **sabit bir projektör matrisinden** hesaplanır
— kameradan değil:

* kamera döndüğünde matris değişmez → doku yüzeye **yapışık** kalır;
* parça patladığında düğümün **durağan (rest) dünya matrisi** kullanılır →
  doku parçayla birlikte gider.

Shader'da dört kapı var; biri kapanınca piksel PBR'ye düşer:
**kadraj**, **yönelim** (projektöre sırtını dönen yüzey), **görünürlük**
(projektörden alınan derinlik haritasıyla gölge testi), **ürün maskesi**.

### 9b. Hizalama ölçülür, tahmin edilmez

Model fotoğraftan ölçülmüş değil; standart tablolardan kurulmuş bir yeniden
inşa. Dolayısıyla fotoğraf asla piksel piksel oturmaz. Hizalama sayısal
çözülüyor: modelin silueti ile fotoğraftaki ürünün maskesini çakıştıran 2B
dönüşüm. Üç kademeli arama (120 yön × her fotoğraf):

| kademe | ne yapar | maliyet |
|---|---|---|
| 1. Tarama | bütün yönler için siluet + yalnız moment hizalaması | ~3 sn |
| 2. Rötuş | en iyi 10 (fotoğraf, yön) çifti için tam optimizasyon | ~2 sn |
| 3. Karar | 3 finalist tam çözünürlükte + **kaplama** puanı | ~12 sn |

Sonuç iş dizininde önbelleklenir; anahtar `core/projection.py`'nin **özetini**
içerir, yani kod değişince önbellek kendiliğinden geçersizleşir.

### 9c. Bu oturumda düzeltilen dört hata

Dördü de sessizce yanlış çıktı üretiyordu; ikisi ancak **gerçek Chrome'da**
görülebildi.

1. **Serbest dönme fotoğrafı yan yatırıyordu.** Hizalama benzerlik dönüşümünü
   serbest bırakmıştı. Örtüşmeyi (IoU 0,83) yükseltmek uğruna fotoğrafı **76°**
   çeviriyor, vananın dişini gövdenin yanına yapıştırıyordu: sayı iyi, sonuç
   çöp. Dönme ±20°, en-boy oranı 1,35 ile **sınırlandı** ve sınır
   parametreleştirmeye gömüldü (`tanh`), cezaya değil. Aynı modelde dönme
   **0,04°**'ye, ölçek tek bir sayıya indi — yani gerçek bir eşleşme.
2. **Seçim ölçütü yanlıştı.** Yalnız IoU'ya bakmak vananın **ucundan** çekilmiş
   fotoğrafı seçtiriyordu; silueti iyi oturuyor ama ürünün yalnız kapak yüzünü
   taşıyor. Artık **kaplama** da ölçülüyor: modelin yüzey alanının kaçta kaçı
   gerçekten fotoğraf giyiyor. Puan = örtüşme × kaplama. Seçim yandan çekilmiş
   fotoğrafa (urun-1) kaydı: IoU 0,82, **kaplama %40**.
3. **Maske fon iki tonluysa duvarı ürün sanıyordu.** Arkada duvar, altta deri
   koltuk ve ikisinin birleştiği yerde parlak bir dikiş şeridi var. Tek bir
   "ortalama fon" rengi ikisine de uymuyordu; üstelik sonuç **çözünürlüğe göre
   değişiyordu** — 320 px'te vana, 512 px'te duvar kazanıyordu. Üç düzeltme:
   fon kenar şeridinden **kümelenerek** öğreniliyor, bileşen seçimi alan ×
   **merkeze yakınlık** ile puanlanıyor ve asıl çözüm olarak **öğrenilmiş
   kesim** (rembg / U²-Net `u2netp`, 4,5 MB model, 0,16 sn) öne alındı. Paket
   kurulu değilse klasik yola düşülür, zincir durmaz.
4. **Maske PNG'si teslim klasörüne yazılmıyordu.** Yazım, projeksiyon
   aramasının önbellek dalının **içinde** kalmıştı: ikinci paketlemede dosya
   hiç kopyalanmıyor, sayfa onu 404 alıyor, maske kapısı her pikseli kapatıyor
   ve fotoğraf modelde **hiç** görünmüyordu. Önbellek artık yalnız sayıları
   taşıyor; maske her pakette yeniden yazılıyor. Sayfa da savunmaya geçti:
   maske inmezse kapıyı kapatmak yerine **devre dışı bırakıyor**.

Buna ek olarak projektörün derinlik haritasına **zemin düzlemi** karışıyordu:
o aşamada model henüz zemine oturtulmamış (ortalanmış) olduğu için y=0 düzlemi
gövdenin tam ortasından geçiyor ve alt yarı "arkada kaldı" sayılıyordu.

### 9d. Fallback: fotoğrafın görmediği yüzeyler

Fotoğraf yüzeyin ~%40'ını giydiriyor. Kalanı — arka yüz, iç mekanizma,
patlatınca ortaya çıkan vida ve contalar — parlak stüdyo PBR'sinde kalsaydı
fotoğrafın yanında plastik gibi durur, "yarısı render yarısı fotoğraf"
izlenimi verirdi. Artık projeksiyon ağırlığının **tersiyle** orantılı olarak
koyu, pürüzlü endüstriyel çeliğe kayıyor. İki incelik:

* **Yalıtkanlar daha az karartılır** (0,82 / 0,54): zaten koyu olan NBR contayı
  0,54 ile çarpmak onu simsiyah bir lekeye çeviriyordu.
* **Pürüzlülük sabitlenmez, EKLENİR** (+0,18). Parlatılmış küreyi 0,64'e çekmek
  onu mat bir taşa çeviriyordu; oysa o parça gerçekten ayna gibi parlatılmış,
  yalnızca fotoğrafta görünmüyor.

Kayma fotoğraf karışımına bağlı: "Foto doku" kapatılınca model bütünüyle eski
parlak PBR'sine döner.

### 9e. AO — ışın izleme değil, boşluk doluluk oranı

Kaba kuvvet AO her köşeden yarıküreye yüzlerce ışın atar; 66.000 köşede saf
numpy ışın motoruyla dakikalar sürer. Parça zaten **kapalı bir katı** olduğu
için voksel ızgarasına doldurulabiliyor ve AO analitik olarak okunabiliyor:

| yüzey | çevredeki katı oranı | AO |
|---|---|---|
| düzlem | 0,50 | 1,00 |
| 90° iç köşe | 0,75 | 0,50 |
| oluk/delik dibi | → 1,00 | 0,42 (taban) |
| dış kenar | 0,25 | 1,00 (kırpılır) |

Maliyet köşe sayısından **bağımsız** (tek gauss bulanıklığı): 13 parça için
18,5 sn, çalışma zamanında sıfır. Üç karar sonucu belirledi:

* **Adım hacimden seçilir**, en uzun kenardan değil. M16×96 cıvatada "en uzun
  kenar / 64" kuralı 1,5 mm adım veriyor ve 1 mm derinliğindeki diş ızgaranın
  altında kalıyordu.
* **Yarıçaplar karakteristik ölçüye** (kutu hacminin küp kökü) bağlı — yine
  uzun ince parçalar için.
* **Düz yüzeyin referansı 0,5 değil.** Vokselleştirme yüzeyi kesen hücreleri de
  dolu sayıyor; katı yarım voksel şişiyor ve düz bir küp yüzünde bile AO 0,855
  çıkıyordu. Kayma analitik olarak hesaplanıp referans değer düzeltildi
  (`_planar_level`); düzlem artık tam 1,0, dik iç köşe tam 0,5.

AO glTF'ye standart `COLOR_0` (VEC4/ubyte, 4 bayt hizalama şartı yüzünden VEC4)
olarak yazılıyor: doğrulayıcıdan geçiyor, Draco sıkıştırıyor, **örnekleme
güvenli** (4 cıvata hâlâ tek mesh paylaşıyor). Sayfa onu kendi `ao` niteliğine
taşıyor ve three.js'in `aomap_fragment` bloğunu değiştirerek **dolaylı yayınım
ve ortam yansımasına** uyguluyor — metalde yayınım olmadığı için yalnız
yayınıma uygulansaydı paslanmaz çelikte hiçbir şey değişmezdi.

AO parçanın **yalnız kendi** gölgesidir ve ızgara parçanın kendi sınır kutusuna
taşınarak pişirilir; yani montajdaki konumdan bağımsızdır. Örneklenen
parçalarda bunun tutması şart.

### 9f. Ölçülen sonuç

| | |
|---|---|
| Hizalama | urun-1.jpg, **IoU 0,82**, kaplama **%40**, dönme 0,04°, anizotropi yok |
| Arama süresi | 17 sn (önceki serbest arama ~60 sn) |
| Siluet rasterleştirici | 0,84 sn → **0,30 sn** (kademeli kalıp taraması, sonuç **birebir** aynı) |
| AO pişirme | 18,5 sn / montaj, çalışma zamanı maliyeti 0 |
| Model | 1,02 MB → 1,13 MB (AO), Draco sonrası 124 KB → **146 KB** |
| Khronos doğrulayıcı | **0 hata, 0 uyarı, 0 bilgi** |
| Test | **383 test, 382 geçti / 1 atlandı, 5 dk 53 sn** (342 + `test_projection.py` 22 + `test_ao.py` 13 + 6 paket testi) |

Gerçek Chrome'da doğrulandı: açılış karesinde gövdedeki **"2311" döküm damgası
okunuyor**, kamera döndürüldüğünde doku kaymıyor, patlatmada fotoğraf
parçalarla birlikte gidiyor ve ortaya çıkan iç parçalar koyu endüstriyel
metale düşüyor.

**Canlı public link üzerinden** (masaüstü 1240×880 ve mobil 390×844) yeniden
doğrulandı: `index.html`, `model.glb` (`model/gltf-binary`),
`projection-mask.png`, `studio.hdr`, fotoğraflar ve `vendor/three/*` 200;
`/api/jobs` **404** (yönetim paneli dışarı sızmıyor); **konsolda tek bir hata
bile yok** — sayfanın tek dış isteği olan favicon artık gömülü veri adresi.
Tarayıcıda ölçüldü: 23 mesh'in 23'ünde `ao` niteliği var, maske ve fotoğraf
dokusu yüklü, karışım 0,85.

### 9g. Bilinen sınırlar

* Projektöre **yan** bakan yüzeylerde doku esner (klasik projeksiyon sıyrığı).
  Yönelim kapısı 0,30–0,65 arasında kapanarak o yüzeyleri PBR'ye bırakıyor;
  yine de 60°'den fazla çevrildiğinde gövdenin üst kuşağında hafif bir çekme
  görülebilir.
* Parametrik model gerçek ürünle **birebir aynı oranlarda değil**: bu vanada
  ISO 5211 pabucu modelde yuvarlak, üründe kare. Fotoğraf oraya oturur ama
  kenarı taşar. Çözümü projeksiyon değil, kütüphaneyi gerçek CAD dosyalarıyla
  büyütmektir.
* `rembg` isteğe bağlıdır ama **önerilir**; onsuz iki tonlu fonlarda hizalama
  belirgin ölçüde kötüleşir.
* **Siluet eşleştirmesi ön ile arkayı ayıramaz.** Eksenel simetriye yakın bir
  üründe 180° çevrilmiş yönün silueti neredeyse aynıdır; hangi tarafın
  seçildiği kaplama ve yönelim çarpanlarının kıl payı farkına kalır. Simetrik
  üründe görsel olarak fark etmez, asimetrik üründe kesin ayrım ancak
  fotoğrafın İÇERİĞİ karşılaştırılarak yapılabilir.

---

## 10. Endüstriyel sahne oturumu (10 Ekim 2026, 22:00)

**İstenen:** (1) geometri fotoğraflara uysun — üst pabuç **kare ve 8 delikli**,
uçlar dişli; (2) sunum karanlık boşluktan çıkıp **boru hattına** otursun;
(3) parçalanma **iki aşamalı** olsun (önce hattan kopma, sonra patlama);
(4) malzeme ayrımı ve AO güçlensin; (5) arayüz sadeleşsin.

### 10a. Sekiz fotoğrafın söylediği

Sekiz fotoğraf tek tek incelendi. Tepeden çekilmiş kare (7 numara) belirleyici
oldu: ISO 5211 pabucu **yuvarlak değil kare**, ve üzerinde **iki takım delik**
var — dışta dört büyük (F07), içeride dört küçük (F05), hepsi köşegende. Plaka
iki karşılıklı kenarının ortasında döküm kanalı taşıyor. Mil ucu **kare**,
hemen altında dişli bölüm ve somun.

Bu, kataloglarda "çift delikli pabuç" diye geçen olağan çözümdür: aynı gövdeye
hem küçük hem bir boy büyük aktüatör doğrudan otursun diye plaka iki kez
delinir ve üstüne iki kod birden damgalanır (fotoğrafta `F05` ve `F07`
okunuyor). Model bunu artık `std.MountPad.second_*` alanlarıyla taşıyor.

| | önce | sonra |
|---|---|---|
| Pabuç biçimi | devirme yüzeyi (yuvarlak) | **kare plaka**, kenar ortalarında kanal |
| Delik | 4 (tek takım) | **8** (F05 + F07, ikisi de köşegende) |
| Pabuç kodu | `F05` | `F05/F07` |
| Mil ucu | iki yüzlü (double-D) | **kare** (4 yüz) |
| Diş sırası | diş en üstte | diş altta, kare uçta — somun takılabilsin |

**Pabuç ölçüsünde bir tuzak:** kenarı ikincil (büyük) pabucun tablo ölçüsünden
almak plakayı 86 mm yapıyor ve 3/4 görünüşte vananın tamamını örtüyordu.
Fotoğrafta plaka gövde boyunun ~%60'ı; doğrusu birincil pabucun ölçüsü
(64 mm) ve büyük takımın delikleri o plakaya köşegende zaten sığıyor.
Kesitte ölçülen: 86 mm → **64 mm**, 10 kontur (1 dış kare + 8 delik + mil).

### 10a-2. Sekizi de gerçekten kullanılıyor

İki yerde yalnızca **üç** kare kullanılıyordu; ikisi de düzeltildi.

* **Tanıma (Claude Vision).** `VISION_MAX_IMAGES` 3 → **6**. Pabucun kare ve
  8 delikli olduğu yalnızca tepeden çekilen karede görünüyor ve o kare ilk üç
  temsilcinin arasında değildi. Kare başına ~1300 görsel token; altı kare hâlâ
  ucuz, karşılığında geometri doğru kuruluyor.
* **Projeksiyon araması.** Pakete önce yalnız üç temsilci kopyalanıyor ve
  hizalama onların arasından seçiliyordu. Artık **bütün fotoğraflar** aday
  (`MAX_PHOTOS` 3 → 12); arama bittikten sonra pakete **yalnız kazanan kare**
  konur, gerisi silinir. Hem daha iyi hizalama hem daha küçük paket:
  teslim 1,9 MB → **1,7 MB**.

Sekiz adayın ölçülen sonucu: kazanan `urun-1.jpg`, örtüşme **0,82**, kaplama
**%40**, eksene diklik 0,94.

### 10b. Boru hattı bağlamı

Vana artık DN50 bir hatta monte: iki boru, kaynak bilezikleri, askı kelepçesi
ve ayakları. Boru çapı tahmin edilmiyor, **anma ölçüsünden** geliyor
(EN 10220 dış çap); eksen bütün ailelerin paylaştığı sözleşme (**akış Z**).
Anma ölçüsü bilinmiyorsa hat hiç kurulmuyor — yanlış çapta boru çizmektense.

Borular modelin değil **sahnenin** çocuğu: parçalanmada vana hattan ayrılırken
onlar yerinde kalmalı.

Üç hata bu bölümde yakalandı ve düzeltildi:

1. **Boru 1000 kat büyüktü.** mm→m ölçeği kök düğümün `scale`'inden okunuyordu;
   oysa `root` glTF *sahnesi*dir ve ölçeği 1'dir — dönüşüm onun çocuğundadır.
   30 metre çapında bir levha sahneyi kaplıyordu. Ölçek artık **ölçülüyor**:
   dünya köşegeninin bilinen mm köşegenine oranı.
2. **Açılış karesi hattın İÇİNDEN bakıyordu.** Kazanan projektör yönü aynı
   zamanda açılış kamerasıdır; yalnız doku uyumuna bakınca akış ekseni boyunca
   bakan bir kare kazanıyor ve öndeki boru vanayı tamamen kapatıyordu. Puana
   **eksene diklik** çarpanı eklendi (`AXIS_PENALTY`): hatta karşıdan bakan yön
   tam puan, hattın içinden bakan yön 0,45 katı. Yasak değil, pahalı.
3. **Açık uçlu tüpün içi görünüyordu.** Boru dolu silindire çevrildi; uzak
   uçlar zaten kadrajın dışında.

**Hat boyalı, çıplak metal değil.** Ortam bilerek koyu (metalin kontrastı
oradan geliyor) ve koyu bir ortamı yansıtan metal siyah çıkıyor; hat plastik
bir hortuma dönüyordu. Boyalı yüzey dağınık yansıtır ve koyu ortamda bile
okunur — gerçek tesislerde de hatlar boyalıdır.

### 10c. Fabrika holü: neden İKİ dosya

Arka planı aydınlatma HDRI'siyle yapmak denendi ve **ölçülerek elendi**:

* ortamı fon olacak kadar parlatmak (`backgroundIntensity`) metali gri boyaya
  çeviriyor — bu, 8. bölümde zaten bir kez düşülmüş tuzak;
* parlatmadan göstermek siyah kalıyor;
* arada bir yerde ise **aydınlatma softbox'ları** (34°×50° gibi kocaman
  olmak zorundalar) kareyi baştan sona beyaza boyuyor.

Çözüm iki ayrı dosya: `studio.hdr` aydınlatır (koyu, yüksek kontrast),
`backdrop.jpg` görünür (fabrika holü: zemin, ufuk çizgisi, kolon ritmi, tavan
armatürleri). Fonun yansımaya katkısı olmadığı için LDR olması yeterli —
**18 KB**. Bulanıklaştırma üretim aşamasında yapılıyor, çalışma zamanında
değil.

Zemin de artık **görünür bir yüzey** (koyu mat beton), yalnız gölge tutucu
değil. Ürün hafif yukarıdan çekildiği için arkada kalan şey zemindir; zemin
yoksa kadraj yine "hiçbir yer"dir. Zeminin fondaki parlaklığı
(`BACKDROP_FLOOR_GAIN`) aydınlatmadakinden ayrı tutuluyor.

**Açılış kamerasının yüksekliği sınırlandı (≤9°).** Fotoğraflar masaya bakarak
20-30° yukarıdan çekiliyor; o açıdan bakan kamera ufku karenin dışında
bırakıyor ve sayfa yine karanlık açılıyordu. Fotoğrafın oturmasını bozmaz:
doku kameraya değil, sabit projektör matrisine çapalı.

### 10d. İki aşamalı sinematik parçalanma

| t | ne olur |
|---|---|
| 0 → 0,34 | **Kopma.** Vana hattan ayrılıp izleyiciye doğru gelir ve hafifçe kalkar. Yön, kamera bakışının boru eksenine DİK bileşenidir — parça hattın içinden değil, hattan dışarı çıkar. |
| 0,24 → 1 | **Patlama.** Bilinen eksenel ayrışma. Aşamalar 0,10 pay kadar üst üste biner; tam ardışık çalıştırıldığında hareket iki ayrı animasyon gibi duruyordu. |

Hat, vana çıkarken %45 soluyor (tamamen gizlemek bağlamı siler). Kamera **iki
kez** geri çekiliyor: parçalar yayıldığı için ve vana kameraya yaklaştığı için.

**Kaldırma hareketi sadece estetik değil zorunlu:** zemin artık opak; aşağı
açılan parçalar (top, oturmalar) zeminin altına inip görünmez oluyordu.

### 10e. Malzeme ayrımı — "gümüş blok"tan çıkış

Tablo bütün paslanmaz aileyi parlatılmış numunenin F0'ına (~0,78 sRGB) yakın
tutuyordu; döküm gövde, çekme saplama ve parlatılmış küre aynı renkte
okunuyordu. Oysa F0 yüzey işlemiyle düşer: kum püskürtülmüş döküm yüzeyde
mikro çıkıntılar ışığı birbirine çarptırıp yutar.

| malzeme | sRGB | pürüzlülük | nerede |
|---|---|---|---|
| `stainless_cast` | 0,688 | 0,54 | gövde, uç kapakları |
| `stainless_machined` | 0,786 | 0,25 | mil, somunlar, salmastra somunu |
| `stainless_bright` ★ | 0,826 | 0,15 | gövde saplamaları (A2-70) |
| `stainless_polished` | 0,858 | 0,07 | top |
| `tfm` / `ptfe` | ~0,92 | 0,28 | oturmalar, contalar |
| `graphite` | 0,225 | 0,78 | mil salmastrası |

Saplama ve somun artık **ayrı** malzeme: gerçekte de farklı yüzeyler ve
parçaları gözle ayırmanın en güçlü ipucu.

**Fallback'te bir hata bulundu:** fotoğrafın görmediği yüzeyleri karartan
katsayı parlatılmış küreyi kapkara bir lekeye çeviriyor, patlatılmış görünümde
top ekranda durduğu hâlde **görünmüyordu**. Karartma artık pürüzlülükle
orantılı — "endüstriyel" görünüm yüzeyin mat olmasından gelir, koyu
olmasından değil.

AO güçlendirildi: `STRENGTH` 1,0 → 1,22, taban 0,42 → 0,33, sayfadaki taban
renk katkısı 0,55 → 0,70.

### 10e-2. Hizalama motorunda bulunan üç hata

Geometri değişince (kare pabuç) hizalama testleri düştü. Düşen testler birer
*test sorunu* değil, üç gerçek kusuru açığa çıkardı.

1. **Dönme parametresi pratikte hiç aranmıyordu.** Nelder-Mead'in varsayılan
   başlangıç simpleksi her parametreyi kendi değerinin %5'i kadar oynatır.
   Dönme, moment tahmininden sıfıra yakın geliyor (vana silueti ana eksen
   bakımından belirsizdir) ve adım **0,03 dereceye** düşüyordu: optimize edici
   dönmeyi oynatamıyordu. Simpleks artık parametrelerin fiziksel ölçeğinden
   kuruluyor (~7° dönme, ~%9 ölçek, karenin %5'i kayma). Ölçülen: 9° çevrilmiş
   bir maskede örtüşme **0,80 → 0,95**.

2. **Kısa liste yalnız örtüşmeye bakıyordu.** Kaplama yalnızca finalistler
   için hesaplanıyor; finalistler de örtüşmeye göre seçiliyordu. Sonuç:
   tepeden çekilmiş pabuç fotoğrafı (yüksek örtüşme, düşük kaplama) bütün
   finalist yerlerini kapatıyor ve **kaplama hiç ölçülmeden** kazanıyordu.
   Kısa liste artık fotoğraf başına en iyi iki yönü garantiliyor.

3. **İki ayrı soru tek puana sıkıştırılmıştı.** "Hangi fotoğraf" bir *işe
   yararlık* sorusudur ve cevabı kaplamadır; "hangi yön" bir *hizalama*
   sorusudur ve cevabı örtüşmedir. Tek puanda birleştirilince, derinlik testi
   olmayan yaklaşık bir kaplama farkı, ölçülmüş %5'lik bir hizalama farkını
   çevirebiliyordu — sentetik veride **37° sapma** olarak ölçüldü. Karar
   artık iki adımlı: önce fotoğraf (örtüşme × kaplama × diklik), sonra o
   fotoğrafın en iyi hizalanan yönü. Aynı sentetik veride sapma **5,2°**.

Arada örtüşmeyi *karesiyle* ağırlıklandırmak denendi ve **gerçek veride
elendi**: sentetik testi geçiriyor ama müşterinin fotoğraflarında tepeden
çekilmiş kareyi seçtiriyordu (kaplama %40 → %31). Sentetik bir testi geçmek
uğruna gerçek çıktıyı bozmak kabul edilmedi; onun yerine kararın yapısı
düzeltildi.

Sekiz adayın son durumu — her fotoğraf finale girdi, kazanan `urun-1.jpg`:

| fotoğraf | örtüşme | kaplama | diklik | puan |
|---|---|---|---|---|
| **urun-1** | 0,817 | **0,403** | 0,937 | **0,309** |
| urun-7 (tepeden) | 0,844 | 0,365 | 0,806 | 0,248 |
| urun-2 | 0,836 | 0,369 | 0,656 | 0,203 |

### 10f. Arayüz

| kaldırılan | neden |
|---|---|
| Müşteri fotoğrafı galerisi + küçük resimler | Aynı fotoğraf zaten 3B modelin üzerinde; panelde ikinci kez göstermek gözü üründen alıyordu. Dosyalar pakette duruyor (projeksiyon dokusu onlardan okunuyor). |
| "Görüntü al" düğmesi | Tarayıcının kendi ekran görüntüsü aynı işi yapıyor; şerit mobilde taşıyordu. |
| Kaynaklar/linkler | Katalog adresleri müşteriye bir şey anlatmıyor, üstelik sunumdan dışarı açılan bir kapı. Veri `metadata.json`'da. |
| Alt başlık (özet tekrarı) | Yan panelde zaten var. |

Başlık şeridi alçaltıldı (12→7 px dolgu, küçük çipler, gizli alt başlık) ve
mobilde tuval payı %62 → %70'e çıktı. Tuval gözle görülür biçimde yukarı
taşındı.

### 10g. Doğrulama

| | |
|---|---|
| Test | **405 test, 404 geçti / 1 atlandı, 5 dk 54 sn** (önceki 383 + 22 yeni) |
| Takım süresi | 6 dk. `tests/conftest.py` iki pahalı adımı (AO ızgarası, öğrenilmiş kesim) kendi dosyaları dışında kısıyor — düz renkli test kareleri U²-Net'i de çalıştırıyor ve paket testleri dakikalarca sürüyordu |
| Yeni testler | çift delikli pabuç (4), kare pabuç + 8 delik kesiti (2), kare mil ucu, iç dişin varlığı, saplama≠somun, boru hattı sözleşmesi (2), fabrika fonu (4), zemin, iki aşamalı patlatma, arayüz temizliği (3), dönmenin gerçekten aranması, puan dengesi, bütün fotoğrafların aday olması |
| Khronos doğrulayıcı | **0 hata, 0 uyarı, 0 bilgi** |
| Gerçek Chrome | montajlı, patlatılmış ve mobil kareler; **konsolda hata yok** |
| Paket | 1,9 MB (fabrika fonu +18 KB) |

### 10h. Bilinen sınırlar

* Fotoğraf projeksiyonu **ön yüzü** giydirir (yüzeyin ~%40'ı); kalan yüzeyler
  endüstriyel PBR çeliğe düşer. Bu bir eksik değil, tasarım: fotoğrafın
  görmediği yere fotoğraf uydurmak yanıltıcı olurdu.
* Hol fonu prosedüreldir; gerçek bir fabrika fotoğrafı değildir. Lisanslı bir
  HDRI ile değiştirilmek istenirse `core/hdri.write_backdrop` yerine o dosya
  pakete konup `DATA.backdrop` ona gösterilebilir.
* Boru hattı **temsilidir**: gerçek tesisteki flanş tipi, dirsek ve askı
  düzeni bilinmiyor; amaç ölçeği ve işlevi anlatmak.

---

## 11. Endüstriyel simülasyon oturumu (11 Ekim 2026, 04:30)

**İstenen:** ürün tek yüzü gerçekçi bir model olmaktan çıksın; 8 fotoğrafın
tamamı her yönden yansısın, üst flanş fotoğraftaki gibi olsun, müşterinin yeni
gönderdiği **pnömatik aktüatör** sete dahil edilsin, borular gerçek dokulu ve
sızdırmaz otursun, arka plan fiziksel bir diorama olsun, parçalanma mantıklı
bir sırayla aksın ve birleştirme kusursuz geri dönsün.

### 11a. 360° projeksiyon — tek projektörden projektör kümesine

Tek projektör ürünün yalnız bir yüzünü giydiriyordu; model çevrilince arkası
çıplak PBR kalıyordu. Artık **çok yönlü** projeksiyon var:

* Her fotoğrafın kendi en iyi iki yönü finale kalır (`per_photo=2`).
* Kazananlar **açgözlü küme kaplama** ile seçilir: her adımda HENÜZ
  giyinmemiş yüzeyin en çoğunu ekleyen aday alınır.
* **Her fotoğraftan en fazla bir projektör.** Aynı kareyi iki karşıt yönden
  yansıtmak kaplamayı yükseltir ama ürünün arkasına önünün aynasını boyar —
  uydurmadır. Farklı kareler gerçekten farklı yüzleri gösterir.
* Katkısı %3,5'in altında kalan aday alınmaz: her projektör sayfaya bir
  fotoğraf, bir maske ve bir 1024² derinlik haritası ekler.

Shader N projektör için **açılarak** üretiliyor (GLSL ES 1.0'da sampler
dizisini değişkenle indekslemek yasak). Ağırlıklar toplanıyor: bir yüzeyi
birden çok fotoğraf görüyorsa renkleri ağırlıklı ortalanır, ağırlık yönelimin
**karesiyle** gider — yüzeye daha dik bakan kare baskın olur, yoksa ikisi
eşit karışıp bulanıklaşıyordu.

| | önce | sonra |
|---|---|---|
| Projektör | 1 | **3** (urun-1, urun-4, urun-2) |
| Toplam kaplama | %37 | **%73** |

**Aktüatör projeksiyonun dışında.** Müşterinin 8 karesi çıplak milli vanayı
gösteriyor; aktüatör sonradan eklendi. Projeksiyon oraya da vurunca aktüatörün
üstüne vananın gövdesinden kopan "1000 WOG" lekeleri düşüyordu. Fotoğrafın
içermediği ürüne fotoğraf giydirmek uydurmadır — o parçalar kendi PBR
renkleriyle kalır (parça bazlı kapı: `uProjPart`).

### 11b. Üst flanş tamiri

Fotoğraftaki dikey sıra: konik boyun → salmastra bosu ve somunu → **EN ÜSTTE
kare pabuç**. Önceki modelde pabuç ortadaydı ve üstünde dişli bir mil uzantısı
ile bir somun duruyordu; üründe orada hiçbir şey yok.

* Pabuç artık **ayrı, pres geçme bir parça** (`montaj_pabucu`) — gövdeye
  kaynaklı değil. Ayrı olması sunumda da doğru: patlatıldığında aktüatörle
  birlikte çıkar ve parça listesinde kendi adıyla görünür.
* Milin dişli uzantısı ve **mil somunu silindi**; yalnız kare tahrik ucu
  pabucun içinden geçip üstünde bitiyor. Somun orada olsaydı aktüatörün
  kovanı mile geçemezdi.
* Yaylı rondela da doğru yere taşındı: salmastra somununun **altına**. Milin
  tepesindeyken salmastraya hiçbir kuvvet aktaramıyordu.

Model yüksekliği 161 mm → **125 mm** (aktüatörsüz), yani gerçek bir DN50
3 parçalı vananın ölçüsüne indi.

### 11c. Pnömatik aktüatör

Müşterinin gönderdiği ürün fotoğrafından modellendi (`cad/actuator.py`):
ekstrüzyon alüminyum gövde + NAMUR platosu, **mavi** uç kapakları (kapak
başına 4 alyan cıvata), sarı kadran + siyah gösterge kubbesi ve oku, iki
**kırmızı** hava portu tapası, pabuca oturan ara bağlantı.

Ayrı modülde duruyor çünkü aktüatör vananın parçası değil, ISO 5211
arayüzünden takılan bağımsız bir üründür; ölçüleri pabuç kenarından türetilir,
DN değişince birlikte büyür. `NO_ACTUATOR` listesinden pnömatik çıkarıldı —
müşteri ürünü set olarak satıyor.

Dört ayrı renk kullanılması bilinçli: hepsini tek gümüşe bağlamak aktüatörü
vananın devamı gibi gösteriyordu.

**Yakalanan hata:** aynalanan kapak ve cıvata yerleşimleri `at(...)`'in
sözleşmesini yanlış kullanıyordu — döndürme montaj ORİJİNİ etrafında yapılır,
öteleme ondan sonra eklenir. Kendi yerinde duran bir mesh 180° çevrilince
karşı tarafa fırlıyor, öteleme onu bir kat daha uzağa taşıyordu: montajın X
boyu 168 mm yerine **331 mm** çıkıyordu. Mesh artık orijinde kuruluyor.

### 11d. Boru hattı ve sızdırmazlık

* Boru vananın ucuna DAYANMIYOR, **içine giriyor** (0,55·yarıçap girinti).
  Dayanmak milimetrik bir çizgi bırakıyordu ve her açıdan "hava sızdıran"
  bir boşluk olarak okunuyordu.
* Eklemin üstüne **altıgen rakor somunu** oturuyor.
* Boru, bilezik ve diorama yüzeyleri artık `industrialMaterial` ile
  üretiliyor: pürüzlülük nesne uzayı gürültüsüyle dalgalanıyor ve taban renk
  hafifçe değişiyor (çizik/leke hissi). Ek doku dosyası inmiyor.

### 11e. Diorama — kutudan ŞASEye

İlk deneme dört duvarlı bir odaydı ve **kamera serbestçe döndüğü için
duvarlardan biri sürekli ürünün önüne geliyordu**: açılış karesinde ekran
baştan sona kahverengiydi (ölçüldü — kamera x=−0,69, arka duvar x=−0,36;
kamera duvarın arkasında kalmıştı). Odayı kameranın etrafını saracak kadar
büyütmek ise ürünü 5 metrelik bir hacimde nokta gibi bırakıyor.

**Şase bu ikilemi çözüyor:** bütün yüzeyler ya ürünün ALTINDA (platform, kenar
kirişleri) ya da hattın UÇLARINDA (boruların delip geçtiği bölmeler) durur.
Hangi açıdan bakılırsa bakılsın ürünle kamera arasına hiçbir şey girmez, ama
ürün de boşlukta süzülmez.

Bölmelerdeki delik `Shape` + `holePath` ile açılıyor — boruyu duvara dayamak
yerine gerçekten delip geçirmek, hattın "bir yerden gelip bir yere gittiği"
hissini veren ayrıntı.

Arka plan **görseli tamamen kaldırıldı** (`backdrop.jpg` ve üreticisi silindi);
sahnenin fonu artık yalnız koyu bir renk, görünen her şey gerçekten orada
duran bir yüzey. Stüdyo HDRI'si yalnız AYDINLATMA için duruyor.

### 11f. Parçalanma akışı

Sökme sırası gerçek bakım sırası oldu (küçük aşama = önce sökülür):

| aşama | parça |
|---|---|
| 1-4 | aktüatör: gösterge, kadran, kapaklar, cıvatalar, gövde, ara bağlantı |
| 5 | ISO 5211 montaj pabucu |
| 6 | gövde saplamaları ve somunları |
| 7 | uç kapakları |
| 8 | contalar, oturmalar, küre |
| 9 | mil yığını |
| 0 | orta gövde (sabit kalır) |

Buna ek olarak **hat da açılıyor**: borular eksen boyunca iki yana çekiliyor
ve %45 soluyor. Vana yerinden çıkarken borular olduğu yerde kalırsa izleyici
"nereden çıktı" diye soruyor.

**Etiketler patlatmada kendiliğinden açılıyor** (kullanıcı elle kapattıysa
ona dokunulmuyor) ve artık **oluğa diziliyor** — teknik çizimlerdeki kılavuz
çizgisi düzeni. Etiketi parçanın yanına koymak patlatılmış görünümde işe
yaramıyordu: vananın iç parçaları ekranda birkaç piksel arayla üst üste düşüyor,
hepsi aynı yöne itiliyor ve 20 etiketin 13'ü okunmaz tek bir sütuna yığılıyordu.
Geniş ekranda iki oluk (parça ekranın hangi yanındaysa o taraf), telefonda tek
oluk; aralık sütun yüksekliğine göre kısıldığı için taşma mümkün değil (doğal
yüksekliğe yapışmaya çalışan ilk deneme son iki etiketi araç çubuğunun altında
bırakıyordu).

**Birleştirme milimetrik.** Hattın açılması her zaman durağan konumdan
hesaplanıyor; artımlı toplamak yuvarlama hatası biriktirirdi. Gerçek tarayıcıda
ölçüldü: tam patlatma–birleştirme turundan sonra 48 nesnenin (kök + 8 hat
parçası + 39 parça örneği) en büyük sapması **0,00000 mm**.

### 11g. Doğrulama

| | |
|---|---|
| Montaj | 20 parça / 39 örnek, **20/20 su geçirmez katı**, 6,33 kg |
| Khronos doğrulayıcı | **0 hata, 0 uyarı, 0 bilgi** |
| Projeksiyon | 3 yön, toplam kaplama **%73** |
| Birleştirme | 56 nesnede **0,00000 mm** sapma |
| Gerçek Chrome | açılış, patlatma, 3 ayrı yörünge açısı, mobil 390×844; **konsolda hata yok** |
| Test | **417 test, tamamı yeşil** (tam takım 415+1 atlandı / 7 dk 53 sn; sonraki düzenlemeler dosya dosya doğrulandı) |
| Yeni testler | aktüatör (6), pabuç ayrı parça + üstünde vida yok (2), çok yönlü projeksiyon (4), diorama/fon (1), her projektörün kendi maskesi, aktüatörün projeksiyon dışında kalması, etiket oluğu |
| Paket | 2,0 MB (3 fotoğraf + 3 maske; fon görseli yok) |

### 11h. Bilinen sınırlar

* **Aktüatör fotoğraftan ölçülmedi**, oranlandı: gövde/kapak/gösterge oranları
  müşterinin poster görselinden okundu, ölçüler ISO 5211 pabuç kenarından
  türetildi. Gerçek bir AT/GT serisi için üretici kataloğu gerekir.
* Hat boyunca bakıldığında (eksen doğrultusu) boru kadrajı kaplar — bu
  perspektifin kendisinden gelir, bir kusur değil.
* Projeksiyon kaplaması %73; kalan %27 ürünün altı, iç boşlukları ve
  fotoğraflarda hiç görünmeyen yüzeyler. Oralar endüstriyel PBR'de kalır.
* **Test takımı OneDrive'a bağımlı.** Depo `OneDrive\Desktop` altında; eşitleme
  kuyruğu doluyken aynı takım 8 dakikadan 45+ dakikaya çıkıyor (pytest %2
  CPU'da bloklanıyor). Suçlu biriken `jobs/*/delivery_*` klasörleri: her biri
  ~600 vendor dosyası taşıyor. Bu oturumda 49 klasör (136 MB / ~30 bin dosya)
  silindi, `.zip` arşivleri her sürümü saklıyor.

---

## 13. Müşteri geri bildirimi turu (11 Ekim 2026, 16:00)

Müşteri videolu geri bildirim gönderdi ve altı kusur gösterdi. Hepsi gerçek
çıktı; her biri önce **ölçülerek** doğrulandı, sonra düzeltildi.

### 13.1 Fotoğraf projeksiyonu kapatıldı — "çamur gibi kaplama"

Paslanmaz gövde hardal/haki lekelere dönüyordu: bir yanı gümüş, bir yanı sarı.
Sebep harmanlamanın hatası değil, **girdinin kendisi**: 8 kare sıcak iç mekân
ışığında, koyu fon önünde, kare başına farklı beyaz ayarıyla çekilmiş. Doğru
beyaz ayarı ve kareler arası pozlama eşitlemesi olmadan ağırlıklı ortalama
çamur üretir.

`core/config.py` → `projection_enabled` artık **varsayılan kapalı**. Sayfa saf
PBR paslanmazla açılıyor; "Foto doku" düğmesi hiç görünmüyor. Alt sistem
duruyor, `PROJECTION_ENABLED=true` ile geri açılabilir.

İlgili iki kusur daha çıktı:
* `.tool{display:flex}` tarayıcının `[hidden]` kuralını eziyordu; gizlenmesi
  gereken düğme yine de duruyordu. `.tool[hidden]{display:none}` eklendi.
* Aynı fotoğrafın iki kopyası, **adları farklı** olduğu için iki ayrı kare
  sayılıyor ve ikincisi ürünün arkasına önünün aynasını boyuyordu. Eşitlik
  artık dosya adıyla değil **içerik özetiyle** belirleniyor.

### 13.2 Aktüatör vanaya oturdu

`SPACER_HEIGHT = 0.42` (DN50'de 27 mm) aktüatörü ince bir kulenin üstünde,
havada bırakıyordu. Yerine **alçak ve pabuç kadar geniş bir bağlantı ayağı**
(`YOKE_HEIGHT = 0.14`) ve onu pabuca çeken **dört cıvata** geldi.

"Kamera dönerken alt kısım kayıyor" şikâyetinin sebebi mesh pivotu ya da
ebeveyn ilişkisi değildi: ayağın alt yüzü pabucun üst yüzüyle **tam aynı
düzlemdeydi** ve iki yüzey z-savaşına giriyordu. `YOKE_SINK` payı o çakışmayı
kaldırıyor.

Milin kare tahrik ucu `0,62 × mil çapı`ndan `1,05`e uzatıldı: eski boyda uç
ayağın içinde kalıyor, pinyona hiç ulaşmıyordu. Fotoğraftaki kare uç de
pabucun belirgin biçimde üstünde duruyor.

Mavi kapak cıvataları tek bir dairenin üstündeydi (yarı yüksekliğin %59'u),
yani kapağın ortasına toplanmıştı; referans fotoğraftaki gibi **dört köşeye**
alındı. Başlarına **alyan yuvası** açıldı ve malzemeleri matlaştırıldı:
parlatılmış paslanmaz düz bir cıvata başı yakın planda aynaya dönüp
"beyaz bir delik" gibi okunuyordu.

### 13.3 Boru hattı vananın DELİĞİNE oturdu

En büyük sessiz hata buydu. Sayfa boruyu modelin **sınır kutusunun**
merkezine koyuyordu; aktüatör kutuyu yukarı çektiği için borular vananın
deliğinden değil **gövdesinin üstünden** geçiyordu — ölçüldü: delik ekseni
y=0'dayken kutu merkezi **y=+59,8 mm**.

Yeni sözleşme `Assembly.flow_line()`: eksen, eksenin geçtiği nokta ve vananın
iki uç yüzeyi. Uçlar **basınç zarfından** (`housing` + `seal`) ölçülüyor;
gövde cıvataları uçlardan taştığı için onlara dayanan bir boru bir yanda
içeri giriyor, öbür yanda boşluk bırakıyordu. Değer `cad.json → flow_line`
üzerinden sayfaya taşınıyor.

Borudaki "anlamsız delikler/kesikler" altı kenarlı rakor bileziği, askı
kelepçesi ve ayağıydı; 48 dilimli borunun yanında 6 dilimli bir bilezik
yüzeyde kesik gibi okunuyordu. Hepsi kaldırıldı: **düz silindir + yuvarlak
flanş**, başka hiçbir şey yok. Boru vananın uç yüzeyine `outer * 0.06` pay
kadar girerek dayanıyor — tam temas eden iki yüzey kıl gibi bir z-savaşı
çizgisi bırakıyor, o çizgi de "sızdıran boşluk" diye okunuyordu.

### 13.4 Diorama kapalı odaya dönüştü

Önceki şase açıktı (zemin + iki uç bölmesi); kamera yana çevrildiğinde aradan
boşluk görünüyordu. Artık **tavan + dört duvar** var, yüzeyler yalnız
içeriden görünüyor ve kamera odanın dışına çıkamıyor:

* `controls.maxDistance` — tekerleğin yumuşak sınırı,
* `confineCamera()` — her karede uygulanan sert kutu kelepçesi. `dolly`
  kamerayı doğrudan taşıdığı için maxDistance tek başına yetmiyordu.

Oda ölçüsü **kameradan** türüyor (modelden değil), boru boyu ise **odadan**:
uç duvarı delip geçecek kadar uzun. Sıra bu yüzden zorunlu —
`computeFlowLine → frame → buildDiorama → buildPipeline → frame`.

**Ölçüm:** `tools/node/void_check.mjs` sahnenin arka planını macentaya çevirip
kamerayı 24 azimut × 11 yükseklik açısında gezdiriyor ve kaç piksel kaldığını
sayıyor. Önce **48 yönde, en kötüsü karenin %31'i**; şimdi **en kötü yönde
57.600 pikselin 2'si** (duvar dikişinde kalan kıl payı).

### 13.5 Patlatma düzene girdi

İki ayrı kusur vardı.

**Yön kameraya bağlıydı.** `pullDirection()` bakış yönünün boru eksenine dik
bileşenini alıyordu: aynı ürün her açıdan farklı diziliyor, patlatma açıkken
sahne döndürülünce montaj eski yönde asılı kalıyordu. Artık **sabit yukarı** —
hattan sökülen vana zaten yukarı kaldırılır.

**Mesafeler ölçülmeden yazılmıştı.** Küre 0,58 köşegen aşağı gidip gövdenin
tabanının içinde kalıyordu (6.454 mm³ ortak hacim), salmastra bileziği ile
yaylı rondela aynı 5 mm'ye oturuyordu. Mesafeler `ball_valve.py` başında
**tek bir merdiven** olarak toplandı; aktüatörün kapakları ve cıvataları
gövdesiyle **aynı kadar yükselen** bileşik yönler aldı, yoksa yükselen
gövdeden kopup boşlukta kalıyorlardı.

`Assembly.explode_overlaps()` bunu kilitliyor: önce sınır kutusu elemesi,
hayatta kalan çiftlerde **gerçek kesişim hacmi**. Yalnız kutuya bakmak işe
yaramıyordu — ürünün yarısı eş eksenli (salmastra milin etrafında, cıvata
kapağın yanında), kutuları çakışıyor ama katıları çakışmıyor. 741 çiftten
7'si elemeyi geçiyor, gerisini kesin hesaplamak ucuz. Bugün **sıfır çakışma**.

Kamera da artık **ölçülen** kutuya göre çerçeveliyor: patlarken hem geri
çekiliyor hem bakış noktasını yukarı kaydırıyor (`explodedCenter`,
`explodedRadius`, `explodedDistance`). Oranla geri çekilmek tahmindi ve
gösterge kadrajın üstünden taşıyordu.

### 13.6 Testlerin yakalayamadığı kusur

Bu turda şablona bir **söz dizimi hatası** girdi (bir shader dizesinde `
`
gerçek satır sonuna dönüştü). Sayfa "Invalid or unexpected token" ile hiç
açılmadı, **432 test yeşil kaldı**: hepsi HTML içinde metin arıyordu.

`test_the_page_script_actually_parses` eklendi — sayfanın modülünü ayıklayıp
`node --check` ile derletiyor. Testin gerçekten ısırdığı, şablon bilerek
bozularak doğrulandı.

### 13.7 Bu turda değişen dosyalar

| Dosya | Ne değişti |
|---|---|
| `core/config.py` | `projection_enabled` varsayılan **false** |
| `core/projection.py` | aynı kare içerik özetiyle elenir |
| `cad/assembly.py` | `flow_line()`, `group_bounds()`, `explode_overlaps()` |
| `cad/actuator.py` | ayak + ayak cıvataları, köşe kapak cıvataları, alyan yuvası, bileşik patlatma yönleri |
| `cad/families/ball_valve.py` | kare tahrik ucu 1,05; patlatma merdiveni tek yerde |
| `agents/cad_agent.py` | `cad.json → flow_line` |
| `agents/packager_agent.py` | `pipeline.origin_mm` / `ends_mm` |
| `templates/viewer.html.j2` | `computeFlowLine`, düz flanşlı boru, kapalı oda, `confineCamera`, ölçülen patlatma kadrajı, `.tool[hidden]` |
| `tools/node/void_check.mjs` | **yeni** — "dışarısı görünüyor mu" ölçümü |
| `tools/node/orbit_shots.mjs` | **yeni** — tek oturumda çok açılı çekim |

**433 test geçiyor.**

---

## 14. LookDev turu (11 Ekim 2026, 20:00)

Yapısal hatalar çözülünce ürün "fazla temiz ve ruhsuz" kaldı. Dört madde.

### 14.1 Yüzey: üç bant

Tek bir ince tane bandı vardı (frekans 260, genlik ≤0,20) ve gözün
seçemeyeceği kadar küçüktü; ürün plastik gibi duruyordu. Üç banda çıkarıldı:

| Bant | Ölçek | Genlik | Neyi anlatır |
|---|---|---|---|
| `mBroad` | ~2,5 cm | `min(0,22; 0,62·r)` | kum döküm yüzeyin iri dalgası |
| `mGrain` | ~4 mm | `min(0,15; 0,52·r²)` | ince tane |
| `mScratch`| yönlü | `0,085·(1−1,6·r)` | taşlama/torna çizikleri |

İri bant pürüzlülükle **artar** (döküm gövde dalgalı, işlenmiş altıgen uç
düz), çizik bandı pürüzlülükle **ters** gider (çizik ancak parlak yüzeyde
görünür).

**Ara ölçüm:** ince bandı 0,30'a çıkarmak yanlıştı — 260 frekansta desen
piksel ölçeğine düşüyor ve yakın planda döküm çelik değil **zımpara** gibi
duruyordu. Karakteri iri bant taşıyor, ince bant yalnız onu kırıyor.

### 14.2 AO derinleştirildi

`cad/ao.py` → `STRENGTH 1,22 → 1,48`, `FLOOR 0,33 → 0,22`; sayfada
`AO_TINT 0,70 → 0,90`.

Analitik değerin üstü "doğru" değil ama **gerekli**: pişirilen AO yalnız
parçanın kendi gölgesidir, parçalar arası temas kararmasını hiç görmez.
Gövde–kapak birleşme çizgisi, somunun oturduğu yüzey, pabucun altı —
fotoğraftaki en koyu yerler bunlar ve modelde hiç yoktu.

AO zinciri doğrulandı: GLB'de `COLOR_0`, sayfada `adoptAO()` ile tek
bileşenli `ao` niteliğine taşınıyor ve **ortam yansımasına da** uygulanıyor.
Metalde taban renk F0 olduğu için girinti etkisini asıl veren budur.

### 14.3 Sahneleme

`context 1,50 → 1,12` ve `ROOM_CLEARANCE 1,22 → 1,05`. Eski değerde hat
kadraja giriyordu ama vana kutunun içinde oyuncak gibi kalıyordu; oda da
kameradan türediği için ürünle birlikte büyüyordu. Şimdi boru iki kenardan
giriyor, vana kareyi dolduruyor.

Kapalı oda ölçümü yeniden koşuldu: en kötü yönde **57.600 pikselin 4'ü**
(oda daralınca 2'den 4'e çıktı, hâlâ görünmez).

### 14.4 Etiket sadeleştirmesi

Patlatmada 21 etiket birden açılıyordu. Ölçüt `packager_agent._mark_key_parts`
içinde ve **aileden bağımsız**: bağlantı elemanı/sızdırmazlık grubunda
DEĞİL, ve montaj kütlesinin en az %1'i. Vanada **21 parçadan 8'i** kalıyor
(uç kapağı, orta gövde, pabuç, küre, mil, aktüatör gövdesi/kapağı/ayağı).

Ad listesi tutulmadı: kütle ölçütü yeni ailelerde de çalışır — kelebek
vanada disk ve mil, süzgeçte sepet kendiliğinden ana parça çıkar. Etiketi
olmayan parça kaybolmuyor, sağ paneldeki listede duruyor ve tıklanınca
seçiliyor.

**438 test geçiyor.**

---

## 12. Kaldığımız son nokta

```powershell
cd "C:\Users\vedat\OneDrive\Desktop\claude falan filan\ajan3d"
.\baslat.ps1
```

Komut public linki verir **ve panoya kopyalar**. `inbox\` içine fotoğraf
klasörü atın; tanıma → teknik veri → CAD montajı → paket → yayın kendiliğinden
işler ve sonuç klasöre `3D_SONUC.txt` olarak yazılır.

Tek adım denemek için:
```powershell
python run_vision.py "inbox\Yeni klasör"      # tanıma (ücretli)
python run_cad.py "jobs\<is>" --force         # montaj (ücretsiz, yerel)
python run_package.py "jobs\<is>"             # sunum sayfası
python run_cad.py --families                  # kütüphanedeki aileler
```

Test işi hazır: `jobs\test-vana-yeni\` (DN50 PN63 3 parçalı dişli küresel vana,
gerçek araştırma verisiyle, API harcamadan).

### Çözülmemiş / sıradaki işler

- **ZIP'i çift tıklayarak açmak** çalışmıyor (yukarıdaki sınır).
- **Dişli standardı (NPT / BSP) fotoğraftan ayırt edilemiyor.** Vision bunu
  kendi `issues` listesinde dürüstçe bildiriyor; model genel boru dişiyle
  kuruluyor. Müşteriye tek soruyla netleşir.
- **Eski mimariden kalan işler** `jobs\_arsiv-eski-mimari\` altında duruyor
  (silinmedi). İçinde eski şemayla üretilmiş 4 iş ve eski yayın paketi var;
  gerek kalmazsa elle silinebilir.
- **Tarayıcıda gözle kontrol** (6. bölümün sonundaki 4 madde).
- **Kalıcı link.** Ücretsiz tünel adresi her başlatmada değişir. Kalıcı çözüm:
  kendi alan adı + adlı Cloudflare tüneli → `.env` → `TUNNEL_HOSTNAME`.
- **Kütüphaneyi büyütmek.** En yüksek getirili iş bu: `cad_library/` içine
  tedarikçiden gelen gerçek `.glb` dosyalarını koymak. Sistem parametrik
  üretimden gerçek katalog eşleştirmesine kayar.
- Yeni aileler: pompa, redüktör, dirsek/te, emniyet vanası, manometre.
- Diş profili **konsantrik oluk**tur, gerçek helis değil. Render ölçeğinde
  ayırt edilemez; imalat resmi olarak kullanılamaz.

### Bu oturumda düzeltilen hatalar

Çoğu teste yazılırken yakalandı; her biri sessizce yanlış çıktı üretiyordu:

1. **Diş profili taşması** — M16×39 gibi ara boylarda zikzak istenen boyu aşıp
   geri dönüyor, katıyı kendisiyle kesiştiriyordu. Aralık artık eşit yarım
   hatve adımlarına bölünüyor.
2. **`merge_vertices` kapalı katıyı deliyordu** — pah ile altıgen köşesinin
   buluştuğu yerde ayrı köşeleri birleştirip yüzeyi açıyordu. Kaynaştırma
   yüzeyi açarsa artık geri alınıyor.
3. **DN8/DN10 flanşta `KeyError`** — boru tablosu DN8'e iniyor, flanş tablosu
   DN15'te başlıyordu.
4. **Tanıtım metni açık alanı eziyordu** — "ISO 5211 montaj flanşlı" ifadesi,
   bağlantı alanı "dişli" dediği hâlde vanayı flanşlı kurduruyordu; "pnömatik
   aktüatör takılabilir" cümlesi kollu vanaya volan taktırıyordu. Ayrıştırıcılar
   artık metinleri **sırayla** tarıyor, açık alan önce geliyor.
5. **Dejenere yüzlerde sıfır normal** — devirme ekseninde kalan sıfır alanlı
   üçgenler glTF'de geçersiz normal üretiyordu.
6. **ISO 5211 etiketi şeritten düşüyordu** — üst şerit 7 ile sınırlıydı ve
   sıralama sıcaklığı ürün arayüzünün önüne koyuyordu. Ayrıca pabuç kodu
   yalnızca ailede hesaplandığı için `cad.json`'a hiç yazılmıyordu.
7. **`--rebuild-cad` paketi yenilemiyordu** — model yeniden kuruluyor ama
   teslim klasöründe eski `model.glb` kalıyordu.
8. **Sırlar `repr`e sızıyordu** — `Settings` donmuş bir dataclass olduğu için
   testler onu kopyalıyor; bir hata anında pytest tam `repr`i basıyor ve
   Anthropic anahtarı ile Gmail şifresi günlüğe düşüyordu (yaşandı). Sır
   alanları artık `repr=False`.

### Web optimizasyonu için ortam

Draco **isteğe bağlıdır**; kurulu değilse zincir sıkıştırmasız çalışır.
Kurulumu:

```powershell
cd tools\node
npm install
```

Gerekli dosyalar: `tools/node/optimize_glb.mjs`, `tools/node/node_modules/`
(@gltf-transform + draco3dgltf) ve `vendor/draco/` (çözücü, 250 KB).
Kapatmak için `.env` → `DRACO_ENABLED=false`.

### Ortam notu

Yeni zorunlu paketler: **`manifold3d`** (Boolean motoru), **`shapely`** ve
**`mapbox-earcut`** (delikli poligon kalıbı). `requirements.txt` güncel;
ortam sıfırdan kurulursa `pip install -r requirements.txt` yeterli.
`vendor/three/` içindeki 5 dosya (≈540 KB, three r180) pakete kopyalanır,
yoksa sayfa CDN'e düşer.

### ⚠️ Güvenlik notu — `.env`

`.env` içinde gerçek sırlar düz metin duruyor (Anthropic anahtarı, HF token,
Gmail uygulama şifresi). Proje git deposu değil ama OneDrive ile senkronlanıyor.
HF token artık **hiç kullanılmıyor** (3D üretim kaldırıldı), silinebilir.
SMTP kullanılmıyorsa Gmail şifresi de silinebilir — sistem onsuz çalışır.
