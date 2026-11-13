/* 株トレ道場 - チャート描画エンジン
   学習用の合成チャート(実在銘柄の値動きではない)を、形が毎回同じになるよう種つき乱数で作る。 */
(function () {
  'use strict';
  var K = (window.KABU = window.KABU || {});

  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(r) { return (r() + r() + r() + r() - 2) / 0.577; }
  function inRange(specs, i) {
    var m = 1;
    if (specs) for (var k = 0; k < specs.length; k++) if (i >= specs[k][0] && i <= specs[k][1]) m = specs[k][2];
    return m;
  }

  /* 通過点(pts)をなめらかにつないで終値の列を作り、そこからローソク足と出来高を組み立てる */
  function build(def) {
    var r = rng(def.seed || 7), pts = def.pts, n = pts[pts.length - 1][0] + 1;
    var noise = def.noise == null ? 0.006 : def.noise, c = [], i, k;
    var anchor = {};
    for (k = 0; k < pts.length; k++) anchor[pts[k][0]] = 1;
    for (k = 0; k < pts.length - 1; k++) {
      var i0 = pts[k][0], p0 = pts[k][1], i1 = pts[k + 1][0], p1 = pts[k + 1][1];
      for (i = i0; i < i1; i++) {
        var t = (i - i0) / (i1 - i0), s = 0.5 * t + 0.25 * (1 - Math.cos(Math.PI * t));
        c[i] = p0 + (p1 - p0) * s;
      }
    }
    c[n - 1] = pts[pts.length - 1][1];
    for (i = 0; i < n; i++) if (!anchor[i]) c[i] *= 1 + gauss(r) * noise * inRange(def.calm, i);

    var avg = 0;
    for (i = 1; i < n; i++) avg += Math.abs(c[i] - c[i - 1]);
    avg = avg / (n - 1) || 1;
    var out = [];
    for (i = 0; i < n; i++) {
      var prev = i ? c[i - 1] : c[0] * 0.996;
      var o = prev + gauss(r) * avg * 0.15;
      if (def.gaps && def.gaps.indexOf(i) >= 0) o = prev + (c[i] - prev) * 0.8;
      var wick = avg * 0.45 * inRange(def.calm, i);
      var h = Math.max(o, c[i]) + Math.abs(gauss(r)) * wick;
      var l = Math.min(o, c[i]) - Math.abs(gauss(r)) * wick;
      var v = (0.7 + (Math.abs(c[i] - prev) / avg) * 0.35 + r() * 0.3) * inRange(def.vol, i);
      if (def.volDown && c[i] < o) v *= inRange(def.volDown, i);
      if (def.volUp && c[i] >= o) v *= inRange(def.volUp, i);
      out.push({ o: o, h: h, l: l, c: c[i], v: v });
    }
    return out;
  }

  /* ---- インジケーター計算 ---- */
  function sma(a, n) {
    var out = [], s = 0;
    for (var i = 0; i < a.length; i++) {
      s += a[i]; if (i >= n) s -= a[i - n];
      out.push(i >= n - 1 ? s / n : null);
    }
    return out;
  }
  function ema(a, n) {
    var out = [], k = 2 / (n + 1), e = a[0];
    for (var i = 0; i < a.length; i++) { e = i ? a[i] * k + e * (1 - k) : a[0]; out.push(e); }
    return out;
  }
  function rsi(a, n) {
    var out = [null], g = 0, l = 0;
    for (var i = 1; i < a.length; i++) {
      var d = a[i] - a[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
      if (i <= n) { g += up / n; l += dn / n; } else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n; }
      out.push(i >= n ? (l === 0 ? 100 : 100 - 100 / (1 + g / l)) : null);
    }
    return out;
  }
  function macd(a) {
    var f = ema(a, 12), s = ema(a, 26), m = a.map(function (_, i) { return f[i] - s[i]; });
    var sig = ema(m, 9);
    return { macd: m, signal: sig, hist: m.map(function (x, i) { return x - sig[i]; }) };
  }
  function bb(a, n, k) {
    var mid = sma(a, n), up = [], lo = [];
    for (var i = 0; i < a.length; i++) {
      if (mid[i] == null) { up.push(null); lo.push(null); continue; }
      var s = 0;
      for (var j = i - n + 1; j <= i; j++) s += (a[j] - mid[i]) * (a[j] - mid[i]);
      var sd = Math.sqrt(s / n);
      up.push(mid[i] + k * sd); lo.push(mid[i] - k * sd);
    }
    return { mid: mid, up: up, lo: lo };
  }
  K.ind = { sma: sma, ema: ema, rsi: rsi, macd: macd, bb: bb };
  K.buildSeries = build;

  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function f1(x) { return (Math.round(x * 10) / 10).toFixed(1); }

  function path(arr, X, Y) {
    var d = '', pen = false;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i] == null) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + f1(X(i)) + ' ' + f1(Y(arr[i]));
      pen = true;
    }
    return d;
  }

  /* def: チャート定義 / opt: {w, plain(注釈なし), ma, bb, vol, ind} */
  function render(def, opt) {
    opt = opt || {};
    var d = opt.data || build(def), n = d.length;
    var W = Math.max(280, opt.w || 680), padL = 6, padR = 44, top = 16;
    var showVol = opt.vol == null ? !def.novol : opt.vol;
    var ind = opt.ind === undefined ? def.ind : opt.ind;
    var mas = opt.ma || def.ma || [];
    var useBB = opt.bb == null ? !!def.bb : opt.bb;
    var PH = W < 480 ? 200 : 250, VH = showVol ? 52 : 0, IH = ind ? 86 : 0, gap = 10;
    var H = top + PH + (VH ? gap + VH : 0) + (IH ? gap + IH : 0) + 8;
    var bw = (W - padL - padR) / n;
    var X = function (i) { return padL + (i + 0.5) * bw; };
    var closes = d.map(function (k) { return k.c; });

    var lo = Infinity, hi = -Infinity, i;
    for (i = 0; i < n; i++) { if (d[i].l < lo) lo = d[i].l; if (d[i].h > hi) hi = d[i].h; }
    var bands = useBB ? bb(closes, 20, 2) : null;
    if (bands) for (i = 0; i < n; i++) if (bands.up[i] != null) { hi = Math.max(hi, bands.up[i]); lo = Math.min(lo, bands.lo[i]); }
    var padY = (hi - lo) * 0.09; lo -= padY; hi += padY;
    var Y = function (p) { return top + (hi - p) / (hi - lo) * PH; };

    var s = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(def.name || 'チャート') + '">';
    // 目盛り
    var step = niceStep((hi - lo) / 4);
    for (var g = Math.ceil(lo / step) * step; g < hi; g += step) {
      s += '<line class="c-grid" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + f1(Y(g)) + '" y2="' + f1(Y(g)) + '"/>';
      s += '<text class="c-axis" x="' + (W - padR + 6) + '" y="' + f1(Y(g) + 4) + '">' + Math.round(g) + '</text>';
    }
    // ボリンジャーバンド
    if (bands) {
      s += '<path class="c-bb" d="' + path(bands.up, X, Y) + '"/><path class="c-bb" d="' + path(bands.lo, X, Y) + '"/><path class="c-bbmid" d="' + path(bands.mid, X, Y) + '"/>';
    }
    // ローソク足
    var cw = Math.max(1, Math.min(9, bw * 0.66));
    for (i = 0; i < n; i++) {
      var k = d[i], up = k.c >= k.o, cls = up ? 'c-up' : 'c-dn';
      var y1 = Y(Math.max(k.o, k.c)), y2 = Y(Math.min(k.o, k.c));
      s += '<line class="' + cls + '" x1="' + f1(X(i)) + '" x2="' + f1(X(i)) + '" y1="' + f1(Y(k.h)) + '" y2="' + f1(Y(k.l)) + '"/>';
      s += '<rect class="' + cls + '" x="' + f1(X(i) - cw / 2) + '" y="' + f1(y1) + '" width="' + f1(cw) + '" height="' + f1(Math.max(1, y2 - y1)) + '"/>';
    }
    // 移動平均線
    var legend = [];
    mas.forEach(function (m, j) {
      s += '<path class="c-ma c-ma' + (j + 1) + '" d="' + path(sma(closes, m), X, Y) + '"/>';
      legend.push('<tspan class="c-ma' + (j + 1) + 't">― ' + m + '日線</tspan>');
    });
    if (bands) legend.push('<tspan class="c-bbt">― ボリンジャーバンド(20, ±2σ)</tspan>');
    if (legend.length) s += '<text class="c-legend" x="' + (padL + 4) + '" y="12">' + legend.join('<tspan dx="10"> </tspan>') + '</text>';

    if (!opt.plain) {
      (def.lines || []).forEach(function (L) {
        s += '<line class="c-line c-' + (L[4] || 'neck') + '" x1="' + f1(X(L[0])) + '" y1="' + f1(Y(L[1])) + '" x2="' + f1(X(L[2])) + '" y2="' + f1(Y(L[3])) + '"/>';
      });
      var marks = (def.marks || []).slice();
      if (def.auto === 'cross' && mas.length > 1) {
        var a = sma(closes, mas[0]), b = sma(closes, mas[1]);
        for (i = 1; i < n; i++) {
          if (a[i - 1] == null || b[i - 1] == null) continue;
          if (a[i - 1] <= b[i - 1] && a[i] > b[i]) marks.push([i, a[i], 'ゴールデンクロス', 'below']);
          if (a[i - 1] >= b[i - 1] && a[i] < b[i]) marks.push([i, a[i], 'デッドクロス', 'above']);
        }
      }
      marks.forEach(function (m) {
        var x = X(m[0]), y = Y(m[1]), below = m[3] === 'below';
        var tx = Math.min(W - padR - 4 - m[2].length * 5.6, Math.max(padL + m[2].length * 5.6, x));
        s += '<circle class="c-dot" cx="' + f1(x) + '" cy="' + f1(y) + '" r="3"/>';
        s += '<text class="c-mark" text-anchor="middle" x="' + f1(tx) + '" y="' + f1(y + (below ? 20 : -11)) + '">' + esc(m[2]) + '</text>';
      });
    }
    // 出来高
    var y0 = top + PH;
    if (VH) {
      y0 += gap;
      var vmax = 0; for (i = 0; i < n; i++) vmax = Math.max(vmax, d[i].v);
      for (i = 0; i < n; i++) {
        var vh = d[i].v / vmax * (VH - 12);
        s += '<rect class="' + (d[i].c >= d[i].o ? 'c-up' : 'c-dn') + ' c-vol" x="' + f1(X(i) - cw / 2) + '" y="' + f1(y0 + VH - vh) + '" width="' + f1(cw) + '" height="' + f1(vh) + '"/>';
      }
      s += '<text class="c-pane" x="' + (padL + 4) + '" y="' + (y0 + 10) + '">出来高</text>';
      y0 += VH;
    }
    // 下段インジケーター
    if (ind === 'rsi') {
      y0 += gap;
      var R = rsi(closes, 14), YR = function (v) { return y0 + (100 - v) / 100 * IH; };
      [70, 30].forEach(function (v) {
        s += '<line class="c-grid c-dash" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + f1(YR(v)) + '" y2="' + f1(YR(v)) + '"/><text class="c-axis" x="' + (W - padR + 6) + '" y="' + f1(YR(v) + 4) + '">' + v + '</text>';
      });
      s += '<path class="c-ind" d="' + path(R, X, YR) + '"/><text class="c-pane" x="' + (padL + 4) + '" y="' + (y0 + 10) + '">RSI(14)</text>';
      if (!opt.plain) (def.indMarks || []).forEach(function (m) {
        s += '<circle class="c-dot" cx="' + f1(X(m[0])) + '" cy="' + f1(YR(R[m[0]])) + '" r="3"/><text class="c-mark" text-anchor="middle" x="' + f1(X(m[0])) + '" y="' + f1(YR(R[m[0]]) - 9) + '">' + esc(m[1]) + '</text>';
      });
    } else if (ind === 'macd') {
      y0 += gap;
      var M = macd(closes), mm = 0;
      for (i = 0; i < n; i++) mm = Math.max(mm, Math.abs(M.macd[i]), Math.abs(M.signal[i]), Math.abs(M.hist[i]));
      var YM = function (v) { return y0 + IH / 2 - v / (mm || 1) * (IH / 2 - 6); };
      s += '<line class="c-grid" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + f1(YM(0)) + '" y2="' + f1(YM(0)) + '"/><text class="c-axis" x="' + (W - padR + 6) + '" y="' + f1(YM(0) + 4) + '">0</text>';
      for (i = 0; i < n; i++) {
        var hv = M.hist[i], ya = YM(Math.max(hv, 0)), yb = YM(Math.min(hv, 0));
        s += '<rect class="c-hist" x="' + f1(X(i) - cw / 2) + '" y="' + f1(ya) + '" width="' + f1(cw) + '" height="' + f1(Math.max(0.5, yb - ya)) + '"/>';
      }
      s += '<path class="c-ind" d="' + path(M.macd, X, YM) + '"/><path class="c-ind c-sig" d="' + path(M.signal, X, YM) + '"/>';
      s += '<text class="c-pane" x="' + (padL + 4) + '" y="' + (y0 + 10) + '">MACD(12,26,9) <tspan class="c-indt">― MACD</tspan> <tspan class="c-sigt">― シグナル</tspan></text>';
    }
    return s + '</svg>';
  }
  function niceStep(raw) {
    var p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), m = raw / p;
    return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
  }
  K.renderChart = render;

  /* ローソク足の形の図解: groups = [{t:ラベル, k:[{o,h,l,c}]}] 値は0〜100 */
  K.renderCandles = function (groups, w) {
    var per = 92, cols = Math.max(2, Math.min(groups.length, Math.floor(w / per)));
    var rows = Math.ceil(groups.length / cols), cellW = w / cols, RH = 150, H = rows * RH;
    var s = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + H + '" viewBox="0 0 ' + w + ' ' + H + '" role="img" aria-label="ローソク足の形">';
    groups.forEach(function (g, gi) {
      var cx = (gi % cols + 0.5) * cellW, oy = Math.floor(gi / cols) * RH + 10;
      var Y = function (v) { return oy + (100 - v) / 100 * 104; };
      g.k.forEach(function (k, j) {
        var x = cx + (j - (g.k.length - 1) / 2) * 26, up = k.c >= k.o, cls = up ? 'c-up' : 'c-dn';
        var y1 = Y(Math.max(k.o, k.c)), y2 = Y(Math.min(k.o, k.c));
        s += '<line class="' + cls + '" stroke-width="2" x1="' + f1(x) + '" x2="' + f1(x) + '" y1="' + f1(Y(k.h)) + '" y2="' + f1(Y(k.l)) + '"/>';
        s += '<rect class="' + cls + '" x="' + f1(x - 9) + '" y="' + f1(y1) + '" width="18" height="' + f1(Math.max(2, y2 - y1)) + '"/>';
      });
      s += '<text class="c-mark" text-anchor="middle" x="' + f1(cx) + '" y="' + (oy + 128) + '">' + esc(g.t) + '</text>';
    });
    return s + '</svg>';
  };

  /* 資産曲線など単純な折れ線群 */
  K.renderLines = function (paths, w, h, opt) {
    opt = opt || {};
    var lo = Infinity, hi = -Infinity, n = 0;
    paths.forEach(function (p) { n = Math.max(n, p.d.length); p.d.forEach(function (v) { if (v < lo) lo = v; if (v > hi) hi = v; }); });
    if (hi === lo) hi = lo + 1;
    var padR = 52, top = 10, bot = 22, PH = h - top - bot;
    var X = function (i) { return 6 + i / (n - 1) * (w - padR - 6); };
    var Y = function (v) { return top + (hi - v) / (hi - lo) * PH; };
    var s = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(opt.label || '推移') + '">';
    var step = niceStep((hi - lo) / 4);
    for (var g = Math.ceil(lo / step) * step; g <= hi; g += step) {
      s += '<line class="c-grid" x1="6" x2="' + (w - padR) + '" y1="' + f1(Y(g)) + '" y2="' + f1(Y(g)) + '"/><text class="c-axis" x="' + (w - padR + 6) + '" y="' + f1(Y(g) + 4) + '">' + (opt.fmt ? opt.fmt(g) : Math.round(g)) + '</text>';
    }
    if (opt.base != null && opt.base > lo && opt.base < hi) s += '<line class="c-line c-neck" x1="6" x2="' + (w - padR) + '" y1="' + f1(Y(opt.base)) + '" y2="' + f1(Y(opt.base)) + '"/>';
    paths.forEach(function (p) { s += '<path class="' + p.cls + '" d="' + path(p.d, X, Y) + '"/>'; });
    if (opt.xlabel) s += '<text class="c-axis" x="6" y="' + (h - 6) + '">' + esc(opt.xlabel) + '</text>';
    return s + '</svg>';
  };
})();
