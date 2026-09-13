const { chromium } = require('playwright');
const fs = require('fs');

const html = fs.readFileSync('artifacts/recovery-dashboard.html', 'utf8');
const out = 'artifacts/recovery-browser';
fs.mkdirSync(out, { recursive: true });

const channel = {
  subscribers: 82,
  total_analytics_views: 68,
  total_views: 11739,
  video_count: 52,
  channel_title: 'Canal de teste somente leitura',
  watch_time_hours: 4.2,
  default_language: 'pt-BR',
  country: 'BR',
  search_share: 0.05,
  shorts_share_of_recent_views: 0.2,
  long_share_of_recent_views: 0.8,
  topic_terms: ['vida no campo'],
};
const identity = {
  id: 'fixture-channel',
  title: 'Canal de teste somente leitura',
  description: 'Fixture local para validar o dashboard sem tocar no YouTube real.',
  country: 'BR',
  default_language: 'pt-BR',
  subscribers: 82,
  views: 11739,
  video_count: 52,
  thumbnail: '',
};
const videos = { videos: [
  { id:'v1', title:'Vídeo de teste 1', views:1530, likes:71, comments:8, privacy_status:'public', thumbnail:'' },
  { id:'v2', title:'Vídeo de teste 2', views:1120, likes:58, comments:5, privacy_status:'public', thumbnail:'' },
  { id:'v3', title:'Vídeo de teste 3', views:870, likes:44, comments:4, privacy_status:'public', thumbnail:'' },
]};
const playlists = { playlists: [
  { id:'p1', title:'Playlist somente leitura', count:12, privacy_status:'public', description:'', thumbnail:'' },
  { id:'p2', title:'Arquivo privado', count:4, privacy_status:'private', description:'', thumbnail:'' },
]};

function payload(path) {
  if (path === '/api/dashboard/status') return {youtube_connected:true,chatgpt_native_ready:true,external_ai_configured:false,ai_provider:'',ai_model:''};
  if (path === '/api/dashboard/channel/identity') return identity;
  if (path === '/api/dashboard/channel') return channel;
  if (path === '/api/dashboard/channels') return {channels:[{id:identity.id,title:identity.title,active:true}]};
  if (path === '/api/dashboard/capabilities') return {youtube_data_api:true,youtube_analytics_api:true,safe_writes:true};
  if (path === '/api/dashboard/playlists') return playlists;
  if (path === '/api/dashboard/videos') return videos;
  if (path === '/api/dashboard/live') return {broadcasts:[]};
  if (path === '/api/ai/keys') return {provider:'gemini',auto_rotate:false,keys:[]};
  return {};
}

