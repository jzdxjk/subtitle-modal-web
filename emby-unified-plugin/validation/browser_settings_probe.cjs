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
    // Emby 4.8's router can leave the Home view mounted above the legacy
    // configuration page, where its item cards intercept pointer events. A real
    // administrator does not see that stale view; dismiss it so clicks reach the
    // settings page. Newer hosts never mount this view on the settings route.
    await page.evaluate(() => {
        for (const node of document.querySelectorAll('.view-home-home')) {
            if (getComputedStyle(node).display !== 'none') {
                node.style.display = 'none';
                node.setAttribute('aria-hidden', 'true');
            }
        }
    });
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

async function save(expectedStatus = '设置已保存') {
    ensure(await page.locator('[data-settings-form]').evaluate(form => form.checkValidity()), 'Native form validation blocked settings submission');
    const response = page.waitForResponse(value => new URL(value.url()).pathname.endsWith('/SubtitleAssistant/settings') && value.request().method() === 'POST');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    const result = await (await response).json();
    ensure(result.Ok, 'Settings save failed');
    await page.locator('[data-status]').filter({ hasText: expectedStatus }).waitFor();
}

async function orderKeys() {
    return page.locator('[data-provider-order] .sa-order-row').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-provider-key')));
}

async function mouseDragOrder(fromIndex, toIndex) {
    const rows = page.locator('[data-provider-order] .sa-order-row');
    await page.locator('[data-provider-order]').evaluate(element => element.scrollIntoView({ block: 'center' }));
    await page.waitForTimeout(100);
    const from = await rows.nth(fromIndex).boundingBox(), to = await rows.nth(toIndex).boundingBox();
    ensure(from && to, 'Provider order rows have no layout box');
    ensure(from.y > 0 && to.y > 0, 'Provider order rows are outside the viewport');
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(to.x + to.width / 2, to.y + to.height * 0.4, { steps: 8 });
    await page.mouse.up();
}

