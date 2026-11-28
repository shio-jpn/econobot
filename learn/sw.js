/* 株トレ道場のサービスワーカー(2026-11-28)
   ・データ(data/*.json)は常にネットから取り、取れない時(電波が無い等)だけ最後に取れた分を出す
   ・画面の部品(html・js・css・アイコン)は、手元の分ですぐ開き、裏で新しい分を取って次に開く時に使う
   これでホーム画面から開くのが速くなり、オフラインでも最後の分析が読める。毎日の更新は今までどおり届く */
var CACHE = 'kabutore-v1';
var SHELL = ['./', 'index.html', 'js/app.js', 'js/market.js', 'js/outlook.js', 'js/charts.js', 'manifest.webmanifest', 'icon.svg', 'icon-192.png', 'icon-512.png'];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL).catch(function () {}); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  var req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (/\.json$/.test(url.pathname)) {      // データ: ネットを先に
    e.respondWith(fetch(req).then(function (res) {
      if (res && res.ok) { var cp = res.clone(); caches.open(CACHE).then(function (c) { c.put(url.pathname, cp); }); }
      return res;
    }).catch(function () { return caches.match(url.pathname); }));
    return;
  }
  e.respondWith(caches.match(req, { ignoreSearch: true }).then(function (hit) {   // 部品: 手元を先に、裏で更新
    var net = fetch(req).then(function (res) {
      if (res && res.ok) { var cp = res.clone(); caches.open(CACHE).then(function (c) { c.put(req, cp); }); }
      return res;
    }).catch(function () { return hit; });
    return hit || net;
  }));
});