(async()=>{
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1000},locale:'pt-BR'});
  const page = await context.newPage();
  const calls = [];
  const consoleErrors = [];
  const pageErrors = [];
  const httpFailures = [];
  let failPlaylists = false;

  page.on('console', msg=>{ if(msg.type()==='error') consoleErrors.push(msg.text()); });
  page.on('pageerror', err=>pageErrors.push(err.message));
  page.on('response', response=>{
    if(response.status() >= 400) httpFailures.push({url:response.url(),status:response.status()});
  });

  await page.route('https://recovery.test/dashboard', route=>route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:html}));
  await page.route('http://127.0.0.1:17823/**', route=>route.fulfill({status:200,contentType:'application/json',body:'{"status":"offline","ollama_reachable":false,"model_ready":false}'}));
  await page.route('https://recovery.test/api/**', async route=>{
    const u = new URL(route.request().url());
    const started = Date.now();
    const delays = {
      '/api/dashboard/status':120,
      '/api/dashboard/channel/identity':260,
      '/api/dashboard/channels':180,
      '/api/dashboard/capabilities':160,
      '/api/dashboard/playlists':420,
      '/api/dashboard/videos':520,
      '/api/dashboard/channel':650,
    };
    await new Promise(r=>setTimeout(r, delays[u.pathname] || 20));
    calls.push({path:u.pathname,method:route.request().method(),ms:Date.now()-started});
    if (failPlaylists && u.pathname === '/api/dashboard/playlists') {
      return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Falha simulada de playlists'})});
    }
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payload(u.pathname))});
  });

  const shot = name=>page.screenshot({path:`${out}/${name}.png`,fullPage:true});
  await page.goto('https://recovery.test/dashboard',{waitUntil:'domcontentloaded',timeout:15000});
  await shot('01-primeira-abertura');
  await page.waitForTimeout(1400);

  const body = await page.locator('body').innerText();
  if (!body.includes('Canal de teste somente leitura')) throw new Error('Identidade do canal não carregou.');
  if (!body.includes('Conectado · leitura verificada')) throw new Error('UI declarou conexão sem/antes da leitura real de identidade.');
  if (body.includes('Verificando YouTube API')) throw new Error('Health check automático legado reapareceu.');
  await shot('02-visao-geral-carregada');
  await shot('03-canal-identificado');
  await shot('04-kpis');
  await shot('05-playlists');

  const core = ['/api/dashboard/status','/api/dashboard/channel/identity','/api/dashboard/channels','/api/dashboard/capabilities','/api/dashboard/playlists','/api/dashboard/videos','/api/dashboard/channel'];
  for (const path of core) {
    const count = calls.filter(x=>x.path===path).length;
    if (count !== 1) throw new Error(`${path} deveria ocorrer uma vez no boot; ocorreu ${count}.`);
  }
  const forbiddenAuto = calls.filter(x=>/\/api\/dashboard\/(?:free|audit|evidence|strategy|research|live)(?:\/|$)/.test(x.path));
  if (forbiddenAuto.length) throw new Error(`Chamadas pesadas/passivas no boot: ${forbiddenAuto.map(x=>x.path).join(', ')}`);

  await page.evaluate(()=>setTab('videos'));
  await page.waitForTimeout(120);
  await shot('06-videos');
  await page.evaluate(()=>setTab('strategy'));
  await shot('07-estrategia');
  await page.evaluate(()=>setTab('audit'));
  await shot('08-auditoria');
  await page.evaluate(()=>setTab('settings'));
  await page.waitForTimeout(250);
  await shot('09-configuracoes');

  // Return to overview first and let any normal tab refresh settle. Only then
  // inject one explicit playlist failure so the recovery assertion measures
  // the card failure itself rather than navigation side effects.
  await page.evaluate(()=>setTab('overview'));
  await page.waitForTimeout(500);
  failPlaylists = true;
  await page.evaluate(()=>loadPlaylists());
  await page.waitForTimeout(550);
  const errorText = await page.locator('#playlistList').innerText();
  if (!errorText.includes('Falha simulada de playlists')) throw new Error('Falha parcial de playlists não virou erro recuperável.');
  if (!(await page.locator('#channelIdentity').innerText()).includes('Canal de teste somente leitura')) throw new Error('Falha de playlists derrubou identidade do canal.');
  await shot('10-erro-recuperavel');

  await page.setViewportSize({width:390,height:844});
  failPlaylists = false;
  await page.evaluate(()=>setTab('overview'));
  await page.waitForTimeout(100);
  const overflow = await page.evaluate(()=>document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  if (overflow) throw new Error('Layout mobile possui overflow horizontal.');
  await shot('11-mobile');

  const unexpectedHttpFailures = httpFailures.filter(x=>!(x.status===503 && x.url.includes('/api/dashboard/playlists')));
  const unexpectedConsoleErrors = consoleErrors.filter(x=>!x.includes('server responded with a status of 503'));
  const simulatedPlaylistFailures = httpFailures.filter(x=>x.status===503 && x.url.includes('/api/dashboard/playlists'));
  if (simulatedPlaylistFailures.length !== 1) throw new Error(`Esperava exatamente uma falha 503 simulada de playlists; houve ${simulatedPlaylistFailures.length}.`);
  if (unexpectedHttpFailures.length) throw new Error(`Falhas HTTP inesperadas: ${JSON.stringify(unexpectedHttpFailures)}`);
  if (pageErrors.length) throw new Error(`Erros JavaScript: ${pageErrors.join(' | ')}`);
  if (unexpectedConsoleErrors.length) throw new Error(`Erros de console inesperados: ${unexpectedConsoleErrors.join(' | ')}`);

  const initialCalls = calls.slice(0, core.length);
  const report = {
    ok:true,
    revision:'professional-v1.12-single-read-boot',
    initial_request_count:initialCalls.length,
    initial_calls:initialCalls,
    all_calls:calls,
    expected_recoverable_http_failures:simulatedPlaylistFailures,
    console_errors:consoleErrors,
    page_errors:pageErrors,
    forbidden_auto_calls:forbiddenAuto,
  };
  fs.writeFileSync(`${out}/report.json`,JSON.stringify(report,null,2));
  await browser.close();
  console.log(JSON.stringify(report,null,2));
})().catch(err=>{console.error(err.stack||err);process.exit(1);});