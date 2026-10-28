const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const suffix = process.argv[2];
if (!['4811', '49180', '495', '410040', '4102'].includes(suffix)) throw Error('Invalid browser validation case');
const directory = path.join(__dirname, 'browser-output');
fs.mkdirSync(directory, { recursive: true });
// The initial 4102 successful probe predated per-version report names; retain its exact bytes.
const initial = path.join(directory, 'report.json'), retained = path.join(directory, '4102-report.json');
if (!fs.existsSync(retained) && fs.existsSync(initial)) {
    const report = JSON.parse(fs.readFileSync(initial, 'utf8'));
    if (report.ok && report.host === 'http://127.0.0.1:19042') fs.copyFileSync(initial, retained);
}
const files = [`${suffix}-report.json`, ...['local', 'thunder', 'cloud', 'proxy'].map(tab => `${suffix}-${tab}.png`)];
if (suffix === '4811') files.push('4811-pre-network-idle-failure.json');
const remote = 'set -eu; tar -czf - -C /volume1/docker/emby-subtitle-assistant-validation-20261027/browser/browser-output ' + files.join(' ') + ' | base64 -w 0';
const encoded = execFileSync('pwsh', ['-NoLogo', '-NoProfile', '-File', 'C:/Users/jzdxjk/.codex/nas-sudo.ps1', '-Command', remote],
    { encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 32 * 1024 * 1024, timeout: 60000 });
const archive = path.join(directory, `${suffix}-artifacts.tar.gz`);
fs.writeFileSync(archive, Buffer.from(encoded.trim(), 'base64'));
const entries = execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' }).trim().split(/\r?\n/);
if (entries.some(entry => !files.includes(entry))) throw Error('Unexpected archive entry');
execFileSync('tar', ['-xzf', archive, '-C', directory], { stdio: ['ignore', 'pipe', 'pipe'] });
const report = JSON.parse(fs.readFileSync(path.join(directory, `${suffix}-report.json`), 'utf8'));
if (!report.ok || !report.restored || report.screenshots.length !== 4) throw Error('Browser report is incomplete');
const text = JSON.stringify(report);
if (/"(?:Password|AccessToken|Username|CloudApiToken)"\s*:|Bearer |X-Emby-Token/i.test(text)) throw Error('Unexpected credential field in public report');
if ((report.recentResources || []).some(resource => resource.path.includes('?'))) throw Error('Query string in resource diagnostics');
console.log(JSON.stringify({ serverVersion: report.serverVersion, ok: report.ok, restored: report.restored,
    screenshotCount: report.screenshots.length, redactionShapeAudit: true }));
