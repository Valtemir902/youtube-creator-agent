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
  const legacy = '<article class="card full"><h3>Inteligência artificial externa opcional</h3>';
  if (!html.includes('id="aiKeyVault"') && html.includes(legacy)) {
    html = html.replace(
      legacy,
      '<article class="card full" id="aiKeyVault"></article>\n          <article class="card full legacy-ai-config" hidden aria-hidden="true"><h3>Inteligência artificial externa opcional</h3>',
    );
  }

  const eliteCss = pyRaw('src/elite_v2_ui.py', 'V2_CSS');
  const eliteJs = pyRaw('src/elite_v2_ui.py', 'V2_JS');
  const reconnect = pyRaw('src/creator_service/dashboard_runtime_hotfix.py', '_RECONNECT_JS');
  const vaultCss = pyRaw('src/creator_service/ai_vault_ui.py', '_CSS');
  const vaultScript = pyRaw('src/creator_service/ai_vault_ui.py', '_SCRIPT');
  const humanCss = pyRaw('src/creator_service/dashboard_human_results_ui.py', '_CSS');
  const humanScript = pyRaw('src/creator_service/dashboard_human_results_ui.py', '_SCRIPT');

  html = html.replace('</head>', `${vaultCss}\n${humanCss}\n<style data-yca-elite-v2>${eliteCss}</style></head>`);
  html = html.replace('</body>', `${vaultScript}\n${humanScript}\n<script data-yca-cloud-elite-v2>${eliteJs}\n${reconnect}</script></body>`);
  return html;
}

const healthy = {
  identity: { id:'UC_TEST', title:'Canal de Teste', description:'Descrição realista de teste do canal.', country:'BR', default_language:'pt-BR', subscribers:1240, views:58200, videos:38 },
  profile: { subscribers:1240, total_views:58200, total_analytics_views:7420, video_count:38, channel_title:'Canal de Teste', country:'BR', default_language:'pt-BR', search_share:0.18, shorts_share_of_recent_views:0.33, long_share_of_recent_views:0.67, topic_terms:['agro','campo','trilha'] },
};

const auditPayload = {
  period_days: 28,
  channel: {
    channel_title: 'Canal de Teste', subscribers: 1240, total_views: 58200, video_count: 38,
    search_views: 930, engagement_rate_28d: 0.047,
    top_videos: [{ video_id:'top1', title:'Vídeo forte', views_28d:3200, engagement_rate_28d:0.061, format:'long' }],
    weak_videos: [{ video_id:'weak1', title:'Vídeo para revisar', views_28d:41, engagement_rate_28d:0.009, format:'short' }],
  },
  evidence: {
    strengths: ['Retenção consistente nos vídeos longos'],
    weaknesses: ['Baixa participação de busca em conteúdos recentes'],
    opportunities: [{ keyword:'trilha rural', demand_index:82, competition_label:'média', rationale:'Demanda recente acima da média.' }],
    recommendations: ['Revisar títulos dos vídeos com baixa descoberta por busca.'],
  },
};

const keysPayload = {
  auto_rotate: true,
  keys: [
    { id:'KEY1', label:'Gemini principal', masked:'AIza••••••A1', status:'ok', active:true, enabled:true, preferred_model:'gemini-3.5-flash', last_model:'gemini-3.5-flash', last_error:'' },
    { id:'KEY2', label:'Gemini reserva', masked:'AIza••••••B2', status:'warning', active:false, enabled:true, preferred_model:'gemini-3.5-flash-lite', last_model:'gemini-3.5-flash-lite', last_error:'Quota temporariamente atingida; aguardando janela de recuperação.' },
  ],
};

async function fulfillJson(route, payload, status=200) {
  await route.fulfill({ status, contentType:'application/json', body:JSON.stringify(payload) });
}

