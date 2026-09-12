from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


CACHE_VERSION = 1
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class CacheHit:
    key: str
    data: Any
    stored_at: float
    age_seconds: float


class DesktopNativeCache:
    """Thread-safe local factual snapshot cache used by the Windows desktop shell.

    Only read payloads are stored. The cache never stores OAuth tokens, passwords,
    request headers or write approvals. It is deliberately dumb and deterministic:
    facts in, facts out, plus a small amount of local provenance metadata.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if int(raw.get("version", 0)) != CACHE_VERSION:
                return
            entries = raw.get("entries")
            if isinstance(entries, dict):
                self._entries = entries
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        payload = {"version": CACHE_VERSION, "entries": self._entries}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _safe_key(key: str) -> bool:
        return key.startswith("/api/dashboard/") and len(key) <= 600

    @staticmethod
    def _decorate(data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        result.setdefault("desktop_native", {})
        meta = result.get("desktop_native")
        if isinstance(meta, dict):
            meta = dict(meta)
            meta.update({
                "engine": "python_native_cache",
                "external_ai_used": False,
                "source": "last_known_good_remote_fact_packet",
            })
            result["desktop_native"] = meta
        return result

    def put(self, key: str, data: Any) -> None:
        if not self._safe_key(key):
            raise ValueError("desktop cache key not allowed")
        with self._lock:
            self._entries[key] = {
                "stored_at": time.time(),
                "data": self._decorate(data),
            }
            self._save()

    def get(self, key: str, *, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> CacheHit | None:
        if not self._safe_key(key):
            return None
        with self._lock:
            item = self._entries.get(key)
            if not isinstance(item, dict):
                return None
            stored_at = float(item.get("stored_at", 0) or 0)
            age = max(0.0, time.time() - stored_at)
            if age > max_age_seconds:
                return None
            return CacheHit(key=key, data=item.get("data"), stored_at=stored_at, age_seconds=age)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "engine": "python_native_cache",
                "entries": len(self._entries),
                "external_ai_used": False,
                "writes_performed": 0,
            }


class _NativeHandler(BaseHTTPRequestHandler):
    server_version = "YCA-DesktopNative/1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def cache(self) -> DesktopNativeCache:
        return self.server.cache  # type: ignore[attr-defined]

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin.startswith("https://creator.silvadigitaltech.com"):
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, **self.cache.stats()})
            return
        if parsed.path == "/cache":
            key = (parse_qs(parsed.query).get("key") or [""])[0]
            hit = self.cache.get(key)
            if hit is None:
                self._json(HTTPStatus.OK, {"hit": False})
                return
            self._json(HTTPStatus.OK, {
                "hit": True,
                "key": hit.key,
                "stored_at": hit.stored_at,
                "age_seconds": round(hit.age_seconds, 3),
                "data": hit.data,
            })
            return
        self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/cache":
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0") or 0), 8 * 1024 * 1024)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            key = str(payload.get("key", ""))
            self.cache.put(key, payload.get("data"))
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "detail": str(exc)[:300]})
            return
        self._json(HTTPStatus.OK, {"ok": True})


class DesktopNativeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], cache: DesktopNativeCache) -> None:
        super().__init__(address, _NativeHandler)
        self.cache = cache


def start_native_server(cache_path: Path) -> tuple[DesktopNativeServer, threading.Thread, str]:
    cache = DesktopNativeCache(cache_path)
    server = DesktopNativeServer(("127.0.0.1", 0), cache)
    thread = threading.Thread(target=server.serve_forever, name="yca-desktop-native", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def desktop_fetch_bootstrap(native_base: str) -> str:
    """Return JS injected before dashboard code to provide bounded, cached reads.

    The wrapper only intercepts same-origin GET dashboard reads. Writes, uploads,
    auth and OAuth always go straight to the VPS. Cache hits are refreshed in the
    background without recursively calling refreshAll(), which previously caused a
    permanent refresh loop that kept resetting visible loaders.
    """
    base = json.dumps(native_base)
    return f"""
