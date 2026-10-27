// Run only inside the owned browser validation container. Never enable traces or storageState.
const fs = require('node:fs');
const crypto = require('node:crypto');
const { chromium, request } = require('playwright');

const port = Number(process.env.EMBY_VALIDATION_PORT || '19042');
if (![19048, 19049, 19059, 19040, 19042].includes(port)) throw new Error('Unauthorized validation port');
const base = `http://127.0.0.1:${port}`;
const caseInfo = {
    19048: ['4811', '4.8.11.0'], 19049: ['49180', '4.9.1.80'], 19059: ['495', '4.9.5.0'],
    19040: ['410040', '4.10.0.40'], 19042: ['4102', '4.10.2.0']
}[port];
const pluginId = '76cd4168-e0b3-4aac-8a52-5cb638121744';
const output = '/work/browser-output';
const report = { host: base, playwright: require('playwright/package.json').version, checks: [], screenshots: [], restored: false };
let stage = 'private-session', browser, context, api, page, original, fullOriginal, changed = false;
let sensitiveValues = [];
const clean = (text, maximum = 300) => {
    let value = String(text || '');
    for (const secret of sensitiveValues) if (secret) value = value.split(secret).join('[redacted]');
    return value.replace(/https?:\/\/[^\s)]+/gi, '[url]').slice(0, maximum);
};
const ensure = (condition, description) => { if (!condition) throw new Error(description); };
const check = description => report.checks.push(description);

async function call(path, method = 'GET', data) {
    ensure(path.startsWith('/') && !path.includes('://'), 'Invalid isolated API path');
    const response = await api.fetch(base + '/emby' + path, { method, data });
    ensure(response.ok(), 'Isolated API request failed');
    return response.status() === 204 ? null : response.json();
}

async function waitForSettings() {
    await page.locator('#SubtitleAssistantConfigurationPage [data-settings-form]:not([hidden])').waitFor({ timeout: 30000 });
}

async function openSettings() {
    await page.evaluate(async () => {
        const module = await Emby.importModule('./modules/pagejs/page.js');
        (module.default || module).show('/configurationpage?name=subtitleassistant');
    });
    await waitForSettings();
}

async function select(tab) {
    await page.locator(`[data-tab="${tab}"]`).click();
    ensure(await page.locator(`[data-panel="${tab}"]`).isVisible(), 'Selected settings panel is hidden');
    for (const other of ['local', 'thunder', 'pool', 'cloud', 'proxy'].filter(value => value !== tab))
        ensure(!await page.locator(`[data-panel="${other}"]`).isVisible(), 'Inactive settings panel is visible');
}

async function save() {
    ensure(await page.locator('[data-settings-form]').evaluate(form => form.checkValidity()), 'Native form validation blocked settings submission');
    const response = page.waitForResponse(value => new URL(value.url()).pathname.endsWith('/SubtitleAssistant/settings') && value.request().method() === 'POST');
    await page.getByRole('button', { name: '保存设置', exact: true }).click();
    const result = await (await response).json();
    ensure(result.Ok, 'Settings save failed');
    await page.locator('[data-status]').filter({ hasText: '设置已保存' }).waitFor();
}

async function restore() {
    if (!changed || !original || !fullOriginal) return;
    const payload = { ...original, Proxy: { ...original.Proxy } };
    delete payload.Version; delete payload.HasCloudApiToken; delete payload.Proxy.HasPassword;
    payload.CloudApiToken = fullOriginal.CloudApiToken || '';
    payload.ClearCloudApiToken = !payload.CloudApiToken;
    payload.Proxy.Password = fullOriginal.Proxy?.Password || '';
    payload.Proxy.ClearPassword = !payload.Proxy.Password;
    const result = await call('/SubtitleAssistant/settings', 'POST', payload);
    ensure(result.Ok, 'Settings restoration failed');
    const restored = await call('/SubtitleAssistant/settings');
    for (const key of Object.keys(original).filter(key => key !== 'Version' && key !== 'Proxy'))
        ensure(JSON.stringify(restored[key]) === JSON.stringify(original[key]), 'A setting was not restored');
    for (const key of Object.keys(original.Proxy))
        ensure(JSON.stringify(restored.Proxy[key]) === JSON.stringify(original.Proxy[key]), 'A proxy setting was not restored');
    const full = await call(`/Plugins/${pluginId}/Configuration`);
    ensure((full.CloudApiToken || '') === (fullOriginal.CloudApiToken || ''), 'Cloud credential restoration failed');
    ensure((full.Proxy?.Password || '') === (fullOriginal.Proxy?.Password || ''), 'Proxy credential restoration failed');
    report.restored = true;
    changed = false;
}

