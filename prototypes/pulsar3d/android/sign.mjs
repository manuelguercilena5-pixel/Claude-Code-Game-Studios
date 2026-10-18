// Signs (v1 + v2 + v3) and zipaligns an APK with apk_sign_ts.
// Usage: node sign.mjs in.apk out.apk key.pem cert.pem   (run with cwd = a folder that has apk_sign_ts installed)
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const [input, output, keyPem, certPem] = process.argv.slice(2);
const entry = path.join(process.cwd(), 'node_modules', 'apk_sign_ts', 'dist', 'index.js');
const { ApkSigner, SigningKey } = await import(pathToFileURL(entry).href);

const signer = new ApkSigner({ signingKey: SigningKey.fromPEM(readFileSync(keyPem, 'utf8'), readFileSync(certPem, 'utf8')) });
const { signedApk } = await signer.sign(new Uint8Array(readFileSync(input)));
writeFileSync(output, signedApk);
console.log('signed', output, signedApk.length, 'bytes');
