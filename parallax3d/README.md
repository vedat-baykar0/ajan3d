# parallax3d — 2D fotograf -> 2.5D Parallax Video

Tek bir fotograftan, LeiaPix / TikTok "3D zoom" tarzinda derinlikli, kusursuz
donen (loop) bir `.mp4` (istege bagli `.gif`) uretir. Sunucu, web arayuzu veya
internet baglantisi gerekmez — sadece Python pipeline'i. (Model ilk calistirmada
bir kez indirilir, sonrasinda tamamen offline calisir.)

## Nasil calisir

```
Fotograf
   |
   v  [1] Derinlik tahmini      Depth-Anything V2 (veya MiDaS-DPT) -> derinlik haritasi
   v  [2] Segmentasyon          rembg (varsa) ya da derinlik + Otsu -> on plan maskesi
   v  [3] Sahne hazirligi      arka plan plakasi: ozne silinip `cv2.inpaint` ile dolduruluyor
   v  [4] Kamera                sinus tabanli dongusel yol (loop dikissiz)
   v  [5] Render + yazma        her piksel kendi derinligi kadar kayar -> H.264 mp4 / GIF
```

Iki render motoru var:

* **`warp` (varsayilan)** — her piksel kendi derinligi kadar kayar. Hedef pikselin
  kaynagi sabit nokta iterasyonuyla cozulur; iterasyon yakinsamazsa orasi ozne
  kayinca acilan bosluktur ve inpaint'li arka plan plakasindan doldurulur.
  Kenarlarda hayalet/basamak izi birakmaz, daha hizlidir.
* **`layers`** — goruntuyu 16 derinlik bandina bolup her bandi toptan kaydirir
  (`--engine layers`). Klasik yontem; bazi fotograflarda daha "sert" bir 3D hissi verir.

## Kurulum

```powershell
pip install -r requirements.txt
```

GPU (CUDA) ile daha hizli derinlik cikarimi istersen torch'u CUDA surumuyle kur:

```powershell
pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126
```

Daha temiz nesne kenarlari icin (istege bagli):

```powershell
pip install rembg onnxruntime
```

## Kullanim

```powershell
# En basit hali -> output/foto_orbit.mp4
python main.py foto.jpg

# Hareket, sure, GIF
python main.py foto.jpg -o cikti.mp4 -m orbit -d 4 --fps 30 --gif

# Klasordeki tum fotograflar
python main.py .\fotograflar -m zoom -s 1.2 -o .\output

# Derinlik/maske ara cikti goruntuleriyle
python main.py foto.jpg --debug
```

### Kamera hareketleri (`-m`)

| Deger        | Etki                                               |
|--------------|----------------------------------------------------|
| `orbit`      | Eliptik salinim — klasik "3D foto" (varsayilan)    |
| `zoom`       | Derinlige dogru yakinlasip geri cikma              |
| `dolly`      | Yakinlasma + hafif yana kayma                      |
| `horizontal` | Sola-saga kayma                                    |
| `vertical`   | Yukari-asagi kayma                                 |
| `swing`      | Yatay salinim + nefes alan zoom                    |
| `zigzag`     | Daha hareketli, sosyal medya tarzi                 |

### Onemli parametreler

| Parametre     | Varsayilan | Aciklama                                                      |
|---------------|------------|----------------------------------------------------------------|
| `-s/--strength` | `1.0`    | Parallax siddeti. `0.5` sakin, `1.5` agresif (fazlasi bozar).  |
| `--focus`     | `0.5`      | Sabit kalan derinlik duzlemi. `0.8` -> ozne sabit, arka kayar. |
| `--engine`    | `warp`     | Render motoru: `warp` (temiz) veya `layers` (katmanli).        |
| `--layers`    | `16`       | `--engine layers` icin bant sayisi.                            |
| `--max-side`  | `1280`     | Calisma cozunurlugu. `1920` daha net, daha yavas.              |
| `--model`     | `small`    | `small`/`base`/`large` (kalite-hiz), `midas`, `midas-large`.   |
| `--segment`   | `auto`     | `rembg` varsa onu kullan, yoksa `depth`. `none` = kapali.      |
| `--overscan`  | `0.07`     | Kenar kirpma payi; az olursa kenarlarda bosluk gorulur.        |

## Python API

```python
from parallax3d import ParallaxPipeline, PipelineConfig

pipe = ParallaxPipeline(PipelineConfig(motion="orbit", duration=4.0, strength=1.1, gif=True))
pipe.run("foto.jpg", "output/foto.mp4")   # model bir kez yuklenir, tekrar tekrar cagirilabilir
```

## Modul yapisi

| Dosya         | Sorumlulugu                                        |
|---------------|----------------------------------------------------|
| `depth.py`    | Derinlik modeli yukleme + tahmin + normalize/yumusatma |
| `segment.py`  | On plan maskesi (rembg / derinlik-Otsu)            |
| `warp.py`     | Piksel bazli ters warp render'i (varsayilan motor)  |
| `render.py`   | Katmanli render + arka plan inpaint plakasi         |
| `camera.py`   | Dongusel kamera yollari                            |
| `video.py`    | mp4 (H.264) ve GIF yazma (ffmpeg palette)          |
| `pipeline.py` | Adimlari birlestiren akis + yapilandirma           |
| `cli.py`      | Komut satiri arayuzu, toplu isleme                 |

## Ipuclari

- Belirgin bir on plani (ozne) ve uzak arka plani olan fotograflar en iyi sonucu verir.
- Kenarlarda "esneme" goruyorsan: `-s 0.7` veya `--overscan 0.1` dene.
- Ozne etrafinda hayalet/halo varsa: `--segment rembg` (kurulumu gerekir) veya `--refine 11`.
- Kenarda esneme yerine daha sert bir 3D hissi istersen: `--engine layers`.
- Duz duvar/belge fotografinda derinlik yoktur; efekt zayif gorunur — normaldir.

## Test

Model indirmeden calisan hizli dogrulama (sentetik sahne uzerinde segmentasyon,
katmanlama, warp ve video yazma adimlarini kontrol eder):

```powershell
python tests/smoke_test.py
```
