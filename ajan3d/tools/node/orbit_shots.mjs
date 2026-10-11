// Sunum sayfasini acip KAMERAYI gezdirerek seri ekran goruntusu alir.
// Tek Chrome oturumunda calisir; her kare icin ayri surec baslatmaz.
//   node tools/node/orbit_shots.mjs <url> <cikti-klasoru> [--w 1280] [--h 860]
//
// Kareler: <klasor>\<ad>.png  —  adlar asagidaki SHOTS listesinden.
import puppeteer from 'puppeteer-core';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const args = process.argv.slice(2);
const url = args[0], dir = args[1];
const flag = (n, d) => { const i = args.indexOf('--' + n); return i < 0 ? d : args[i + 1]; };
const width = +flag('w', 1280), height = +flag('h', 860);
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

// az: yatay aci (derece, 0 = +Z'den), el: yukseklik acisi (derece)
const SHOTS = [
  { name: 'on',        az:   0, el:  12 },
  { name: 'yan',       az:  90, el:  10 },
  { name: 'arka',      az: 180, el:  12 },
  { name: 'ust',       az:  35, el:  70 },
  { name: 'alt',       az:  35, el: -35 },
  { name: 'ufuk',      az:  35, el:   0 },
  { name: 'tepe-yakin',az:  20, el:  28, zoom: 0.42, lift: 0.34 },
];

mkdirSync(dir, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--enable-gpu', '--use-angle=default', '--ignore-gpu-blocklist',
         '--enable-unsafe-swiftshader', '--hide-scrollbars'],
});
const page = await browser.newPage();
await page.setViewport({ width, height, deviceScaleFactor: 1 });
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
await page.waitForFunction(() => window.__viewer && window.__viewer.root,
                           { timeout: 45000 });
await new Promise(r => setTimeout(r, 2500));

// Taban yaricap bir kez olculur: her karede yeniden okunsaydi zoom'lu
// kareden sonraki kareler de yakin kalirdi (kayan referans).
const BASE = await page.evaluate(() => {
  const v = window.__viewer;
  return v.camera.position.distanceTo(v.controls.target);
});
const HOME = await page.evaluate(() => {
  const t = window.__viewer.controls.target;
  return { x: t.x, y: t.y, z: t.z };
});

async function place(s) {
  await page.evaluate(({ az, el, zoom, lift, base, home }) => {
    const v = window.__viewer;
    const t = new v.THREE.Vector3(home.x, home.y, home.z);
    const r = base * (zoom || 1);
    const a = az * Math.PI / 180, e = el * Math.PI / 180;
    if (lift) t.y += r * lift;
    v.camera.position.set(t.x + r * Math.cos(e) * Math.sin(a),
                          t.y + r * Math.sin(e),
                          t.z + r * Math.cos(e) * Math.cos(a));
    v.controls.target.copy(t);
    v.camera.lookAt(t); v.controls.update(); v.render();
  }, { ...s, base: BASE, home: HOME });
  await new Promise(r => setTimeout(r, 420));
}

for (const s of SHOTS) {
  await place(s);
  await page.screenshot({ path: join(dir, s.name + '.png') });
}

// Patlatma: dugmeye bas, acilmasini bekle, iki aciden cek
await page.evaluate(() => document.querySelector('#t-explode')?.click());
await new Promise(r => setTimeout(r, 3800));
for (const s of [{ name: 'patlak-on', az: 0, el: 12 },
                 { name: 'patlak-yan', az: 90, el: 14 }]) {
  await place(s);
  await page.screenshot({ path: join(dir, s.name + '.png') });
}
// Geri birlestir ve boru/vana ek yerine yakin bak
await page.evaluate(() => document.querySelector('#t-explode')?.click());
await new Promise(r => setTimeout(r, 3800));
await place({ name: 'ek', az: 70, el: 4, zoom: 0.45 });
await page.screenshot({ path: join(dir, 'birlesim-yakin.png') });

console.log(JSON.stringify({ dir, shots: SHOTS.length + 3, errors }, null, 2));
await browser.close();
