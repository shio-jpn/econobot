/* 株トレ道場 - アプリ本体(ビルド不要の素のJavaScript) */
(function () {
  'use strict';
  var K = window.KABU;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var view = $('#view');
  var DAY = 86400000;

  /* ================= 保存(ブラウザ内) ================= */
  var KEY = 'kabu-dojo-v1';
  var EMPTY = function () { return { done: {}, srs: {}, tests: {}, candle: 'us', last: null, drill: { n: 0, hit: 0, conf: {}, real: { n: 0, hit: 0 }, seen: [] }, notes: {} }; };
  var state = EMPTY();
  try { var raw = localStorage.getItem(KEY); if (raw) Object.assign(state, JSON.parse(raw)); } catch (e) { /* 保存領域が使えなくても動かす */ }
  if (!state.drill) state.drill = EMPTY().drill;
  if (!state.notes) state.notes = {};
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* noop */ } }

  /* ================= 小道具 ================= */
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
  function reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&'); }
  function shuffle(a, r) { a = a.slice(); for (var i = a.length - 1; i > 0; i--) { var j = Math.floor((r || Math.random)() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function yen(n) { return Math.round(n).toLocaleString('ja-JP'); }
  function num(id) { var v = parseFloat(($('#' + id) || {}).value); return isFinite(v) ? v : NaN; }
  function sgn(x, d, u) { return x == null || !isFinite(x) ? '—' : (x > 0 ? '+' : '') + x.toFixed(d) + (u || ''); }
  function cls(x) { return x == null ? '' : x > 0 ? 'up' : x < 0 ? 'down' : ''; }

  /* ================= データの索引 ================= */
  var lessons = [], lessonById = {}, termByName = {}, chartById = {}, traderById = {}, macroById = {}, questions = [];
  K.stages.forEach(function (st, si) {
    st.lessons.forEach(function (l) {
      l.stage = st; l.stageNo = si; l.no = lessons.length; l.level = l.lv || '基礎'; lessons.push(l); lessonById[l.id] = l;
      (l.quiz || []).forEach(function (q, i) { q.id = l.id + '-' + i; q.lesson = l; questions.push(q); });
    });
  });
  K.glossary.forEach(function (g) { termByName[g.name] = g; });
  K.charts.forEach(function (c) { chartById[c.id] = c; });
  K.traders.forEach(function (t) { traderById[t.id] = t; });
  K.macro.forEach(function (m) { macroById[m.id] = m; });

  /* トピックと領域 */
  var areaById = {}, topicById = {};
  K.areas.forEach(function (a) { areaById[a.id] = a; a.topics = []; });
  K.topics.forEach(function (t) {
    topicById[t.id] = t; areaById[t.area].topics.push(t);
    t.items = t.lessons.map(function (id) { return lessonById[id]; }).filter(Boolean);
    t.items.forEach(function (l) { (l.topics = l.topics || []).push(t); if (!l.home) l.home = t; });
  });
  lessons.forEach(function (l) { if (!l.home) { l.home = K.topics[K.topics.length - 1]; l.topics = [l.home]; } l.area = areaById[l.home.area]; });
  var LEVELS = [['基礎', 'base'], ['応用', 'adv'], ['実戦', 'prac'], ['プロ', 'pro']];
  var levelBySlug = {}; LEVELS.forEach(function (x) { levelBySlug[x[1]] = x[0]; });
  function lvTag(l) { var i = LEVELS.map(function (x) { return x[0]; }).indexOf(l.level); return '<span class="lv lv-' + LEVELS[i][1] + '">' + l.level + '</span>'; }

  /* 問題: 確認問題・ケース演習・用語カードを同じ間隔反復に乗せる */
  var qById = {}; questions.forEach(function (q) { qById[q.id] = q; });
  K.cases.forEach(function (c) { c.kind = 'case'; c.area = K.stageArea[c.ch] || 'strategy'; qById[c.id] = c; });
  var termCards = K.glossary.map(function (g) {
    var same = K.glossary.filter(function (x) { return x.cat === g.cat && x !== g; });
    var pick = [], seed = g.name.length * 7 + g.def.length;
    while (pick.length < 3) { var c = same[seed % same.length]; seed = (seed * 31 + 17) % 100003; if (pick.indexOf(c) < 0) pick.push(c); }
    var hide = new RegExp([g.name].concat(g.aka.filter(function (x) { return x.length > 1; })).map(reEsc).join('|'), 'gi');
    return { id: 'term-' + g.name, kind: 'term', term: g, q: '次の説明に当てはまる用語は? 「' + g.def.replace(hide, '○○') + '」', a: [g.name].concat(pick.map(function (x) { return x.name; })), e: g.name + ': ' + g.def };
  });
  termCards.forEach(function (c) { qById[c.id] = c; });
  function areaOfQ(q) { return q.lesson ? q.lesson.area.id : q.kind === 'case' ? q.area : null; }
  function mastery(aid) {
    var ids = Object.keys(qById).filter(function (id) { return areaOfQ(qById[id]) === aid; });
    var sum = 0; ids.forEach(function (id) { if (state.srs[id]) sum += Math.min(4, state.srs[id].box) / 4; });
    return ids.length ? Math.round(sum / ids.length * 100) : 0;
  }
  function doneRateOf(list) { return list.length ? Math.round(list.filter(function (l) { return state.done[l.id]; }).length / list.length * 100) : 0; }
  function areaLessons(aid) { return lessons.filter(function (l) { return l.area.id === aid; }); }
  var RANKS = [[0, '入門'], [10, '初級'], [30, '中級'], [55, '上級'], [80, 'ベテラン級']];
  function overall() {
    var m = 0; K.areas.forEach(function (a) { m += mastery(a.id); }); m = Math.round(m / K.areas.length);
    var tm = 0; termCards.forEach(function (c) { if (state.srs[c.id]) tm += Math.min(4, state.srs[c.id].box) / 4; }); tm = Math.round(tm / termCards.length * 100);
    var score = Math.round(m * 0.75 + tm * 0.25), rank = RANKS[0][1];
    RANKS.forEach(function (r) { if (score >= r[0]) rank = r[1]; });
    return { score: score, rank: rank, terms: tm };
  }

  /* ================= 本文の表示 ================= */
  var NO_LINK = { 'ベース': 1, 'レンジ': 1, '株式': 1, '決算': 1, '金利': 1, 'トレンド': 1, '出来高': 1 };
  var termNames = K.glossary.map(function (g) { return g.name; }).filter(function (n) { return n.length >= 2 && !NO_LINK[n]; }).sort(function (a, b) { return b.length - a.length; });
  var termRe = new RegExp('(' + termNames.map(reEsc).join('|') + ')', 'g');
  function inline(text, seen) {
    return text.split(/(\*\*[^*]+\*\*)/).map(function (part) {
      var bold = /^\*\*[^*]+\*\*$/.test(part);
      if (bold) part = part.slice(2, -2);
      var out = part.split(termRe).map(function (seg, i) {
        if (i % 2 === 0) return esc(seg);
        if (!seen || seen[seg]) return esc(seg);
        seen[seg] = 1;
        return '<button type="button" class="term" data-term="' + esc(seg) + '">' + esc(seg) + '</button>';
      }).join('');
      return bold ? '<strong>' + out + '</strong>' : out;
    }).join('');
  }
  /* 簡易マークアップ → HTML。toc を渡すと見出しに番号付きの id を振り、目次を集める */
  function md(src, toc) {
    var seen = toc ? {} : null, out = [], lines = String(src).split('\n'), i = 0;
    function flush(tag, items) { out.push('<' + tag + '>' + items.map(function (x) { return '<li>' + inline(x, seen) + '</li>'; }).join('') + '</' + tag + '>'); }
    while (i < lines.length) {
      var L = lines[i].trim();
      if (!L) { i++; continue; }
      var m;
      if (L.indexOf('### ') === 0) out.push('<h4>' + inline(L.slice(4)) + '</h4>');
      else if (L.indexOf('## ') === 0) {
        var id = toc ? 'sec-' + (toc.length + 1) : '';
        if (toc) toc.push([id, L.slice(3)]);
        out.push('<h3' + (id ? ' id="' + id + '"' : '') + '>' + inline(L.slice(3)) + '</h3>');
      } else if (L.indexOf('# ') === 0) out.push('<h3>' + inline(L.slice(2)) + '</h3>');
      else if (L.indexOf('> ') === 0) out.push('<p class="note">' + inline(L.slice(2), seen) + '</p>');
      else if (L.indexOf('! ') === 0) out.push('<p class="warn"><span class="warn-label">注意</span>' + inline(L.slice(2), seen) + '</p>');
      else if ((m = /^\{chart:([\w-]+)\}$/.exec(L))) out.push(chartFigure(m[1]));
      else if ((m = /^\{candles:([\w-]+)\}$/.exec(L))) out.push('<figure class="fig"><div class="chart" data-candles="' + m[1] + '"></div></figure>');
      else if (L.charAt(0) === '|') {
        var rows = [];
        while (i < lines.length && lines[i].trim().charAt(0) === '|') {
          var r = lines[i].trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); });
          if (!r.every(function (c) { return /^:?-{2,}:?$/.test(c); })) rows.push(r);
          i++;
        }
        out.push('<div class="table-wrap"><table><thead><tr>' + rows[0].map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
          rows.slice(1).map(function (r) { return '<tr>' + r.map(function (c) { return '<td>' + arrows(inline(c, seen)) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>');
        continue;
      } else if (/^\d+\. /.test(L)) {
        var nums = [];
        while (i < lines.length && /^\d+\. /.test(lines[i].trim())) { nums.push(lines[i].trim().replace(/^\d+\. /, '')); i++; }
        flush('ol', nums); continue;
      } else if (/^[-*] /.test(L)) {
        var items = [];
        while (i < lines.length && /^[-*] /.test(lines[i].trim())) { items.push(lines[i].trim().slice(2)); i++; }
        flush('ul', items); continue;
      } else out.push('<p>' + inline(L, seen) + '</p>');
      i++;
    }
    return out.join('');
  }
  function arrows(h) { return h.replace(/^↑/, '<span class="up">↑</span>').replace(/^↓/, '<span class="down">↓</span>'); }
  function chartFigure(id, plain) {
    var c = chartById[id];
    if (!c) return '';
    return '<figure class="fig"><div class="chart" data-chart="' + id + '"' + (plain ? ' data-plain="1"' : '') + '></div>' +
      (plain ? '' : '<figcaption><a href="#chart-' + id + '">' + esc(c.name) + '</a> — ' + esc(c.what) + '</figcaption>') + '</figure>';
  }
  function drawCharts(root) {
    $$('.chart', root).forEach(function (el) {
      var w = Math.floor(el.clientWidth);
      if (!w) return;
      if (el._draw) el._draw(w);
      else if (el.dataset.chart) el.innerHTML = K.renderChart(chartById[el.dataset.chart] || K.labSeries, Object.assign({ w: w, plain: !!el.dataset.plain }, el._opt || {}));
      else if (el.dataset.candles) el.innerHTML = K.renderCandles(K.candleFigs[el.dataset.candles], w);
    });
  }
  var rz; window.addEventListener('resize', function () { clearTimeout(rz); rz = setTimeout(function () { drawCharts(); }, 150); });

  /* ================= 検索 ================= */
  function kana(s) { return s.replace(/[ァ-ヶ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0x60); }); }
  function norm(s) { return kana(String(s).normalize('NFKC').toLowerCase()); }
  function plain(body) { return body.replace(/\{[\w:-]+\}/g, ' ').replace(/^[#>!|\-\s]+/gm, '').replace(/\*\*/g, '').replace(/\|/g, ' ').replace(/\s+/g, ' '); }
  var docs = [];
  function addDoc(type, title, keys, text, href, extra) {
    text = String(text).normalize('NFKC');
    docs.push(Object.assign({ type: type, title: title, nt: norm(title), nk: norm(keys || ''), text: text, nx: norm(text), href: href }, extra || {}));
  }
  K.glossary.forEach(function (g) { addDoc('term', g.name, g.aka.join(' '), g.def, null, { term: g }); });
  lessons.forEach(function (l) {
    addDoc('lesson', l.t, l.topics.map(function (t) { return t.name; }).join(' ') + ' ' + l.level, l.sum + ' ' + plain(l.body) + ' ' + (l.quiz || []).map(function (q) { return q.q + ' ' + q.e; }).join(' '), '#lesson-' + l.id, { lesson: l });
  });
  K.macro.forEach(function (m) { addDoc('macro', m.title, m.aka, m.chain.join(' → ') + ' ' + m.effects.map(function (e) { return e[0] + ' ' + e[2]; }).join(' ') + ' ' + m.jp + ' ' + m.caveat, '#macro-' + m.id, { macro: m }); });
  K.charts.forEach(function (c) { addDoc('chart', c.name, c.aka + ' ' + c.cat, c.what + ' ' + c.how + ' ' + c.fail, '#chart-' + c.id, { chart: c }); });
  K.traders.forEach(function (t) { addDoc('trader', t.name, t.aka + ' ' + t.style, t.record + ' ' + t.ideas.join(' ') + ' ' + t.takeaway, '#trader-' + t.id, { trader: t }); });
  K.topics.forEach(function (t) { addDoc('topic', t.name, areaById[t.area].name, t.items.map(function (l) { return l.t + ' ' + l.sum; }).join(' '), '#topic-' + t.id, { topic: t }); });
  var syn = {};
  K.glossary.forEach(function (g) { [g.name].concat(g.aka).map(norm).filter(function (x) { return x.length >= 2; }).forEach(function (n) { (syn[n] = syn[n] || []).push(norm(g.name)); }); });
  function expand(tok) { var set = {}; set[tok] = 1; (syn[tok] || []).forEach(function (x) { set[x] = 1; }); return Object.keys(set); }
  function scoreDoc(d, variants) {
    var best = 0;
    variants.forEach(function (v, vi) {
      var s = 0;
      if (d.nt === v) s = 100; else if (d.nt.indexOf(v) === 0) s = 60; else if (d.nt.indexOf(v) >= 0) s = 45;
      if (!s && d.nk.split(' ').indexOf(v) >= 0) s = 55; else if (!s && d.nk.indexOf(v) >= 0) s = 35;
      var p = d.nx.indexOf(v), cnt = 0;
      while (p >= 0 && cnt < 6) { cnt++; p = d.nx.indexOf(v, p + v.length); }
      if (cnt) s += 8 + cnt * 3;
      if (vi > 0) s *= 0.85;
      if (s > best) best = s;
    });
    return best;
  }
  /* 質問文から検索語を取り出す(助詞や疑問の言い回しで区切る) */
  var STOP = /(とは|って|ってなに|ですか|ますか|ください|教えて|知りたい|について|なぜ|どうして|どう|どの|どれ|なに|何|いつ|する|して|した|される|ある|いる|なる|ため|ので|から|まで|より|では|には|とき|時|こと|もの|よう|場合|方法|の|は|が|を|に|で|と|も|や|へ|か|ね|よ)/g;
  function keywords(q) {
    var t = String(q).normalize('NFKC').replace(/[?？!！。、,.「」『』()()・\s]+/g, ' ');
    var parts = t.replace(STOP, ' ').split(/\s+/).filter(function (x) { return x.length >= 2; });
    return parts.length ? parts : t.split(/\s+/).filter(Boolean);
  }
  function search(q) {
    var toks = norm(q).split(/[\s　、,]+/).filter(Boolean);
    if (!toks.length) return { toks: [], hits: [], vars: [] };
    var vars = toks.map(expand);
    function run(needAll) {
      var hits = [];
      docs.forEach(function (d) {
        var total = 0, matched = 0;
        vars.forEach(function (v) { var s = scoreDoc(d, v); if (s) matched++; total += s; });
        if (!matched || (needAll && matched < toks.length)) return;
        if (d.type === 'term') total *= 1.15;
        hits.push({ d: d, s: total * (needAll ? 1 : matched / toks.length) });
      });
      return hits.sort(function (a, b) { return b.s - a.s; });
    }
    var hits = run(true);
    if (!hits.length && toks.length > 1) hits = run(false);
    return { toks: toks, vars: [].concat.apply([], vars), hits: hits };
  }
  K.search = search;
  K.keywords = keywords;
  function snippet(d, vars, len) {
    len = len || 110;
    var pos = -1;
    vars.forEach(function (v) { var p = d.nx.indexOf(v); if (p >= 0 && (pos < 0 || p < pos)) pos = p; });
    var start = Math.max(0, pos - 28), s = d.text.slice(start, start + len);
    return (start > 0 ? '…' : '') + highlight(s, vars) + (start + len < d.text.length ? '…' : '');
  }
  function highlight(s, vars) {
    var n = norm(s), marks = [];
    if (n.length !== s.length) return esc(s);
    vars.forEach(function (v) { var p = n.indexOf(v); while (p >= 0) { marks.push([p, p + v.length]); p = n.indexOf(v, p + v.length); } });
    marks.sort(function (a, b) { return a[0] - b[0]; });
    var out = '', at = 0;
    marks.forEach(function (m) { if (m[0] < at) return; out += esc(s.slice(at, m[0])) + '<mark>' + esc(s.slice(m[0], m[1])) + '</mark>'; at = m[1]; });
    return out + esc(s.slice(at));
  }
  var TYPE_LABEL = { term: '用語', topic: 'トピック', lesson: 'レッスン', macro: '因果マップ', chart: 'チャート', trader: 'トレーダー研究' };
  var TYPE_ORDER = ['term', 'topic', 'macro', 'lesson', 'chart', 'trader'];
  var SUGGEST = ['金利', 'CPI', '逆イールド', '円安', '出来高', 'VCP', '損切り', '決算', '期待値', 'オプション', 'テスタ', '片山'];
  var ASK_SUGGEST = ['逆イールドが解消に向かう時、なぜ警戒が必要なの?', 'CPIが予想より高いと、どの業種が売られやすい?', 'VCPと普通の保ち合いはどう見分ける?', '決算をまたぐか迷った時の判断基準は?', '損切りが続く時、何を見直せばいい?', '円高の日に日本株で強くなりやすい業種は?'];

  function viewSearch(q) {
    var h = '<div class="page-head"><h1>検索</h1><p class="lead">用語・トピック・因果マップ・レッスン・チャート・トレーダー研究をまとめて探します。文章で聞きたい時は「質問」を使ってください。</p></div>';
    if (!q) return h + '<section><h2>よく調べられる言葉</h2><div class="chips">' + SUGGEST.map(function (s) { return '<button type="button" class="chip" data-q="' + esc(s) + '">' + esc(s) + '</button>'; }).join('') + '</div></section>';
    var r = search(q);
    h += '<section class="ask-cta"><p>「' + esc(q) + '」について、教材をもとに説明してほしい時は</p><button type="button" class="btn" data-ask="' + esc(q) + '">質問する</button></section>';
    if (!r.hits.length) return h + '<section><p class="empty">「' + esc(q) + '」に一致する内容は見つかりませんでした。短い単語や別の言い方(例: 物価→CPI)で試すか、質問してください。</p></section>';
    h += '<p class="count">「' + esc(q) + '」 ' + r.hits.length + '件</p>';
    var top = r.hits.filter(function (x) { return x.d.type === 'term' && x.s >= 60; })[0];
    if (top) {
      var g = top.d.term;
      h += '<section class="hero-term"><p class="eyebrow">' + esc(g.cat) + 'の用語</p><h2 class="plain-h">' + esc(g.name) + '</h2>' + (g.aka.length ? '<p class="aka">' + esc(g.aka.slice(0, 5).join(' / ')) + '</p>' : '') + '<p>' + esc(g.def) + '</p>' + relChips(g) + '</section>';
    }
    TYPE_ORDER.forEach(function (type) {
      var list = r.hits.filter(function (x) { return x.d.type === type && x !== top; });
      if (!list.length) return;
      var max = type === 'term' ? 8 : 6;
      h += '<section class="results"><h2>' + TYPE_LABEL[type] + ' <span class="n">' + list.length + '</span></h2><ul>' +
        list.slice(0, max).map(function (x) {
          var d = x.d;
          if (type === 'term') return '<li><button type="button" class="res" data-term="' + esc(d.title) + '"><span class="res-t">' + highlight(d.title, r.vars) + '</span><span class="res-s">' + highlight(d.text, r.vars) + '</span></button></li>';
          var sub = type === 'lesson' ? d.lesson.area.name + ' / ' + d.lesson.home.name + ' ・ ' + d.lesson.level : type === 'topic' ? areaById[d.topic.area].name + ' ・ ' + d.topic.items.length + 'レッスン' : type === 'chart' ? d.chart.cat : type === 'trader' ? d.trader.style : d.macro.group;
          return '<li><a class="res" href="' + d.href + '"><span class="res-k">' + esc(sub) + '</span><span class="res-t">' + highlight(d.title, r.vars) + '</span><span class="res-s">' + snippet(d, r.vars) + '</span></a></li>';
        }).join('') + '</ul>' + (list.length > max ? '<p class="more">ほか ' + (list.length - max) + '件</p>' : '') + '</section>';
    });
    return h;
  }
  function relChips(g) {
    var rel = g.rel.filter(function (n) { return termByName[n]; });
    return rel.length ? '<div class="chips"><span class="chips-label">関連</span>' + rel.map(function (n) { return '<button type="button" class="chip" data-q="' + esc(n) + '">' + esc(n) + '</button>'; }).join('') + '</div>' : '';
  }
  function openTerm(name) {
    var g = termByName[name];
    if (!g) return;
    var uses = lessons.filter(function (l) { return l.body.indexOf(name) >= 0; }).slice(0, 5);
    $('#sheet-body').innerHTML = '<p class="eyebrow">' + esc(g.cat) + '</p><h2 id="sheet-title">' + esc(g.name) + '</h2>' +
      (g.aka.length ? '<p class="aka">' + esc(g.aka.slice(0, 5).join(' / ')) + '</p>' : '') + '<p>' + esc(g.def) + '</p>' + relChips(g) +
      (uses.length ? '<p class="sheet-sub">この言葉が出てくるレッスン</p><ul class="plain">' + uses.map(function (l) { return '<li><a href="#lesson-' + l.id + '">' + esc(l.t) + '</a></li>'; }).join('') + '</ul>' : '') +
      '<div class="actions"><button type="button" class="btn ghost" data-q="' + esc(g.name) + '">関連する内容をすべて見る</button><button type="button" class="btn ghost" data-ask="' + esc(g.name + 'について、実際の売買でどう使うかも含めて詳しく教えて') + '">もっと詳しく質問する</button></div>';
    $('#sheet').hidden = false;
    $('#sheet-close').focus();
  }
  function openMenu() {
    $('#sheet-body').innerHTML = '<h2 id="sheet-title">メニュー</h2><nav class="menu">' + navHTML(curName) + '</nav>';
    $('#sheet').hidden = false; $('#sheet-close').focus();
  }
  function closeSheet() { $('#sheet').hidden = true; }

  /* ================= 復習(間隔反復) ================= */
  var GAPS = [0, 1, 3, 7, 16, 35];
  function grade(qid, ok) {
    var c = state.srs[qid] || { box: 0 };
    c.box = ok ? Math.min(5, c.box + 1) : 0;
    c.due = Date.now() + (ok ? GAPS[c.box] * DAY : 10 * 60000);
    c.seen = (c.seen || 0) + 1;
    state.srs[qid] = c; save();
  }
  function dueList() { var now = Date.now(); return Object.keys(state.srs).filter(function (id) { return qById[id] && state.srs[id].due <= now; }); }
  function quizHTML(q, idx, total) {
    var opts = shuffle(q.a.map(function (t, i) { return { t: t, ok: i === 0 }; }));
    return '<div class="q" data-qid="' + (q.id || '') + '"><p class="q-n">' + (total ? '問' + (idx + 1) + ' / ' + total : '確認問題') + '</p><p class="q-t">' + esc(q.q) + '</p><div class="q-opts">' +
      opts.map(function (o, i) { return '<button type="button" class="opt" data-ok="' + (o.ok ? 1 : 0) + '"><span class="opt-k">' + 'ABCD'.charAt(i) + '</span>' + esc(o.t) + '</button>'; }).join('') +
      '</div><div class="q-exp" hidden><p><strong class="q-res"></strong> ' + esc(q.e) + '</p></div></div>';
  }
  function answer(btn) {
    var box = btn.closest('.q');
    if (box.dataset.done) return;
    box.dataset.done = 1;
    var ok = btn.dataset.ok === '1';
    $$('.opt', box).forEach(function (b) { b.disabled = true; if (b.dataset.ok === '1') b.classList.add('right'); });
    if (!ok) btn.classList.add('wrong');
    box.querySelector('.q-exp').hidden = false;
    var res = box.querySelector('.q-res'); res.textContent = ok ? '正解。' : '不正解。'; res.className = 'q-res ' + (ok ? 'up' : 'down');
    if (box.dataset.qid) grade(box.dataset.qid, ok);
    box.dispatchEvent(new CustomEvent('answered', { bubbles: true, detail: { ok: ok } }));
  }

  /* ================= 実データ ================= */
  var MK = null, mkReady = false;
  K.mkt.load().then(function (d) { MK = d; mkReady = true; renderTicker(); if (curName === 'home' || curName === 'market' || curName === 'drill' || curName === 'outlook') route(); });
  var AN = null, anReady = false;
  K.mkt.loadAnalysis().then(function (d) { AN = d; anReady = true; if (curName === 'why' || curName === 'outlook' || curName === 'home') route(); });
  function mkStats(id) { var s = MK && MK.series[id]; return s ? K.mkt.stats(s.rows, s.kind) : null; }
  function fmtLevel(st, kind) { if (!st) return '—'; if (st.kind === 'gauge') return st.last.toFixed(2); if (st.rate) return st.last.toFixed(2) + '%'; return st.last >= 1000 ? st.last.toLocaleString('en-US', { maximumFractionDigits: 0 }) : st.last.toFixed(2); }
  function fmtChg(st, k) { if (!st || st[k] == null) return '—'; if (st.kind === 'gauge') return sgn(st[k], 2); return st.rate ? sgn(st[k] * 100, 0, 'bp') : sgn(st[k], 2, '%'); }
  function renderTicker() {
    var el = $('#ticker'); if (!el) return;
    if (!MK) { el.hidden = true; return; }
    el.hidden = false;
    var items = ['SP500', 'NASDAQCOM', 'DJIA', 'NIKKEI225', 'DGS10', 'DEXJPUS', 'VIXCLS', 'DCOILWTICO'].filter(function (id) { return MK.series[id]; }).map(function (id) {
      var st = mkStats(id); if (!st) return '';
      return '<a class="tk" href="#market"><span class="tk-n">' + esc(MK.series[id].name) + '</span><span class="tk-c ' + cls(st.d1) + '">' + fmtChg(st, 'd1') + '</span></a>';
    }).join('');
    el.innerHTML = items;
    el.hidden = false;
  }

  /* ================= AIへの質問 ================= */
  var samplePromise = null, sampleOK = null;
  function getSample() {
    if (!samplePromise) {
      samplePromise = (window.claude && typeof window.claude.use === 'function') ? window.claude.use('sample').catch(function () { return null; }) : Promise.resolve(null);
      samplePromise.then(function (s) { sampleOK = !!s; if (curName === 'ask' || curName === 'home') { var b = $('#ask-mode'); if (b) b.textContent = sampleOK ? 'AIが教材をもとに回答' : '教材から関連する解説を表示'; } });
    }
    return samplePromise;
  }
  getSample();
  var chat = [], asking = null;
  var PREAMBLE = 'あなたは日本株・米国株の両方で長年の実績があるベテラントレーダー兼講師です。学習アプリ「株トレ道場」の利用者の質問に、日本語で答えます。\n' +
    '利用者はある程度の基礎知識がある個人投資家で、副業として高い成績を目指しています。\n' +
    'ルール:\n1. 下の「アプリの教材」の内容を優先して使う。教材にない一般的な知識を使う時は、そう分かるように書く。\n' +
    '2. 不確かな数値や事実は断定しない。現在の市場の数値は「今日の相場データ」にあるものだけを使い、それ以外の最新の値やニュースを推測で書かない。データが無いことは「データが無い」と書く。\n' +
    '3. 特定の銘柄の売買を勧めない。判断の手順、確認すること、具体例(仮の数字と明記)で教える。\n' +
    '4. 構成は「## 結論」「## 理由」「## 具体例」「## 次に確認すること」を基本に、必要なら表(| 区切り)を使う。箇条書きは「- 」で書く。\n' +
    '5. 最後に「## 関連レッスン」として、下の教材リストにあるレッスン名だけを最大3つ挙げる。\n';
  function buildContext(q) {
    var r = search(keywords(q).join(' '));
    var picked = r.hits.filter(function (x) { return x.d.type !== 'topic'; }).slice(0, 6);
    var ctx = picked.map(function (x) {
      var d = x.d, name = (TYPE_LABEL[d.type] || '') + '「' + d.title + '」';
      var body = d.type === 'lesson' ? d.lesson.sum + ' ' + snippetPlain(d, r.vars, 900) : d.text.slice(0, 600);
      return '### ' + name + '\n' + body;
    }).join('\n\n');
    var mk = MK ? '\n\n# 今日の相場データ(公的統計FREDから自動取得)\n' + K.mkt.context(MK) : '\n\n# 今日の相場データ\nこのアプリには今日の相場データがまだ読み込まれていない。';
    return { text: '# アプリの教材(関連する部分の抜粋)\n' + (ctx || '(該当なし)') + mk, hits: picked };
  }
  function snippetPlain(d, vars, len) {
    var pos = -1; vars.forEach(function (v) { var p = d.nx.indexOf(v); if (p >= 0 && (pos < 0 || p < pos)) pos = p; });
    var start = Math.max(0, pos - 150); return d.text.slice(start, start + len);
  }
  function sendAsk(q) {
    q = String(q || '').trim();
    if (!q || asking) return;
    var ctx = buildContext(q);
    chat.push({ role: 'user', content: q });
    var msg = { role: 'assistant', content: '', related: ctx.hits, pending: true };
    chat.push(msg);
    if (curName !== 'ask') { location.hash = '#ask'; } else renderChat();
    getSample().then(function (sample) {
      if (!sample) { msg.pending = false; msg.fallback = true; renderChat(); return; }
      var hist = chat.slice(0, -1).filter(function (m) { return !m.fallback && !m.error; }).map(function (m) { return { role: m.role, content: m.content }; });
      hist[hist.length - 1] = { role: 'user', content: PREAMBLE + '\n' + ctx.text + '\n\n# 質問\n' + q };
      if (hist[0].role !== 'user') hist.shift();
      hist = hist.reduce(function (acc, m) { var l = acc[acc.length - 1]; if (l && l.role === m.role) l.content += '\n\n' + m.content; else acc.push({ role: m.role, content: m.content }); return acc; }, []);
      asking = new AbortController();
      sample(hist, { modelTier: 'default', cache: false, signal: asking.signal, onText: function (e) { msg.content = e.text; msg.pending = false; paintLast(); } })
        .then(function (res) { msg.content = res.text; msg.truncated = res.truncated; })
        .catch(function (err) { msg.error = err && err.code === 'rate_limited' ? '質問が続いたため、少し時間を置いてからもう一度送ってください。' : err && err.code === 'not_granted' ? 'AIへの質問が許可されていません。教材から関連する解説を表示します。' : 'AIからの回答を受け取れませんでした。'; if (err && err.code === 'not_granted') { sampleOK = false; msg.fallback = true; } if (err && err.text) msg.content = err.text; })
        .then(function () { msg.pending = false; asking = null; renderChat(); });
    });
  }
  function fallbackAnswer(m) {
    var q = chat[chat.indexOf(m) - 1].content, r = search(keywords(q).join(' '));
    var term = r.hits.filter(function (x) { return x.d.type === 'term'; })[0];
    var les = r.hits.filter(function (x) { return x.d.type === 'lesson'; }).slice(0, 3);
    var h = '<p class="sub">AIへの質問は、このページをclaude.aiで開いた時に使えます。ここでは教材から関連する解説を表示します。</p>';
    if (term) h += '<h4>' + esc(term.d.title) + '</h4><p>' + esc(term.d.text) + '</p>';
    les.forEach(function (x) { h += '<h4><a href="' + x.d.href + '">' + esc(x.d.title) + '</a></h4><p>' + snippet(x.d, r.vars, 220) + '</p>'; });
    if (!term && !les.length) h += '<p>教材に一致する内容が見つかりませんでした。短い言葉(例: 「逆イールド」)で検索してみてください。</p>';
    return h;
  }
  function msgHTML(m, i) {
    if (m.role === 'user') return '<div class="msg msg-u"><span class="msg-who">YOU</span><div class="msg-b">' + esc(m.content) + '</div></div>';
    var body = m.pending ? '<p class="typing">考えています…</p>' : m.fallback ? fallbackAnswer(m) : '<div class="prose">' + md(m.content) + '</div>' + (m.truncated ? '<p class="sub">回答が長いため途中で終わっています。「続けて」と送ると続きを聞けます。</p>' : '');
    if (m.error) body += '<p class="warn"><span class="warn-label">エラー</span>' + esc(m.error) + '</p>';
    var rel = (m.related || []).filter(function (x) { return x.d.href; }).slice(0, 4);
    return '<div class="msg msg-a" data-i="' + i + '"><span class="msg-who">DOJO</span><div class="msg-b">' + body +
      (rel.length && !m.pending ? '<div class="msg-rel"><span class="chips-label">教材</span>' + rel.map(function (x) { return '<a class="chip" href="' + x.d.href + '">' + esc(x.d.title) + '</a>'; }).join('') + '</div>' : '') + '</div></div>';
  }
  function paintLast() {
    var box = $('#chat'); if (!box) return;
    var i = chat.length - 1, el = box.querySelector('.msg-a[data-i="' + i + '"] .msg-b');
    if (el) el.innerHTML = '<div class="prose">' + md(chat[i].content) + '</div>';
    var stop = $('#ask-stop'); if (stop) stop.hidden = !asking;
  }
  function renderChat() {
    var box = $('#chat'); if (!box) return;
    box.innerHTML = chat.length ? chat.map(msgHTML).join('') : '<div class="chat-empty"><p>相場・企業分析・チャート・リスク管理など、知りたいことを文章で質問してください。教材の該当部分' + (MK ? 'と今日の相場データ' : '') + 'をもとに答えます。</p><div class="chips">' + ASK_SUGGEST.map(function (s) { return '<button type="button" class="chip" data-ask="' + esc(s) + '">' + esc(s) + '</button>'; }).join('') + '</div></div>';
    var last = box.lastElementChild; if (last && chat.length) last.scrollIntoView({ block: 'nearest' });
    var stop = $('#ask-stop'); if (stop) stop.hidden = !asking;
  }
  function viewAsk() {
    return '<div class="page-head"><h1>質問する</h1><p class="lead">分からないことをそのまま聞いてください。アプリの教材' + (MK ? 'と今日の相場データ' : '') + 'を参照して答えます。</p><p class="mode"><span class="dot"></span><span id="ask-mode">' + (sampleOK === false ? '教材から関連する解説を表示' : sampleOK ? 'AIが教材をもとに回答' : '確認中…') + '</span></p></div>' +
      '<section class="chat-panel"><div id="chat" class="chat"></div><form id="ask-form" class="ask-form"><textarea id="ask-in" rows="2" placeholder="例: 決算で窓を開けた株を翌日に買う時、何を確認すればいい?" aria-label="質問"></textarea><div class="ask-actions"><button type="button" class="btn ghost" id="ask-stop" hidden>止める</button><button type="button" class="btn ghost" id="ask-clear">会話をリセット</button><button type="submit" class="btn">送信</button></div></form></section>' +
      '<p class="disclaimer">回答は学習の参考です。AIの回答には誤りが含まれることがあります。売買の判断は、ご自身で確認してから行ってください。</p>';
  }

  /* ================= 画面: ホーム ================= */
  function nextLesson() {
    var last = state.last && lessonById[state.last], pool = last ? last.home.items : [];
    for (var i = 0; i < pool.length; i++) if (!state.done[pool[i].id]) return pool[i];
    for (var j = 0; j < lessons.length; j++) if (!state.done[lessons[j].id]) return lessons[j];
    return null;
  }
  function marketMini() {
    if (!mkReady) return '<p class="sub">読み込み中…</p>';
    if (!MK) return '<p>今日の相場データはまだありません。毎朝、既存のニュースBotが公的統計(FRED)から指数・金利・為替・VIXなどを取得して、この画面に表示します(GitHub Pagesで公開した版で有効になります)。</p><p><a href="#lesson-daily-read">値動きを読み解く手順を先に学ぶ →</a></p>';
    var r = K.mkt.regime(MK), rows = ['SP500', 'NASDAQCOM', 'NIKKEI225', 'DGS10', 'DEXJPUS', 'VIXCLS'].filter(function (id) { return MK.series[id]; });
    return (r ? '<p class="regime-t">' + esc(r.title) + '<span class="sub"> ・ ' + esc(r.date) + '</span></p><p class="sub">' + esc(r.text) + '</p>' : '') +
      '<div class="table-wrap"><table class="num"><tbody>' + rows.map(function (id) { var st = mkStats(id); return '<tr><td>' + esc(MK.series[id].name) + '</td><td>' + fmtLevel(st) + '</td><td class="' + cls(st.d1) + '">' + fmtChg(st, 'd1') + '</td><td class="' + cls(st.d21) + '">' + fmtChg(st, 'd21') + '</td></tr>'; }).join('') + '</tbody></table></div><p><a href="#market">今日の相場を詳しく見る →</a></p>';
  }
  function skillHTML() {
    return '<div class="skill">' + K.areas.map(function (a) {
      var d = doneRateOf(areaLessons(a.id)), m = mastery(a.id);
      return '<a class="skill-row" href="#library-' + a.id + '"><span class="skill-n">' + aico(a.id) + esc(a.name) + '</span><span class="skill-v">読了 ' + d + '% ・ 定着 ' + m + '%</span><span class="meter"><i style="width:' + d + '%"></i><i style="width:' + m + '%"></i></span></a>';
    }).join('') + '</div><p class="legend"><span><i></i>読了</span><span><i class="on"></i>定着(復習で正解を重ねた割合)</span></p>';
  }
  function lessonChart(l) { var m = /\{chart:([\w-]+)\}/.exec(l.body); return m ? chartById[m[1]] : null; }
  /* 領域ごとの棚: 見出しの行と、横に流れる小さなタイル */
  function shelf(a) {
    var ls = areaLessons(a.id), d = ls.filter(function (l) { return state.done[l.id]; }).length, tiles = '', pics = 0;
    var order = ls.filter(function (l) { return !state.done[l.id]; }).concat(ls.filter(function (l) { return state.done[l.id]; }));
    order.slice(0, 12).forEach(function (l) {
      var c = lessonChart(l);
      if (c && pics < 3) { pics++; tiles += '<a class="mini pic" href="#lesson-' + l.id + '" aria-label="' + esc(l.t) + '" data-spark="' + c.id + '"></a>'; }
      tiles += '<a class="mini' + (state.done[l.id] ? ' done' : '') + '" href="#lesson-' + l.id + '"><span>' + esc(l.t) + '</span></a>';
    });
    var next = order.filter(function (l) { return !state.done[l.id]; })[0];
    if (next) tiles += '<a class="mini todo" href="#lesson-' + next.id + '"><span><i class="ring"></i>次は「' + esc(next.t) + '」</span></a>';
    return '<section class="shelf"><a class="shelf-head" href="#library-' + a.id + '">' + aico(a.id) + '<strong>' + esc(a.name) + '</strong><span class="shelf-n">' + d + ' / ' + ls.length + '<i>›</i></span></a><div class="shelf-row">' + tiles + '</div></section>';
  }
  function viewHome() {
    var nx = nextLesson(), due = dueList().length, ov = overall(), dr = state.drill, r = MK && K.mkt.regime(MK);
    var started = Object.keys(state.done).length > 0;
    var h = '<section class="hero"><div class="chart" id="hero-chart"></div><div class="hero-top"><div id="ticker" class="ticker" hidden></div></div><p class="hero-cap">' +
      (r ? esc(r.date.slice(5).replace('-', '月') + '日') + ' ・ ' + esc(r.title) : '株トレ道場 ・ 日本株と米国株をプロの水準まで') + '</p></section>';
    h += '<section class="say"><p>' + (r ? esc(r.text) : nx ? (started ? '続きは「' + esc(nx.t) + '」。' : 'まずは「' + esc(nx.t) + '」から。') + esc(nx.sum) : '全レッスンを読み終えました。あとは復習と演習で磨きます。') + '</p>' +
      '<div class="actions">' + (r ? (AN ? '<a class="btn" href="#why">なぜ動いたか</a>' : '') + '<a class="btn' + (AN ? ' ghost' : '') + '" href="#outlook">今後の見立てを見る</a><a class="btn ghost" href="#market">今日の相場</a>' : '') + (nx ? '<a class="btn' + (r ? ' ghost' : '') + '" href="#lesson-' + nx.id + '">' + (started ? '続きから読む' : '読み始める') + '</a>' : '') + (due ? '<a class="btn ghost" href="#review">復習 ' + due + '問</a>' : '') + '</div>' +
      '<p class="stamp">' + ov.rank + ' ・ 定着 ' + ov.score + '% ・ 演習 ' + dr.n + '回</p></section>';
    K.areas.forEach(function (a) { h += shelf(a); });
    h += '<div class="dash">';
    h += '<section class="span-6"><h2>' + ico('chat') + '質問する</h2><form class="ask-mini" id="ask-mini"><input id="ask-mini-in" placeholder="例: 逆イールドが解消に向かう時、なぜ警戒する?" aria-label="質問"><button class="btn" type="submit">送信</button></form><div class="chips">' + ASK_SUGGEST.slice(0, 3).map(function (x) { return '<button type="button" class="chip" data-ask="' + esc(x) + '">' + esc(x) + '</button>'; }).join('') + '</div></section>';
    h += '<section class="span-6"><h2>' + ico('target') + 'チャート演習<a class="h-r" href="#drill">開く ›</a></h2><p>右側を隠したチャートを見て、その後の展開と確信度を答えます。学習用の型' + (MK ? 'と、実際の指数' : '') + 'で練習できます。</p><div class="actions"><a class="btn" href="#drill">演習を始める</a></div></section>';
    if (MK) h += '<section class="span-12"><h2>' + ico('pulse') + '今日の相場<a class="h-r" href="#market">詳しく ›</a></h2>' + marketMini() + '</section>';
    h += '<section class="span-12"><h2>' + ico('grid') + '習熟マップ</h2>' + skillHTML() + '</section>';
    h += '<section class="span-12"><h2>' + ico('person') + '勝ち残る人に共通する5つの原則<a class="h-r" href="#traders">人物 ›</a></h2><ol class="principles">' + K.principles.map(function (x) { return '<li><strong>' + esc(x[0]) + '</strong><span>' + esc(x[1]) + '</span></li>'; }).join('') + '</ol></section>';
    h += '</div><p class="disclaimer">学習を目的とした教材で、特定の銘柄の売買をすすめるものではありません。学習用のチャートは作成したもので、実在の銘柄ではありません。実際の指数データは公的統計(FRED)によります。投資の判断と結果の責任はご自身にあります。</p>';
    return h;
  }
  function areaGrid() {
    return '<div class="area-grid">' + K.areas.map(function (a) {
      return '<div class="area"><a class="area-h" href="#library-' + a.id + '">' + aico(a.id) + esc(a.name) + '</a><ul>' + a.topics.map(function (t) {
        var d = t.items.filter(function (l) { return state.done[l.id]; }).length;
        return '<li><a href="#topic-' + t.id + '"><span>' + esc(t.name) + '</span><em>' + d + '/' + t.items.length + '</em></a></li>';
      }).join('') + '</ul></div>';
    }).join('') + '</div>';
  }

  /* ================= 画面: ライブラリとトピック ================= */
  function lessonRow(l) {
    return '<li><a href="#lesson-' + l.id + '" class="' + (state.done[l.id] ? 'done' : '') + '"><span class="check" aria-hidden="true">' + (state.done[l.id] ? '✓' : '') + '</span><span class="ll-body"><strong>' + esc(l.t) + ' ' + lvTag(l) + '</strong><span>' + esc(l.sum) + '</span></span><span class="ll-min">' + readMin(l) + '分</span></a></li>';
  }
  function readMin(l) { return Math.max(3, Math.round(plain(l.body).length / 600)); }
  function levelChips(cur) {
    return '<div class="chips"><span class="chips-label">レベル</span><a class="chip' + (!cur ? ' on' : '') + '" href="#library">すべて</a>' + LEVELS.map(function (x) { return '<a class="chip' + (cur === x[1] ? ' on' : '') + '" href="#library-' + x[1] + '">' + x[0] + ' <em>' + lessons.filter(function (l) { return l.level === x[0]; }).length + '</em></a>'; }).join('') + '</div>';
  }
  function viewLibrary(arg) {
    var h = '<div class="page-head"><h1>ライブラリ</h1><p class="lead">知りたいことから引けるよう、' + lessons.length + 'のレッスンを' + K.topics.length + 'のトピックに分けています。順番に読む必要はありません。</p>' + levelChips(levelBySlug[arg] ? arg : '') + '</div>';
    if (levelBySlug[arg]) {
      var lv = levelBySlug[arg];
      K.areas.forEach(function (a) {
        var ls = areaLessons(a.id).filter(function (l) { return l.level === lv; });
        if (ls.length) h += '<section><h2>' + esc(a.name) + '</h2><ul class="lesson-list">' + ls.map(lessonRow).join('') + '</ul></section>';
      });
      return h;
    }
    var areas = areaById[arg] ? [areaById[arg]] : K.areas;
    areas.forEach(function (a) {
      h += '<section><h2>' + esc(a.name) + '</h2><p class="sub">' + esc(a.note) + '</p><div class="topic-grid">' + a.topics.map(function (t) {
        var d = t.items.filter(function (l) { return state.done[l.id]; }).length;
        var lvs = {}; t.items.forEach(function (l) { lvs[l.level] = 1; });
        return '<a class="topic-card" href="#topic-' + t.id + '"><strong>' + esc(t.name) + '</strong><span class="tc-l">' + t.items.map(function (l) { return esc(l.t); }).join(' / ') + '</span><span class="tc-m">' + Object.keys(lvs).map(function (x) { return lvTag({ level: x }); }).join('') + '<em>' + d + '/' + t.items.length + '</em></span></a>';
      }).join('') + '</div></section>';
    });
    if (areaById[arg]) h += areaTestHTML(arg);
    return h;
  }
  function areaTestHTML(aid) {
    var nCase = K.cases.filter(function (c) { return c.area === aid; }).length, best = state.tests[aid];
    return '<section><h2>' + esc(areaById[aid].name) + 'のテスト</h2><p class="sub">この領域の確認問題' + (nCase ? 'とケース演習' : '') + 'から10問。8問以上で合格。' + (best != null ? ' 最高: ' + best + ' / 10' : '') + '</p><div class="actions"><button type="button" class="btn" data-review="test-' + aid + '">テストを始める</button>' +
      (nCase ? '<button type="button" class="btn ghost" data-review="case-' + aid + '">ケース演習(' + nCase + '問)</button>' : '') + '</div><div id="session"></div></section>';
  }
  function viewTopic(id) {
    var t = topicById[id]; if (!t) return notFound();
    var a = areaById[t.area], inT = {}; t.items.forEach(function (l) { inT[l.id] = 1; });
    var hit = function (x) { return x.lessons.some(function (y) { return inT[y]; }); };
    var macros = K.macro.filter(hit), who = K.traders.filter(hit), body = t.items.map(function (l) { return l.body; }).join('\n'), cs = [];
    K.charts.forEach(function (c) { if (body.indexOf('{chart:' + c.id + '}') >= 0) cs.push(c); });
    var counts = termNames.map(function (n) { return [n, body.split(n).length - 1]; }).filter(function (x) { return x[1] > 1; }).sort(function (x, y) { return y[1] - x[1]; }).slice(0, 16);
    var d = t.items.filter(function (l) { return state.done[l.id]; }).length;
    var h = '<div class="page-head"><p class="crumb"><a href="#library-' + a.id + '">' + esc(a.name) + '</a></p><h1>' + esc(t.name) + '</h1><div class="meter big"><i style="width:' + Math.round(d / t.items.length * 100) + '%"></i></div><p class="sub">' + d + ' / ' + t.items.length + ' 読了 ・ 合計 約' + t.items.reduce(function (s, l) { return s + readMin(l); }, 0) + '分</p></div>';
    h += '<div class="dash"><section class="span-8"><h2>レッスン<span class="h-r">' + t.items.length + '</span></h2><ul class="lesson-list">' + t.items.map(lessonRow).join('') + '</ul></section><div class="span-4 stack">';
    if (counts.length) h += '<section><h2>重要語</h2><div class="chips">' + counts.map(function (x) { return '<button type="button" class="chip" data-term="' + esc(x[0]) + '">' + esc(x[0]) + '</button>'; }).join('') + '</div></section>';
    if (macros.length) h += '<section><h2>因果マップ</h2><ul class="plain">' + macros.map(function (m) { return '<li><a href="#macro-' + m.id + '">' + esc(m.title) + '</a></li>'; }).join('') + '</ul></section>';
    if (who.length) h += '<section><h2>参考にする投資家</h2><ul class="plain">' + who.map(function (x) { return '<li><a href="#trader-' + x.id + '">' + esc(x.name) + '</a> <span class="sub">' + esc(x.style) + '</span></li>'; }).join('') + '</ul></section>';
    h += '<section><h2>質問する</h2><p class="sub">このトピックで分からないことを聞く</p><button type="button" class="btn ghost" data-ask="' + esc(t.name + 'について、プロのトレーダーが実際に見ているポイントを具体例つきで教えて') + '">プロの見方を質問する</button></section></div></div>';
    if (cs.length) h += '<section><h2>このトピックのチャート</h2><div class="chart-grid">' + cs.map(function (c) { return '<a class="chart-card" href="#chart-' + c.id + '"><div class="chart" data-chart="' + c.id + '" data-plain="1"></div><strong>' + esc(c.name) + '</strong></a>'; }).join('') + '</div></section>';
    h += areaTestHTML(a.id);
    return h;
  }

  /* ================= 画面: レッスン ================= */
  function viewLesson(id) {
    var l = lessonById[id];
    if (!l) return notFound();
    state.last = id; save();
    var t = l.home, idx = t.items.indexOf(l), prev = t.items[idx - 1], next = t.items[idx + 1];
    var related = K.macro.filter(function (m) { return m.lessons.indexOf(id) >= 0; });
    var who = K.traders.filter(function (x) { return x.lessons.indexOf(id) >= 0; });
    var toc = [], body = md(l.body, toc);
    var h = '<article class="lesson"><div class="lesson-head"><p class="crumb"><a href="#library-' + l.area.id + '">' + esc(l.area.name) + '</a> / <a href="#topic-' + t.id + '">' + esc(t.name) + '</a> ・ ' + (idx + 1) + ' / ' + t.items.length + '</p>' +
      '<h1>' + esc(l.t) + '</h1><p class="lead">' + esc(l.sum) + '</p><p class="meta">' + lvTag(l) + '<span>約' + readMin(l) + '分</span>' + (state.done[id] ? '<span class="up">読了</span>' : '') + (l.topics.length > 1 ? '<span>ほかのトピック: ' + l.topics.slice(1).map(function (x) { return '<a href="#topic-' + x.id + '">' + esc(x.name) + '</a>'; }).join('、') + '</span>' : '') + '</p></div>';
    h += '<div class="lesson-grid"><div class="lesson-main"><div class="prose">' + body + '</div>';
    if (related.length || who.length) {
      h += '<aside class="card related"><h3>あわせて見る</h3><ul class="plain">' +
        related.map(function (m) { return '<li><span class="res-k">因果マップ</span> <a href="#macro-' + m.id + '">' + esc(m.title) + '</a></li>'; }).join('') +
        who.map(function (x) { return '<li><span class="res-k">トレーダー研究</span> <a href="#trader-' + x.id + '">' + esc(x.name) + '</a></li>'; }).join('') + '</ul></aside>';
    }
    h += '<section class="quiz" id="lesson-quiz" data-lesson="' + id + '"><h2>確認問題<span class="h-r">' + l.quiz.length + '問</span></h2><p class="sub">本文を見返さずに答えてください。全問に答えると読了になり、問題は復習に入ります。</p>' +
      l.quiz.map(function (q, i) { return quizHTML(q, i, l.quiz.length); }).join('') + '<div class="quiz-done" hidden></div></section>';
    h += '<nav class="pager">' + (prev ? '<a href="#lesson-' + prev.id + '">← ' + esc(prev.t) + '</a>' : '<a href="#topic-' + t.id + '">← ' + esc(t.name) + '</a>') + (next ? '<a href="#lesson-' + next.id + '">' + esc(next.t) + ' →</a>' : '<a href="#topic-' + t.id + '">トピックへ戻る →</a>') + '</nav></div>';
    h += '<aside class="toc"><p class="toc-h">目次</p><ol>' + toc.map(function (x) { return '<li><a href="#lesson-' + id + '" data-goto="' + x[0] + '">' + esc(x[1]) + '</a></li>'; }).join('') + '</ol><button type="button" class="btn ghost small" data-ask="' + esc('「' + l.t + '」で、') + '" data-ask-edit="1">このレッスンについて質問</button></aside></div></article>';
    return h;
  }
  function lessonAnswered(sec) {
    var all = $$('.q', sec), done = $$('.q[data-done]', sec);
    if (done.length < all.length) return;
    var id = sec.dataset.lesson, l = lessonById[id], t = l.home, next = t.items[t.items.indexOf(l) + 1];
    state.done[id] = state.done[id] || Date.now(); save();
    var box = sec.querySelector('.quiz-done');
    box.hidden = false;
    box.innerHTML = '<p><strong>読了。</strong> ' + all.length + '問中 ' + Math.max(0, all.length - $$('.opt.wrong', sec).length) + '問正解。間違えた問題はすぐに、正解した問題は明日また出題されます。</p>' +
      (next ? '<a class="btn" href="#lesson-' + next.id + '">次へ: ' + esc(next.t) + '</a>' : '<a class="btn" href="#topic-' + t.id + '">トピックへ戻る</a>');
  }

  /* ================= 画面: 今日の相場 ================= */
  function viewMarket() {
    var h = '<div class="page-head"><h1>今日の相場</h1>';
    if (!mkReady) return h + '<p class="lead">読み込み中…</p></div>';
    if (!MK) {
      return h + '<p class="lead">公的統計(FRED)の指数・金利・為替・VIXなどの数値から、今日の値動きの型と、指数のトレンドの状態を表示する画面です。</p></div>' +
        '<section><h2>データがまだありません</h2><p>この画面のデータは、毎朝6時に動く既存のニュースBotが <code>learn/data/market.json</code> として書き出します。GitHub Pagesで公開した版で、Botが一度動いた後から表示されます。</p><p>それまでは、読み解きの手順を先に身につけておきましょう。</p><div class="actions"><a class="btn" href="#lesson-daily-read">今日の値動きを読み解く手順</a><a class="btn ghost" href="#macro">因果マップ</a><a class="btn ghost" href="#drill">チャート演習</a></div></section>';
    }
    var r = K.mkt.regime(MK);
    h += '<p class="lead">データ更新 ' + esc((MK.updated || '').replace('T', ' ').slice(0, 16)) + ' ・ 出典 ' + esc(MK.source || 'FRED') + '。各系列の最新の日付は系列ごとに異なります。</p></div><div class="dash">';
    if (r) {
      h += '<section class="span-7"><h2>今日の値動きの型<span class="h-r">' + esc(r.date) + '</span></h2><p class="regime-t">' + esc(r.title) + '</p><p>' + esc(r.text) + '</p><ul class="facts">' + r.facts.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' +
        (r.notes.length ? '<ul class="plain notes">' + r.notes.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
        '<p class="sub">組み合わせから当てはめた目安です。原因の確定には、材料の時刻と業種ごとの動きで裏を取ります。</p><div class="actions"><a class="btn" href="#outlook">相場の見立て(今後の見通し)を見る</a><button type="button" class="btn" data-ask="今日の相場の動きを、データから読み解いてください。何が効いた可能性が高く、何を確かめるべきか、日本株への影響も含めて。">AIに読み解いてもらう</button>' + r.lessons.map(function (x) { return lessonById[x] ? '<a class="btn ghost" href="#lesson-' + x + '">' + esc(lessonById[x].t) + '</a>' : ''; }).join('') + '</div></section>';
    }
    h += '<section class="span-5"><h2>あなたの3行メモ</h2><p class="sub">何が起きたか / なぜか(仮説) / 何を確かめるか</p><textarea id="mk-note" rows="7" placeholder="何が起きたか: \nなぜか: \n何を確かめるか: ">' + esc(state.notes[r ? r.date : 'x'] || '') + '</textarea><p class="sub" id="mk-note-s">このブラウザに日付ごとに保存されます。</p></section>';
    h += '<section class="span-12"><h2>主要な数値</h2><div class="table-wrap"><table class="num quotes"><thead><tr><th>系列</th><th>日付</th><th>最新</th><th>前日比</th><th>5日</th><th>1か月</th><th>3か月</th><th>状態</th><th>60日</th></tr></thead><tbody>' +
      K.mkt.ORDER.filter(function (id) { return MK.series[id]; }).map(function (id) {
        var s = MK.series[id], st = K.mkt.stats(s.rows, s.kind), v = s.rows.slice(-60).map(function (x) { return x[1]; });
        return '<tr><td>' + esc(s.name) + '</td><td>' + esc(st.date.slice(5)) + '</td><td>' + fmtLevel(st) + '</td><td class="' + cls(st.d1) + '">' + fmtChg(st, 'd1') + '</td><td class="' + cls(st.d5) + '">' + fmtChg(st, 'd5') + '</td><td class="' + cls(st.d21) + '">' + fmtChg(st, 'd21') + '</td><td class="' + cls(st.d63) + '">' + fmtChg(st, 'd63') + '</td><td>' + (st.stage ? '<span class="pill ' + st.stage.cls + '">' + esc(st.stage.name) + '</span>' : '') + '</td><td class="tick-cell">' + K.renderTick(v, 84, 22, v[v.length - 1] >= v[0]) + '</td></tr>';
      }).join('') + '</tbody></table></div><p class="sub">金利・スプレッドの変化はベーシスポイント(bp、0.01%)。状態は終値と50日・200日平均から判定した目安。</p></section>';
    ['SP500', 'NASDAQCOM', 'NIKKEI225', 'DJIA', 'DEXJPUS'].filter(function (id) { return MK.series[id] && MK.series[id].rows.length > 60; }).forEach(function (id) {
      var s = MK.series[id], st = K.mkt.stats(s.rows, s.kind);
      h += '<section class="span-6"><h2>' + esc(s.name) + '<span class="h-r">' + esc(st.date) + '</span></h2><div class="chart" data-series="' + id + '"></div><ul class="plain desc">' + K.mkt.describe(st).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></section>';
    });
    if (MK.headline || (MK.points || []).length) {
      h += '<section class="span-12"><h2>ニュースの要点</h2>' + (MK.headline ? '<p class="regime-t">' + esc(MK.headline) + '</p>' : '') + '<ul>' + (MK.points || []).map(function (p) { return '<li>' + (p.category ? '<span class="pill flat">' + esc(p.category) + '</span> ' : '') + esc(p.text) + '</li>'; }).join('') + '</ul><p class="sub">毎朝のニュースBotがAIで要約した内容です。数値は記事と照合済みのものだけを載せています。</p></section>';
    }
    h += '<section class="span-12"><h2>次に確かめること</h2><ol><li>動き始めた時刻と、経済指標・発言・決算の時刻は合っているか</li><li>どの業種が主導したか(金利に敏感な業種か、景気敏感か、特定の企業か)</li><li>値上がり銘柄数と値下がり銘柄数(相場の幅)は指数と同じ方向か</li><li>主導株は50日平均を守っているか。翌日も同じ方向に続くか</li><li>日本株: 日経平均先物、SOX指数、ドル円の順に確認</li></ol></section></div>';
    return h;
  }
  function drawMarketCharts() {
    $$('[data-series]', view).forEach(function (el) {
      var s = MK.series[el.dataset.series], rows = s.rows.slice(-460), pre = Math.max(0, rows.length - 260);
      el._draw = function (w) { el.innerHTML = K.renderSeries(rows.map(function (x) { return x[1]; }), { w: w, h: 180, pre: pre, mas: [50, 200].filter(function (m) { return s.rows.length > m; }), labels: rows.map(function (x) { return x[0]; }), label: s.name }); };
    });
  }


  /* ================= 画面: 相場の見立て ================= */
  var olAI = { text: '', state: 'idle', err: '' };
  var OL_PREAMBLE = 'あなたはヘッジファンドで20年以上の経験を持つプロのトレーダー兼アナリストです。マイケル・バーリやジム・チェイノスのような空売り筋・懐疑派の視点と、オニールやミネルヴィニのようなトレンドフォローの視点、ドラッケンミラーのようなマクロと流動性の視点、オプション市場の読み方を併せ持っています。\n' +
    '下の「採点結果」と「市場データ」だけを根拠に、今の米国株と日本株の状況を、個人投資家に向けて日本語で詳しく分析し、今後の見通しを立ててください。\n' +
    'ルール:\n1. データに無いニュースや出来事、データに無い最新の数値を作らない。原因はデータから推定できる範囲で「〜の可能性が高い」と書き、事実と推定をはっきり分ける。\n' +
    '2. 結論をあいまいにしない。短期(数日〜2週間)と中期(1〜3か月)それぞれで「上昇が続く/下落が続く/揉み合い」のどれが最も可能性が高いかと、その確率の目安を示す。\n' +
    '3. 次の見出しで書く: 「## 結論」「## なぜ今の株価になっているのか」「## 弱気筋(バーリ・空売り筋)ならこう見る」「## 強気筋ならこう見る」「## チャートから」「## オプション・恐怖指数から」「## シナリオと注目の価格水準」「## 見立てが変わる条件」「## 日本株への影響」「## 個人投資家としての動き方」。\n' +
    '4. 「個人投資家としての動き方」では特定の銘柄を勧めず、投資比率、損切り、待つべき合図など、行動の原則を書く。\n' +
    '5. このデータに含まれない情報(個別企業の決算、出来高、相場の幅、プット・コール・レシオなど)が判断に重要な場合は、「確認すべきこと」として挙げる。\n' +
    '6. 表(| 区切り)と箇条書き(- )を使って読みやすくする。\n';
  function runOutlookAI() {
    if (!MK || olAI.state === 'run') return;
    var o = K.mkt.outlook(MK); if (!o) return;
    olAI = { text: '', state: 'run', err: '' }; paintOutlookAI();
    getSample().then(function (sample) {
      if (!sample) { olAI.state = 'none'; paintOutlookAI(); return; }
      sample(OL_PREAMBLE + '\n' + K.mkt.outlookContext(MK, o), { modelTier: 'complex', cache: true, onText: function (e) { olAI.text = e.text; paintOutlookAI(); } })
        .then(function (r) { olAI.text = r.text; olAI.state = 'done'; })
        .catch(function (err) { olAI.state = 'err'; olAI.err = err && err.code === 'rate_limited' ? '少し時間を置いてからもう一度押してください。' : err && err.code === 'not_granted' ? 'AIの利用が許可されていません。' : 'AIからの回答を受け取れませんでした。'; if (err && err.text) olAI.text = err.text; })
        .then(paintOutlookAI);
    });
  }
  function paintOutlookAI() {
    var el = $('#ol-ai'); if (!el) return;
    if (olAI.state === 'idle') { el.innerHTML = ''; return; }
    if (olAI.state === 'none') { el.innerHTML = '<p class="sub">AIによる解説は、このページをclaude.aiで開いた時に使えます。上の採点と各視点の説明が、同じ材料にもとづく分析です。</p>'; return; }
    el.innerHTML = (olAI.text ? '<div class="prose">' + md(olAI.text) + '</div>' : '<p class="typing">データを読み込んで分析しています…</p>') + (olAI.state === 'err' ? '<p class="warn"><span class="warn-label">エラー</span>' + esc(olAI.err) + '</p>' : '');
  }
  function sigChip(v, label) {
    var c = v >= 0.5 ? 'up' : v <= -0.5 ? 'down' : 'flat', t = v >= 1.5 ? '強気' : v >= 0.5 ? 'やや強気' : v <= -1.5 ? '弱気' : v <= -0.5 ? 'やや弱気' : '中立';
    return '<span class="pill ' + c + '">' + label + ' ' + t + '</span>';
  }
  function verdictBox(v, title) {
    return '<div class="verdict ' + v.cls + '"><p class="v-span">' + title + '(' + v.span + ')</p><p class="v-label">' + esc(v.label) + '</p><div class="v-bar"><i style="width:' + v.up + '%"></i></div><p class="v-p"><span class="up">上昇 ' + v.up + '%</span><span class="down">下落 ' + v.down + '%</span></p></div>';
  }
  var LENS_INFO = [
    ['トレンド', 'オニール / ミネルヴィニ / ワインスタイン', '株価と50日・200日平均の位置と向き。上昇トレンドが崩れるまでは逆らわない。'],
    ['勢いと過熱', '逆張りの投資家', 'RSIと平均線からの離れ具合。行き過ぎは短期の反動を生む。'],
    ['恐怖と保険(オプション市場)', 'オプション市場', 'VIXの水準と、1か月先と3か月先の予想変動率の関係。恐怖のピークは短期の底になりやすい。'],
    ['信用', 'マイケル・バーリ / 空売り筋', '低格付け社債の上乗せ金利。信用市場は株より先に悪化することが多い。'],
    ['金利と金融政策', 'ドラッケンミラー', '長短金利の変化と組み合わせ。FRBに逆らわない。'],
    ['流動性', 'マクロ投資家', 'FRBの総資産と金融環境指数。お金の量と借りやすさ。'],
    ['ドル', 'グローバルマクロ', 'ドル指数。強すぎるドルは世界のリスク資産の重し。']
  ];
  function viewOutlook() {
    var h = '<div class="page-head"><h1>相場の見立て</h1><p class="lead">プロのトレーダーとアナリストが使う7つの視点で、今の株価がなぜこうなっているのか、この先どうなりやすいのかを組み立てます。マイケル・バーリや空売り筋の懐疑的な目線も入れています。</p></div>';
    if (!mkReady) return h + '<section><p class="sub">読み込み中…</p></section>';
    var o = MK && K.mkt.outlook(MK);
    if (!o) {
      return h + '<section><h2>' + ico('pulse') + 'データを待っています</h2><p>この画面は、毎朝のニュースBotが公的統計(FRED)から書き出す市場データを使います。公開版でBotが一度動いた後から、毎朝自動で見立てが更新されます。</p><div class="actions"><a class="btn" href="#lesson-outlook-method">見立ての作り方を学ぶ</a><a class="btn ghost" href="#lesson-short-sellers">バーリ・空売り筋の思考</a></div></section>' +
        '<section><h2>' + ico('grid') + '使う7つの視点</h2><ul class="lens-list">' + LENS_INFO.map(function (x) { return '<li><strong>' + x[0] + '</strong><span class="sub">' + x[1] + '</span><p>' + x[2] + '</p></li>'; }).join('') + '</ul></section>';
    }
    var reg = K.mkt.regime(MK);
    if (AN && AN.ai && AN.ai.chief) h += '<section class="ai-card"><h2>' + ico('flow') + 'なぜ動いたか(深掘り分析)<a class="h-r" href="#why">詳しく ›</a></h2><p class="why-head">' + esc(AN.ai.chief.headline) + '</p><p>' + esc(AN.ai.chief.us.summary) + '</p><div class="actions"><a class="btn" href="#why">セクター・金利・世界情勢からの分析を見る</a></div></section>';
    else if (AN) h += '<section><h2>' + ico('flow') + 'なぜ動いたか<a class="h-r" href="#why">詳しく ›</a></h2><p>セクター・金利・商品・世界の市場の動きから、値動きの原因を分析しています。</p></section>';
    h += '<section><h2>' + ico('target') + '結論<span class="h-r">' + esc(o.name) + ' ・ ' + esc(o.date) + '</span></h2><div class="verdicts">' + verdictBox(o.short, '短期') + verdictBox(o.mid, '中期') + '</div>' +
      '<p class="sub">確率は7つの視点の採点から置いた目安です。統計的に厳密な予測ではありません。</p></section>';
    var top = o.lenses.slice().sort(function (a, b) { return Math.abs(b.mid) + Math.abs(b.short) - Math.abs(a.mid) - Math.abs(a.short); }).filter(function (l) { return l.mid || l.short; }).slice(0, 3);
    h += '<section><h2>' + ico('chat') + 'なぜ今の株価になっているのか</h2>' + (reg ? '<p><strong>直近の値動き: ' + esc(reg.title) + '。</strong>' + esc(reg.text) + '</p>' : '') +
      (top.length ? '<p>いま相場を最も強く動かしている要因:</p><ol class="why">' + top.map(function (l) { return '<li><strong>' + esc(l.name) + '</strong>(' + esc(l.who) + ')— ' + esc(l.text) + '</li>'; }).join('') + '</ol>' : '<p>どの視点にも強い材料は出ておらず、相場は方向を探っています。</p>') + '</section>';
    h += '<div class="dash"><section class="span-6 bear-card"><h2>' + ico('shield') + '弱気筋・空売り筋の見立て</h2>' + (o.bear.length ? '<ul>' + o.bear.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<p class="sub">いまのデータからは、弱気筋が強く主張できる材料は多くありません。</p>') + '</section>' +
      '<section class="span-6 bull-card"><h2>' + ico('pulse') + '強気筋の見立て</h2>' + (o.bull.length ? '<ul>' + o.bull.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<p class="sub">いまのデータからは、強気筋が強く主張できる材料は多くありません。</p>') + '</section></div>';
    h += '<section><h2>' + ico('grid') + '7つの視点の採点</h2><ul class="lens-list">' + o.lenses.map(function (l) {
      return '<li><div class="lens-h"><strong>' + esc(l.name) + '</strong><span class="sub">' + esc(l.who) + '</span><span class="lens-s">' + sigChip(l.short, '短期') + sigChip(l.mid, '中期') + '</span></div><p class="lens-m">' + esc(l.metric) + '</p><p>' + esc(l.text) + '</p>' + (lessonById[l.lesson] ? '<a class="sub" href="#lesson-' + l.lesson + '">考え方: ' + esc(lessonById[l.lesson].t) + ' ›</a>' : '') + '</li>';
    }).join('') + '</ul></section>';
    h += '<section><h2>' + ico('shield') + 'バーリ流の過熱チェック<span class="h-r">' + o.burry.n + ' / 4</span></h2><ul class="froth">' + o.burry.items.map(function (x) { return '<li class="' + (x[1] ? 'on' : '') + '"><span class="fz">' + (x[1] ? '該当' : '—') + '</span><span>' + esc(x[0]) + '</span><em>' + esc(x[2]) + '</em></li>'; }).join('') + '</ul><p class="sub">3つ以上が重なると、懐疑派が警戒を強める環境。ただし「下がる理由」の蓄積であって、「下がり始めた合図」ではありません。行動はトレンドと信用の変化を待ちます。<a href="#lesson-short-sellers">詳しく</a></p></section>';
    h += '<section><h2>' + ico('target') + 'シナリオと注目の価格水準</h2><ul class="scen">' + o.scenarios.map(function (x) { return '<li><div class="scen-h"><strong class="' + x.cls + '">' + x.name + '</strong><span class="scen-p">' + x.p + '%</span></div><div class="v-bar ' + x.cls + '"><i style="width:' + x.p + '%"></i></div><p>' + esc(x.text) + '</p><p class="sub">確認の条件: ' + esc(x.trigger) + '</p></li>'; }).join('') + '</ul></section>';
    h += '<section><h2>' + ico('redo') + '見立てが変わる条件</h2><ul>' + o.changes.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></section>';
    if (o.jp) h += '<section><h2>' + aico('market') + '日本株への影響</h2><p>' + esc(o.jp.text) + '</p></section>';
    h += '<section class="ai-card"><h2>' + ico('chat') + 'プロのアナリストとしての分析</h2><p class="sub">上の採点と数値を材料に、AIがプロのトレーダー兼アナリストの目線で、原因・弱気筋と強気筋の見方・シナリオ・日本株への影響・動き方まで詳しく書きます。</p><div class="actions"><button type="button" class="btn" id="ol-run">' + (olAI.state === 'done' ? 'もう一度分析する' : '詳しく分析してもらう') + '</button><button type="button" class="btn ghost" data-ask="今日の相場の見立てについて、バーリのような空売り筋が今いちばん警戒しているのは何か、具体的に教えて">質問で深掘りする</button></div><div id="ol-ai"></div></section>';
    h += '<p class="disclaimer">この見立ては公的統計の数値から規則にもとづいて組み立てた学習用の分析で、将来の値動きを保証するものではありません。個別株の決算、出来高、相場の幅、オプションの売買動向は含まれていません。売買の判断はご自身で行ってください。</p>';
    return h;
  }

  /* ================= 画面: なぜ動いたか(深掘り分析) ================= */
  var whyH = 'c1';
  var WHY_ROLES = [['macro', 'マクロ・金利', 'pulse'], ['sector', 'セクター・資金の流れ', 'grid'], ['world', '世界情勢・ニュース', 'flow'], ['bear', '弱気筋(バーリ・空売り筋)', 'shield'], ['bull', '強気筋(トレンド・需給)', 'target']];
  function anName(id) {
    if (/^N\d+$/.test(id)) return 'ニュース' + id.slice(1);
    var lb = AN.ai && AN.ai.labels; if (lb && lb[id]) return lb[id];
    var f = AN.features && AN.features[id]; if (f) return f.name;
    var s = (AN.signals || []).filter(function (x) { return x.id === id; })[0]; return s ? s.name : id;
  }
  function evChips(ev) { return ev && ev.length ? '<div class="ev">' + ev.slice(0, 6).map(function (e) { return /^N\d+$/.test(e) ? '<a class="ev-c" href="#why-news" data-news="' + e + '">' + esc(anName(e)) + '</a>' : '<span class="ev-c">' + esc(anName(e)) + '</span>'; }).join('') + '</div>' : ''; }
  function newsList() {
    var ls = ((AN.ai && AN.ai.news) || []).filter(function (l) { return /^N\d+ /.test(l); });
    if (!ls.length) return '';
    return '<section id="why-news-sec"><details class="panel"><summary>' + ico('book') + '<span><strong>分析に使ったニュース(' + ls.length + '件)</strong><span class="sub">根拠の「ニュース○」は、この番号の記事です。英語の記事は見出しと概要のまま載せています。</span></span></summary><ol class="news-list">' +
      ls.map(function (l) { var m = l.match(/^(N\d+) \(([^,]*), ([^)]*)\) (.*)$/); return m ? '<li id="news-' + m[1] + '"><span class="ev-c">ニュース' + m[1].slice(1) + '</span> <span class="sub">' + esc(m[2]) + ' ・ ' + esc(m[3]) + '</span><p>' + esc(m[4]) + '</p></li>' : '<li>' + esc(l) + '</li>'; }).join('') + '</ol></details></section>';
  }
  function dirPill(d) { return '<span class="pill ' + (d === '上昇' ? 'up' : d === '下落' ? 'down' : 'flat') + '">' + esc(d || 'もみ合い') + '</span>'; }
  function wpct(x, unit) { if (x == null) return '—'; return unit === 'bp' ? (x > 0 ? '+' : '') + Math.round(x) + 'bp' : (x > 0 ? '+' : '') + x.toFixed(2) + '%'; }
  function heatBg(z) { if (z == null) return 'var(--tile)'; var a = Math.min(Math.abs(z) / 2.5, 1) * 0.5 + 0.06; return z >= 0 ? 'rgba(95, 211, 160, ' + a.toFixed(2) + ')' : 'rgba(255, 127, 115, ' + a.toFixed(2) + ')'; }
  function heatGrid(group) {
    var z = 'z' + whyH.slice(1), rs = 'rs' + whyH.slice(1);
    var xs = Object.keys(AN.features).map(function (k) { return AN.features[k]; }).filter(function (f) { return f.group === group; })
      .sort(function (a, b) { return (b[whyH] == null ? -99 : b[whyH]) - (a[whyH] == null ? -99 : a[whyH]); });
    return '<div class="heat">' + xs.map(function (f) {
      return '<div class="heat-t" style="background:' + heatBg(f[z]) + '" title="ふだんの値動きの ' + (f[z] == null ? '—' : Math.abs(f[z]).toFixed(1)) + ' 倍"><span class="heat-n">' + esc(f.name) + '</span><span class="heat-v">' + wpct(f[whyH]) + '</span>' + (f[rs] != null ? '<span class="heat-r">対指数 ' + wpct(f[rs]) + '</span>' : '') + (f.stale && whyH === 'c1' ? '<span class="heat-r">データ遅れ</span>' : '') + '</div>';
    }).join('') + '</div>';
  }
  function sigRow(s) {
    var z = s['z' + whyH.slice(1)], v = s[whyH], w = z == null ? 0 : Math.min(Math.abs(z) / 3, 1) * 50;
    return '<li><div class="sig-h"><strong>' + esc(s.name) + '</strong><span class="' + (v > 0 ? 'up' : v < 0 ? 'down' : '') + '">' + wpct(v) + '</span></div>' +
      '<div class="sig-bar"><i class="' + (v >= 0 ? 'pos' : 'neg') + '" style="width:' + w + '%"></i></div><p class="sub">' + esc(s.meaning) + (z != null && Math.abs(z) >= 1.5 ? ' <strong class="hot">ふだんの' + Math.abs(z).toFixed(1) + '倍の動き</strong>' : '') + '</p></li>';
  }
  function crossTable(groups) {
    var xs = Object.keys(AN.features).map(function (k) { return AN.features[k]; }).filter(function (f) { return groups.indexOf(f.group) >= 0 && f.group !== 'us' && f.group !== 'jp'; });
    return '<div class="table-wrap"><table class="num"><thead><tr><th>市場</th><th>水準</th><th>1日</th><th>5日</th><th>20日</th></tr></thead><tbody>' + xs.map(function (f) {
      var lv = f.unit === 'bp' ? f.last.toFixed(2) + '%' : f.last >= 1000 ? Math.round(f.last).toLocaleString('ja-JP') : f.last.toFixed(2);
      return '<tr><td>' + esc(f.name) + '</td><td>' + lv + '</td>' + ['c1', 'c5', 'c20'].map(function (k) { var v = f[k], col = f.group !== 'cross' && f.sym !== 'TLT'; return '<td class="' + (!col ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '') + '">' + wpct(v, f.unit) + '</td>'; }).join('') + '</tr>';
    }).join('') + '</tbody></table></div>';
  }
  function contribCard(c, title, gapName) {
    if (!c) return '';
    var h = whyH === 'c1' ? 'd1' : 'd5', d = c[h]; if (!d) return '';
    var items = d.items.filter(function (x) { return x.contrib != null && Math.abs(x.contrib) >= 0.01; }).slice(0, 6);
    var mx = Math.max.apply(null, items.map(function (x) { return Math.abs(x.contrib); }).concat([Math.abs(d.gap), 0.01]));
    return '<section class="span-6"><h2>' + esc(title) + '<span class="h-r">' + (h === 'd1' ? '1日' : '5日') + '</span></h2><p class="sub">' + esc(gapName) + ' <strong class="' + (d.gap > 0 ? 'up' : d.gap < 0 ? 'down' : '') + '">' + (d.gap > 0 ? '+' : '') + d.gap.toFixed(2) + 'pt</strong> のうち、各銘柄の寄与(推定)</p><ul class="sigs">' +
      items.map(function (x) {
        var w = Math.abs(x.contrib) / mx * 50;
        return '<li><div class="sig-h"><strong>' + esc(x.name) + ' <span class="sub">' + wpct(x.ret) + '</span></strong><span class="' + (x.contrib > 0 ? 'up' : 'down') + '">' + (x.contrib > 0 ? '+' : '') + x.contrib.toFixed(2) + 'pt</span></div><div class="sig-bar"><i class="' + (x.contrib >= 0 ? 'pos' : 'neg') + '" style="width:' + w + '%"></i></div></li>';
      }).join('') + '</ul></section>';
  }
  function moversCard() {
    var mv = AN.movers || []; if (!mv.length) return '';
    return '<section><h2>' + ico('pulse') + 'その日に大きく動いた大型株(米国)<span class="h-r">時価総額500億ドル以上</span></h2><div class="table-wrap"><table class="num"><thead><tr><th class="l">銘柄</th><th>騰落</th><th>時価総額</th><th></th></tr></thead><tbody>' +
      mv.map(function (m) { return '<tr><td class="l"><strong>' + esc(m.sym) + '</strong> <span class="sub">' + esc(m.name) + '</span></td><td class="' + (m.chg > 0 ? 'up' : 'down') + '">' + wpct(m.chg) + '</td><td>' + (m.cap_b >= 1000 ? (m.cap_b / 1000).toFixed(1) + '兆' : m.cap_b * 10 + '億') + 'ドル</td><td>' + (m.earnings ? '<span class="pill warn">決算</span>' : '') + '</td></tr>'; }).join('') +
      '</tbody></table></div><p class="sub">毎日の値動き上位から、指数に影響する大型株だけを拾っています(小型株の急騰・急落は指数の説明に使えないため外しています)。同じ業種の銘柄がそろって動いた日は、その業種全体に材料が出ています。</p></section>';
  }
  function qualityLine() {
    var q = AN.quality; if (!q) return '';
    var nTot = Object.keys(AN.features || {}).length, st = Object.keys(q.stale || {}), ck = q.checks || [];
    return '<p class="sub dq">データの確認: 米国 ' + esc((q.expected_us || '').slice(5).replace('-', '/')) + ' ・ 日本 ' + esc((q.expected_jp || '').slice(5).replace('-', '/')) + ' の終値 ・ ' +
      (q.missing && q.missing.length ? '取れなかった銘柄 ' + esc(q.missing.join(', ')) + ' ・ ' : '全銘柄取得 ・ ') +
      (st.length ? '遅れ ' + esc(st.join(', ')) + '(1日の値は出していません) ・ ' : '遅れなし ・ ') +
      ck.map(function (c) { return esc(c.name) + 'の照合 ' + (c.ok ? 'OK' : 'ずれあり(' + c.a + ' / ' + c.b + ')'); }).join(' ・ ') + '</p>';
  }
  function mktCard(m, title) {
    if (!m) return '';
    return '<section class="span-6"><h2>' + esc(title) + '<span class="h-r">' + dirPill(m.direction) + '</span></h2><p>' + esc(m.summary) + '</p><ol class="causes">' + (m.causes || []).map(function (c) {
      return '<li><div class="cause-h"><strong>' + esc(c.title) + '</strong><span class="cause-w">' + c.weight + '%</span></div><div class="wbar"><i style="width:' + c.weight + '%"></i></div><p>' + esc(c.explain) + '</p>' + evChips(c.evidence) + '</li>';
    }).join('') + '</ol></section>';
  }
  function ruleList(list) {
    return list && list.length ? '<ol class="why">' + list.map(function (r) { return '<li><strong>' + esc(r.title) + '</strong> <span class="pill ' + (r.side === '上昇要因' ? 'up' : r.side === '下落要因' ? 'down' : 'flat') + '">' + esc(r.side) + '</span><br>' + esc(r.text) + '</li>'; }).join('') + '</ol>' : '<p class="sub">ふだんより大きな動きは見つかりませんでした。</p>';
  }
  /* 過去の見立ての答え合わせ: 見立ての日から5営業日後のS&P 500(ETF)の騰落 */
  function scoreHistory() {
    var hs = (AN.history || []).filter(function (x) { return x.spy; });
    return hs.map(function (x, i) {
      var later = hs[i + 5], chg = later ? (later.spy / x.spy - 1) * 100 : null, hit = null;
      if (chg != null && x.us) hit = x.us === '上昇' ? chg > 0.5 : x.us === '下落' ? chg < -0.5 : Math.abs(chg) <= 1.5;
      return { date: x.date, us: x.us, headline: x.headline, chg: chg, hit: hit };
    }).reverse();
  }
  function viewWhy() {
    var h = '<div class="page-head"><h1>なぜ動いたか</h1><p class="lead">米国12セクター・日本17業種・金利・商品・世界の市場・ニュースを材料に、役割の違う5人のアナリストが順に分析を重ね、チーフアナリストが統合し、査読で矛盾を直した見解です。毎朝更新されます。</p></div>';
    if (!anReady) return h + '<section><p class="sub">読み込み中…</p></section>';
    if (!AN) return h + '<section><h2>' + ico('pulse') + 'データを待っています</h2><p>この画面のデータは、毎朝のニュースBotが投稿の後に <code>learn/data/analysis.json</code> として書き出します。公開版でBotが一度動いた後から表示されます。</p><div class="actions"><a class="btn" href="#outlook">相場の見立て</a><a class="btn ghost" href="#lesson-money-flow">セクターの読み方</a></div></section>';
    var ai = AN.ai || {}, c = ai.chief, hs = whyH === 'c1' ? '1日' : whyH === 'c5' ? '5日' : '20日';
    var asof = (AN.asof && AN.asof.us ? '米国 ' + AN.asof.us.slice(5).replace('-', '/') : '') + (AN.asof && AN.asof.jp ? ' ・ 日本 ' + AN.asof.jp.slice(5).replace('-', '/') : '');
    if (c) {
      h += '<section class="ai-card"><h2>' + ico('target') + 'チーフアナリストの結論</h2><p class="sub">' + esc(asof) + ' ・ 確信度 ' + esc(c.confidence) + '</p><p class="why-head">' + esc(c.headline) + '</p>' +
        (c.debate ? '<p><strong>強気と弱気、どちらが優勢か:</strong> ' + esc(c.debate) + '</p>' : '') + '</section>';
      h += '<div class="dash">' + mktCard(c.us, '米国株: なぜこう動いたか') + mktCard(c.jp, '日本株: なぜこう動いたか') + '</div>';
      h += qualityLine();
    } else {
      h += '<section><h2>' + ico('target') + 'データから見える主因</h2><p class="sub">' + esc(asof) + '。今日はAIの分析ができなかったため、データの自動判定だけを表示しています。</p><h3 class="mini-h">直近5日</h3>' + ruleList(AN.rules && AN.rules.d5) + '<h3 class="mini-h">今日(1日)</h3>' + ruleList(AN.rules && AN.rules.d1) + '</section>';
    }
    if (!c) h += qualityLine();
    var seg = '<div class="seg small" role="group" aria-label="期間">' + [['c1', '1日'], ['c5', '5日'], ['c20', '20日']].map(function (x) { return '<button type="button" data-whyh="' + x[0] + '" class="' + (whyH === x[0] ? 'on' : '') + '">' + x[1] + '</button>'; }).join('') + '</div>';
    var bu = AN.breadth && AN.breadth.us, bj = AN.breadth && AN.breadth.jp;
    h += '<section><h2>' + ico('grid') + 'セクターの動き<span class="h-r">' + hs + '</span></h2>' + seg +
      '<h3 class="mini-h">米国(セクターETF)' + (bu ? '<span class="sub mini-s">今日の上昇 ' + bu.up1 + ' / ' + bu.n + ' ・ 50日線の上 ' + bu.above50 + ' / ' + bu.n + '</span>' : '') + '</h3>' + heatGrid('us') +
      '<h3 class="mini-h">日本(TOPIX-17業種のETF)' + (bj ? '<span class="sub mini-s">今日の上昇 ' + bj.up1 + ' / ' + bj.n + ' ・ 50日線の上 ' + bj.above50 + ' / ' + bj.n + '</span>' : '') + '</h3>' + heatGrid('jp') +
      '<p class="sub">色の濃さは「ふだんの値動きの何倍か」。濃いほど、めったにない大きさの動きです。対指数は S&P 500 / TOPIX との差。日本の業種ETFは売買が少ない日に指数とずれることがあります。</p>' +
      (c && c.sectors && c.sectors.length ? '<h3 class="mini-h">大きく動いた業種と、その理由</h3><ul class="sec-why">' + c.sectors.map(function (x) { return '<li><strong>' + esc(x.name) + '</strong><p>' + esc(x.why) + '</p></li>'; }).join('') + '</ul>' : '') + '</section>';
    var cu = AN.contrib && AN.contrib.us, cj = AN.contrib && AN.contrib.jp;
    if (cu || cj) h += '<div class="dash">' + contribCard(cj, '日経平均を動かした値がさ株', '日経平均とTOPIXの差') + contribCard(cu, 'S&P 500を動かした巨大株', '時価総額加重と均等加重の差') + '</div>';
    h += moversCard();
    h += '<section><h2>' + ico('flow') + 'お金の流れ<span class="h-r">' + hs + '</span></h2>' + seg + '<ul class="sigs">' + (AN.signals || []).map(sigRow).join('') + '</ul><p class="sub">「買われた側 − 売られた側」の騰落の差。プロは指数そのものより、この差で市場が何を織り込んでいるかを読みます。<a href="#lesson-money-flow">考え方</a></p></section>';
    h += '<div class="dash"><section class="span-6"><h2>' + ico('pulse') + '金利・恐怖指数・商品・為替</h2>' + crossTable(['cross', 'style']) + '</section><section class="span-6"><h2>' + aico('market') + '世界の株価指数</h2>' + crossTable(['global']) + '</section></div>';
    var passes = ai.passes || {};
    if (Object.keys(passes).length) {
      h += '<section><h2>' + ico('chat') + 'アナリスト会議</h2><p class="steps">' + (ai.steps || []).map(esc).join(' → ') + '</p><p class="sub">同じデータとニュースを、5つの役割で順に分析しました。後の人は前の人の分析を読んだうえで、補ったり反論したりしています。</p><div class="panels">' +
        WHY_ROLES.filter(function (r) { return passes[r[0]]; }).map(function (r, i) {
          var p = passes[r[0]];
          return '<details class="panel ' + r[0] + '"' + (i === 0 ? ' open' : '') + '><summary>' + ico(r[2]) + '<span><strong>' + esc(r[1]) + '</strong><span class="sub">' + esc(p.view) + '</span></span></summary><ul class="items">' + (p.items || []).map(function (it) {
            return '<li><div class="cause-h"><strong>' + esc(it.title) + '</strong>' + (it.impact ? '<span class="pill ' + (it.impact === '上昇要因' ? 'up' : it.impact === '下落要因' ? 'down' : 'flat') + '">' + esc(it.impact) + '</span>' : '') + (it.confidence ? '<span class="sub">確信度 ' + esc(it.confidence) + '</span>' : '') + '</div><p>' + esc(it.explain) + '</p>' + evChips(it.evidence) + '</li>';
          }).join('') + '</ul>' + (p.watch && p.watch.length ? '<p class="sub"><strong>注目点:</strong> ' + p.watch.map(esc).join(' / ') + '</p>' : '') + '</details>';
        }).join('') + '</div></section>';
    }
    if (c) {
      h += '<div class="dash"><section class="span-6"><h2>' + ico('compass') + 'この先の見通し</h2><h3 class="mini-h">数日〜2週間</h3><p>' + esc(c.outlook_short) + '</p><h3 class="mini-h">1〜3か月</h3><p>' + esc(c.outlook_mid) + '</p></section>' +
        '<section class="span-6"><h2>' + ico('redo') + '見解が変わる条件</h2><ul>' + (c.change || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></section></div>';
      if (c.watch && c.watch.length) h += '<section><h2>' + ico('target') + 'これから注目するもの</h2><ul class="sec-why">' + c.watch.map(function (x) { return '<li><strong>' + esc(x.what) + '</strong><p>' + esc(x.why) + '</p></li>'; }).join('') + '</ul></section>';
      if (c.lesson) h += '<section class="say"><h2>' + ico('book') + '今日の相場から学べること</h2><p>' + esc(c.lesson) + '</p></section>';
      h += '<section><h2>' + ico('grid') + 'データの自動判定(AIを使わない計算)</h2><p class="sub">上の分析の土台です。ふだんの値動きより大きく動いたものだけを、型に当てはめています。</p><h3 class="mini-h">直近5日</h3>' + ruleList(AN.rules && AN.rules.d5) + '<h3 class="mini-h">この1か月(20日)</h3>' + ruleList(AN.rules && AN.rules.d20) + '</section>';
    }
    var sh = scoreHistory().filter(function (x) { return x.us; });
    if (sh.length) {
      var done = sh.filter(function (x) { return x.hit != null; }), hits = done.filter(function (x) { return x.hit; }).length;
      h += '<section><h2>' + ico('redo') + '過去の見解の答え合わせ<span class="h-r">' + (done.length ? '的中 ' + hits + ' / ' + done.length : '5営業日後に判定') + '</span></h2><div class="table-wrap"><table class="num"><thead><tr><th>日付</th><th>米国の方向</th><th>その後5日</th><th>判定</th><th class="l">見出し</th></tr></thead><tbody>' +
        sh.slice(0, 15).map(function (x) { return '<tr><td>' + esc(x.date.slice(5).replace('-', '/')) + '</td><td>' + dirPill(x.us) + '</td><td class="' + (x.chg > 0 ? 'up' : x.chg < 0 ? 'down' : '') + '">' + (x.chg == null ? '—' : wpct(x.chg)) + '</td><td>' + (x.hit == null ? '判定待ち' : x.hit ? '的中' : '外れ') + '</td><td class="l">' + esc(x.headline) + '</td></tr>'; }).join('') +
        '</tbody></table></div><p class="sub">「方向」は直近5日の動きの判定です。その後の5営業日のS&P 500(ETF)で、上昇=+0.5%超、下落=−0.5%未満、もみ合い=±1.5%以内を的中としています。外れた日に何を見落としたかを考えるのが、いちばんの練習になります。</p></section>';
    }
    h += newsList();
    h += '<p class="disclaimer">AIの文章は、数字をデータとニュースに照らして確かめ、確かめられない数字を含む文は捨てています(今日は ' + ((ai.dropped || []).length) + ' 文)。それでも分析は推測を含み、将来の値動きを保証するものではありません。売買の判断はご自身で行ってください。更新 ' + esc((AN.updated || '').replace('T', ' ').slice(0, 16)) + '</p>';
    return h;
  }

  /* ================= 画面: チャート演習 ================= */
  var drill = null, drillMode = 'pattern', drillOpt = { ma: true, vol: true, rsi: false };
  var CAT_REASONS = { '継続パターン': ['contraction', 'volume', 'trend'], '反転パターン': ['level', 'volume', 'momentum'], '支持・抵抗': ['level', 'volume'], '出来高': ['volume', 'trend'], '移動平均線': ['ma', 'trend'], 'トレンド': ['trend', 'ma'], '下落の形': ['trend', 'level', 'volume'] };
  var DIRS = { up: '上昇', down: '下落', flat: '横ばい' };
  function newDrill() {
    if (drillMode === 'real' && MK) {
      var ids = ['SP500', 'NASDAQCOM', 'NIKKEI225', 'DJIA', 'DEXJPUS'].filter(function (id) { return MK.series[id] && MK.series[id].rows.length > 600; });
      if (ids.length) {
        var sid = ids[Math.floor(Math.random() * ids.length)], c = K.mkt.drillCase(MK.series[sid].rows, Math.random);
        if (c) { drill = { mode: 'real', sid: sid, c: c, ans: c.ans, base: K.mkt.baseRates(MK.series[sid].rows) }; return; }
      }
      drillMode = 'pattern';
    }
    var keys = Object.keys(K.drillCuts).filter(function (k) { return chartById[k] && state.drill.seen.indexOf(k) < 0; });
    if (!keys.length) { state.drill.seen = []; keys = Object.keys(K.drillCuts).filter(function (k) { return chartById[k]; }); }
    var id = keys[Math.floor(Math.random() * keys.length)];
    drill = { mode: 'pattern', id: id, cut: K.drillCuts[id][0], ans: K.drillCuts[id][1], data: K.buildSeries(chartById[id]) };
  }
  function viewDrill() {
    if (!drill) newDrill();
    var d = drill, st = state.drill;
    var h = '<div class="page-head"><h1>チャート演習</h1><p class="lead">右側を隠したチャートを見て、その後の展開・確信度・根拠を答えます。当てることより、根拠と確信度の付け方を鍛える練習です。</p>' +
      '<div class="seg" role="group" aria-label="演習の種類"><button type="button" data-dmode="pattern" class="' + (d.mode === 'pattern' ? 'on' : '') + '">学習用の型</button><button type="button" data-dmode="real" class="' + (d.mode === 'real' ? 'on' : '') + '"' + (MK ? '' : ' disabled title="実データは公開版で毎朝更新されます"') + '>実際の指数(FRED)</button></div></div>';
    h += '<div class="dash"><section class="span-8"><h2>' + (d.mode === 'real' ? esc(MK.series[d.sid].name) + 'の日足(終値)' : '学習用チャート(実在の銘柄ではありません)') + '<span class="h-r">' + (d.mode === 'real' ? '〜 ' + esc(d.c.date) : '') + '</span></h2>' +
      '<div class="seg small" role="group" aria-label="表示"><label><input type="checkbox" id="dr-ma"' + (drillOpt.ma ? ' checked' : '') + '> 移動平均</label>' + (d.mode === 'pattern' ? '<label><input type="checkbox" id="dr-vol"' + (drillOpt.vol ? ' checked' : '') + '> 出来高</label>' : '') + '<label><input type="checkbox" id="dr-rsi"' + (drillOpt.rsi ? ' checked' : '') + '> RSI</label></div>' +
      '<div class="chart" id="drill-chart"></div>' + (d.done ? drillResult() : drillForm()) + '</section>';
    var conf = ['55', '65', '80'].map(function (k) { var c = st.conf[k] || [0, 0]; return '<tr><td>' + k + '%</td><td>' + c[0] + '</td><td>' + (c[0] ? Math.round(c[1] / c[0] * 100) + '%' : '—') + '</td></tr>'; }).join('');
    h += '<section class="span-4"><h2>成績</h2><dl class="kv"><div><dt>演習の回数</dt><dd>' + st.n + '</dd></div><div><dt>的中率</dt><dd>' + (st.n ? Math.round(st.hit / st.n * 100) + '%' : '—') + '</dd></div><div><dt>実データの的中率</dt><dd>' + (st.real.n ? Math.round(st.real.hit / st.real.n * 100) + '%(' + st.real.n + '回)' : '—') + '</dd></div></dl>' +
      '<h3 class="mini-h">確信度ごとの的中率</h3><div class="table-wrap"><table class="num"><thead><tr><th>確信度</th><th>回数</th><th>的中</th></tr></thead><tbody>' + conf + '</tbody></table></div><p class="sub">付けた確信度と実際の的中率が近いほど、自分の判断の精度を正しく把握できています。<a href="#lesson-scenario-thinking">考え方</a></p></section></div>';
    return h;
  }
  function drillForm() {
    var d = drill, dirs = d.mode === 'real' ? ['up', 'flat', 'down'] : ['up', 'down'];
    return '<form id="drill-form" class="drill-form"><fieldset><legend>' + (d.mode === 'real' ? 'この後20営業日の動きは?(±2%以内を横ばい)' : 'この後の展開は?') + '</legend><div class="seg">' + dirs.map(function (x, i) { return '<label class="radio"><input type="radio" name="dr-dir" value="' + x + '"' + (i === 0 ? ' checked' : '') + '> ' + DIRS[x] + '</label>'; }).join('') + '</div></fieldset>' +
      '<fieldset><legend>確信度</legend><div class="seg">' + ['55', '65', '80'].map(function (x, i) { return '<label class="radio"><input type="radio" name="dr-conf" value="' + x + '"' + (i === 0 ? ' checked' : '') + '> ' + x + '%</label>'; }).join('') + '</div></fieldset>' +
      '<fieldset><legend>判断の根拠(複数可)</legend><div class="reasons">' + K.drillReasons.map(function (r) { return '<label><input type="checkbox" name="dr-r" value="' + r[0] + '"> ' + esc(r[1]) + '</label>'; }).join('') + '</div></fieldset>' +
      '<div class="actions"><button type="submit" class="btn">答え合わせ</button><button type="button" class="btn ghost" id="dr-skip">別のチャート</button></div></form>';
  }
  function drillResult() {
    var d = drill, ok = d.guess === d.ans, h = '<div class="drill-res"><p class="res-big ' + (ok ? 'up' : 'down') + '">' + (ok ? '的中' : '外れ') + '<span> あなた: ' + DIRS[d.guess] + '(確信度' + d.conf + '%) / 結果: ' + DIRS[d.ans] + '</span></p>';
    if (d.mode === 'pattern') {
      var c = chartById[d.id], want = CAT_REASONS[c.cat] || ['trend'], names = {}; K.drillReasons.forEach(function (r) { names[r[0]] = r[1]; });
      h += '<h3>' + esc(c.name) + '</h3><p>' + esc(c.what) + '</p><p><strong>使い方:</strong> ' + esc(c.how) + '</p><p><strong>うまくいかない時:</strong> ' + esc(c.fail) + '</p>' +
        '<p class="sub">この形で重視する根拠: ' + want.map(function (k) { return '<span class="pill ' + (d.reasons.indexOf(k) >= 0 ? 'up' : 'flat') + '">' + esc(names[k]) + '</span>'; }).join(' ') + '</p>';
    } else {
      var st = d.c.stats, b = d.base;
      h += '<p>隠していた20営業日の騰落率: <strong class="' + cls(d.c.ret) + '">' + sgn(d.c.ret, 2, '%') + '</strong></p><h3>この時点で読めたこと</h3><ul>' + K.mkt.describe(st).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + (st.stage ? '<li>' + esc(st.stage.name) + '</li>' : '') + '</ul>' +
        '<p class="sub">基準率(この指数で、何も考えずに同じ答えを続けた場合の的中率): 上昇 ' + b.up.toFixed(0) + '% / 横ばい ' + b.flat.toFixed(0) + '% / 下落 ' + b.down.toFixed(0) + '%。自分の的中率がこれを上回って初めて、分析に価値があります。</p>' +
        '<p class="sub">1回の結果は運に大きく左右されます。数十回の的中率で評価してください。</p>';
    }
    return h + '<div class="actions"><button type="button" class="btn" id="dr-next">次のチャート</button><button type="button" class="btn ghost" data-ask="' + esc(drillAskText()) + '">この場面をAIに解説してもらう</button></div></div>';
  }
  function drillAskText() {
    var d = drill;
    if (d.mode === 'pattern') return '学習用チャート「' + chartById[d.id].name + '」の演習で、私は' + DIRS[d.guess] + 'と答え、結果は' + DIRS[d.ans] + 'でした。この形を見分けるポイントと、実際の売買での使い方・失敗する時の見分け方を教えて。';
    return MK.series[d.sid].name + 'の' + d.c.date + '時点のチャート演習です。その時点の状態: ' + K.mkt.describe(d.c.stats).join('、') + '。私は' + DIRS[d.guess] + 'と予想し、実際の20営業日後は' + sgn(d.c.ret, 2, '%') + 'でした。この時点で何に注目すべきだったか教えて。';
  }
  function drawDrill() {
    var el = $('#drill-chart'); if (!el || !drill) return;
    var d = drill;
    if (d.mode === 'pattern') {
      var c = chartById[d.id], data = d.done ? d.data : d.data.slice(0, d.cut + 1);
      el._draw = function (w) { el.innerHTML = K.renderChart(c, { w: w, data: data, plain: !d.done, ma: drillOpt.ma ? (c.ma && c.ma.length ? c.ma : [20]) : [], vol: drillOpt.vol, ind: drillOpt.rsi ? 'rsi' : null }); };
    } else {
      var rows = d.c.win, vals = rows.map(function (x) { return x[1]; }), shown = d.done ? vals : vals.slice(0, d.c.split + 1);
      el._draw = function (w) { el.innerHTML = K.renderSeries(shown, { w: w, pre: d.c.pre, mas: drillOpt.ma ? [20, 50] : [], split: d.done ? d.c.split : null, rsi: drillOpt.rsi, labels: rows.slice(0, shown.length).map(function (x) { return x[0]; }), label: '演習チャート' }); };
    }
    drawCharts(el.parentNode);
  }
  function submitDrill() {
    var f = $('#drill-form'), d = drill;
    d.guess = (f.querySelector('[name="dr-dir"]:checked') || {}).value;
    d.conf = (f.querySelector('[name="dr-conf"]:checked') || {}).value;
    d.reasons = $$('[name="dr-r"]:checked', f).map(function (x) { return x.value; });
    d.done = true;
    var ok = d.guess === d.ans, st = state.drill;
    st.n++; if (ok) st.hit++;
    var c = st.conf[d.conf] || [0, 0]; c[0]++; if (ok) c[1]++; st.conf[d.conf] = c;
    if (d.mode === 'real') { st.real.n++; if (ok) st.real.hit++; } else { st.seen.push(d.id); if (st.seen.length > 12) st.seen.shift(); }
    save(); route();
  }

  /* ================= 画面: 因果マップ・チャート・人物・用語 ================= */
  var DIR = { up: ['↑', '追い風', 'up'], down: ['↓', '逆風', 'down'], mixed: ['→', '状況次第', 'flat'] };
  function viewMacro(id) {
    var h = '<div class="page-head"><h1>因果マップ</h1><p class="lead">「何かが起きると、何がどう動きやすいか」の典型的な連鎖です。必ず「ただし」まで読んでください。相場は期待との差で動くため、教科書どおりにならない場面にこそ理由があります。</p></div>';
    var groups = {};
    K.macro.forEach(function (m) { (groups[m.group] = groups[m.group] || []).push(m); });
    h += '<div class="dash"><section class="span-4"><h2>出来事<span class="h-r">' + K.macro.length + '</span></h2><div class="macro-pick">' + Object.keys(groups).map(function (g) {
      return '<div class="pick-group"><span class="chips-label">' + esc(g) + '</span>' + groups[g].map(function (m) { return '<a class="pick' + (m.id === (id || 'rate-cut') ? ' on' : '') + '" href="#macro-' + m.id + '">' + esc(m.title) + '</a>'; }).join('') + '</div>';
    }).join('') + '</div></section>';
    var m = macroById[id || 'rate-cut'];
    if (m) {
      h += '<section class="span-8 macro-card" id="macro-detail"><h2>' + esc(m.title) + '<span class="h-r">' + esc(m.group) + '</span></h2>' +
        '<ol class="chain">' + m.chain.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ol>' +
        '<h3>動きやすい方向</h3><div class="table-wrap"><table><thead><tr><th>対象</th><th>方向</th><th>理由</th></tr></thead><tbody>' +
        m.effects.map(function (e) { var d = DIR[e[1]]; return '<tr><td>' + esc(e[0]) + '</td><td><span class="pill ' + d[2] + '">' + d[0] + ' ' + d[1] + '</span></td><td>' + esc(e[2]) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
        '<h3>日本株では</h3><p>' + esc(m.jp) + '</p><p class="warn"><span class="warn-label">ただし</span>' + esc(m.caveat) + '</p>' +
        '<h3>関連レッスン</h3><ul class="plain">' + m.lessons.filter(function (x) { return lessonById[x]; }).map(function (x) { return '<li><a href="#lesson-' + x + '">' + esc(lessonById[x].t) + '</a></li>'; }).join('') + '</ul>' +
        '<div class="actions"><button type="button" class="btn ghost" data-ask="' + esc('「' + m.title + '」時に、プロのトレーダーは具体的に何を確認して、どう動くか教えて') + '">プロの対応を質問する</button></div></section>';
    }
    return h + '</div>';
  }
  function viewCharts() {
    var h = '<div class="page-head"><h1>チャート図鑑</h1><p class="lead">形と出来高をセットで覚えます。チャートは学習用に作成したもので、実在の銘柄ではありません。</p>' + candleToggle() + '</div>';
    var cats = [];
    K.charts.forEach(function (c) { if (cats.indexOf(c.cat) < 0) cats.push(c.cat); });
    cats.forEach(function (cat) {
      h += '<section><h2>' + esc(cat) + '</h2><div class="chart-grid">' + K.charts.filter(function (c) { return c.cat === cat; }).map(function (c) {
        return '<a class="chart-card" href="#chart-' + c.id + '"><div class="chart" data-chart="' + c.id + '" data-plain="1"></div><strong>' + esc(c.name) + '</strong></a>';
      }).join('') + '</div></section>';
    });
    h += '<section><h2>インジケーター実験室</h2><p class="sub">同じ値動きに指標を重ねて、何が見えるかを確かめます。指標は価格と出来高から計算した二次情報で、必ず遅れます。</p>' +
      '<div class="seg small">' + ['ma1:移動平均(25日)', 'ma2:移動平均(75日)', 'bb:ボリンジャーバンド', 'vol:出来高'].map(function (x) {
        var p = x.split(':'); return '<label><input type="checkbox" id="lab-' + p[0] + '"' + (p[0] === 'ma1' || p[0] === 'vol' ? ' checked' : '') + '> ' + p[1] + '</label>';
      }).join('') + '<label>下段 <select id="lab-ind"><option value="">なし</option><option value="rsi">RSI</option><option value="macd">MACD</option></select></label></div>' +
      '<figure class="fig"><div class="chart" id="lab" data-chart="lab"></div><figcaption id="lab-note"></figcaption></figure></section>';
    return h;
  }
  function candleToggle() {
    return '<div class="seg" role="group" aria-label="ローソク足の色"><span class="chips-label">ローソク足の色</span><button type="button" data-candle="us" class="' + (state.candle === 'us' ? 'on' : '') + '">上昇=緑 / 下落=赤</button><button type="button" data-candle="jp" class="' + (state.candle === 'jp' ? 'on' : '') + '">上昇=赤 / 下落=青</button></div>';
  }
  function labUpdate() {
    var el = $('#lab'); if (!el) return;
    var ma = []; if ($('#lab-ma1').checked) ma.push(25); if ($('#lab-ma2').checked) ma.push(75);
    var ind = $('#lab-ind').value;
    el._opt = { ma: ma, bb: $('#lab-bb').checked, vol: $('#lab-vol').checked, ind: ind || null };
    var notes = [];
    if (ma.length) notes.push('移動平均: 線が上向きで株価がその上にある区間が上昇トレンド。天井圏では線が横ばいになり、株価が線をまたぎ始めます。');
    if (ma.length > 1) notes.push('2本の線の交差は、実際の転換点よりかなり遅れます。');
    if (el._opt.bb) notes.push('ボリンジャーバンド: 横ばいで帯が狭まり、上昇が始まると帯が広がります。');
    if (el._opt.vol) notes.push('出来高: 上放れで増え、天井圏では下げる日の出来高が目立ちます。');
    if (ind === 'rsi') notes.push('RSI: 強い上昇の間は高い水準に張り付きます。70超えだけを理由に売ると早すぎます。');
    if (ind === 'macd') notes.push('MACD: ゼロより上で推移する間は上昇基調。シグナルとの交差には遅れがあります。');
    $('#lab-note').textContent = notes.join(' ');
    drawCharts(el.parentNode);
  }
  function viewChart(id) {
    var c = chartById[id]; if (!c) return notFound();
    var i = K.charts.indexOf(c), prev = K.charts[i - 1], next = K.charts[i + 1];
    var uses = lessons.filter(function (l) { return l.body.indexOf('{chart:' + id + '}') >= 0; });
    return '<article class="lesson"><div class="lesson-head"><p class="crumb"><a href="#charts">チャート図鑑</a> / ' + esc(c.cat) + '</p><h1>' + esc(c.name) + '</h1></div>' +
      '<section><figure class="fig"><div class="chart" data-chart="' + id + '"></div></figure></section>' +
      '<div class="prose card"><h3>何を表しているか</h3><p>' + esc(c.what) + '</p><h3>実績者はどう使うか</h3><p>' + esc(c.how) + '</p><h3>うまくいかない時</h3><p>' + esc(c.fail) + '</p></div>' +
      (uses.length ? '<aside class="card related"><h3>このチャートが出てくるレッスン</h3><ul class="plain">' + uses.map(function (l) { return '<li><a href="#lesson-' + l.id + '">' + esc(l.t) + '</a></li>'; }).join('') + '</ul></aside>' : '') +
      '<nav class="pager">' + (prev ? '<a href="#chart-' + prev.id + '">← ' + esc(prev.name) + '</a>' : '<span></span>') + (next ? '<a href="#chart-' + next.id + '">' + esc(next.name) + ' →</a>' : '<a href="#drill">チャート演習 →</a>') + '</nav></article>';
  }
  function viewTraders() {
    return '<div class="page-head"><h1>トレーダー研究</h1><p class="lead">長年の実績が公表・報道されている投資家に絞り、考え方と取り入れられることをまとめました。経歴や数字は本人の著書・公表・報道に基づく要約です。</p></div>' +
      '<section><h2>共通する5つの原則</h2><ol class="principles">' + K.principles.map(function (x) { return '<li><strong>' + esc(x[0]) + '</strong><span>' + esc(x[1]) + '</span></li>'; }).join('') + '</ol></section>' +
      '<section><h2>人物<span class="h-r">' + K.traders.length + '</span></h2><div class="trader-grid">' + K.traders.map(function (t) {
        return '<a class="trader-card" href="#trader-' + t.id + '"><span class="res-k">' + esc(t.region) + '</span><strong>' + esc(t.name) + '</strong><span>' + esc(t.style) + '</span></a>';
      }).join('') + '</div></section>';
  }
  function viewTrader(id) {
    var t = traderById[id]; if (!t) return notFound();
    return '<article class="lesson"><div class="lesson-head"><p class="crumb"><a href="#traders">トレーダー研究</a> / ' + esc(t.region) + '</p><h1>' + esc(t.name) + '</h1><p class="lead">' + esc(t.style) + '</p></div>' +
      '<div class="prose card"><h3>実績</h3><p>' + esc(t.record) + '</p><h3>考え方</h3><ul>' + t.ideas.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' +
      '<p class="note"><strong>取り入れること:</strong> ' + esc(t.takeaway) + '</p>' +
      '<h3>関連レッスン</h3><ul>' + t.lessons.filter(function (x) { return lessonById[x]; }).map(function (x) { return '<li><a href="#lesson-' + x + '">' + esc(lessonById[x].t) + '</a></li>'; }).join('') + '</ul>' +
      '<h3>もとにした資料</h3><ul class="sources">' + t.sources.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>' +
      '<nav class="pager"><a href="#traders">← 一覧へ</a><span></span></nav></article>';
  }
  function viewGlossary() {
    var cats = [];
    K.glossary.forEach(function (g) { if (cats.indexOf(g.cat) < 0) cats.push(g.cat); });
    return '<div class="page-head"><h1>用語集</h1><p class="lead">' + K.glossary.length + '語。上の入力欄から別名(例: 消費者物価指数 → CPI)でも探せます。</p></div>' +
      cats.map(function (cat) {
        return '<section><h2>' + esc(cat) + '<span class="h-r">' + K.glossary.filter(function (g) { return g.cat === cat; }).length + '</span></h2><dl class="gloss">' + K.glossary.filter(function (g) { return g.cat === cat; }).map(function (g) {
          return '<div><dt><button type="button" class="term" data-term="' + esc(g.name) + '">' + esc(g.name) + '</button></dt><dd>' + esc(g.def) + '</dd></div>';
        }).join('') + '</dl></section>';
      }).join('');
  }

  /* ================= 画面: 復習 ================= */
  var session = null;
  function viewReview() {
    var due = dueList(), learned = Object.keys(state.srs).length;
    var h = '<div class="page-head"><h1>復習</h1><p class="lead">正解するたびに 1日 → 3日 → 7日 → 16日 → 35日 と間隔を広げて出題し、間違えると最初に戻ります。</p></div>';
    h += '<section><h2>モード</h2><div class="tiles">' +
      tileB('今日の復習', due.length ? due.length + '問が出題待ち。' : learned ? '今日の分は終わっています。' : 'レッスンの確認問題を解くと、ここに入ります。', due.length ? 'due' : '', true) +
      tileB('ランダム10問', '確認問題 全' + questions.length + '問から出題。', 'random') +
      tileB('ケース演習', '相場の状況を読んで判断を選ぶ。全' + K.cases.length + '問。', 'case') +
      tileB('用語カード', '説明から用語を当てる。全' + termCards.length + '語。', 'term') +
      tileB('チャート当て', '注釈を消したチャートの形の名前を当てる。', 'chart') +
      '<div class="tile"><strong>チャート演習</strong><span>右側を隠したチャートで、その後の展開を考える。</span><a class="btn ghost small" href="#drill">開く</a></div></div></section>';
    h += '<section><h2>領域ごとのテスト</h2><div class="tiles">' + K.areas.map(function (a) { var b = state.tests[a.id]; return '<div class="tile"><strong>' + esc(a.name) + '</strong><span>定着 ' + mastery(a.id) + '%' + (b != null ? ' ・ 最高 ' + b + '/10' : '') + '</span><button type="button" class="btn ghost small" data-review="test-' + a.id + '">テスト</button></div>'; }).join('') + '</div></section>';
    var boxes = [0, 0, 0, 0, 0, 0];
    Object.keys(state.srs).forEach(function (id) { if (qById[id]) boxes[state.srs[id].box]++; });
    if (learned) h += '<section><h2>定着の状況</h2><div class="boxes">' + boxes.map(function (n, i) { return '<div><span class="box-n">' + n + '</span><span class="box-l">' + (i === 0 ? 'やり直し' : GAPS[i] + '日後') + '</span></div>'; }).join('') + '</div></section>';
    return h + '<div id="session"></div>';
  }
  function tileB(t, s, kind, primary) { return '<div class="tile"><strong>' + t + '</strong><span>' + esc(s) + '</span>' + (kind ? '<button type="button" class="btn small' + (primary ? '' : ' ghost') + '" data-review="' + kind + '">始める</button>' : '') + '</div>'; }
  function startSession(kind) {
    var items, wrap = function (q) { return { q: q }; }, arg = kind.split('-').slice(1).join('-');
    var fresh = function (list) { return shuffle(list).sort(function (a, b) { return (state.srs[a.id] ? state.srs[a.id].box + 1 : 0) - (state.srs[b.id] ? state.srs[b.id].box + 1 : 0); }).slice(0, 10); };
    if (kind === 'due') items = shuffle(dueList()).slice(0, 20).map(function (id) { return { q: qById[id] }; });
    else if (kind === 'random') items = shuffle(questions).slice(0, 10).map(wrap);
    else if (kind === 'term') items = shuffle(fresh(termCards)).map(wrap);
    else if (kind.indexOf('case') === 0) items = shuffle(fresh(K.cases.filter(function (c) { return !arg || c.area === arg; }))).map(wrap);
    else if (kind.indexOf('test-') === 0) {
      var pool = questions.filter(function (q) { return q.lesson.area.id === arg; }), cs = shuffle(K.cases.filter(function (c) { return c.area === arg; })).slice(0, 4);
      items = shuffle(cs.concat(shuffle(pool).slice(0, 10 - cs.length))).map(wrap);
    } else {
      var cp = K.charts.filter(function (c) { return c.quiz; });
      items = shuffle(cp).slice(0, 10).map(function (c) {
        var wrong = shuffle(cp.filter(function (x) { return x !== c; })).slice(0, 3).map(function (x) { return x.name; });
        return { chart: c, q: { q: 'このチャートの形は?', a: [c.name].concat(wrong), e: c.what } };
      });
    }
    session = { items: items, i: 0, right: 0, kind: kind };
    showSession();
  }
  function showSession() {
    var box = $('#session'), s = session;
    if (!box || !s) return;
    if (s.i >= s.items.length) {
      var note = '';
      if (s.kind.indexOf('test-') === 0) {
        var tid = s.kind.slice(5), score = Math.round(s.right / s.items.length * 10);
        if (!(state.tests[tid] >= score)) { state.tests[tid] = score; save(); }
        note = score >= 8 ? ' 合格です。' : ' 合格は8問以上。間違えた問題は復習に入りました。';
      }
      box.innerHTML = '<section class="quiz"><h2>結果</h2><p>' + s.items.length + '問中 ' + s.right + '問正解。' + note + '</p><a class="btn" href="' + (location.hash || '#review') + '" data-reload="1">戻る</a></section>';
      session = null; return;
    }
    var it = s.items[s.i], qh = quizHTML(it.q, s.i, s.items.length);
    if (it.chart) qh = qh.replace('<p class="q-t">', '<figure class="fig"><div class="chart" data-chart="' + it.chart.id + '" data-plain="1"></div></figure><p class="q-t">');
    box.innerHTML = '<section class="quiz" id="session-quiz">' + (it.q.lesson ? '<p class="crumb">出典: <a href="#lesson-' + it.q.lesson.id + '">' + esc(it.q.lesson.t) + '</a></p>' : it.q.kind === 'case' ? '<p class="crumb">ケース演習 / ' + esc(areaById[it.q.area].name) + '</p>' : it.q.kind === 'term' ? '<p class="crumb">用語カード / ' + esc(it.q.term.cat) + '</p>' : '') + qh +
      '<div class="quiz-next" hidden><button type="button" class="btn" id="next-q">' + (s.i + 1 < s.items.length ? '次の問題' : '結果を見る') + '</button>' + (it.chart ? ' <a href="#chart-' + it.chart.id + '">解説を見る</a>' : '') + '</div></section>';
    drawCharts(box);
    box.scrollIntoView({ block: 'start' });
  }

  /* ================= 画面: ツール ================= */
  function viewTools() {
    var h = '<div class="page-head"><h1>ツール</h1><p class="lead">知識を判断に変える道具です。</p></div><div class="dash">';
    h += '<section class="span-6 tool" id="tool-size"><h2>ポジションサイズ計算</h2><p class="sub">失ってよい額から株数を逆算します。<a href="#lesson-position-size">考え方</a></p><div class="form">' +
      '<label>市場<select id="ps-mkt"><option value="jp">日本株(100株単位)</option><option value="us">米国株(1株単位)</option></select></label>' +
      field('ps-cap', '資金(円)', 3000000, 10000) + field('ps-risk', '1回の許容リスク(%)', 1, 0.1) + field('ps-entry', '買値', 2000, 0.01, 'ps-unit') + field('ps-stop', '損切り価格', 1880, 0.01, 'ps-unit2') +
      '<label id="ps-fx-wrap" hidden>為替(1ドル=円)<input type="number" id="ps-fx" value="150" step="0.1" inputmode="decimal"></label></div><div class="result" id="ps-out" aria-live="polite"></div></section>';
    h += '<section class="span-6 tool" id="tool-sim"><h2>期待値シミュレーター</h2><p class="sub">乱数で200通りの未来を作り、成績の広がりを見ます。<a href="#lesson-expectancy">考え方</a></p><div class="form">' + field('sim-win', '勝率(%)', 40, 1) + field('sim-rr', '平均利益÷平均損失', 3, 0.1) + field('sim-risk', '1回のリスク(%)', 1, 0.1) + field('sim-n', '取引回数', 100, 10) + '</div>' +
      '<div class="actions"><button type="button" class="btn ghost small" id="sim-run">もう一度試す</button></div><div class="result" id="sim-out" aria-live="polite"></div><figure class="fig"><div class="chart" id="sim-chart"></div><figcaption>細い線は個々の試行(30本)、太い線は中央値。開始時の資産を100とした推移。</figcaption></figure></section>';
    h += '<section class="span-6 tool"><h2>買う前のチェックリスト</h2><ul class="checklist">' + ['相場全体(指数)は上昇トレンドか', '業績の裏付け、または明確な材料があるか', '株価は上昇トレンド(ステージ2)にあるか', '買い場は自分の型に合っているか。飛びつきではないか', '損切り価格を決めたか。買値から8%以内か', '株数は許容リスク(資金の1%前後)から計算したか', '利益目標は損失の2倍以上あるか', '決算発表日を確認したか', '3つのシナリオと確認の条件を書いたか', '買うと同時に損切りの逆指値を入れるか'].map(function (x, i) { return '<li><label><input type="checkbox" id="ck-' + i + '"> ' + x + '</label></li>'; }).join('') + '</ul></section>';
    h += '<section class="span-6 tool"><h2>記録のバックアップ</h2><p class="sub">学習の進み具合・復習の予定・演習の成績・メモは、このブラウザにだけ保存されています。別の端末に移す時は書き出して、移行先で読み込んでください。</p>' +
      '<textarea id="bk" rows="4" spellcheck="false" aria-label="バックアップ用の文字列"></textarea><div class="actions"><button type="button" class="btn ghost small" id="bk-out">書き出す</button><button type="button" class="btn ghost small" id="bk-in">読み込む</button><span id="bk-msg" class="form-msg" role="status"></span></div></section></div>';
    return h;
  }
  function field(id, label, val, step, unitId) { return '<label><span>' + label + (unitId ? '<span id="' + unitId + '"></span>' : '') + '</span><input type="number" id="' + id + '" value="' + val + '" step="' + step + '" inputmode="decimal"></label>'; }
  K.calcSize = function (o) {
    var fx = o.mkt === 'us' ? o.fx : 1, per = Math.abs(o.entry - o.stop) * fx, budget = o.cap * o.risk / 100;
    var lot = o.mkt === 'jp' ? 100 : 1, raw = budget / per, shares = Math.floor(raw / lot) * lot;
    return { budget: budget, per: per, raw: raw, shares: shares, cost: shares * o.entry * fx, loss: shares * per, pct: shares * o.entry * fx / o.cap * 100, stopPct: Math.abs(o.entry - o.stop) / o.entry * 100 };
  };
  function sizeUpdate() {
    var out = $('#ps-out'); if (!out) return;
    var mkt = $('#ps-mkt').value, us = mkt === 'us';
    $('#ps-fx-wrap').hidden = !us;
    $('#ps-unit').textContent = $('#ps-unit2').textContent = us ? '(ドル)' : '(円)';
    var o = { mkt: mkt, cap: num('ps-cap'), risk: num('ps-risk'), entry: num('ps-entry'), stop: num('ps-stop'), fx: num('ps-fx') };
    if (!(o.cap > 0 && o.risk > 0 && o.entry > 0 && o.stop > 0) || (us && !(o.fx > 0))) { out.innerHTML = '<p class="empty">すべての欄に0より大きい数字を入れてください。</p>'; return; }
    if (o.stop >= o.entry) { out.innerHTML = '<p class="empty">買いの計算です。損切り価格は買値より低くしてください。</p>'; return; }
    var r = K.calcSize(o), warn = [];
    if (r.shares === 0) warn.push('この条件では' + (us ? '1株' : '100株') + 'も買えません。損切りを近くできる買い場を待つか、見送ります。');
    if (r.stopPct > 8) warn.push('損切りまで' + r.stopPct.toFixed(1) + '%。8%を超える場合は、買うのが遅い可能性があります。');
    if (r.pct > 25) warn.push('投資額が資金の' + r.pct.toFixed(0) + '%。窓を開けた下落に備え、1銘柄は20〜25%までが目安です。');
    if (o.risk > 2) warn.push('1回のリスクが2%超。連敗時の資産減少が急に大きくなります。');
    out.innerHTML = '<div class="stats"><div><span class="st-n">' + r.shares.toLocaleString() + '<small>株</small></span><span class="st-l">株数</span></div><div><span class="st-n">' + yen(r.cost) + '<small>円</small></span><span class="st-l">投資額(資金の' + r.pct.toFixed(1) + '%)</span></div>' +
      '<div><span class="st-n">' + yen(r.loss) + '<small>円</small></span><span class="st-l">損切り時の損失(上限 ' + yen(r.budget) + '円)</span></div><div><span class="st-n">' + r.stopPct.toFixed(1) + '<small>%</small></span><span class="st-l">損切りまでの幅</span></div></div>' +
      '<p class="calc">' + yen(o.cap) + '円 × ' + o.risk + '% = ' + yen(r.budget) + '円 ÷ 1株あたりの損失 ' + (us ? (o.entry - o.stop).toFixed(2) + 'ドル × ' + o.fx + '円 = ' : '') + yen(r.per) + '円 = ' + r.raw.toFixed(1) + '株' + (us ? '' : ' → 100株単位に切り捨て') + '</p>' +
      warn.map(function (w) { return '<p class="warn"><span class="warn-label">注意</span>' + esc(w) + '</p>'; }).join('');
  }
  K.simulate = function (o, rand) {
    var paths = [], finals = [], dds = [];
    for (var p = 0; p < o.paths; p++) {
      var eq = 100, peak = 100, dd = 0, d = [100];
      for (var i = 0; i < o.n; i++) { eq *= 1 + (rand() < o.win / 100 ? o.rr : -1) * o.risk / 100; if (eq > peak) peak = eq; dd = Math.max(dd, (peak - eq) / peak * 100); d.push(eq); }
      paths.push(d); finals.push(eq); dds.push(dd);
    }
    var med = [];
    for (var k = 0; k <= o.n; k++) { var col = paths.map(function (x) { return x[k]; }).sort(function (a, b) { return a - b; }); med.push(col[Math.floor(col.length / 2)]); }
    finals.sort(function (a, b) { return a - b; }); dds.sort(function (a, b) { return a - b; });
    var q = function (a, f) { return a[Math.min(a.length - 1, Math.floor(a.length * f))]; };
    return { paths: paths, med: med, exp: o.win / 100 * o.rr - (1 - o.win / 100), p5: q(finals, 0.05), p50: q(finals, 0.5), p95: q(finals, 0.95), dd50: q(dds, 0.5), dd95: q(dds, 0.95), lose: finals.filter(function (x) { return x < 100; }).length / finals.length * 100 };
  };
  function simUpdate() {
    var out = $('#sim-out'); if (!out) return;
    var o = { win: num('sim-win'), rr: num('sim-rr'), risk: num('sim-risk'), n: Math.round(num('sim-n')), paths: 200 };
    if (!(o.win >= 0 && o.win <= 100 && o.rr > 0 && o.risk > 0 && o.risk <= 100 && o.n >= 10 && o.n <= 1000)) { out.innerHTML = '<p class="empty">勝率は0〜100、取引回数は10〜1000、その他は0より大きい数字を入れてください。</p>'; return; }
    var r = K.simulate(o, Math.random), be = 100 / (1 + o.rr);
    out.innerHTML = '<div class="stats"><div><span class="st-n ' + (r.exp > 0 ? 'up' : 'down') + '">' + sgn(r.exp, 2) + '<small>R</small></span><span class="st-l">1回あたりの期待値</span></div><div><span class="st-n">' + pct(r.p50) + '</span><span class="st-l">' + o.n + '回後(中央値)</span></div>' +
      '<div><span class="st-n">' + pct(r.p5) + '〜' + pct(r.p95) + '</span><span class="st-l">90%の範囲</span></div><div><span class="st-n">-' + r.dd50.toFixed(0) + '<small>%</small></span><span class="st-l">最大下落(中央値。悪い場合 -' + r.dd95.toFixed(0) + '%)</span></div></div>' +
      '<p class="calc">期待値 = ' + o.win + '% × ' + o.rr + 'R − ' + (100 - o.win) + '% × 1R = ' + r.exp.toFixed(2) + 'R。損をしない勝率は ' + be.toFixed(0) + '%以上。' + o.n + '回後に資産が減っている確率 ' + r.lose.toFixed(0) + '%。</p>' +
      (r.exp <= 0 ? '<p class="warn"><span class="warn-label">注意</span>期待値がゼロ以下です。回数を重ねるほど資産が減ります。</p>' : '') +
      (r.exp > 0 && r.dd95 > 30 ? '<p class="warn"><span class="warn-label">注意</span>運が悪いと30%以上の下落を経験します。1回のリスクを下げると続けやすくなります。</p>' : '');
    var el = $('#sim-chart');
    el._draw = function (w) { var lines = r.paths.slice(0, 30).map(function (d) { return { d: d, cls: 'c-path' }; }); lines.push({ d: r.med, cls: 'c-median' }); el.innerHTML = K.renderLines(lines, w, 230, { base: 100, label: '資産の推移', xlabel: '取引回数 0 → ' + o.n }); };
    drawCharts(el.parentNode);
  }
  function pct(v) { var x = v - 100; return (x >= 0 ? '+' : '') + x.toFixed(0) + '%'; }
  function notFound() { return '<div class="page-head"><h1>ページが見つかりません</h1><p class="lead"><a href="#home">ホームへ戻る</a></p></div>'; }

  /* ================= ナビゲーションとルーティング ================= */
  var NAV = [
    ['市場', [['home', 'ダッシュボード', 'grid'], ['market', '今日の相場', 'pulse'], ['why', 'なぜ動いたか', 'flow'], ['outlook', '相場の見立て', 'compass'], ['drill', 'チャート演習', 'target']]],
    ['学ぶ', [['library', 'ライブラリ', 'book'], ['macro', '因果マップ', 'flow'], ['charts', 'チャート図鑑', 'candle'], ['traders', 'トレーダー研究', 'person']]],
    ['鍛える', [['review', '復習', 'redo'], ['tools', 'ツール', 'tool']]],
    ['調べる', [['ask', '質問する', 'chat'], ['glossary', '用語集', 'abc']]]
  ];
  var DOCK_L = [['home', 'ホーム', 'grid'], ['library', '学ぶ', 'bookmark']];
  var DOCK_M = [['market', '相場', 'pulse'], ['outlook', '見立て', 'compass'], ['drill', '演習', 'target']];
  var ICON = {
    grid: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    book: '<path d="M5 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H5zM19 4h-4a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h4z"/>',
    flow: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="12" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8.5 6.8l7 4M8.5 17.2l7-4"/>',
    candle: '<path d="M7 3v18M17 5v16"/><rect x="4.5" y="7" width="5" height="8" rx="1"/><rect x="14.5" y="9" width="5" height="7" rx="1"/>',
    person: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
    redo: '<path d="M4 12a8 8 0 1 0 2.6-5.9M4 4v5h5"/>',
    tool: '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8h7M8.5 12h2M13.5 12h2M8.5 16h2M13.5 16h2"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    abc: '<path d="M5 6.5h14M5 12h14M5 17.5h9"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c3 3 3 14 0 17M12 3.5c-3 3-3 14 0 17"/>',
    doc: '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10.5a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z"/><path d="M9.5 12h5M9.5 15.5h5"/>',
    shield: '<path d="M12 3.5l7 2.5v5.5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
    compass: '<circle cx="12" cy="12" r="8.5"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    bookmark: '<path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    checkbox: '<rect x="4" y="4" width="14" height="14" rx="3.5"/><path d="M14.5 19.5l2 2 4-4.5"/>'
  };
  var AREA_ICON = { market: 'globe', company: 'doc', chart: 'candle', risk: 'shield', strategy: 'target', base: 'compass' };
  function aico(id) { return '<span class="aico a-' + id + '">' + ico(AREA_ICON[id]) + '</span>'; }
  function ico(name) { return '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">' + ICON[name] + '</svg>'; }
  var TITLES = { home: '株トレ道場', market: '今日の相場', why: 'なぜ動いたか', outlook: '相場の見立て', drill: 'チャート演習', library: 'ライブラリ', macro: '因果マップ', charts: 'チャート図鑑', traders: 'トレーダー研究', review: '復習', tools: 'ツール', ask: '質問する', glossary: '用語集' };
  var NAV_OF = { lesson: 'library', topic: 'library', course: 'library', chart: 'charts', trader: 'traders', search: 'ask' };
  function navHTML(cur) {
    var due = dueList().length;
    return NAV.map(function (g) {
      return '<p class="side-h">' + g[0] + '</p>' + g[1].map(function (n) { return '<a href="#' + n[0] + '"' + (n[0] === cur ? ' aria-current="page"' : '') + '>' + ico(n[2]) + '<span>' + n[1] + '</span>' + (n[0] === 'review' && due ? '<em class="badge">' + due + '</em>' : '') + '</a>'; }).join('');
    }).join('');
  }
  var query = '', curName = '';
  function route() {
    var hash = (location.hash || '#home').slice(1), cut = hash.indexOf('-'), name = cut < 0 ? hash : hash.slice(0, cut), arg = cut < 0 ? '' : hash.slice(cut + 1);
    if (name === 'course') { location.replace('#library'); return; }
    var html, prevName = curName;
    curName = name;
    switch (name) {
      case 'home': html = viewHome(); break;
      case 'market': html = viewMarket(); break;
      case 'why': html = viewWhy(); break;
      case 'outlook': html = viewOutlook(); break;
      case 'drill': html = viewDrill(); break;
      case 'ask': html = viewAsk(); break;
      case 'library': html = viewLibrary(arg); break;
      case 'topic': html = viewTopic(arg); break;
      case 'lesson': html = viewLesson(arg); break;
      case 'macro': html = viewMacro(arg); break;
      case 'charts': html = viewCharts(); break;
      case 'chart': html = viewChart(arg); break;
      case 'traders': html = viewTraders(); break;
      case 'trader': html = viewTrader(arg); break;
      case 'glossary': html = viewGlossary(); break;
      case 'review': html = viewReview(); break;
      case 'tools': html = viewTools(); break;
      case 'search': html = viewSearch(query); break;
      default: html = notFound();
    }
    closeSheet();
    session = null;
    view.innerHTML = html;
    var nav = NAV_OF[name] || name;
    var grp = function (list) { return '<div class="dock-group">' + list.map(function (n) { return '<a href="#' + n[0] + '"' + (n[0] === nav ? ' aria-current="page"' : '') + ' aria-label="' + n[1] + '">' + ico(n[2]) + '<span>' + n[1] + '</span></a>'; }).join('') + '</div>'; };
    $('#dock').innerHTML = '<div class="dock-in">' + grp(DOCK_L) + grp(DOCK_M) + '<a class="fab' + (nav === 'ask' ? ' on' : '') + '" href="#ask" aria-label="質問する" title="質問する">' + ico('plus') + '</a></div>';
    var due = dueList().length, badge = $('#due-badge');
    badge.hidden = !due; badge.textContent = due > 99 ? '99+' : due;
    $('#top').classList.toggle('searching', name === 'search');
    $('#top-title').textContent = TITLES[nav] || '株トレ道場';
    renderTicker();
    if (name !== 'search') { $('#q').value = ''; query = ''; }
    document.documentElement.dataset.candle = state.candle;
    if (name === 'charts') labUpdate();
    if (name === 'tools') { sizeUpdate(); simUpdate(); }
    var hero = $('#hero-chart');
    if (hero) hero._draw = function (w) { var src = MK && MK.series.SP500 ? MK.series.SP500.rows.slice(-180).map(function (x) { return x[1]; }) : K.labSeries; hero.innerHTML = K.renderSpark(src, w, Math.round(Math.max(200, Math.min(300, w * 0.52))), true); };
    if (name === 'market' && MK) drawMarketCharts();
    if (name === 'drill') drawDrill();
    if (name === 'outlook') paintOutlookAI();
    if (name === 'ask') renderChat();
    drawCharts(view);
    $$('[data-spark]', view).forEach(function (el) { el.innerHTML = K.renderSpark(chartById[el.dataset.spark], 92, 92); });
    if (name === 'macro' && arg && window.innerWidth < 900) { var det = $('#macro-detail'); if (det) det.scrollIntoView({ block: 'start' }); }
    else if (name !== 'search' && !(name === prevName && (name === 'drill' || name === 'market' || name === 'home' || name === 'outlook'))) window.scrollTo(0, 0);
  }
  function goSearch(q) {
    query = q; $('#q').value = q;
    if (location.hash === '#search') { view.innerHTML = viewSearch(q); } else location.hash = '#search';
  }
  function looksLikeQuestion(q) { return q.length >= 8 && /[?？]|とは|なぜ|どう|教えて|ですか|ますか|違い|方法|べき/.test(q); }

  /* ================= イベント ================= */
  window.addEventListener('hashchange', route);
  var st;
  $('#q').addEventListener('input', function (e) { clearTimeout(st); var v = e.target.value; st = setTimeout(function () { if (v.trim()) goSearch(v.trim()); }, 200); });
  $('#search-form').addEventListener('submit', function (e) {
    e.preventDefault(); clearTimeout(st);
    var v = $('#q').value.trim(); if (!v) return;
    var viaAsk = e.submitter && e.submitter.id === 'ask-btn';
    if (viaAsk || looksLikeQuestion(v)) { $('#q').value = ''; sendAsk(v); } else goSearch(v);
  });
  document.addEventListener('click', function (e) {
    var t = e.target.closest('#ol-run,#menu-btn,#search-open,#search-close,[data-term],[data-q],[data-ask],[data-goto],.opt,[data-review],#next-q,button[data-candle],[data-dmode],[data-whyh],[data-news],#dr-next,#dr-skip,#sim-run,#sheet-close,#bk-out,#bk-in,[data-reload],#ask-clear,#ask-stop');
    if (!t) { if (e.target.id === 'sheet') closeSheet(); return; }
    if (t.id === 'ol-run') { runOutlookAI(); return; }
    if (t.id === 'menu-btn') { openMenu(); return; }
    if (t.id === 'search-open') { $('#top').classList.add('searching'); $('#q').focus(); return; }
    if (t.id === 'search-close') { $('#top').classList.remove('searching'); $('#q').value = ''; if (location.hash === '#search') { if (history.length > 1) history.back(); else location.hash = '#home'; } return; }
    if (t.dataset.term) { openTerm(t.dataset.term); return; }
    if (t.dataset.q) { closeSheet(); goSearch(t.dataset.q); return; }
    if (t.dataset.ask) {
      closeSheet();
      if (t.dataset.askEdit) { location.hash = '#ask'; setTimeout(function () { var a = $('#ask-in'); if (a) { a.value = t.dataset.ask; a.focus(); } }, 50); return; }
      sendAsk(t.dataset.ask); return;
    }
    if (t.dataset.goto) { e.preventDefault(); var g = document.getElementById(t.dataset.goto); if (g) g.scrollIntoView({ block: 'start' }); return; }
    if (t.classList.contains('opt')) { answer(t); return; }
    if (t.dataset.review) { startSession(t.dataset.review); return; }
    if (t.id === 'next-q') { session.i++; showSession(); return; }
    if (t.dataset.candle) { state.candle = t.dataset.candle; save(); route(); return; }
    if (t.dataset.news) { e.preventDefault(); var sec = document.querySelector('#why-news-sec details'); if (sec) { sec.open = true; var li = document.getElementById('news-' + t.dataset.news); (li || sec).scrollIntoView({ behavior: 'smooth', block: 'center' }); if (li) { li.classList.add('flash'); setTimeout(function () { li.classList.remove('flash'); }, 1600); } } return; }
    if (t.dataset.whyh) { whyH = t.dataset.whyh; var y = window.scrollY; route(); window.scrollTo(0, y); return; }
    if (t.dataset.dmode) { drillMode = t.dataset.dmode; drill = null; route(); return; }
    if (t.id === 'dr-next' || t.id === 'dr-skip') { drill = null; route(); return; }
    if (t.id === 'sim-run') { simUpdate(); return; }
    if (t.id === 'sheet-close') { closeSheet(); return; }
    if (t.id === 'ask-clear') { if (asking) asking.abort(); chat = []; renderChat(); return; }
    if (t.id === 'ask-stop') { if (asking) asking.abort(); return; }
    if (t.dataset.reload) { e.preventDefault(); route(); return; }
    if (t.id === 'bk-out') { $('#bk').value = JSON.stringify(state); $('#bk').select(); $('#bk-msg').textContent = '書き出しました。全体をコピーして保管してください。'; return; }
    if (t.id === 'bk-in') {
      try {
        var o = JSON.parse($('#bk').value);
        if (!o || typeof o !== 'object' || !o.done || !o.srs) throw new Error('形式');
        state = Object.assign(EMPTY(), { done: o.done, srs: o.srs, tests: o.tests || {}, candle: o.candle === 'jp' ? 'jp' : 'us', last: o.last || null, drill: o.drill || EMPTY().drill, notes: o.notes || {} }); save();
        $('#bk-msg').textContent = '読み込みました。';
      } catch (err) { $('#bk-msg').textContent = '読み込めませんでした。書き出した文字列を全て貼り付けてください。'; }
    }
  });
  document.addEventListener('answered', function (e) {
    var sec = e.target.closest('.quiz'); if (!sec) return;
    if (sec.id === 'lesson-quiz') lessonAnswered(sec);
    else if (session) { if (e.detail.ok) session.right++; sec.querySelector('.quiz-next').hidden = false; $('#next-q').focus(); }
  });
  document.addEventListener('submit', function (e) {
    if (e.target.id === 'ask-form') { e.preventDefault(); var a = $('#ask-in'); var v = a.value; a.value = ''; sendAsk(v); }
    else if (e.target.id === 'ask-mini') { e.preventDefault(); sendAsk($('#ask-mini-in').value); }
    else if (e.target.id === 'drill-form') { e.preventDefault(); submitDrill(); }
  });
  document.addEventListener('input', function (e) {
    var id = e.target.id || '';
    if (id.indexOf('ps-') === 0) sizeUpdate();
    else if (id.indexOf('sim-') === 0) simUpdate();
    else if (id.indexOf('lab-') === 0) labUpdate();
    else if (id === 'mk-note') { var r = MK && K.mkt.regime(MK); if (r) { state.notes[r.date] = e.target.value; save(); } }
  });
  document.addEventListener('change', function (e) {
    var id = e.target.id || '';
    if (id.indexOf('lab-') === 0) labUpdate();
    else if (id.indexOf('dr-') === 0) { drillOpt = { ma: !!($('#dr-ma') || {}).checked, vol: !!($('#dr-vol') || {}).checked, rsi: !!($('#dr-rsi') || {}).checked }; drawDrill(); }
    else if (id === 'ps-mkt') { if (e.target.value === 'us') { $('#ps-entry').value = 100; $('#ps-stop').value = 94; } else { $('#ps-entry').value = 2000; $('#ps-stop').value = 1880; } sizeUpdate(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeSheet();
    if (e.key === 'Enter' && e.target.id === 'ask-in' && !e.shiftKey && !e.isComposing) { e.preventDefault(); var v = e.target.value; e.target.value = ''; sendAsk(v); }
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); $('#search-open').click(); }
  });

  route();
})();