async function touchDragOrder(fromIndex, toIndex) {
    const rows = page.locator('[data-provider-order] .sa-order-row');
    await page.locator('[data-provider-order]').evaluate(element => element.scrollIntoView({ block: 'center' }));
    await page.waitForTimeout(100);
    const from = await rows.nth(fromIndex).boundingBox(), to = await rows.nth(toIndex).boundingBox();
    ensure(from && to, 'Provider order rows have no layout box for touch');
    ensure(from.y > 0 && to.y > 0, 'Provider order rows are outside the touch viewport');
    await page.evaluate(() => {
        window.__saOrderEvents = [];
        const point = event => {
            const touch = (event.touches && event.touches[0]) || (event.changedTouches && event.changedTouches[0]);
            const x = touch ? touch.clientX : event.clientX;
            const y = touch ? touch.clientY : event.clientY;
            return Number.isFinite(x) && Number.isFinite(y) ? { x: Math.round(x), y: Math.round(y) } : null;
        };
        for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'touchstart', 'touchmove', 'touchend', 'touchcancel']) {
            document.addEventListener(type, event => {
                if (!String(event.target?.className || '').includes('sa-order-row')) return;
                const box = event.target.getBoundingClientRect();
                window.__saOrderEvents.push({ type, pointerType: event.pointerType || '', target: event.target.getAttribute('data-provider-key'),
                    point: point(event), targetBox: { x: Math.round(box.x), y: Math.round(box.y), width: Math.round(box.width), height: Math.round(box.height) },
                    dragging: !!document.querySelector('.sa-order-row.sa-dragging'),
                    drop: document.querySelector('.sa-order-row.sa-drop-target')?.getAttribute('data-provider-key') || null });
            }, true);
        }
    });
    const cdp = await context.newCDPSession(page);
    await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
    const sx = from.x + from.width / 2, sy = from.y + from.height / 2;
    const ex = to.x + to.width / 2, ey = to.y + to.height * 0.4;
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: sx, y: sy, id: 1 }] });
    for (let step = 1; step <= 8; step++) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove',
            touchPoints: [{ x: sx + (ex - sx) * step / 8, y: sy + (ey - sy) * step / 8, id: 1 }] });
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await cdp.detach();
    await page.waitForTimeout(150);
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
    for (const field of ['SimplifiedChineseLanguage', 'TraditionalChineseLanguage', 'UpdateManifestUrl'])
        ensure(await page.locator(`[data-field="${field}"]`).count() === 0, 'A fixed or hidden settings field is still visible');
    ensure(await page.locator('[data-proxy-test-url]').count() === 0, 'The custom proxy test URL field is still visible');
    check('Fixed language markers, manifest URL and custom test URL are absent from the page');

    stage = 'partial-save';
    await select('local');
    await page.locator('[data-field="LocalMaxResults"]').fill('7');
    changed = true;
    ensure(await page.locator('[data-unsaved]').isVisible(), 'Unsaved indicator was not shown');
    await save();
    ensure(await page.locator('[data-unsaved]').isHidden(), 'Unsaved indicator survived a successful save');
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

    stage = 'source-order';
    await select('proxy');
    let order = await orderKeys();
    ensure(JSON.stringify(order) === JSON.stringify(['Pool', 'Local', 'Thunder']), 'Default source order is not Pool, Local, Thunder');
    check('Global settings renders three source rows in the default Pool, Local, Thunder order');
    await mouseDragOrder(0, 2);
    order = await orderKeys();
    ensure(JSON.stringify(order) === JSON.stringify(['Local', 'Thunder', 'Pool']), 'Mouse drag did not move the first source to the end');
    ensure(await page.locator('[data-unsaved]').isVisible(), 'Reordering did not mark settings as unsaved');
    await save('重启 Emby 后生效');
    settings = await call('/SubtitleAssistant/settings');
    ensure(JSON.stringify(settings.ProviderDisplayOrder) === JSON.stringify(['Local', 'Thunder', 'Pool']), 'Saved source order was not persisted');
    ensure((await page.locator('[data-status]').textContent()).includes('重启 Emby'), 'Order save did not warn that Emby must restart');
    check('Mouse drag reorders sources, marks the form dirty, persists ProviderDisplayOrder and warns about the restart');
    await touchDragOrder(2, 0);
    report.touchOrderEvents = await page.evaluate(() => window.__saOrderEvents || []);
    order = await orderKeys();
    ensure(JSON.stringify(order) === JSON.stringify(['Pool', 'Local', 'Thunder']), 'Touch drag did not restore the default source order');
    await save('重启 Emby 后生效');
    settings = await call('/SubtitleAssistant/settings');
    ensure(JSON.stringify(settings.ProviderDisplayOrder) === JSON.stringify(['Pool', 'Local', 'Thunder']), 'Touch reorder was not persisted');
    check('Touch drag reorders sources and persists the restored default order');

    stage = 'save-button';
    const saveButton = page.getByRole('button', { name: '保存', exact: true });
    const formBox = await page.locator('[data-settings-form]').boundingBox();
    const buttonBox = await saveButton.boundingBox();
    ensure(formBox && buttonBox && buttonBox.width >= formBox.width - 2, 'Save button is not full width inside the settings form');
    ensure(Math.abs(buttonBox.x - formBox.x) <= 2
        && Math.abs((buttonBox.x + buttonBox.width) - (formBox.x + formBox.width)) <= 2,
        'Save button does not align with the settings form edges');
    const positioned = await saveButton.evaluate(element => {
        const values = [];
        for (let node = element; node; node = node.parentElement) {
            const position = getComputedStyle(node).position;
            if (position === 'sticky' || position === 'fixed') values.push(position);
        }
        return values;
    });
    ensure(positioned.length === 0, 'Save button still sits inside a sticky or fixed bar');
    ensure(await page.locator('.sa-actionbar, .sa-save').count() === 0, 'Legacy custom save bar is still rendered');
    check('Save button is a native in-flow full-width emby-button aligned with the form edges');

    stage = 'proxy-inline-result';
    let proxyPayloadOk = false;
    await page.route(url => url.pathname.endsWith('/SubtitleAssistant/proxy/test'), route => {
        const body = route.request().postDataJSON();
        proxyPayloadOk = !!body && body.Purpose === 'Thunder' && !Object.hasOwn(body, 'Url');
        return route.fulfill({ status: 200, contentType: 'application/json',
            body: JSON.stringify({ Ok: true, LatencyMs: 123, Route: 'Proxy' }) });
    });
    await select('proxy');
    await page.locator('[data-proxy-purpose]').selectOption('Thunder');
    await page.locator('[data-proxy-test]').click();
    await page.locator('[data-proxy-result]').filter({ hasText: '延迟 123 ms' }).waitFor();
    ensure(proxyPayloadOk, 'Proxy test did not send a purpose-only payload');
    ensure((await page.locator('[data-proxy-result]').textContent()).includes('代理'), 'Proxy route label is missing');
    check('Proxy test renders route and latency inline beside the button');

    stage = 'mobile-layout';
    await page.setViewportSize({ width: 390, height: 844 });
    await select('proxy');
    const mobileButton = await saveButton.boundingBox();
    const mobileForm = await page.locator('[data-settings-form]').boundingBox();
    ensure(mobileButton && mobileForm && mobileButton.width >= mobileForm.width - 2, 'Mobile save button is not full width');
    ensure(await page.locator('.sa-content').evaluate(node => node.scrollWidth <= node.clientWidth + 1), 'Settings content overflows horizontally on mobile');
    const mobileRows = await orderKeys();
    ensure(JSON.stringify(mobileRows) === JSON.stringify(['Pool', 'Local', 'Thunder']), 'Mobile source order control lost its rows');
    check('Mobile viewport keeps the save button full width, all source rows and no horizontal overflow');
    await page.setViewportSize({ width: 1440, height: 1100 });

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
