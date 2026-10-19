// Pinned adapter to REA's canonical bundle boundary and its real public CLI.
// All original resource metadata and child diagnostics stay in privateWorkspace.
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

const [requestPath, reaPackage, privateWorkspace] = process.argv.slice(2);
if (!requestPath || !reaPackage || !privateWorkspace) throw Error('Expected request, REA package and private workspace');
const pkg = JSON.parse(await readFile(path.join(reaPackage, 'package.json'), 'utf8'));
if (pkg.name !== 'rea-agents' || pkg.version !== '6.7.0') throw Error('This adapter requires rea-agents 6.7.0');
const moduleUrl = relative => pathToFileURL(path.join(reaPackage, relative)).href;
const { parseEvidence } = await import(moduleUrl('dist/domain/evidence.js'));
const { createEvidenceBundle, parseEvidenceBundle } = await import(moduleUrl('dist/domain/evidenceBundle.js'));
const { reconstructionObligationLedgerSchema, reconstructionObligationLedgerInputSchema } =
  await import(moduleUrl('dist/domain/reconstructionObligationLedgerSchemas.js'));
const request = JSON.parse(await readFile(requestPath, 'utf8'));
const record = parseEvidence(JSON.parse(await readFile(request.evidence_path, 'utf8')));
if (record.operation !== 'inspect_pe_resources' || record.authority !== 'shipped-artifact')
  throw Error('Expected authenticated shipped-artifact PE resource Evidence');
const bundle = parseEvidenceBundle(createEvidenceBundle([record]));
const input = reconstructionObligationLedgerInputSchema.parse({
  evidence_bundle: bundle, reviewed_obligations: request.reviewed_obligations,
  manifest: { bindings: [], contradictions: [] },
});
const inputPath = path.join(privateWorkspace, 'canonical-ledger-input.json');
await writeFile(inputPath, JSON.stringify(input), { flag: 'wx' });
const child = spawnSync(process.execPath, [path.join(reaPackage, 'scripts/rea.mjs'),
  'build-reconstruction-obligation-ledger', inputPath, '--format', 'json'],
  { encoding: 'utf8', timeout: 120000, maxBuffer: 20 * 1024 * 1024 });
await writeFile(path.join(privateWorkspace, 'rea-cli.stderr.log'), child.stderr ?? '', { flag: 'wx' });
await writeFile(path.join(privateWorkspace, 'rea-cli.stdout.log'), child.stdout ?? '', { flag: 'wx' });
if (child.error || child.status !== 0) throw Error('REA CLI failed; private diagnostics were retained');
const result = parseEvidence(JSON.parse(child.stdout));
reconstructionObligationLedgerSchema.parse(result.normalized_result);
if (result.operation !== 'build_reconstruction_obligation_ledger') throw Error('Unexpected REA operation');
await writeFile(path.join(privateWorkspace, 'rea-ledger.json'), JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
await writeFile(path.join(privateWorkspace, 'versions.json'), JSON.stringify({ rea: pkg.version, node: process.version }), { flag: 'wx' });
