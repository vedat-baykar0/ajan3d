// "Disarisi gorunuyor mu?" denetimi.
//
// Odanin kapali oldugunu goz karari degil OLCEREK dogrular: sahnenin arka
// plani cig bir renge cevrilir, kamera butun yonlere dondurulur ve her
// karede o renkten KAC PIKSEL kaldigi sayilir. Kapali bir odada sifir
// olmali; bir pikseli bile varsa oradan disarisi goruluyor demektir.
//
//   node tools/node/void_check.mjs <url> [--explode]
import puppeteer from 'puppeteer-core';

const args = process.argv.slice(2);
const url = args[0];
const explode = args.includes('--explode');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--enable-gpu', '--use-angle=default', '--ignore-gpu-blocklist',
         '--enable-unsafe-swiftshader', '--hide-scrollbars'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 860, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
await page.waitForFunction(() => window.__viewer && window.__viewer.root,
                           { timeout: 45000 });
await new Promise(r => setTimeout(r, 2000));

if (explode) {
  await page.evaluate(() => document.querySelector('#t-explode')?.click());
  await new Promise(r => setTimeout(r, 4000));
}

const report = await page.evaluate(async (doExplode) => {
  const v = window.__viewer, T = v.THREE;
  const was = v.scene.background;
  v.scene.background = new T.Color(1, 0, 1);          // cig macenta
  const size = 240;
  const rt = new T.WebGLRenderTarget(size, size);
  const buf = new Uint8Array(size * size * 4);
  const target = v.controls.target.clone();
  const dist = v.camera.position.distanceTo(target);
  // Sayfanin KENDI objektifi: daha genis bir aci ile bakmak sayfada
  // hic gorunmeyen bir kacagi hata diye bildirirdi.
  const cam = v.camera.clone();
  cam.aspect = 1; cam.updateProjectionMatrix();
  const room = v.room;
  const clamp = (p) => {
    if (!room) return;
    p.set(Math.min(Math.max(p.x, room.min.x), room.max.x),
          Math.min(Math.max(p.y, room.min.y), room.max.y),
          Math.min(Math.max(p.z, room.min.z), room.max.z));
  };

  const worst = [];
  for (let az = 0; az < 360; az += 15) {
    for (let el = -85; el <= 85; el += 17) {
      const a = az * Math.PI / 180, e = el * Math.PI / 180;
      cam.position.set(target.x + dist * Math.cos(e) * Math.sin(a),
                       target.y + dist * Math.sin(e),
                       target.z + dist * Math.cos(e) * Math.cos(a));
      clamp(cam.position);     // kamera kafesi: sayfanin kendi kurali
      cam.lookAt(target); cam.updateMatrixWorld(true);
      v.renderer.setRenderTarget(rt);
      v.renderer.render(v.scene, cam);
      v.renderer.readRenderTargetPixels(rt, 0, 0, size, size, buf);
      let hits = 0;
      for (let i = 0; i < buf.length; i += 4) {
        if (buf[i] > 200 && buf[i + 1] < 60 && buf[i + 2] > 200) hits++;
      }
      if (hits > 0) worst.push({ az, el, px: hits, pct: +(100 * hits / (size * size)).toFixed(3) });
    }
  }
  v.renderer.setRenderTarget(null);
  v.scene.background = was;
  worst.sort((a, b) => b.px - a.px);
  return { leaks: worst.length,
           maxPx: worst.length ? worst[0].px : 0,
           totalPx: worst.reduce((n, w) => n + w.px, 0),
           framePx: size * size,
           worst: worst.slice(0, 6) };
}, explode);

console.log(JSON.stringify({ explode, ...report, errors }, null, 2));
await browser.close();
