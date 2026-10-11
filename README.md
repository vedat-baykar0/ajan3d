# 🏭 ajan3d — From a Photograph to a Parametric CAD Showroom

> **Upload photos of an industrial product → get back a watertight parametric CAD
> assembly and a photorealistic, interactive Three.js presentation page with a
> public share link. In about 60 seconds. Unattended.**

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Three.js" src="https://img.shields.io/badge/Three.js-r180-000000?logo=threedotjs&logoColor=white">
  <img alt="Claude" src="https://img.shields.io/badge/Claude-Vision%20%2B%20Web%20Search-D97757">
  <img alt="CAD" src="https://img.shields.io/badge/CAD-manifold3d%20%C2%B7%20trimesh-1f6feb">
  <img alt="Tests" src="https://img.shields.io/badge/tests-438%20passing-2ea44f">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey">
</p>

---

## 🎯 What this is

A customer drops a folder of phone photos of a valve, a flange or a bearing into
`inbox/`. A chain of agents then:

1. **recognizes** the product's *technical identity* (type, DN, PN, material,
   connection, actuation, stamped markings),
2. **researches** its catalogue data and standard parts list on the web,
3. **builds** a real parametric CAD assembly — closed Boolean solids, dimensions
   taken from **EN 1092-1 / ISO 5211 / ISO 724** standard tables,
4. **packages** an industrial Three.js presentation page (exploded view, X-ray,
   labelled parts, mass breakdown, the customer's own photo projected onto the
   model),
5. **publishes** it through a tunnel and hands back a **public HTTPS link**.

### 🧠 The core idea: the photo is an *identifier*, not a geometry source

Image-to-3D networks (TRELLIS, InstantMesh) only ever produce the **outer
shell**. They cannot know that the body is solid, where the bolt threads into,
or which groove the seat sits in — that information simply is not in the
photograph. Measured on a real valve: **186,191 faces forming a single connected
component (99.8%)**. Bolts, handle and body were one surface; splitting it into
"parts" was guesswork.

So geometry is no longer *guessed*. If you know **what the product is**, the
geometry can be **constructed correctly**: a DN50/PN40 flange is 165 mm across,
with a 125 mm bolt circle and 4×M16 bolts — that is written in the EN 1092-1
table. The part exists **first**; the assembly is built from parts.

The measurable proof that a part is a real solid is its **mass** (volume ×
density). A DN50 3-piece ball valve comes out at **4.62 kg** against a catalogue
figure of 3–4.5 kg. A shell model cannot report mass at all — so the mass column
is simultaneously a validation.

---

## ⛓️ The pipeline

```
inbox/<folder>   (customer photos)
   │
   ├─[1] 👁️  Vision Agent     (Claude Vision)        → metadata.json : identity
   │        technical identity: type · DN · PN · material · connection ·
   │        actuation · body piece count · stamped markings
   │
   ├─[2] 📚 Spec Agent        (Claude + web_search)  → metadata.json : spec
   │        catalogue data, standards, standard-parts list
   │
   ├─[3] 📐 CAD Agent         (local, free, offline)  → model.glb + cad.json
   │        library match → parametric Boolean-solid assembly
   │
   ├─[4] 📦 Packager Agent                            → delivery_<product>_<date>/ + .zip
   │        self-contained Three.js industrial presentation page
   │
   └─[5] 🚀 Deployer Agent + tunnel                   → PUBLIC LINK (https://…)
```

Steps 3–5 need **no network, no GPU and no queue**. Only steps 1–2 call a paid
API, and step 2 can be switched off entirely (`SPEC_ENABLED=false`).

---

## ✨ Highlights

### 📐 A real parametric CAD kernel

| Path | Used for | Notes |
|---|---|---|
| `revolve` | everything axially symmetric (body, ball, stem, seats, gaskets) | profile in the `(r, z)` plane |
| `plate` | flanges, caps, mounting pads | shapely polygon, holes punched by die |
| `union` / `cut` | transitions, pockets, thread reliefs | `manifold3d` Boolean engine |

Every part is a **closed solid**: holes are *drilled*, pockets are *cut*, bodies
are *fused*. Measured on a DN50 3-piece ball valve → 16 parts, 26 instances,
**16/16 watertight**, 0 Boolean fallbacks, **0.35 s**.

Dimensions come from real standard tables: **EN 1092-1** flanges (DN15–DN300,
PN16/PN40), **ISO 5211** mounting pads (F03–F12), **ISO 724** metric threads.
The text parsers accept `DN50`, `2"`, `1 1/2"`, `PN40`, `Class 300`, `1000 WOG`
and `16 bar` alike.

