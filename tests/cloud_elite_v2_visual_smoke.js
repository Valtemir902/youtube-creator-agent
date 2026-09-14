const { chromium } = require('playwright');
const fs = require('fs');

const out = process.env.BROWSER_ARTIFACT_DIR || 'artifacts/cloud-web-v2';
fs.mkdirSync(out, { recursive: true });

function pyRaw(path, name) {
  const source = fs.readFileSync(path, 'utf8');
  const re = new RegExp(`${name}\\s*=\\s*r'''([\\s\\S]*?)'''`);
  const match = source.match(re);
  if (!match) throw new Error(`Could not extract ${name} from ${path}`);
  return match[1];
}

function cloudHtml() {
  let html = fs.readFileSync('src/creator_service/web/dashboard.html', 'utf8');
  const css = pyRaw('src/elite_v2_ui.py', 'V2_CSS');
  const js = pyRaw('src/elite_v2_ui.py', 'V2_JS');
  const reconnect = pyRaw('src/creator_service/dashboard_runtime_hotfix.py', '_RECONNECT_JS');
  html = html.replace('</head>', `<style data-yca-elite-v2>${css}</style></head>`);
  html = html.replace('</body>', `<script data-yca-cloud-elite-v2>${js}\n${reconnect}</script></body>`);
  return html;
}

const healthy = {
  identity: { id:'UC_TEST', title:'Canal de Teste', description:'Descrição realista de teste do canal.', country:'BR', default_language:'pt-BR', subscribers:1240, views:58200, videos:38 },
  profile: { subscribers:1240, total_views:58200, total_analytics_views:7420, video_count:38, channel_title:'Canal de Teste', country:'BR', default_language:'pt-BR', search_share:0.18, shorts_share_of_recent_views:0.33, long_share_of_recent_views:0.67, topic_terms:['agro','campo','trilha'] },
};

async function fulfillJson(route, payload, status=200) {
  await route.fulfill({ status, contentType:'application/json', body:JSON.stringify(payload) });
}

async function installRoutes(page, revoked=false) {
  await page.route('https://cloud-v2.test/dashboard', route => route.fulfill({ status:200, contentType:'text/html; charset=utf-8', body:cloudHtml(), headers:{'X-YCA-Dashboard-UI':'elite-v2-cloud'} }));
  await page.route('https://cloud-v2.test/api/**', async route => {
    const u = new URL(route.request().url());
    if (u.pathname === '/api/dashboard/status') return fulfillJson(route, { youtube_connected:true, chatgpt_native_ready:true, external_ai_configured:false });
    if (u.pathname === '/api/dashboard/channel/identity') {
      if (revoked) return fulfillJson(route, { detail:'A autorização do Google expirou ou foi revogada. Reconecte o YouTube para restaurar as leituras do canal.', code:'youtube_reconnect_required', reconnect_required:true, youtube_write_performed:false }, 409);
      return fulfillJson(route, healthy.identity);
    }
    if (u.pathname === '/api/dashboard/channel') {
      if (revoked) return fulfillJson(route, { detail:'A autorização do Google expirou ou foi revogada. Reconecte o YouTube para restaurar as leituras do canal.', code:'youtube_reconnect_required', reconnect_required:true }, 409);
      return fulfillJson(route, healthy.profile);
    }
    if (u.pathname === '/api/dashboard/channels/connect' && route.request().method() === 'POST') return fulfillJson(route, { authorization_url:'https://accounts.google.test/oauth' });
    if (u.pathname === '/api/dashboard/channels') return fulfillJson(route, { channels:[{ id:'UC_TEST', title:'Canal de Teste', active:true }] });
    if (u.pathname === '/api/dashboard/playlists') return fulfillJson(route, { playlists:[{ id:'PL1', title:'Playlist Editorial', count:7, privacy_status:'public', thumbnail:'' }] });
    if (u.pathname === '/api/dashboard/capabilities') return fulfillJson(route, {});
    if (u.pathname === '/api/dashboard/live') return fulfillJson(route, { broadcasts:[] });
    if (u.pathname === '/api/dashboard/videos') return fulfillJson(route, { videos:[{ id:'vid1', title:'Vídeo de teste', views:3200, likes:180, comments:21, privacy_status:'public', thumbnail:'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg' }] });
    return fulfillJson(route, {});
  });
}