(()=>{{
  if(window.__ycaDesktopNativeInstalled)return;
  window.__ycaDesktopNativeInstalled=true;
  const nativeBase={base};
  const realFetch=window.fetch.bind(window);
  const memoryCache=new Map();
  const lastRefresh=new Map();
  // Identity is deliberately excluded.  It is the bounded, fresh YouTube API
  // health probe and must never be satisfied by an old profile snapshot.
  const cacheablePath=pathname=>[
    '/api/dashboard/capabilities','/api/dashboard/channel','/api/dashboard/playlists',
    '/api/dashboard/videos','/api/dashboard/evidence','/api/dashboard/audit'
  ].includes(pathname)||pathname.startsWith('/api/dashboard/free/');
  const cacheable=(url,init)=>{{
    const method=String((init&&init.method)||'GET').toUpperCase();
    if(method!=='GET')return false;
    let u;try{{u=new URL(typeof url==='string'?url:url.url,location.href)}}catch{{return false}}
    if(u.origin!==location.origin)return false;
    return cacheablePath(u.pathname);
  }};
  const keyFor=url=>{{const u=new URL(typeof url==='string'?url:url.url,location.href);return u.pathname+u.search}};
  const timeoutSignal=(ms,external)=>{{const c=new AbortController();const t=setTimeout(()=>c.abort('desktop-timeout'),ms);if(external)external.addEventListener('abort',()=>c.abort(external.reason),{{once:true}});return {{signal:c.signal,done:()=>clearTimeout(t)}}}};
  const localGet=async key=>{{
    if(memoryCache.has(key))return {{hit:true,data:memoryCache.get(key),age_seconds:0,source:'memory'}};
    const c=timeoutSignal(300);
    try{{const r=await realFetch(nativeBase+'/cache?key='+encodeURIComponent(key),{{cache:'no-store',signal:c.signal}});const d=r.ok?await r.json():null;if(d&&d.hit)memoryCache.set(key,d.data);return d}}catch{{return null}}finally{{c.done()}}
  }};
  const localPut=async(key,data)=>{{
    memoryCache.set(key,data);
    try{{await realFetch(nativeBase+'/cache',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key,data}}),cache:'no-store'}})}}catch{{}}
  }};
  const remote=async(input,init,key,timeoutMs)=>{{
    const c=timeoutSignal(timeoutMs,init&&init.signal);
    try{{
      const r=await realFetch(input,{{...(init||{{}}),signal:c.signal}});
      if(r.ok){{const clone=r.clone();clone.json().then(data=>localPut(key,data)).catch(()=>{{}})}}
      return r;
    }}finally{{c.done()}}
  }};
  const refreshLater=(input,init,key)=>{{
    const now=Date.now();
    if(now-(lastRefresh.get(key)||0)<30000)return;
    lastRefresh.set(key,now);
    remote(input,init,key,12000).then(r=>{{
      if(r.ok)window.dispatchEvent(new CustomEvent('yca:desktop-cache-updated',{{detail:{{key}}}}));
    }}).catch(()=>{{}});
  }};
  window.fetch=async(input,init={{}})=>{{
    if(!cacheable(input,init))return realFetch(input,init);
    const key=keyFor(input);
    const cached=await localGet(key);
    if(cached&&cached.hit){{
      refreshLater(input,init,key);
      return new Response(JSON.stringify(cached.data),{{status:200,headers:{{'Content-Type':'application/json','X-YCA-Desktop-Cache':'hit','X-YCA-Cache-Age':String(cached.age_seconds||0)}}}});
    }}
    try{{return await remote(input,init,key,8000)}}catch(err){{
      const body={{detail:'A leitura remota excedeu 8 segundos. O aplicativo interrompeu a espera para não travar a interface.',desktop_native_timeout:true}};
      return new Response(JSON.stringify(body),{{status:504,headers:{{'Content-Type':'application/json','X-YCA-Desktop-Cache':'miss'}}}});
    }}
  }};
}})();
"""
