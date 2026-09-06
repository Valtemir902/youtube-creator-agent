const { chromium } = require('playwright');
const fs = require('fs');

const base = process.env.CREATOR_BASE_URL || 'https://creator.silvadigitaltech.com';
const authHost = process.env.AUTH_HOST || 'auth.silvadigitaltech.com';
const out = process.env.BROWSER_ARTIFACT_DIR || 'artifacts/screenshots';
fs.mkdirSync(out, { recursive: true });

const failures = [];
const observations = [];
const consoleErrors = [];
const check = (ok, message) => {
  observations.push({ ok: !!ok, message });
  if (!ok) failures.push(message);
};
const observe = (ok, message) => observations.push({ ok: !!ok, message });
const scenario = async (name, fn) => {
  try { await fn(); } catch (e) { failures.push(`${name}: ${e.stack || e.message}`); }
};
const shot = async (page, name) => page.screenshot({ path: `${out}/${name}.png`, fullPage: true });

async function waitForStablePublic(request) {
  const urls = [
    `${base}/health`,
    `${base}/login`,
    `https://${authHost}/realms/yca/.well-known/openid-configuration`,
  ];
  for (const url of urls) {
    let good = 0;
    for (let i = 1; i <= 30; i++) {
      try {
        const r = await request.get(url, { timeout: 10000 });
        if (r.status() >= 200 && r.status() < 300) good += 1; else good = 0;
        if (good >= 2) break;
      } catch { good = 0; }
      await new Promise(r => setTimeout(r, 2000));
    }
    check(good >= 2, `Public surface did not become stable: ${url}`);
  }
}

async function waitCreatorReady(page) {
  await page.waitForFunction(() => {
    const b = document.querySelector('#continueBtn');
    const r = document.querySelector('#recoverBtn');
    return b && r && !b.disabled && !r.disabled;
  }, null, { timeout: 15000 });
}

async function checkKeycloakStyle(page, label) {
  const sheets = await page.locator('link[rel="stylesheet"]').count();
  const font = await page.evaluate(() => getComputedStyle(document.body).fontFamily || '');
  check(sheets >= 1, `${label} has no stylesheet loaded`);
  check(!/^\s*["']?(times new roman|times|serif)/i.test(font), `${label} appears unstyled: ${font}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'pt-BR' });
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') {
      const loc = msg.location();
      consoleErrors.push(`console@${loc.url || page.url()}:${loc.lineNumber || 0}: ${msg.text()}`);
    }
  });
  page.on('pageerror', err => consoleErrors.push(`pageerror@${page.url()}: ${err.stack || err.message}`));

  await waitForStablePublic(context.request);

  await scenario('Creator login', async () => {
    const r = await page.goto(`${base}/login`, { waitUntil: 'networkidle', timeout: 30000 });
    check(r?.status() === 200, `GET /login expected 200, got ${r?.status()}`);
    await waitCreatorReady(page);
    await shot(page, '01-creator-login');
    const body = (await page.locator('body').innerText()).toLowerCase();
    check(!body.includes('turnstile'), 'Creator login still exposes Turnstile text');
  });

  await scenario('Creator registration copy', async () => {
    await page.getByRole('button', { name: 'Criar conta' }).click();
    await shot(page, '02-creator-register-tab');
    const body = (await page.locator('body').innerText()).toLowerCase();
    check(body.includes('confirme o endereço') && body.includes('defina sua senha'), 'Registration stages are not explained clearly');
  });

  await scenario('Keycloak registration', async () => {
    await Promise.all([
      page.waitForURL(url => url.hostname === authHost, { timeout: 20000 }),
      page.getByRole('button', { name: 'Criar minha conta' }).click(),
    ]);
    await page.waitForLoadState('networkidle');
    await shot(page, '03-keycloak-register');
    await checkKeycloakStyle(page, 'Keycloak registration');
    check(await page.locator('input[type="email"],input[name="email"],input[name="username"]').count() >= 1, 'Registration has no e-mail field');
    const passwords = await page.locator('input[type="password"]').count();
    observe(passwords >= 2, passwords >= 2 ? 'Registration defines password immediately' : 'Registration uses staged verify-email then password flow');
    const captcha = await page.locator('iframe[src*="recaptcha" i],iframe[src*="turnstile" i],.g-recaptcha,.cf-turnstile').count();
    observe(captcha >= 1, captcha >= 1 ? 'Visible CAPTCHA detected' : 'No visible CAPTCHA on Keycloak registration');
  });

  await scenario('Keycloak login', async () => {
    await page.goto(`${base}/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await waitCreatorReady(page);
    await Promise.all([
      page.waitForURL(url => url.hostname === authHost, { timeout: 20000 }),
      page.getByRole('button', { name: 'Continuar para entrar' }).click(),
    ]);
    await page.waitForLoadState('networkidle');
    await shot(page, '04-keycloak-login');
    await checkKeycloakStyle(page, 'Keycloak login');
    check(await page.locator('input[type="password"]').count() >= 1, 'Keycloak login has no password field');
    check(await page.locator('input[type="email"],input[name="username"],input[id*="username" i]').count() >= 1, 'Keycloak login has no e-mail/username field');
  });

  await scenario('Keycloak recovery', async () => {
    await page.goto(`${base}/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await waitCreatorReady(page);
    await Promise.all([
      page.waitForURL(url => url.hostname === authHost, { timeout: 20000 }),
      page.getByRole('button', { name: 'Esqueci minha senha' }).click(),
    ]);
    await page.waitForLoadState('networkidle');
    await shot(page, '05-keycloak-recovery');
    await checkKeycloakStyle(page, 'Keycloak recovery');
    check(await page.locator('input[type="email"],input[name="username"],input[id*="username" i]').count() >= 1, 'Recovery has no e-mail/username field');
  });

  await scenario('Anonymous route protection and auth API', async () => {
    for (const path of ['/dashboard', '/onboarding']) {
      const r = await context.request.get(`${base}${path}`, { maxRedirects: 0 });
      check([302, 303, 307, 308].includes(r.status()), `${path} should redirect anonymous user, got ${r.status()}`);
    }
    const cfg = await context.request.get(`${base}/api/auth/config`);
    check(cfg.status() === 200, `/api/auth/config expected 200, got ${cfg.status()}`);
    if (cfg.status() === 200) check((await cfg.json()).oidc_ready === true, 'OIDC is not ready');
    const begin = await context.request.post(`${base}/api/auth/begin`, { data: { mode: 'login', next: '/dashboard' } });
    check(begin.status() === 200, `/api/auth/begin expected 200, got ${begin.status()}`);
  });

  check(consoleErrors.length === 0, `Browser console/page errors: ${consoleErrors.join(' | ')}`);
  fs.writeFileSync('artifacts/browser-audit.json', JSON.stringify({ failures, observations, consoleErrors }, null, 2));
  fs.writeFileSync('artifacts/browser-console-errors.txt', consoleErrors.join('\n'));
  await browser.close();

  if (failures.length) {
    console.error(`Browser audit found ${failures.length} issue(s):\n- ${failures.join('\n- ')}`);
    process.exit(1);
  }
  console.log('Live browser audit passed.');
})().catch(err => {
  console.error(err.stack || err);
  process.exit(1);
});
