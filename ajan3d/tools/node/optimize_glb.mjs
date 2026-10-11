/**
 * GLB web optimizasyonu — Draco sıkıştırması.
 *
 *   node optimize_glb.mjs <girdi.glb> <cikti.glb>
 *
 * Uzantıyı (KHR_draco_mesh_compression) elle yazmak yerine `@gltf-transform`
 * kullanılıyor: nitelik kimliklerinin eşlenmesi, geri dönüş erişimcilerinin
 * korunması ve `extensionsRequired` yönetimi spec'e duyarlı ayrıntılar ve
 * elle yazıldığında sessizce yanlış çıkabiliyor.
 *
 * Düğüm `extras` alanları (pid / grp / ax / d / st) sunum sayfasının
 * sözleşmesidir; gltf-transform bunları koruyor, çıktı yine de doğrulanıyor.
 *
 * Çıktı olarak tek satır JSON basar; Python tarafı bunu okur.
 */
import fs from 'node:fs/promises';
import { NodeIO } from '@gltf-transform/core';
import { KHRDracoMeshCompression } from '@gltf-transform/extensions';
import { draco } from '@gltf-transform/functions';
import draco3d from 'draco3dgltf';

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  console.log(JSON.stringify({ ok: false, error: 'kullanim: <girdi> <cikti>' }));
  process.exit(2);
}

try {
  const io = new NodeIO()
    .registerExtensions([KHRDracoMeshCompression])
    .registerDependencies({
      'draco3d.decoder': await draco3d.createDecoderModule(),
      'draco3d.encoder': await draco3d.createEncoderModule(),
    });

  const before = (await fs.stat(input)).size;
  const document = await io.read(input);

  // Sıkıştırma öncesi parmak izi: düğüm sözleşmesi + her mesh'in köşe/üçgen
  // sayısı ve sınır kutusu. Draco kayıplı niceleme yapar, bu yüzden konumlar
  // bire bir aynı olmaz; ama SAYILAR ve sınır kutusu değişmemeli. Değişirse
  // geometri bozulmuş demektir ve optimizasyon reddedilir.
  const fingerprint = (doc) => {
    const nodes = doc.getRoot().listNodes()
      .filter(n => n.getExtras() && n.getExtras().pid).length;
    const meshes = doc.getRoot().listMeshes().map(mesh => {
      const prim = mesh.listPrimitives()[0];
      const position = prim.getAttribute('POSITION');
      return {
        name: mesh.getName(),
        verts: position ? position.getCount() : 0,
        indices: prim.getIndices() ? prim.getIndices().getCount() : 0,
        normals: !!prim.getAttribute('NORMAL'),
        min: position ? position.getMinNormalized([]) : null,
        max: position ? position.getMaxNormalized([]) : null,
      };
    });
    return { nodes, meshes };
  };
  const before_fp = fingerprint(document);
  const extrasBefore = before_fp.nodes;

  await document.transform(
    draco({
      method: 'edgebreaker',      // sıralı yüz dizisi; CAD kabukları için en iyi
      quantizePosition: 14,       // ~0.006 mm çözünürlük (DN50 gövdede)
      quantizeNormal: 10,
      quantizeTexcoord: 12,
      quantizeColor: 8,
      quantizeGeneric: 12,
    }),
  );

  await io.write(output, document);
  const after = (await fs.stat(output)).size;

  // Doğrulama: yazılan dosyayı GERİ OKU (Draco çözülerek) ve parmak izini
  // karşılaştır. Böylece "sıkıştı ama bozuldu" durumu sessizce geçemez.
  const check = await io.read(output);
  const after_fp = fingerprint(check);
  const problems = [];

  if (after_fp.nodes !== before_fp.nodes) {
    problems.push(`dugum sozlesmesi ${before_fp.nodes} -> ${after_fp.nodes}`);
  }
  if (after_fp.meshes.length !== before_fp.meshes.length) {
    problems.push(`mesh sayisi ${before_fp.meshes.length} -> ${after_fp.meshes.length}`);
  } else {
    for (let i = 0; i < before_fp.meshes.length; i++) {
      const a = before_fp.meshes[i], b = after_fp.meshes[i];
      // Draco (edgebreaker) tekrar eden köşeleri birleştirir ve devirme
      // ekseninde kalan sıfır alanlı üçgenleri atar. İkisi de İYİ: yüzey
      // değişmez, dosya küçülür. Bu yüzden AZALMA kabul, ARTMA kabul değil;
      // üçgen kaybı da yüzeyi delecek kadar büyük olamaz.
      if (b.verts > a.verts || b.indices > a.indices) {
        problems.push(`${a.name}: geometri buyudu ${a.verts}/${a.indices} ` +
                      `-> ${b.verts}/${b.indices}`);
      } else if (b.indices < a.indices * 0.97) {
        problems.push(`${a.name}: ucgen kaybi %` +
                      `${((1 - b.indices / a.indices) * 100).toFixed(1)}`);
      } else if (!b.normals) {
        problems.push(`${a.name}: normaller kayboldu`);
      } else if (a.min && b.min) {
        // Niceleme payı: en büyük kenarın binde biri.
        const span = Math.max(...a.max.map((v, k) => v - a.min[k]));
        const drift = Math.max(...a.min.map((v, k) => Math.abs(v - b.min[k])),
                               ...a.max.map((v, k) => Math.abs(v - b.max[k])));
        if (drift > span * 0.001) {
          problems.push(`${a.name}: sinir kutusu ${drift.toExponential(2)} kaydi`);
        }
      }
    }
  }

  if (problems.length) {
    await fs.rm(output, { force: true });
    console.log(JSON.stringify({ ok: false, error: problems.slice(0, 4).join('; ') }));
    process.exit(1);
  }

  console.log(JSON.stringify({
    ok: true, before, after,
    saved_pct: Math.round((1 - after / before) * 100),
    nodes_with_contract: after_fp.nodes, meshes: after_fp.meshes.length,
    triangles: after_fp.meshes.reduce((s, m) => s + m.indices / 3, 0),
  }));
} catch (error) {
  console.log(JSON.stringify({ ok: false, error: String(error && error.message || error) }));
  process.exit(1);
}
