const { chromium } = require('playwright');
const fs = require('fs');

const out = process.env.BROWSER_ARTIFACT_DIR || 'artifacts/screenshots';
fs.mkdirSync(out, { recursive: true });

function injectedDashboardHtml() {
  let html = fs.readFileSync('src/creator_service/web/dashboard.html', 'utf8');
  const enhancer = fs.readFileSync('src/creator_service/dashboard_pro_ui.py', 'utf8');
  const css = enhancer.match(/_CSS = r'''([\s\S]*?)'''/);
  const script = enhancer.match(/_SCRIPT = r'''([\s\S]*?)'''/);
  if (!css || !script) throw new Error('Could not extract dashboard professional enhancement assets.');
  html = html.replace('</head>', `${css[1]}\n</head>`);
  html = html.replace('</body>', `${script[1]}\n</body>`);
  html = html.replace("document.getElementById('home')", "document.getElementById('overview')");
  return html;
}

const channel = {
  subscribers: 82,
  total_analytics_views: 59,
  total_views: 11723,
  video_count: 52,
  channel_title: 'Logan Western',
  search_share: 0.0169,
};
const identity = {
  id: 'UCePN99heaPy2YfUJPEMwbGA',
  title: 'Logan Western',
  description: "Welcome to LOGAN WESTERN. This ain't your granddaddy's country. This is the home for forgotten tales and cursed anthems of the American frontier.\n\nHere, the grit of Outlaw Country meets the shadows of Western Gothic. We delve into the heart of Dark Americana, crafting tragic country stories and raw country ballads that echo from forgotten graves.",
  country: 'AU',
  default_language: 'en',
  subscribers: 82,
  views: 11723,
  videos: 52,
};
const videos = { videos: [
  { id:'v1', title:'The Cursed Fiddle of Appalachia', views:1530, likes:71, comments:8, privacy_status:'public' },
  { id:'v2', title:'Dark Country Ballad | Forgotten Graves', views:1120, likes:58, comments:5, privacy_status:'public' },
  { id:'v3', title:'Outlaw Country Story | No Way Home', views:870, likes:44, comments:4, privacy_status:'public' },
  { id:'v4', title:'Western Gothic Music | The Last Ride', views:690, likes:39, comments:3, privacy_status:'public' },
  { id:'v5', title:'Dark Americana | Devil at the Door', views:510, likes:31, comments:2, privacy_status:'public' },
  { id:'v6', title:'Southern Gothic Acoustic | Cold River', views:330, likes:21, comments:2, privacy_status:'public' },
]};

async function json(route, value, status=200) {
  await route.fulfill({ status, contentType:'application/json', body:JSON.stringify(value) });
}

(async()=>{
  const browser = await chromium.launch({ headless:true });
  const context = await browser.newContext({ viewport:{ width:390, height:844 }, locale:'pt-BR' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });

  await page.route('https://visual.test/dashboard', async route => {
    await route.fulfill({ status:200, contentType:'text/html; charset=utf-8', body:injectedDashboardHtml() });
  });
  await page.route('https://visual.test/api/**', async route => {
    const u = new URL(route.request().url());
    if (u.pathname === '/api/dashboard/channel') return json(route, channel);
    if (u.pathname === '/api/dashboard/channel/identity') return json(route, identity);
    if (u.pathname === '/api/dashboard/videos') return json(route, videos);
    if (u.pathname === '/api/dashboard/status') return json(route, { youtube_connected:true, external_ai_configured:true, ai_provider:'gemini', ai_model:'gemini-2.5-flash' });
    if (u.pathname === '/api/dashboard/channels') return json(route, { channels:[{ channel_id:identity.id, title:identity.title, active:true }] });
    if (u.pathname === '/api/dashboard/playlists') return json(route, { playlists:[] });
    if (u.pathname === '/api/dashboard/capabilities') return json(route, {});
    if (u.pathname === '/api/dashboard/live') return json(route, { broadcasts:[] });
    if (u.pathname === '/api/dashboard/publications') return json(route, { publications:[] });
    if (u.pathname === '/api/dashboard/upload/sessions') return json(route, { sessions:[] });
    return json(route, {});
  });

  await page.goto('https://visual.test/dashboard', { waitUntil:'networkidle' });
  await page.waitForTimeout(500);
  const head = page.locator('#proDashboardHead');
  if (await head.count() !== 1) throw new Error('Professional dashboard overview did not mount.');
  if (!(await head.innerText()).includes('Desempenho real do canal')) throw new Error('Real-data dashboard heading missing.');
  if (!(await head.innerText()).includes('IA ativa')) throw new Error('AI status badge missing.');
  await page.screenshot({ path:`${out}/06-dashboard-mobile-home.png`, fullPage:true });

  const desc = page.locator('#channelDescription');
  if (await desc.count()) {
    const before = await desc.evaluate(el => el.classList.contains('expanded'));
    if (before) throw new Error('Channel description should start collapsed.');
    await desc.click();
    if (!(await desc.evaluate(el => el.classList.contains('expanded')))) throw new Error('Channel description did not expand.');
    await page.screenshot({ path:`${out}/07-dashboard-description-expanded.png`, fullPage:false });
    await desc.click();
  }

  await page.evaluate(() => {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById('strategy')?.classList.add('active');
    const node = document.getElementById('researchResult');
    if (node) {
      node.classList.remove('hidden');
      node.textContent = JSON.stringify({ seed:'dark country music', opportunities:[
        { keyword:'outlaw country music', research:{ opportunity:{ score:64, reasons:['boa aderência ao canal'] }, result_count:18 } },
        { keyword:'dark folk music', research:{ opportunity:{ score:63, reasons:['competição administrável'] }, result_count:21 } },
        { keyword:'western gothic music', research:{ opportunity:{ score:55, reasons:['tema coerente com o catálogo'] }, result_count:16 } },
      ]});
    }
  });
  await page.waitForTimeout(250);
  const pretty = page.locator('#researchResult .result-summary');
  if (await pretty.count() !== 1) throw new Error('Research JSON was not converted into readable cards.');
  if (await page.locator('#researchResult summary', { hasText:'Ver dados técnicos' }).count() !== 1) throw new Error('Technical data disclosure missing.');
  await page.screenshot({ path:`${out}/08-dashboard-mobile-strategy-readable.png`, fullPage:true });

  await page.evaluate(() => {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById('audit')?.classList.add('active');
    const node = document.getElementById('auditRaw');
    if (node) {
      node.classList.remove('hidden');
      node.textContent = JSON.stringify({ period_days:28, channel:{ channel_title:'Logan Western', subscribers:82, total_views:11723, video_count:52, total_analytics_views:59, search_share:0.0169 }, evidence:{ top_search_terms:[{term:'deadbone',views:1}] } });
    }
  });
  await page.waitForTimeout(250);
  if (await page.locator('#auditRaw .result-summary').count() !== 1) throw new Error('Audit JSON was not converted into readable cards.');
  await page.screenshot({ path:`${out}/09-dashboard-mobile-audit-readable.png`, fullPage:true });

  fs.writeFileSync('artifacts/dashboard-visual-audit.json', JSON.stringify({ ok:true, screenshots:4, consoleErrors:errors }, null, 2));
  await browser.close();
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exit(1);
  }
  console.log('Dashboard visual audit passed.');
})().catch(err=>{ console.error(err.stack||err); process.exit(1); });
