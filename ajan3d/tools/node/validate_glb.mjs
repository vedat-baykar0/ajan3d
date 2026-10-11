// Khronos glTF dogrulayicisi: node tools/node/validate_glb.mjs <dosya.glb>
import { validateBytes } from 'gltf-validator';
import { readFileSync } from 'fs';
const file = process.argv[2];
const report = await validateBytes(new Uint8Array(readFileSync(file)));
const i = report.issues;
console.log(JSON.stringify({
  file, errors: i.numErrors, warnings: i.numWarnings, infos: i.numInfos,
  messages: i.messages.slice(0, 12).map(m => m.severity + ': ' + m.code + ' @ ' + m.pointer),
}, null, 1));