(async () => {
    fs.mkdirSync(output, { recursive: true });
    const session = JSON.parse(fs.readFileSync('/run/emby-session.json', 'utf8'));
    sensitiveValues = [session.Username, session.Password, session.AccessToken, session.UserId,
        session.OrdinaryUser?.Name, session.OrdinaryUser?.AccessToken, session.OrdinaryUser?.Id];
    ensure(session.Username && session.Password && session.AccessToken, 'Private session is incomplete');
    stage = 'administrator-api';
    api = await request.newContext({ extraHTTPHeaders: {
        'X-Emby-Token': session.AccessToken,
        'X-Emby-Authorization': 'Emby Client="CodexBrowserValidation", Device="IsolatedBrowser", DeviceId="subtitle-assistant-browser", Version="1.0"'
    } });
    original = await call('/SubtitleAssistant/settings');
    const hostInfo = await call('/System/Info/Public');
    ensure(hostInfo.Version === caseInfo[1], 'Unexpected isolated Emby version');
    report.serverVersion = hostInfo.Version;
    fullOriginal = await call(`/Plugins/${pluginId}/Configuration`);
    sensitiveValues.push(fullOriginal.CloudApiToken, fullOriginal.Proxy?.Password);
    check('Administrator API settings snapshot is available');
    stage = 'browser-login';
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    await context.route('**/*', route => {
        let url;
        try { url = new URL(route.request().url()); } catch { return route.abort(); }
        return url.origin === base ? route.continue() : route.abort();
    });
    page = await context.newPage();
    report.browserErrors = [];
    report.failedResources = [];
    report.recentResources = [];
    report.settingsRequests = [];
    page.on('pageerror', error => { if (report.browserErrors.length < 10) report.browserErrors.push(clean(error.message)); });
    page.on('response', response => {
        const path = new URL(response.url()).pathname;
        report.recentResources.push({ path: clean(path), status: response.status(), type: response.request().resourceType() });
        if (report.recentResources.length > 40) report.recentResources.shift();
        if (path.endsWith('/SubtitleAssistant/settings')) report.settingsRequests.push({ method: response.request().method(), status: response.status() });
        if (response.status() >= 400 && report.failedResources.length < 20) {
            const url = new URL(response.url());
            report.failedResources.push({ path: clean(url.pathname), status: response.status() });
        }
    });
    page.setDefaultTimeout(15000);
    await page.goto(base + '/web/index.html', { waitUntil: 'domcontentloaded' });
    const administratorTile = page.getByText(session.Username, { exact: true }).first();
    await administratorTile.waitFor({ timeout: 30000 });
    const alreadyAuthenticated = await page.evaluate(id => globalThis.ApiClient && String(ApiClient.getCurrentUserId()) === String(id), session.UserId);
    if (!alreadyAuthenticated) {
        // Official 4.8/4.10 routers expose this native form; user-card text can also be a profile link.
        await page.evaluate(async () => {
            const module = await Emby.importModule('./modules/approuter.js');
            (module.default || module).showServerLogin({ apiClient: ApiClient, loginType: 'manual' });
        });
        await page.locator('.txtUserName:visible').waitFor();
        await page.locator('.txtUserName:visible').fill(session.Username);
        await page.locator('.txtPassword:visible').fill(session.Password);
        await page.locator('.txtPassword:visible').locator('xpath=ancestor::form').locator('button[type="submit"]').click();
    } else if (!/#!\/home(?:\?|$)/.test(page.url())) {
        await page.goto(base + '/web/index.html#!/home');
    }
    await page.waitForFunction(() => globalThis.ApiClient && !!ApiClient.getCurrentUserId(), null, { timeout: 30000 });
    ensure(await page.evaluate(id => String(ApiClient.getCurrentUserId()) === String(id), session.UserId), 'Browser authenticated a different user');
    await page.waitForURL(/#!\/home(?:\?|$)/, { timeout: 30000 });
    await page.waitForLoadState('networkidle', { timeout: 15000 });
    ensure(await page.evaluate(async () => (await ApiClient.getCurrentUser()).Policy.IsAdministrator), 'Browser is not using an administrator');
    check('Real Emby browser login completed with the isolated administrator');

    stage = 'five-tabs';
    await openSettings();
    ensure(await page.locator('[data-tab]').count() === 5, 'Five settings tabs are not present');
    for (const tab of ['local', 'thunder', 'pool', 'cloud', 'proxy']) await select(tab);
    check('All five real settings tabs switch with only their matching panel visible');
    report.initialDefaultsWereFive = ['LocalMaxResults', 'ThunderMaxResults', 'PoolMaxResults'].every(key => original[key] === 5);
    ensure(report.initialDefaultsWereFive, 'Initial display limits are not the expected defaults');
    for (const key of ['LocalMaxResults', 'ThunderMaxResults', 'PoolMaxResults'])
        ensure(await page.locator(`[data-field="${key}"]`).inputValue() === '5', 'A default display limit differs from five');
    check('All three source display limits default to five in the actual page');

    stage = 'partial-save';
    await select('local');
    await page.locator('[data-field="LocalMaxResults"]').fill('7');
    changed = true;
    await save();
    let settings = await call('/SubtitleAssistant/settings');
    ensure(settings.LocalMaxResults === 7 && settings.ThunderMaxResults === 5 && settings.PoolMaxResults === 5, 'Saving one tab changed another tab');
    await select('thunder'); await page.locator('[data-field="ThunderMaxResults"]').fill('6');
    await select('pool'); await page.locator('[data-field="PoolMaxResults"]').fill('8');
    await save();
    settings = await call('/SubtitleAssistant/settings');
    ensure(settings.LocalMaxResults === 7 && settings.ThunderMaxResults === 6 && settings.PoolMaxResults === 8, 'Cross-tab edits were lost');
    ensure(settings.PoolUrl === original.PoolUrl && settings.AutoDownloadOnNewMedia === original.AutoDownloadOnNewMedia, 'Unrelated settings changed');
    check('Local-only save and cross-tab save preserve the other source settings');

    stage = 'secret-placeholders';
    const token = crypto.randomBytes(24).toString('hex'), password = crypto.randomBytes(24).toString('hex');
    sensitiveValues.push(token, password);
    await select('cloud'); await page.locator('[data-field="CloudApiToken"]').fill(token);
    await select('proxy'); await page.locator('[data-field="Proxy.Password"]').fill(password);
    await save();
    settings = await call('/SubtitleAssistant/settings');
    ensure(settings.HasCloudApiToken && settings.Proxy.HasPassword, 'Secret presence flags are missing');
    ensure(!Object.hasOwn(settings, 'CloudApiToken') && !Object.hasOwn(settings.Proxy, 'Password'), 'GET snapshot contains a secret field');
    ensure(!JSON.stringify(settings).includes(token) && !JSON.stringify(settings).includes(password), 'GET snapshot exposes a secret value');
    await page.reload({ waitUntil: 'domcontentloaded' }); await waitForSettings();
    for (const key of ['CloudApiToken', 'Proxy.Password']) {
        const field = page.locator(`[data-field="${key}"]`);
        ensure(await field.inputValue() === '', 'Saved secret is echoed into a field');
        ensure((await field.getAttribute('placeholder')).includes('已保存'), 'Saved secret placeholder is missing');
    }
    check('Token and proxy password remain blank after save/reload while presence placeholders survive');

    stage = 'native-task-button-wiring';
    let capturedUpdate = false;
    await page.route('**/ScheduledTasks/Running/*', route => {
        if (route.request().method() === 'POST') { capturedUpdate = true; return route.fulfill({ status: 204 }); }
        return route.continue();
    });
    await page.locator('[data-update]').click();
    await page.locator('[data-status]').filter({ hasText: '更新任务已启动' }).waitFor();
    ensure(capturedUpdate, 'Update button did not call the native task endpoint');
    check('Update button discovers the real native task and sends its POST (intercepted, no task started)');

    stage = 'restore'; await restore();
    await page.reload({ waitUntil: 'domcontentloaded' }); await waitForSettings();
    stage = 'screenshots';
    for (const tab of ['local', 'thunder', 'pool', 'cloud', 'proxy']) {
        await select(tab);
        const name = `${caseInfo[0]}-${tab}.png`;
        await page.locator('#SubtitleAssistantConfigurationPage .sa-content').screenshot({ path: output + '/' + name,
            mask: [page.locator('[data-secret]'), page.locator('[data-field="Proxy.Username"]')] });
        report.screenshots.push(name);
    }
    report.ok = true;
})().catch(async error => {
    report.ok = false; report.failedStage = stage;
    report.error = clean(error.message, 2200);
    if (page) {
        report.frameRoutes = page.frames().map(frame => { try { const url = new URL(frame.url()); return clean(url.pathname + url.hash.split('?')[0]); } catch { return 'about:blank'; } });
        try { report.diagnostic = await page.evaluate(() => ({ route: location.hash.split('?')[0],
            inputs: Array.from(document.querySelectorAll('input')).map(input => ({ id: input.id, className: input.className, type: input.type })),
            itemTypes: [...new Set(Array.from(document.querySelectorAll('[data-type]')).map(node => node.getAttribute('data-type')))],
            invalidFields: Array.from(document.querySelectorAll('[data-settings-form] input:invalid')).map(input => ({ field: input.getAttribute('data-field'), type: input.type, present: !!input.value })),
            status: document.querySelector('[data-status]')?.textContent || '' }));
            report.diagnostic.status = clean(report.diagnostic.status);
            if (stage === 'browser-login') report.diagnostic.visibleText = clean(await page.locator('body').innerText());
        } catch { }
    }
    try { await restore(); } catch { report.restored = false; }
    process.exitCode = 1;
}).finally(async () => {
    if (api) await api.dispose();
    if (context) await context.close();
    if (browser) await browser.close();
    fs.writeFileSync(output + '/report.json', JSON.stringify(report, null, 2));
    fs.writeFileSync(output + '/' + caseInfo[0] + '-report.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
});