**Part families:** `ball_valve` · `gate_valve` (gate/globe) · `butterfly_valve` ·
`check_valve` · `strainer` · `flange_joint` · `bearing` · `generic`.
Anything below the match threshold falls back to `generic_housing` and is marked
*representative* — the system's way of saying **"I don't know."**

### 🖼️ The presentation page (`templates/viewer.html.j2`)

| Capability | Detail |
|---|---|
| **Assemble / Explode** | Slider + button; each part opens along **its own assembly axis**, with a staged delay that shows the disassembly order |
| **X-Ray** | The housing turns 12% transparent, the inner mechanism stays opaque, edge lines are added |
| **Labels** | Projected label + dot + leader line, pushed outward from screen centre |
| **Part picking** | Click in 3D or pick from the list → everything else ghosts out, an info card opens |
| **Photo projection** | The customer's own photo is cast onto the model's shell from a fixed projector; it stays *stuck* to the surface as the camera orbits and travels with the part when exploded |
| **Industrial PBR fallback** | Surfaces the photo never saw (back faces, inner mechanism, screws) slide to dark, rough steel |
| **Baked AO** | Crevice darkening read from `COLOR_0`, applied to indirect light — zero runtime cost |
| **Studio HDRI** | Synthetic `studio.hdr` → PMREM, ACES tone mapping, rectangular softbox rig |
| **Procedural micro-surface** | CAD geometry has no UVs, so roughness is modulated by 3D noise in object space via `onBeforeCompile` — no extra download, nothing to unwrap |
| **Scale bar** | Live mm/m scale relative to the camera |
| **Also** | Rotate, reset, fullscreen, PNG capture, share link; keys `E X L R F Space 1-9` |

**Package size: ~1.9 MB** (down from 11–27 MB in the previous architecture).
Desktop load **2.7 s**, mobile (390×844) **2.6 s**.

### 🔬 Photorealism is measured, not eyeballed

The model used to look like "grey plastic". The materials were already correct —
the fault was the **environment**. Metal shows you whatever it reflects, and a
mid-grey dome reflected in every direction is indistinguishable from grey paint.

| | before | after |
|---|---|---|
| mean radiance | 1.659 | 0.450 |
| light-source fraction (>1.0) | **29.2%** | 9.3% |
| dark-area fraction (<0.05) | 28.1% | **86.4%** |
| **contrast** (peak/median) | **49:1** | **1461:1** |

Rectangular softboxes (a cylindrical body reflects the *shape* of the source), a
dark cyclorama, and radiance normalization so that tweaking the rig never shifts
scene brightness. The contract is locked by tests: source fraction < 15%, dark
area > 70%, contrast > 300:1.

### 🤖 Unattended agency layer (`run_agency.py`)

A watchdog on `inbox/`, a worker, **two separate web servers** and a tunnel.
The admin panel binds to `127.0.0.1` only; the tunnel exposes **only** the
publish server — verified from the open internet that `/api/jobs` returns
**404** while the delivery package returns 200.

### ✅ 438 tests, no network / API / GPU required

| File | Covers |
|---|---|
| `test_cad_kernel.py` | revolve volume, winding repair, perforated plates, nut/bolt solidity at every size, Boolean-fallback *logging*, EN 1092-1 table accuracy, text parsing |
| `test_families.py` | 15 assembly variants × watertightness, positive mass, explosion actually separating, no Boolean warnings, scale sensitivity, matcher accuracy |
| `test_gltf.py` | GLB container & 4-byte alignment, min/max requirement, explode contract on every node, unit normals, sRGB→linear, flipped-axis detection |
| `test_retrieval.py` | local library preferred, broken manifests non-fatal, geometry unchanged when annotating a ready-made GLB, source chain fallthrough |
| `test_package.py` | package self-sufficiency (incl. `vendor/three`), 6 MB ceiling, embedded JSON ↔ `cad.json` agreement, customer-text escaping |
| `test_pipeline.py` | a failing paid search does **not** stop delivery, no duplicate searches, transient vs. permanent errors, low confidence blocks the job |
| `test_tunnel.py` | address extraction, re-establishing when the process dies, thread safety |
| `test_agency_web.py` | publish server leaks no admin data, duplicate ports rejected, XSS |
| `test_hdri.py` | the photorealism contract above |

Externally validated too: **Khronos glTF Validator → 0 errors, 0 warnings,
0 infos**, and loaded by **real three.js r180** (26 meshes, 70,382 triangles,
26/26 nodes carrying the explode contract).

---

## 🧰 Tech stack

