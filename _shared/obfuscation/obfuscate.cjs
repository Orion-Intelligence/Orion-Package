const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function files(root) {
  return fs.readdirSync(root, {withFileTypes: true}).flatMap(entry => {
    const file = path.join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`Unexpected asset symlink: ${file}`);
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : files(file);
    return [file];
  });
}

function protect(root, target = 'browser-no-eval') {
  root = path.resolve(root);
  const browser = target === 'browser-no-eval';
  const entries = files(root);
  if (entries.some(file => /\.(?:tsx?|py|pyc)$/.test(file))) throw new Error('Source files remain in JavaScript release assets');
  const integrity = new Map();
  let count = 0;
  for (const file of entries) {
    if (!/\.(?:m?js|cjs)$/.test(file)) continue;
    const original = fs.readFileSync(file, 'utf8');
    let output;
    if (browser) {
      const marker = '/*! orion-protected:' + crypto.createHash('sha256').update(original).digest('hex') + ' */';
      output = marker + '\n' + original;
    } else {
      const obfuscator = require('javascript-obfuscator');
      const result = obfuscator.obfuscate(original, {
        target, compact: true, sourceMap: false, seed: 73129,
        identifierNamesGenerator: 'hexadecimal', identifiersPrefix: 'o' + crypto.createHash('sha256').update(path.relative(root, file)).digest('hex').slice(0, 8),
        renameGlobals: false, renameProperties: false, transformObjectKeys: false,
        controlFlowFlattening: false, deadCodeInjection: false,
        debugProtection: false, selfDefending: false, disableConsoleOutput: false,
        stringArray: true, stringArrayEncoding: ['base64'], stringArrayThreshold: 1,
        stringArrayCallsTransform: false, splitStrings: false,
      }).getObfuscatedCode();
      const licenses = original.match(/\/\*[!*][\s\S]*?\*\//g) || [];
      const marker = '/*! orion-protected:' + crypto.createHash('sha256').update(result).digest('hex') + ' */';
      output = [marker, ...licenses, result].join('\n');
    }
    for (const algorithm of ['sha256', 'sha384', 'sha512']) {
      integrity.set(algorithm + '-' + crypto.createHash(algorithm).update(original).digest('base64'),
        algorithm + '-' + crypto.createHash(algorithm).update(output).digest('base64'));
    }
    fs.writeFileSync(file, output);
    count++;
  }
  for (const file of entries) {
    if (/\.(?:js|mjs|css)\.map$/.test(file)) fs.unlinkSync(file);
    if (file.endsWith('.html')) {
      fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace(/sha(?:256|384|512)-[A-Za-z0-9+/=]+/g,
        value => integrity.get(value) || value));
    }
  }
  const worker = path.join(root, 'ngsw.json');
  if (fs.existsSync(worker)) {
    const manifest = JSON.parse(fs.readFileSync(worker, 'utf8'));
    for (const name of Object.keys(manifest.hashTable || {})) {
      const asset = path.resolve(root, '.' + name);
      if (!asset.startsWith(root + path.sep)) throw new Error('Unsafe service-worker asset path');
      if (fs.existsSync(asset)) manifest.hashTable[name] = crypto.createHash('sha1').update(fs.readFileSync(asset)).digest('hex');
      else if (/\.(?:js|mjs|css)\.map$/.test(name)) delete manifest.hashTable[name];
      else throw new Error(`Missing service-worker asset: ${name}`);
    }
    for (const group of manifest.assetGroups || []) {
      if (group.urls) group.urls = group.urls.filter(name => !/\.(?:js|mjs|css)\.map$/.test(name));
    }
    fs.writeFileSync(worker, JSON.stringify(manifest));
  }
  console.log(`${browser ? 'Validated' : 'Obfuscated'} ${count} JavaScript assets (${target}); source maps excluded.`);
}

if (require.main === module) protect(process.argv[2], process.argv[3]);
module.exports = {protect};
