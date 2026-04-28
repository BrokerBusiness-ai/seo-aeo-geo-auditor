"""
templates.py — szablony plików dla fix engine.
OWASP A+ security headers, manifest, service worker, htaccess.
"""

HTACCESS_TEMPLATE = """# .htaccess — wygenerowany przez seo-aeo-geo-auditor/fixer
# OWASP A+ security headers + cache + compression + HTTPS redirect

<IfModule mod_headers.c>
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=(), usb=(), interest-cohort=()"
    Header always set Cross-Origin-Opener-Policy "same-origin"
    Header always set Cross-Origin-Resource-Policy "same-origin"
    Header always set Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; upgrade-insecure-requests"
    Header unset X-Powered-By
    Header unset Server
</IfModule>

# === KOMPRESJA ===
<IfModule mod_deflate.c>
    AddOutputFilterByType DEFLATE text/html text/css text/javascript application/javascript application/json application/xml image/svg+xml text/plain
</IfModule>

# === CACHE ===
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresByType text/css "access plus 1 year"
    ExpiresByType application/javascript "access plus 1 year"
    ExpiresByType image/webp "access plus 1 year"
    ExpiresByType image/avif "access plus 1 year"
    ExpiresByType image/png "access plus 6 months"
    ExpiresByType image/jpeg "access plus 6 months"
    ExpiresByType image/svg+xml "access plus 1 year"
    ExpiresByType font/woff2 "access plus 1 year"
    ExpiresByType application/font-woff2 "access plus 1 year"
    ExpiresByType text/html "access plus 1 hour"
    ExpiresByType application/json "access plus 1 hour"
</IfModule>

# === HTTPS REDIRECT ===
RewriteEngine On
RewriteCond %{HTTPS} !=on
RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# === ENFORCE TRAILING SLASH on directories (SEO) ===
RewriteCond %{REQUEST_FILENAME} -d
RewriteCond %{REQUEST_URI} !(.*)/$
RewriteRule ^(.+)$ /$1/ [L,R=301]

# === ERROR PAGES ===
ErrorDocument 404 /404.html
ErrorDocument 500 /500.html
"""


MANIFEST_TEMPLATE = {
    "name": "{{SITE_NAME}}",
    "short_name": "{{SHORT_NAME}}",
    "description": "{{DESCRIPTION}}",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait-primary",
    "background_color": "#ffffff",
    "theme_color": "#1f2937",
    "lang": "pl-PL",
    "dir": "ltr",
    "icons": [
        {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
    "categories": ["education", "lifestyle"],
    "prefer_related_applications": False,
}


SW_TEMPLATE = """// sw.js — Service Worker wygenerowany przez seo-aeo-geo-auditor/fixer
const CACHE_NAME = '{{SITE_SLUG}}-v1';
const PRECACHE_URLS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    event.respondWith(
        caches.match(event.request).then((cached) => {
            if (cached) return cached;
            return fetch(event.request).then((response) => {
                if (response.status === 200 && response.type === 'basic') {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return response;
            }).catch(() => caches.match('/'));
        })
    );
});
"""


# Gotowy header HTML do wstrzyknięcia <link>/<meta>
META_HEAD_INJECTION_TEMPLATE = """<!-- AEO/GEO meta — generowane automatycznie -->
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
<meta name="googlebot" content="index, follow">
<meta http-equiv="Content-Language" content="pl-PL">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#1f2937">
<link rel="icon" type="image/png" sizes="32x32" href="/icons/icon-32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/icons/icon-180.png">
"""


# Spawning ai.txt — opt-in/out dla AI training (nowość 2025)
AI_TXT_TEMPLATE = """# ai.txt — Spawning AI policy declaration
# https://spawning.ai/ai-txt
User-Agent: *
Allow: search
Allow: train
Disallow:
"""