| Layer | Technology |
|---|---|
| **Agents / LLM** | `anthropic` (Claude Vision + `web_search` tool), `pydantic`, `python-dotenv`, `httpx` |
| **CAD kernel** | `manifold3d` (Booleans), `trimesh`, `shapely` + `mapbox-earcut` (perforated polygon dies), `numpy`, `scipy` |
| **Presentation** | **Three.js r180** (vendored for offline use), custom GLB writer, `jinja2`, `pillow`, `segno` (QR) |
| **Service layer** | `fastapi`, `uvicorn`, `watchdog`, `cloudflared` / `ngrok` tunnels |
| **Optimization** | Node + `@gltf-transform` + `draco3dgltf` → **994 KB → 121 KB (−88%)** |
| **Photo cut-out** | `rembg` + `onnxruntime` (U²-Net); falls back to a classic colour mask |
| **QA tooling** | `pytest`, `puppeteer-core` + installed Chrome (`tools/node/shoot.mjs`), `gltf-validator` |

---

## 🚀 Getting started

### 1. Requirements

* **Python 3.11+**
* An **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com) → API Keys
  *(there is no free tier; usage is billed per token)*
* *Optional:* **Node 18+** for Draco compression and screenshot tooling
* *Optional:* `cloudflared` for public links — no account needed

### 2. Install

```powershell
git clone https://github.com/vedat-baykar0/ajan3d.git
cd ajan3d/ajan3d

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

<details>
<summary>🐧 Linux / macOS</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`baslat.ps1` is Windows-only; run `python run_agency.py` directly instead.
</details>

### 3. Configure

```powershell
copy .env.example .env
```

Then put your key in `.env`:

```ini
ANTHROPIC_API_KEY=sk-ant-...
```

Everything else has a working default. `.env.example` documents all ~40 knobs:
model choice and effort per agent, CAD source order, HDRI size, tunnel
provider, SMTP notification, Draco thresholds.

> 🔒 `.env` is gitignored. Never commit it.

### 4. Optional extras

```powershell
# Draco compression + screenshot tooling
cd tools\node && npm install && cd ..\..

# Public-link tunnel: drop cloudflared.exe into tools\bin\
# https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Sample test photos
python tools\fetch_test_photos.py
```

---

## 🕹️ Usage

### One-shot production

```powershell
python run_all.py "inbox\customer-x"
python run_all.py "inbox\customer-x" --repackage     # rebuild only the page
python run_all.py "inbox\customer-x" --rebuild-cad   # rebuild the assembly
python run_all.py "inbox\customer-x" --force         # proceed despite low confidence
```

### Single steps

```powershell
python run_vision.py  "inbox\customer-x"   # recognition only
python run_cad.py     "inbox\customer-x"   # assembly only
python run_cad.py --families               # list the part-family library
python run_package.py "inbox\customer-x"   # presentation page only
```

### Unattended agency mode ⭐

```powershell
.\baslat.ps1              # start (detached — closing the terminal won't kill it)
.\baslat.ps1 -Durum       # status + current public link
.\baslat.ps1 -Gunluk      # tail the log
.\baslat.ps1 -Yeniden     # restart
.\baslat.ps1 -Durdur      # stop

python run_agency.py --check   # preflight: keys, ports, cloudflared
```

Drop a photo folder into `inbox/` and the chain runs on its own: the delivery
package lands in `jobs/`, is published to `public/`, and the public link is
written to `3D_SONUC.txt` inside the customer's folder (and copied to the
clipboard).

> ⚠️ **Known limit:** the delivered page uses ES modules, which browsers refuse
> to load over `file://` (CORS). Opening the ZIP and double-clicking
> `index.html` shows a readable error instead of working. Serve it over the
> public link or any web server.

---

## 📂 Repository layout

```
.
├─ ajan3d/                     ⭐ the main system
│  ├─ baslat.ps1               persistent launcher (-Durum -Durdur -Gunluk -Yeniden)
│  ├─ run_agency.py            orchestrator: watcher + worker + 2 web servers + tunnel
│  ├─ run_all.py               one-shot production
│  ├─ run_vision.py / run_cad.py / run_package.py    single-step runners
│  ├─ cad/                     📐 parametric CAD kernel
│  │  ├─ primitives.py         revolve, perforated plate, threads, bolts/nuts, Booleans
│  │  ├─ standards.py          EN 1092-1 · ISO 5211 · ISO 724 + DN/PN/actuation parsers
│  │  ├─ materials.py          PBR + densities (mass is computed from here)
│  │  ├─ ao.py                 baked ambient occlusion (voxel occupancy)
│  │  ├─ actuator.py           pneumatic actuator mounted on the ISO 5211 pad
│  │  ├─ assembly.py           Part / Placement / Assembly, validation, mass breakdown
│  │  ├─ gltf.py               GLB writer: angle-split normals, node extras
│  │  ├─ library.py            family catalogue + matching + parameter derivation
│  │  ├─ retrieval.py          local library → remote API → parametric
│  │  └─ families/             ball · gate · butterfly · check · strainer · flange · bearing
│  ├─ agents/                  vision · spec · cad · packager · deployer · receiver · notifier
│  ├─ core/                    config · schemas · pipeline · agency · tunnel ·
│  │                           hdri · projection · qr · images · jobs · optimize
│  ├─ templates/viewer.html.j2 the Three.js industrial UI
│  ├─ cad_library/             your own .glb library (see its README)
│  ├─ vendor/three/            Three.js r180 modules, vendored so it runs offline
│  ├─ tools/node/              Draco optimizer, GLB validator, Chrome screenshots
│  ├─ tests/                   438 tests
│  └─ PROJECT_STATUS.md        📖 full engineering log (Turkish) — every decision & measurement
│
└─ parallax3d/                 🎞️ companion tool: one photo → 2.5D parallax video
   ├─ main.py                  python main.py photo.jpg -m orbit -d 4 --gif
   └─ parallax3d/              depth (Depth-Anything V2) · segment · warp · camera · video
```

