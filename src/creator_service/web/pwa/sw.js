'use strict';

const CACHE_PREFIX = 'yca-pwa-static-';
const CACHE_NAME = `${CACHE_PREFIX}v3`;
const STATIC_PATHS = new Set([
  '/manifest.webmanifest',
  '/pwa/bootstrap.js',
  '/pwa/install.css',
  '/pwa/app-icon.svg',
  '/pwa/app-icon-solid.svg',
  '/pwa/app-icon-maskable.svg',
  '/pwa/icon-1024.png',
  '/pwa/icon-512.png',
  '/pwa/icon-192.png',
  '/pwa/icon-180.png',
  '/pwa/icon-maskable-512.png',
  '/pwa/icon-solid-512.png',
  '/pwa/favicon-32.png',
]);
const SENSITIVE_PREFIXES = [
  '/oauth',
  '/auth',
  '/login',
  '/callback',
  '/mcp',
  '/api',
  '/onboarding',
];

function isSensitive(pathname) {
  return SENSITIVE_PREFIXES.some((prefix) => (
    pathname === prefix || pathname.startsWith(`${prefix}/`)
  ));
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll([...STATIC_PATHS]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isSensitive(url.pathname)) return;
  if (!STATIC_PATHS.has(url.pathname)) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(request);
        if (cached) return cached;
        throw new Error(`Static PWA asset unavailable: ${url.pathname}`);
      })
  );
});