async function installRoutes(page, revoked=false) {
  await page.route('https://cloud-v2.test/dashboard', route => route.fulfill({ status:200, contentType:'text/html; charset=utf-8', body:cloudHtml(), headers:{'X-YCA-Dashboard-UI':'elite-v2-cloud','X-YCA-Dashboard-UX':'human-results-key-vault'} }));
  await page.route('https://cloud-v2.test/api/**', async route => {
    const u = new URL(route.request().url());
    const method = route.request().method();
    if (u.pathname === '/api/dashboard/status') return fulfillJson(route, { youtube_connected:true, chatgpt_native_ready:true, external_ai_configured:true, ai_provider:'gemini', ai_model:'gemini-3.5-flash' });
    if (u.pathname === '/api/dashboard/channel/identity') {
      if (revoked) return fulfillJson(route, { detail:'A autorização do Google expirou ou foi revogada. Reconecte o YouTube para restaurar as leituras do canal.', code:'youtube_reconnect_required', reconnect_required:true, youtube_write_performed:false }, 409);
      return fulfillJson(route, healthy.identity);
    }
    if (u.pathname === '/api/dashboard/channel') {
      if (revoked) return fulfillJson(route, { detail:'A autorização do Google expirou ou foi revogada. Reconecte o YouTube para restaurar as leituras do canal.', code:'youtube_reconnect_required', reconnect_required:true }, 409);
      return fulfillJson(route, healthy.profile);
    }
    if (u.pathname === '/api/dashboard/audit') return fulfillJson(route, auditPayload);
    if (u.pathname === '/api/dashboard/channels/connect' && method === 'POST') return fulfillJson(route, { authorization_url:'https://accounts.google.test/oauth' });
    if (u.pathname === '/api/dashboard/channels') return fulfillJson(route, { channels:[{ id:'UC_TEST', title:'Canal de Teste', active:true }] });
    if (u.pathname === '/api/dashboard/playlists') return fulfillJson(route, { playlists:[{ id:'PL1', title:'Playlist Editorial', count:7, privacy_status:'public', thumbnail:'' }] });
    if (u.pathname === '/api/dashboard/capabilities') return fulfillJson(route, {});
    if (u.pathname === '/api/dashboard/live') return fulfillJson(route, { broadcasts:[] });
    if (u.pathname === '/api/dashboard/videos') return fulfillJson(route, { videos:[{ id:'vid1', title:'Vídeo de teste', views:3200, likes:180, comments:21, privacy_status:'public', thumbnail:'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg' }] });
    if (u.pathname === '/api/ai/keys' && method === 'GET') return fulfillJson(route, keysPayload);
    if (/^\/api\/ai\/keys\/[^/]+\/test$/.test(u.pathname) && method === 'POST') {
      const keyId = decodeURIComponent(u.pathname.split('/')[4]);
      const models = keyId === 'KEY1' ? ['gemini-3.5-flash','gemini-3.5-flash-lite'] : ['gemini-3.5-flash-lite'];
      return fulfillJson(route, { ok:true, models, count:models.length, tested_model:'', model_test_ok:null, model_test_error:'' });
    }
    if (/^\/api\/ai\/keys\/[^/]+$/.test(u.pathname) && method === 'PATCH') return fulfillJson(route, { ok:true });
    if (u.pathname === '/api/ai/rotation' && method === 'PUT') return fulfillJson(route, { ok:true });
    if (u.pathname === '/api/ai/config' && method === 'PUT') return fulfillJson(route, { ok:true });
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

async function verifyAuditAndVault(browser) {
  const context = await browser.newContext({ viewport:{width:1440,height:1000}, locale:'pt-BR' });
  const page = await context.newPage();
  const errors=[];
  page.on('pageerror', e=>errors.push(e.message));
  page.on('console', m=>{ if(m.type()==='error') errors.push(m.text()); });
  await installRoutes(page, false);
  await page.goto('https://cloud-v2.test/dashboard', { waitUntil:'networkidle' });
  await page.waitForTimeout(700);

  await page.locator('[data-tab="audit"]').click();
  await page.locator('#runAudit').click();
  await page.locator('#auditRaw.human-result').waitFor({state:'visible'});
  if (await page.locator('#auditRaw > .human-summary').count() !== 1) throw new Error('Audit did not render human KPI summary');
  if (await page.locator('#auditRaw details.human-technical').count() !== 1) throw new Error('Audit lost optional technical JSON details');
  if ((await page.locator('#auditRaw').innerText()).includes('"channel_title"')) throw new Error('Raw JSON is still the primary audit presentation');
  await page.screenshot({ path:`${out}/cloud-elite-v2-audit-human.png`, fullPage:true });

  await page.locator('[data-tab="settings"]').click();
  await page.locator('#aiKeyVault .vault-manager-v2').waitFor({state:'visible'});
  if (await page.locator('.legacy-ai-config:visible').count()) throw new Error('Legacy single-key configuration is still visible');
  if (await page.locator('#aiKeyList .vault-key-row').count() !== 2) throw new Error('Advanced key vault did not render saved keys');
  if (!(await page.locator('#aiKeyList').innerText()).includes('Quota temporariamente atingida')) throw new Error('Key health/quota warning is not visible');

  await page.locator('.vault-key-check[data-key-id="KEY1"]').check();
  await page.locator('#vaultModel').click();
  await page.locator('#vaultLoadModels').click();
  await page.waitForFunction(() => document.querySelectorAll('#vaultModelSelect option').length === 2);
  const options = await page.locator('#vaultModelSelect option').allTextContents();
  if (!options.includes('gemini-3.5-flash') || options.includes('gemini-2.5-flash')) throw new Error(`Per-key model discovery ignored key-specific capability list: ${options.join(', ')}`);
  await page.screenshot({ path:`${out}/cloud-elite-v2-key-vault.png`, fullPage:true });

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
  await verifyAuditAndVault(browser);
  await verifyRevoked(browser);
  await browser.close();
  const files = fs.readdirSync(out).filter(x=>x.endsWith('.png'));
  if (files.length !== 5) throw new Error(`Expected 5 screenshots, got ${files.length}`);
  fs.writeFileSync(`${out}/result.json`, JSON.stringify({ok:true,screenshots:files,human_audit_verified:true,key_vault_verified:true,per_key_model_discovery_verified:true,reconnect_state_verified:true,http500_exposed:false,youtube_write_actions_executed:false},null,2));
  console.log('Cloud Elite V2 visual smoke passed with human results and per-key model vault.');
})().catch(err=>{console.error(err.stack||err);process.exit(1)});