### 🎞️ `parallax3d` in one paragraph

A standalone side tool: turns a **single** photograph into a seamlessly looping
"3D zoom" `.mp4`/`.gif`. Depth-Anything V2 estimates depth, `rembg` (or depth +
Otsu) cuts the subject, the background plate is inpainted, and a sine-based
camera path drives a per-pixel warp solved by fixed-point iteration. No server,
no web UI, no internet after the first model download.

```powershell
cd parallax3d
pip install -r requirements.txt
python main.py ornekler\vana.jpg -m orbit -d 4 --fps 30 --gif
```

---

## 🗂️ CAD source order

Configured by `CAD_SOURCES` (default `local,parametric`), tried left to right:

1. **Local library** — `cad_library/<folder>/model.glb` + `manifest.json`.
   Your real supplier CAD files. The `.glb` is never modified; the explode
   contract is only *annotated* onto the nodes named in the manifest, so library
   models feed exactly the same UI as parametric ones.
2. **Remote API** — generic contract via `CAD_API_URL` (off by default). The
   `{query}` placeholder is substituted, the response is scanned for a `.glb`
   link.
3. **Parametric** — the path that **always** works, and therefore must be last.

> 💡 **An honest note on GrabCAD / Thangs:** GrabCAD has **no** open download
> API (it needs a session, and content may not be redistributed). Thangs' API is
> key-gated and its content is mostly STEP/SLDPRT — not `.glb`, and not arriving
> as named, separated parts. So no specific provider is hardcoded; plug in
> whichever service you hold a key for.

---

## 💵 Cost per job (measured)

| Step | Cost |
|---|---|
| Recognition (Claude Vision, 6 images @1280px) | ~$0.01 |
| Technical research (Claude + 4 web searches) | ~$0.11–0.17 |
| CAD assembly · packaging · publishing | **$0.00** (fully local) |

Set `SPEC_ENABLED=false` to drop the second line entirely — the chain still
builds the model, only the specification table gets thinner.

---

## 📊 End-to-end run (real photos, real API, real public link)

| Step | Time | Result |
|---|---|---|
| Recognition | 13 s | DN50 · PN63 · CF8 (AISI 304) · threaded · 3-piece · **bare stem** |
| Markings read | — | `DN50 PN63`, `CF8`, `2311`, `SJ`, `A2-70` |
| Technical data | 41 s | 4 searches, 39 sources, 10 properties, 19 standard parts |
| CAD assembly | 1 s | 13 parts / 23 instances, **13/13 watertight**, 4.42 kg, 0.97 MB |
| Package + publish | 2 s | 2.29 MB |
| **Total** | **66 s** | public HTTPS link |

---

## 🤝 Contributing

```powershell
cd ajan3d
.venv\Scripts\Activate.ps1
pytest -q            # 438 passed, 1 skipped — fully offline
python run_agency.py --check
```

New geometry belongs in `cad/families/` as a builder returning closed solids;
`tests/test_families.py` will automatically hold it to watertightness, positive
mass, real separation on explode and a clean Boolean log.

`PROJECT_STATUS.md` is the engineering log — it records not only what the code
does but **why each earlier approach failed**, with the measurements. Read it
before changing the CAD kernel or the lighting rig.

---

## 📄 License

No license has been chosen yet — all rights reserved for now.
Vendored third-party assets (`vendor/three`, `vendor/draco`, `vendor/model-viewer-umd.min.js`)
keep their own upstream licenses.

---

<p align="center">
  <sub>Built with Python 🐍, Three.js ✨ and Claude 🤖</sub>
</p>