async function verifyHealthy(browser, viewport, name) {
  const context = await browser.newContext({ viewport, locale:'pt-BR' });
  const page = await context.newPage();
  const errors=[];
  page.on('pageerror', e=>errors.push(e.message));
  page.on('console', m=>{ if(m.type()==='error') errors.push(m.text()); });
  await installRoutes(page, false);
  await page.goto('https://cloud-v2.test/dashboard', { waitUntil:'networkidle' });
  await page.waitForTimeout(900);
  if (await page.locator('html[data-ui-version="elite-v2"]').count() !== 1) throw new Error('Elite V2 root marker missing');
  if (await page.locator('.v2-command-grid').count() !== 1) throw new Error('Elite V2 command center missing');
  if (await page.locator('[data-yca-google-reconnect]').count() !== 0) throw new Error('Reconnect banner shown for healthy credential');
  const metric = await page.locator('#kpiSubs').innerText();
  if (!metric || metric === '—') throw new Error('Healthy cloud dashboard did not render channel KPIs');
  await page.screenshot({ path:`${out}/${name}`, fullPage:true });
  if (errors.length) throw new Error(`Browser errors: ${errors.join(' | ')}`);
  await context.close();
}

async function verifyRevoked(browser) {
  const context = await browser.newContext({ viewport:{width:430,height:900}, locale:'pt-BR' });
  const page = await context.newPage();
  const errors=[];
  const expected409=[];
  page.on('pageerror', e=>errors.push(e.message));
  page.on('console', m=>{
    if(m.type()!=='error') return;
    const text=m.text();
    if(text.includes('409 (Conflict)')) expected409.push(text); else errors.push(text);
  });
  await installRoutes(page, true);
  await page.goto('https://cloud-v2.test/dashboard', { waitUntil:'networkidle' });
  await page.waitForTimeout(900);
  const banner = page.locator('[data-yca-google-reconnect]');
  if (await banner.count() !== 1) throw new Error('Revoked credential did not produce reconnect banner');
  const text = await banner.innerText();
  if (!text.includes('Reconecte o YouTube') || !text.includes('Reconectar agora')) throw new Error('Reconnect guidance is incomplete');
  if ((await page.locator('body').innerText()).includes('Erro HTTP 500')) throw new Error('Raw HTTP 500 leaked into recoverable revoked-token state');
  if (!expected409.length) throw new Error('Revoked-token scenario did not exercise the expected HTTP 409 contract');
  await page.screenshot({ path:`${out}/cloud-elite-v2-reconnect-mobile.png`, fullPage:true });
  if (errors.length) throw new Error(`Unexpected browser errors: ${errors.join(' | ')}`);
  await context.close();
}

(async()=>{
  const browser = await chromium.launch({headless:true});
  await verifyHealthy(browser,{width:1440,height:900},'cloud-elite-v2-desktop.png');
  await verifyHealthy(browser,{width:430,height:900},'cloud-elite-v2-mobile.png');
  await verifyRevoked(browser);
  await browser.close();
  const files = fs.readdirSync(out).filter(x=>x.endsWith('.png'));
  if (files.length !== 3) throw new Error(`Expected 3 screenshots, got ${files.length}`);
  fs.writeFileSync(`${out}/result.json`, JSON.stringify({ok:true,screenshots:files,reconnect_state_verified:true,http500_exposed:false,youtube_write_actions_executed:false},null,2));
  console.log('Cloud Elite V2 visual smoke passed.');
})().catch(err=>{console.error(err.stack||err);process.exit(1)});
