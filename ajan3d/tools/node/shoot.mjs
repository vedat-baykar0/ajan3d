// Yayinlanmis sunum sayfasini gercek Chrome'da acip ekran goruntusu alir.
//   node tools/node/shoot.mjs <url> <cikti.png> [--explode] [--w 1600] [--h 1000]
import puppeteer from 'puppeteer-core';

const args = process.argv.slice(2);
const url = args[0];
const out = args[1];
const flag = (n, d) => { const i = args.indexOf('--' + n); return i < 0 ? d : args[i + 1]; };
const width = +flag('w', 1600), height = +flag('h', 1000);
const explode = args.includes('--explode');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--enable-gpu', '--use-angle=default', '--ignore-gpu-blocklist',
         '--enable-unsafe-swiftshader', '--hide-scrollbars'],
});
const page = await browser.newPage();
await page.setViewport({ width, height, deviceScaleFactor: 1 });

const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });

// Sahne hazir olana kadar bekle: yukleme ekrani kaybolmali
await page.waitForFunction(() => {
  const l = document.querySelector('#loading, .loading, #loader');
  return !l || l.offsetParent === null || getComputedStyle(l).opacity === '0';
}, { timeout: 45000 }).catch(() => errors.push('TIMEOUT: yukleme ekrani kapanmadi'));

await new Promise(r => setTimeout(r, 2500));  // ilk kareler + yumusak giris

if (explode) {
  await page.evaluate(() => {
    const b = document.querySelector('#t-explode');
    if (b) b.click(); else throw new Error('patlatma dugmesi bulunamadi');
  });
  await new Promise(r => setTimeout(r, 3500));
}

const snippet = flag('eval', null);
if (snippet) {
  const res = await page.evaluate(snippet);
  if (res !== undefined) console.log('eval ->', JSON.stringify(res));
  await new Promise(r => setTimeout(r, 1200));
}

await page.screenshot({ path: out });
console.log(JSON.stringify({ out, errors }, null, 2));
await browser.close();
