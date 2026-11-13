/* 株トレ道場 - アプリ本体(ビルド不要の素のJavaScript) */
(function () {
  'use strict';
  var K = window.KABU;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var view = $('#view');
  var DAY = 86400000;

  /* ================= 保存(ブラウザ内) ================= */
  var KEY = 'kabu-dojo-v1';
  var state = { done: {}, srs: {}, tests: {}, candle: 'us', last: null };
  try { var raw = localStorage.getItem(KEY); if (raw) Object.assign(state, JSON.parse(raw)); } catch (e) { /* 保存領域が使えなくても動かす */ }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* noop */ } }

  /* ================= データの索引 ================= */
  var lessons = [], lessonById = {}, termByName = {}, chartById = {}, traderById = {}, macroById = {}, questions = [];
  K.stages.forEach(function (st, si) {
    st.lessons.forEach(function (l) {
      l.stage = st; l.stageNo = si; l.no = lessons.length; lessons.push(l); lessonById[l.id] = l;
      (l.quiz || []).forEach(function (q, i) { q.id = l.id + '-' + i; q.lesson = l; questions.push(q); });
    });
  });
  K.glossary.forEach(function (g) { termByName[g.name] = g; });
  K.charts.forEach(function (c) { chartById[c.id] = c; });
  K.traders.forEach(function (t) { traderById[t.id] = t; });
  K.macro.forEach(function (m) { macroById[m.id] = m; });
  var qById = {}; questions.forEach(function (q) { qById[q.id] = q; });
  var stageById = {}; K.stages.forEach(function (st) { stageById[st.id] = st; });
  /* ケース演習(判断の練習)と用語カード(定義から用語を当てる)も、同じ間隔反復に乗せる */
  K.cases.forEach(function (c) { c.kind = 'case'; qById[c.id] = c; });
  var termCards = K.glossary.map(function (g) {
    var same = K.glossary.filter(function (x) { return x.cat === g.cat && x !== g; });
    var pick = [], seed = g.name.length * 7 + g.def.length;
    while (pick.length < 3) { var c = same[seed % same.length]; seed = (seed * 31 + 17) % 100003; if (pick.indexOf(c) < 0) pick.push(c); }
    var hide = new RegExp([g.name].concat(g.aka.filter(function (x) { return x.length > 1; })).map(function (x) { return x.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&'); }).join('|'), 'gi');
    return { id: 'term-' + g.name, kind: 'term', term: g, q: '次の説明に当てはまる用語は? 「' + g.def.replace(hide, '○○') + '」', a: [g.name].concat(pick.map(function (x) { return x.name; })), e: g.name + ': ' + g.def };
  });
  termCards.forEach(function (c) { qById[c.id] = c; });
  function chapterOf(q) { return q.lesson ? q.lesson.stage.id : q.kind === 'case' ? q.ch : null; }
  /* 定着度: その章の問題とケースが、復習の箱(0〜5)のどこまで進んだか */
  function mastery(stId) {
    var ids = Object.keys(qById).filter(function (id) { return chapterOf(qById[id]) === stId; });
    var sum = 0; ids.forEach(function (id) { if (state.srs[id]) sum += Math.min(4, state.srs[id].box) / 4; });
    return ids.length ? Math.round(sum / ids.length * 100) : 0;
  }
  function doneRate(st) { return Math.round(st.lessons.filter(function (l) { return state.done[l.id]; }).length / st.lessons.length * 100); }
  var RANKS = [[0, '入門'], [10, '初級'], [30, '中級'], [55, '上級'], [80, 'ベテラン級']];
  function overall() {
    var m = 0; K.stages.forEach(function (st) { m += mastery(st.id); }); m = Math.round(m / K.stages.length);
    var tm = 0; termCards.forEach(function (c) { if (state.srs[c.id]) tm += Math.min(4, state.srs[c.id].box) / 4; }); tm = Math.round(tm / termCards.length * 100);
    var score = Math.round(m * 0.75 + tm * 0.25), rank = RANKS[0][1];
    RANKS.forEach(function (r) { if (score >= r[0]) rank = r[1]; });
    return { score: score, rank: rank, terms: tm };
  }
  function lvTag(l) { return l.lv ? '<span class="lv' + (l.lv === '実戦' ? ' l2' : '') + '">' + l.lv + '</span>' : ''; }
  function skillHTML() {
    return '<div class="skill">' + K.stages.map(function (st, i) {
      var d = doneRate(st), m = mastery(st.id);
      return '<a class="skill-row" href="#course-' + st.id + '"><strong>' + chapterNo(i) + ' ' + esc(st.title) + '</strong><em>修了 ' + d + '% ・ 定着 ' + m + '%</em><span class="pbar"><i style="width:' + d + '%"></i><i style="width:' + m + '%"></i></span></a>';
    }).join('') + '</div><p class="legend"><span><i></i>読んだ(修了)</span><span><i class="on"></i>覚えている(定着)</span></p>';
  }

  /* ================= 小道具 ================= */
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&'); }
  function shuffle(a, r) { a = a.slice(); for (var i = a.length - 1; i > 0; i--) { var j = Math.floor((r || Math.random)() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function yen(n) { return Math.round(n).toLocaleString('ja-JP'); }
  function num(id) { var v = parseFloat(($('#' + id) || {}).value); return isFinite(v) ? v : NaN; }
  function today() { var d = new Date(); return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }

  /* 用語の自動リンク: 本文に出てきた用語集の語を、レッスンごとに最初の1回だけリンクにする */
  var NO_LINK = { 'ベース': 1, 'レンジ': 1, '株式': 1, '決算': 1, '金利': 1, 'トレンド': 1, '出来高': 1 };
  var termNames = K.glossary.map(function (g) { return g.name; }).filter(function (n) { return n.length >= 2 && !NO_LINK[n]; })
    .sort(function (a, b) { return b.length - a.length; });
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

  /* 本文の簡易マークアップをHTMLに */
  function md(src) {
    var seen = {}, out = [], lines = src.split('\n'), i = 0;
    function flush(tag, items) { out.push('<' + tag + '>' + items.map(function (x) { return '<li>' + inline(x, seen) + '</li>'; }).join('') + '</' + tag + '>'); }
    while (i < lines.length) {
      var L = lines[i].trim();
      if (!L) { i++; continue; }
      var m;
      if (L.indexOf('### ') === 0) out.push('<h4>' + inline(L.slice(4)) + '</h4>');
      else if (L.indexOf('## ') === 0) out.push('<h3>' + inline(L.slice(3)) + '</h3>');
      else if (L.indexOf('> ') === 0) out.push('<p class="note">' + inline(L.slice(2), seen) + '</p>');
      else if (L.indexOf('! ') === 0) out.push('<p class="warn"><span class="warn-label">注意</span>' + inline(L.slice(2), seen) + '</p>');
      else if ((m = /^\{chart:([\w-]+)\}$/.exec(L))) out.push(chartFigure(m[1]));
      else if ((m = /^\{candles:([\w-]+)\}$/.exec(L))) out.push('<figure class="fig"><div class="chart" data-candles="' + m[1] + '"></div></figure>');
      else if (L.charAt(0) === '|') {
        var rows = [];
        while (i < lines.length && lines[i].trim().charAt(0) === '|') { rows.push(lines[i].trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); })); i++; }
        out.push('<div class="table-wrap"><table><thead><tr>' + rows[0].map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
          rows.slice(1).map(function (r) { return '<tr>' + r.map(function (c) { return '<td>' + arrows(inline(c, seen)) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>');
        continue;
      } else if (L.indexOf('- ') === 0) {
        var items = [];
        while (i < lines.length && lines[i].trim().indexOf('- ') === 0) { items.push(lines[i].trim().slice(2)); i++; }
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
      (plain ? '' : '<figcaption><a href="#chart-' + id + '">' + esc(c.name) + '</a>:' + esc(c.what) + '</figcaption>') + '</figure>';
  }

  /* チャートの描画(幅に合わせて描き直す) */
  function drawCharts(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('.chart'), function (el) {
      var w = Math.floor(el.clientWidth);
      if (!w) return;
      if (el.dataset.chart) el.innerHTML = K.renderChart(chartById[el.dataset.chart] || K.labSeries, Object.assign({ w: w, plain: !!el.dataset.plain }, el._opt || {}));
      else if (el.dataset.candles) el.innerHTML = K.renderCandles(K.candleFigs[el.dataset.candles], w);
      else if (el._draw) el._draw(w);
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
    addDoc('lesson', l.t, l.stage.title, l.sum + ' ' + plain(l.body) + ' ' + (l.quiz || []).map(function (q) { return q.q + ' ' + q.e; }).join(' '), '#lesson-' + l.id, { lesson: l });
  });
  K.macro.forEach(function (m) {
    addDoc('macro', m.title, m.aka, m.chain.join(' → ') + ' ' + m.effects.map(function (e) { return e[0] + ' ' + e[2]; }).join(' ') + ' ' + m.jp + ' ' + m.caveat, '#macro-' + m.id, { macro: m });
  });
  K.charts.forEach(function (c) { addDoc('chart', c.name, c.aka + ' ' + c.cat, c.what + ' ' + c.how + ' ' + c.fail, '#chart-' + c.id, { chart: c }); });
  K.traders.forEach(function (t) { addDoc('trader', t.name, t.aka + ' ' + t.style, t.record + ' ' + t.ideas.join(' ') + ' ' + t.takeaway, '#trader-' + t.id, { trader: t }); });

  /* 同義語: 用語集の名前と別名を同じ意味として扱う(「消費者物価指数」で「CPI」も探す) */
  var syn = {};
  K.glossary.forEach(function (g) {
    var names = [g.name].concat(g.aka).map(norm).filter(function (x) { return x.length >= 2; });
    names.forEach(function (n) { (syn[n] = syn[n] || []).push(norm(g.name)); });
  });
  function expand(tok) {
    var set = {}; set[tok] = 1;
    (syn[tok] || []).forEach(function (x) { set[x] = 1; });
    return Object.keys(set);
  }
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
  function search(q) {
    var toks = norm(q).split(/[\s　、,]+/).filter(Boolean);
    if (!toks.length) return { toks: [], hits: [] };
    var vars = toks.map(expand);
    function run(needAll) {
      var hits = [];
      docs.forEach(function (d) {
        var total = 0, matched = 0;
        vars.forEach(function (v) { var s = scoreDoc(d, v); if (s) matched++; total += s; });
        if (!matched || (needAll && matched < toks.length)) return;
        if (d.type === 'term') total *= 1.15;
        hits.push({ d: d, s: total });
      });
      return hits.sort(function (a, b) { return b.s - a.s; });
    }
    var hits = run(true);
    if (!hits.length && toks.length > 1) hits = run(false);
    return { toks: toks, vars: [].concat.apply([], vars), hits: hits };
  }
  K.search = search; // テストから使う

  function snippet(d, vars) {
    var nx = d.nx, pos = -1, len = 0;
    vars.forEach(function (v) { var p = nx.indexOf(v); if (p >= 0 && (pos < 0 || p < pos)) { pos = p; len = v.length; } });
    var text = d.text, start = Math.max(0, pos - 28), s = text.slice(start, start + 110);
    return (start > 0 ? '…' : '') + highlight(s, vars) + (start + 110 < text.length ? '…' : '');
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

  var TYPE_LABEL = { term: '用語', lesson: 'レッスン', macro: '因果マップ', chart: 'チャート', trader: 'トレーダー研究' };
  var TYPE_ORDER = ['term', 'macro', 'lesson', 'chart', 'trader'];
  var SUGGEST = ['金利', 'CPI', '雇用統計', '円安', '出来高', '損切り', 'VCP', '決算', '移動平均線', 'ブレイクアウト', '期待値', 'テスタ', '片山'];

  function viewSearch(q) {
    var h = '<div class="page-head"><h1>検索</h1><p class="lead">調べたい言葉を入れると、用語・因果マップ・レッスン・チャート・トレーダー研究をまとめて探します。</p></div>';
    if (!q) {
      h += '<section><h2>よく調べられる言葉</h2><div class="chips">' + SUGGEST.map(function (s) { return '<button type="button" class="chip" data-q="' + esc(s) + '">' + esc(s) + '</button>'; }).join('') + '</div></section>';
      return h;
    }
    var r = search(q);
    if (!r.hits.length) {
      return h + '<section><p class="empty">「' + esc(q) + '」に一致する内容は見つかりませんでした。別の言い方(例: 「物価」→「CPI」)や、短い単語で試してください。</p>' +
        '<div class="chips">' + SUGGEST.map(function (s) { return '<button type="button" class="chip" data-q="' + esc(s) + '">' + esc(s) + '</button>'; }).join('') + '</div></section>';
    }
    h += '<p class="count">「' + esc(q) + '」に関する内容 ' + r.hits.length + '件</p>';
    // いちばん近い用語は大きく見せ、関連語をたどれるようにする
    var top = r.hits.filter(function (x) { return x.d.type === 'term' && x.s >= 60; })[0];
    if (top) {
      var g = top.d.term;
      h += '<section class="hero-term"><p class="eyebrow">' + esc(g.cat) + 'の用語</p><h2>' + esc(g.name) + '</h2>' +
        (g.aka.length ? '<p class="aka">' + esc(g.aka.slice(0, 5).join(' / ')) + '</p>' : '') +
        '<p>' + esc(g.def) + '</p>' + relChips(g) + '</section>';
    }
    TYPE_ORDER.forEach(function (type) {
      var list = r.hits.filter(function (x) { return x.d.type === type && (!top || x !== top); });
      if (!list.length) return;
      var max = type === 'term' ? 8 : 6;
      h += '<section class="results"><h2>' + TYPE_LABEL[type] + ' <span class="n">' + list.length + '</span></h2><ul>' +
        list.slice(0, max).map(function (x) {
          var d = x.d;
          if (type === 'term') return '<li><button type="button" class="res" data-term="' + esc(d.title) + '"><span class="res-t">' + highlight(d.title, r.vars) + '</span><span class="res-s">' + highlight(d.text, r.vars) + '</span></button></li>';
          var sub = type === 'lesson' ? d.lesson.stage.title : type === 'chart' ? d.chart.cat : type === 'trader' ? d.trader.style : d.macro.group;
          return '<li><a class="res" href="' + d.href + '"><span class="res-k">' + esc(sub) + '</span><span class="res-t">' + highlight(d.title, r.vars) + '</span><span class="res-s">' + snippet(d, r.vars) + '</span></a></li>';
        }).join('') + '</ul>' + (list.length > max ? '<p class="more">ほか ' + (list.length - max) + '件。言葉を足すと絞り込めます。</p>' : '') + '</section>';
    });
    return h;
  }
  function relChips(g) {
    var rel = g.rel.filter(function (n) { return termByName[n]; });
    return rel.length ? '<div class="chips"><span class="chips-label">関連</span>' + rel.map(function (n) { return '<button type="button" class="chip" data-q="' + esc(n) + '">' + esc(n) + '</button>'; }).join('') + '</div>' : '';
  }

  /* 用語のポップアップ */
  function openTerm(name) {
    var g = termByName[name];
    if (!g) return;
    var uses = lessons.filter(function (l) { return l.body.indexOf(name) >= 0; }).slice(0, 4);
    $('#sheet-body').innerHTML = '<p class="eyebrow">' + esc(g.cat) + '</p><h2 id="sheet-title">' + esc(g.name) + '</h2>' +
      (g.aka.length ? '<p class="aka">' + esc(g.aka.slice(0, 5).join(' / ')) + '</p>' : '') + '<p>' + esc(g.def) + '</p>' + relChips(g) +
      (uses.length ? '<p class="sheet-sub">この言葉が出てくるレッスン</p><ul class="plain">' + uses.map(function (l) { return '<li><a href="#lesson-' + l.id + '">' + esc(l.t) + '</a></li>'; }).join('') + '</ul>' : '') +
      '<p><button type="button" class="btn ghost" data-q="' + esc(g.name) + '">「' + esc(g.name) + '」に関する内容をすべて見る</button></p>';
    $('#sheet').hidden = false;
    $('#sheet-close').focus();
  }
  function closeSheet() { $('#sheet').hidden = true; }

  /* ================= 復習(間隔反復) ================= */
  var GAPS = [0, 1, 3, 7, 16, 35]; // 箱ごとの次回までの日数
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
    return '<div class="q" data-qid="' + q.id + '"><p class="q-n">' + (total ? '問' + (idx + 1) + ' / ' + total : '確認問題') + '</p><p class="q-t">' + esc(q.q) + '</p><div class="q-opts">' +
      opts.map(function (o) { return '<button type="button" class="opt" data-ok="' + (o.ok ? 1 : 0) + '">' + esc(o.t) + '</button>'; }).join('') +
      '</div><div class="q-exp" hidden><p><strong class="q-res"></strong> ' + esc(q.e) + '</p></div></div>';
  }
  function answer(btn) {
    var box = btn.closest('.q');
    if (box.dataset.done) return;
    box.dataset.done = 1;
    var ok = btn.dataset.ok === '1';
    Array.prototype.forEach.call(box.querySelectorAll('.opt'), function (b) { b.disabled = true; if (b.dataset.ok === '1') b.classList.add('right'); });
    if (!ok) btn.classList.add('wrong');
    var exp = box.querySelector('.q-exp'); exp.hidden = false;
    var res = box.querySelector('.q-res'); res.textContent = ok ? '正解。' : '不正解。'; res.className = 'q-res ' + (ok ? 'up' : 'down');
    if (box.dataset.qid) grade(box.dataset.qid, ok);
    box.dispatchEvent(new CustomEvent('answered', { bubbles: true, detail: { ok: ok } }));
  }

  /* ================= 画面 ================= */
  function progress() { var n = lessons.filter(function (l) { return state.done[l.id]; }).length; return { n: n, total: lessons.length, pct: Math.round(n / lessons.length * 100) }; }
  function nextLesson() { for (var i = 0; i < lessons.length; i++) if (!state.done[lessons[i].id]) return lessons[i]; return null; }

  /* アイコン(線画) */
  var ICON = {
    home: '<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
    book: '<path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z"/>',
    flow: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="12" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8.5 6.8l7 4M8.5 17.2l7-4"/>',
    candle: '<path d="M7 3v18M17 5v16"/><rect x="4.5" y="7" width="5" height="8" rx="1"/><rect x="14.5" y="9" width="5" height="7" rx="1"/>',
    person: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.200 1.900 7 5.500"/>',
    play: '<path d="M8 5.500v13l11-6.500z"/>',
    redo: '<path d="M4 12a8 8 0 1 0 2.600-5.900M4 4v5h5"/>',
    compass: '<circle cx="12" cy="12" r="8.500"/><path d="M15.500 8.500l-2 5-5 2 2-5z"/>',
    coin: '<circle cx="12" cy="12" r="8.500"/><path d="M9 9l3 4 3-4M12 13v4M9.500 14h5"/>',
    globe: '<circle cx="12" cy="12" r="8.500"/><path d="M3.500 12h17M12 3.500c3 3 3 14 0 17M12 3.500c-3 3-3 14 0 17"/>',
    doc: '<path d="M7 3.500h7l4 4V20a.5.5 0 0 1-.5.5h-10.500a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z"/><path d="M9.500 12h5M9.500 15.500h5"/>',
    shield: '<path d="M12 3.500l7 2.500v5.500c0 4.500-3 7.500-7 9-4-1.500-7-4.500-7-9V6z"/>',
    target: '<circle cx="12" cy="12" r="8.500"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.600"/>',
    heart: '<path d="M12 20s-7.500-4.500-7.500-10a4.200 4.200 0 0 1 7.500-2.600 4.200 4.200 0 0 1 7.500 2.600c0 5.500-7.500 10-7.500 10z"/>',
    tool: '<rect x="5" y="3.500" width="14" height="17" rx="2.500"/><path d="M8.500 8h7M8.500 12h2M13.500 12h2M8.500 16h2M13.500 16h2"/>',
    abc: '<path d="M5 6.500h14M5 12h14M5 17.500h9"/>'
  };
  function ico(name, cls) { return '<svg class="ico' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" aria-hidden="true">' + ICON[name].replace(/(\d)00\b/g, '$1') + '</svg>'; }
  var STAGE_ICON = ['compass', 'coin', 'globe', 'doc', 'candle', 'shield', 'target', 'heart'];
  function chapterNo(i) { return i === 0 ? '序章' : '第' + i + '章'; }
  function lessonChart(l) { var m = /\{chart:([\w-]+)\}/.exec(l.body); return m ? chartById[m[1]] : null; }

  /* 章の棚: 見出し行と、横に流れるレッスンの小さなタイル */
  function shelf(st, i) {
    var d = st.lessons.filter(function (l) { return state.done[l.id]; }).length;
    var tiles = '';
    st.lessons.forEach(function (l) {
      var c = lessonChart(l);
      if (c) tiles += '<a class="mini pic" href="#lesson-' + l.id + '" aria-label="' + esc(l.t) + '(チャート)" data-spark="' + c.id + '"></a>';
      tiles += '<a class="mini' + (state.done[l.id] ? ' done' : '') + '" href="#lesson-' + l.id + '"><span>' + esc(l.t) + '</span>' + lvTag(l) + '</a>';
    });
    return '<section class="shelf"><a class="shelf-head" href="#course-' + st.id + '">' + ico(STAGE_ICON[i], 'hue-' + i) + '<strong>' + esc(st.title) + '</strong><span class="shelf-n">' + d + ' / ' + st.lessons.length + ' ›</span></a><div class="shelf-row">' + tiles + '</div></section>';
  }

  function viewHome() {
    var p = progress(), nx = nextLesson(), due = dueList().length;
    var h = '<section class="hero"><div class="chart" id="hero-chart"></div><p class="hero-title">株トレ道場<small>日本株・米国株を、基礎から</small></p><p class="hero-cap">' + p.n + ' / ' + p.total + ' レッスン修了' + (due ? ' ・ 復習待ち ' + due + '問' : '') + '</p></section>';
    h += '<section class="say"><p>' + (nx ? (p.n ? '続きは「' + esc(nx.t) + '」。' : 'まずは「' + esc(nx.t) + '」から。') + esc(nx.sum) : '全レッスンを修了しました。あとは復習で定着させましょう。') + '</p>' +
      '<div class="actions">' + (nx ? '<a class="btn" href="#lesson-' + nx.id + '">' + (p.n ? '続きから学ぶ' : '学習を始める') + '</a>' : '') + (due ? '<a class="btn ghost" href="#review">今日の復習 ' + due + '問</a>' : '') + '</div>' +
      '<p class="stamp">' + chapterNo(nx ? nx.stageNo : 7) + ' ' + esc((nx || lessons[lessons.length - 1]).stage.title) + '</p></section>';
    K.stages.forEach(function (st, i) { h += shelf(st, i); });
    var ov = overall();
    h += '<section><h2>習熟マップ</h2><p class="rank"><strong>' + ov.rank + '</strong><span class="sub">知識の定着 ' + ov.score + '%(章の問題・ケース 75%、用語 25%)</span></p>' + skillHTML() +
      '<p class="sub">「定着」は、間隔を空けた復習で正解を重ねた割合です。読んだだけでは上がりません。全章の定着が80%を超えると、ベテランが持つ知識の土台がそろいます。</p></section>';
    h += '<section><h2>勝ち残る人に共通する5つの原則</h2><p class="sub">片山晃、テスタ、オニール、ミネルヴィニ、ドラッケンミラーなど、手法も時間軸も違う投資家が同じことを語っています。<a href="#traders">トレーダー研究へ</a></p><ol class="principles">' +
      K.principles.map(function (x) { return '<li><strong>' + esc(x[0]) + '</strong><span>' + esc(x[1]) + '</span></li>'; }).join('') + '</ol></section>';
    h += '<section><h2>調べる・試す</h2><div class="tiles">' +
      tile('#macro', '因果マップ', '「金利が下がると」「CPIが高いと」何がどう動くか') +
      tile('#charts', 'チャート図鑑', K.charts.length + '種類の形と出来高の読み方') +
      tile('#traders', 'トレーダー研究', K.traders.length + '人の実績者の考え方') +
      tile('#tools', 'ツール', '株数の計算、期待値シミュレーター') +
      tile('#glossary', '用語集', K.glossary.length + '語。本文の用語はタップで意味を表示') +
      tile('#review', '復習', '間隔を空けて出題。チャート当てクイズも') + '</div></section>';
    h += '<p class="disclaimer">この教材は学習を目的としたもので、特定の銘柄の売買をすすめるものではありません。掲載するチャートは学習用に作成したもので、実在の銘柄ではありません。投資の判断と結果の責任はご自身にあります。</p>';
    return h;
  }
  function tile(href, t, s) { return '<a class="tile" href="' + href + '"><strong>' + t + '</strong><span>' + esc(s) + '</span></a>'; }

  /* 章の一覧、または1つの章(レッスンと、その章に関連する因果マップ・チャート・人物・用語) */
  function chapterNav(cur) {
    return '<div class="chapter-nav"><a class="chip' + (!cur ? ' on' : '') + '" href="#course">すべての章</a>' + K.stages.map(function (st, i) {
      return '<a class="chip' + (st.id === cur ? ' on' : '') + '" href="#course-' + st.id + '">' + chapterNo(i) + ' ' + esc(st.title) + '</a>';
    }).join('') + '</div>';
  }
  function viewCourse(id) {
    var st = K.stages.filter(function (x) { return x.id === id; })[0];
    if (!st) {
      return '<div class="page-head"><h1>カリキュラム</h1><p class="lead">全' + K.stages.length + '章・' + lessons.length + 'レッスン。上から順に進めるのがおすすめです。各レッスンは5〜10分で、最後の確認問題に答えると修了になり、問題は復習に入ります。</p></div>' +
        chapterNav('') + K.stages.map(shelf).join('');
    }
    var i = K.stages.indexOf(st), inCh = {};
    st.lessons.forEach(function (l) { inCh[l.id] = 1; });
    var d = st.lessons.filter(function (l) { return state.done[l.id]; }).length;
    var hit = function (x) { return x.lessons.some(function (y) { return inCh[y]; }); };
    var macros = K.macro.filter(hit), who = K.traders.filter(hit), cs = [], body = st.lessons.map(function (l) { return l.body; }).join('\n');
    K.charts.forEach(function (c) { if (body.indexOf('{chart:' + c.id + '}') >= 0) cs.push(c); });
    var counts = termNames.map(function (n) { return [n, body.split(n).length - 1]; }).filter(function (x) { return x[1] > 0; }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 14);
    var h = chapterNav(st.id) + '<div class="page-head"><p class="eyebrow">' + chapterNo(i) + ' ・ ' + st.lessons.length + 'レッスン</p><h1>' + ico(STAGE_ICON[i], 'hue-' + i) + ' ' + esc(st.title) + '</h1><p class="lead">' + esc(st.goal) + '</p>' +
      '<div class="pbar"><i style="width:' + Math.round(d / st.lessons.length * 100) + '%"></i></div><p class="sub">' + d + ' / ' + st.lessons.length + ' 修了 ・ 定着度 ' + mastery(st.id) + '%</p></div>';
    var listOf = function (ls) {
      return '<ul class="lesson-list">' + ls.map(function (l) {
        return '<li><a href="#lesson-' + l.id + '" class="' + (state.done[l.id] ? 'done' : '') + '"><span class="check" aria-hidden="true">' + (state.done[l.id] ? '✓' : '') + '</span><span class="ll-body"><strong>' + esc(l.t) + lvTag(l) + '</strong><span>' + esc(l.sum) + '</span></span></a></li>';
      }).join('') + '</ul>';
    };
    var base = st.lessons.filter(function (l) { return !l.lv; }), adv = st.lessons.filter(function (l) { return l.lv; });
    h += '<section><h2>' + (adv.length ? '基礎' : 'レッスン') + '</h2>' + listOf(base) + '</section>';
    if (adv.length) h += '<section><h2>応用・実戦</h2><p class="sub">基礎を終えてから進みます。「応用」は一段深い知識、「実戦」は売買の手順に落とし込んだ内容です。</p>' + listOf(adv) + '</section>';
    var nCase = K.cases.filter(function (c) { return c.ch === st.id; }).length, best = state.tests[st.id];
    h += '<section><h2>章末テスト</h2><p class="sub">この章の確認問題' + (nCase ? 'とケース演習' : '') + 'から10問を出題します。8問以上の正解で合格です。' + (best != null ? ' これまでの最高: ' + best + ' / 10' + (best >= 8 ? '(合格)' : '') : '') + '</p><p><button type="button" class="btn' + (best >= 8 ? ' ghost' : '') + '" data-review="test-' + st.id + '">章末テストを始める</button>' +
      (nCase ? ' <button type="button" class="btn ghost" data-review="case-' + st.id + '">この章のケース演習(' + nCase + '問)</button>' : '') + '</p><div id="session"></div></section>';
    if (macros.length) h += '<section><h2>この章の因果マップ</h2><div class="chips">' + macros.map(function (m) { return '<a class="chip" href="#macro-' + m.id + '">' + esc(m.title) + '</a>'; }).join('') + '</div></section>';
    if (cs.length) h += '<section><h2>この章のチャート</h2><div class="chart-grid">' + cs.map(function (c) { return '<a class="chart-card" href="#chart-' + c.id + '"><div class="chart" data-chart="' + c.id + '" data-plain="1"></div><strong>' + esc(c.name) + '</strong></a>'; }).join('') + '</div></section>';
    if (who.length) h += '<section><h2>この章で参考にする投資家</h2><div class="trader-grid">' + who.map(function (t) { return '<a class="trader-card" href="#trader-' + t.id + '"><strong>' + esc(t.name) + '</strong><span>' + esc(t.style) + '</span></a>'; }).join('') + '</div></section>';
    if (counts.length) h += '<section><h2>この章の重要語</h2><div class="chips">' + counts.map(function (x) { return '<button type="button" class="chip" data-term="' + esc(x[0]) + '">' + esc(x[0]) + '</button>'; }).join('') + '</div></section>';
    var prev = K.stages[i - 1], next = K.stages[i + 1];
    h += '<nav class="pager">' + (prev ? '<a href="#course-' + prev.id + '">← ' + chapterNo(i - 1) + ' ' + esc(prev.title) + '</a>' : '<span></span>') + (next ? '<a href="#course-' + next.id + '">' + chapterNo(i + 1) + ' ' + esc(next.title) + ' →</a>' : '<span></span>') + '</nav>';
    return h;
  }

  function viewLesson(id) {
    var l = lessonById[id];
    if (!l) return notFound();
    state.last = id; save();
    var prev = lessons[l.no - 1], next = lessons[l.no + 1];
    var related = K.macro.filter(function (m) { return m.lessons.indexOf(id) >= 0; });
    var who = K.traders.filter(function (t) { return t.lessons.indexOf(id) >= 0; });
    var inCh = l.stage.lessons.indexOf(l) + 1;
    var h = '<article class="lesson"><div class="lesson-head"><p class="crumb"><a href="#course-' + l.stage.id + '">' + chapterNo(l.stageNo) + ' ' + esc(l.stage.title) + '</a> ・ ' + inCh + ' / ' + l.stage.lessons.length + (state.done[id] ? ' ・ <span class="up">修了済み</span>' : '') + '</p>' +
      '<h1>' + esc(l.t) + lvTag(l) + '</h1><p class="lead">' + esc(l.sum) + '</p></div><div class="prose">' + md(l.body) + '</div>';
    if (related.length || who.length) {
      h += '<aside class="card related"><h3>あわせて見る</h3><ul class="plain">' +
        related.map(function (m) { return '<li><span class="res-k">因果マップ</span> <a href="#macro-' + m.id + '">' + esc(m.title) + '</a></li>'; }).join('') +
        who.map(function (t) { return '<li><span class="res-k">トレーダー研究</span> <a href="#trader-' + t.id + '">' + esc(t.name) + '</a></li>'; }).join('') + '</ul></aside>';
    }
    h += '<section class="quiz" id="lesson-quiz" data-lesson="' + id + '"><h2>確認問題</h2><p class="sub">本文を見返さずに答えてみてください。全問に答えるとレッスン修了です。</p>' +
      l.quiz.map(function (q, i) { return quizHTML(q, i, l.quiz.length); }).join('') + '<div class="quiz-done" hidden></div></section>';
    h += '<nav class="pager">' + (prev ? '<a href="#lesson-' + prev.id + '">← ' + esc(prev.t) + '</a>' : '<span></span>') + (next ? '<a href="#lesson-' + next.id + '">' + esc(next.t) + ' →</a>' : '<a href="#review">復習へ →</a>') + '</nav></article>';
    return h;
  }
  function lessonAnswered(sec) {
    var all = sec.querySelectorAll('.q'), done = sec.querySelectorAll('.q[data-done]');
    if (done.length < all.length) return;
    var id = sec.dataset.lesson, l = lessonById[id];
    state.done[id] = state.done[id] || Date.now(); save();
    var next = lessons[l.no + 1], box = sec.querySelector('.quiz-done');
    box.hidden = false;
    box.innerHTML = '<p><strong>レッスン修了。</strong> ' + all.length + '問中 ' + Math.max(0, all.length - sec.querySelectorAll('.opt.wrong').length) + '問正解。問題は復習に入りました。間違えた問題はすぐに、正解した問題は明日また出題されます。</p>' +
      (next ? '<a class="btn" href="#lesson-' + next.id + '">次へ: ' + esc(next.t) + '</a>' : '<a class="btn" href="#review">復習へ</a>');
  }

  /* ---- 因果マップ ---- */
  var DIR = { up: ['↑', '追い風', 'up'], down: ['↓', '逆風', 'down'], mixed: ['→', '状況次第', 'flat'] };
  function viewMacro(id) {
    var h = '<div class="page-head"><h1>因果マップ</h1><p class="lead">「何かが起きると、何がどう動きやすいか」の典型的な連鎖です。出来事を選んでください。必ず「ただし」まで読むこと。相場は期待との差で動くため、教科書どおりにならない場面にこそ理由があります。</p></div>';
    var groups = {};
    K.macro.forEach(function (m) { (groups[m.group] = groups[m.group] || []).push(m); });
    h += '<section><div class="macro-pick">' + Object.keys(groups).map(function (g) {
      return '<div class="pick-group"><span class="chips-label">' + esc(g) + '</span>' + groups[g].map(function (m) { return '<a class="chip' + (m.id === id ? ' on' : '') + '" href="#macro-' + m.id + '">' + esc(m.title) + '</a>'; }).join('') + '</div>';
    }).join('') + '</div></section>';
    var m = macroById[id || 'rate-cut'];
    if (!m) return h;
    h += '<section class="macro-card" id="macro-detail"><p class="eyebrow">' + esc(m.group) + '</p><h2>' + esc(m.title) + '</h2>' +
      '<ol class="chain">' + m.chain.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ol>' +
      '<h3>動きやすい方向</h3><div class="table-wrap"><table class="effects"><thead><tr><th>対象</th><th>方向</th><th>理由</th></tr></thead><tbody>' +
      m.effects.map(function (e) { var d = DIR[e[1]]; return '<tr><td>' + esc(e[0]) + '</td><td><span class="pill ' + d[2] + '">' + d[0] + ' ' + d[1] + '</span></td><td>' + esc(e[2]) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
      '<h3>日本株では</h3><p>' + esc(m.jp) + '</p><p class="warn"><span class="warn-label">ただし</span>' + esc(m.caveat) + '</p>' +
      '<h3>関連レッスン</h3><ul class="plain">' + m.lessons.filter(function (x) { return lessonById[x]; }).map(function (x) { return '<li><a href="#lesson-' + x + '">' + esc(lessonById[x].t) + '</a></li>'; }).join('') + '</ul></section>';
    return h;
  }

  /* ---- チャート ---- */
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
      '<div class="lab-ctl">' + ['ma1:短期の移動平均線(25日)', 'ma2:長期の移動平均線(75日)', 'bb:ボリンジャーバンド', 'vol:出来高'].map(function (x) {
        var p = x.split(':'); return '<label><input type="checkbox" id="lab-' + p[0] + '"' + (p[0] === 'ma1' || p[0] === 'vol' ? ' checked' : '') + '> ' + p[1] + '</label>';
      }).join('') + '<label>下段 <select id="lab-ind"><option value="">なし</option><option value="rsi">RSI</option><option value="macd">MACD</option></select></label></div>' +
      '<figure class="fig"><div class="chart" id="lab" data-chart="lab"></div><figcaption id="lab-note"></figcaption></figure></section>';
    return h;
  }
  function candleToggle() {
    return '<div class="seg" role="group" aria-label="ローソク足の色"><span class="chips-label">ローソク足の色</span>' +
      '<button type="button" data-candle="us" class="' + (state.candle === 'us' ? 'on' : '') + '">上昇=緑 / 下落=赤</button><button type="button" data-candle="jp" class="' + (state.candle === 'jp' ? 'on' : '') + '">上昇=赤 / 下落=青(日本式)</button></div>';
  }
  function labUpdate() {
    var el = $('#lab'); if (!el) return;
    var ma = []; if ($('#lab-ma1').checked) ma.push(25); if ($('#lab-ma2').checked) ma.push(75);
    var ind = $('#lab-ind').value;
    el._opt = { ma: ma, bb: $('#lab-bb').checked, vol: $('#lab-vol').checked, ind: ind || null };
    var notes = [];
    if (ma.length) notes.push('移動平均線: 線が上向きで株価がその上にある区間が上昇トレンド。天井圏では線が横ばいになり、株価が線をまたぎ始めます。');
    if (ma.length > 1) notes.push('2本の線が交わる所(クロス)は、実際の転換点よりかなり遅れている点に注目。');
    if (el._opt.bb) notes.push('ボリンジャーバンド: 横ばいで帯が狭まり、上昇が始まると帯が広がって株価が上の帯に沿って進みます。');
    if (el._opt.vol) notes.push('出来高: 上放れの時に増え、天井圏では下げる日の出来高が目立ちます。');
    if (ind === 'rsi') notes.push('RSI: 強い上昇の間は高い水準に張り付きます。70超えだけを理由に売ると早すぎます。');
    if (ind === 'macd') notes.push('MACD: ゼロより上で推移する間は上昇基調。シグナルとの交差は転換の目安ですが、遅れがあります。');
    $('#lab-note').textContent = notes.join(' ');
    drawCharts(el.parentNode);
  }
  function viewChart(id) {
    var c = chartById[id];
    if (!c) return notFound();
    var i = K.charts.indexOf(c), prev = K.charts[i - 1], next = K.charts[i + 1];
    var uses = lessons.filter(function (l) { return l.body.indexOf('{chart:' + id + '}') >= 0; });
    return '<article class="lesson"><div class="lesson-head"><p class="crumb"><a href="#charts">チャート図鑑</a> ・ ' + esc(c.cat) + '</p><h1>' + esc(c.name) + '</h1>' +
      '<figure class="fig"><div class="chart" data-chart="' + id + '"></div></figure></div>' +
      '<div class="prose"><h3>何を表しているか</h3><p>' + esc(c.what) + '</p><h3>実績者はどう使うか</h3><p>' + esc(c.how) + '</p><h3>うまくいかない時</h3><p>' + esc(c.fail) + '</p></div>' +
      (uses.length ? '<aside class="card related"><h3>このチャートが出てくるレッスン</h3><ul class="plain">' + uses.map(function (l) { return '<li><a href="#lesson-' + l.id + '">' + esc(l.t) + '</a></li>'; }).join('') + '</ul></aside>' : '') +
      '<nav class="pager">' + (prev ? '<a href="#chart-' + prev.id + '">← ' + esc(prev.name) + '</a>' : '<span></span>') + (next ? '<a href="#chart-' + next.id + '">' + esc(next.name) + ' →</a>' : '<a href="#review">チャート当てクイズ →</a>') + '</nav></article>';
  }

  /* ---- トレーダー研究 ---- */
  function viewTraders() {
    return '<div class="page-head"><h1>トレーダー研究</h1><p class="lead">長年の実績が公表・報道されている投資家に絞り、考え方と、そこから取り入れられることをまとめました。経歴や数字は本人の著書・公表・報道に基づく要約です。手法をそのまま真似るのではなく、共通する原則を自分のルールに落とし込むために使ってください。</p></div>' +
      '<section><h2>共通する5つの原則</h2><ol class="principles">' + K.principles.map(function (x) { return '<li><strong>' + esc(x[0]) + '</strong><span>' + esc(x[1]) + '</span></li>'; }).join('') + '</ol></section>' +
      '<section><h2>人物</h2><div class="trader-grid">' + K.traders.map(function (t) {
        return '<a class="trader-card" href="#trader-' + t.id + '"><span class="res-k">' + esc(t.region) + '</span><strong>' + esc(t.name) + '</strong><span>' + esc(t.style) + '</span></a>';
      }).join('') + '</div></section>';
  }
  function viewTrader(id) {
    var t = traderById[id];
    if (!t) return notFound();
    return '<article class="lesson"><div class="lesson-head"><p class="crumb"><a href="#traders">トレーダー研究</a> ・ ' + esc(t.region) + '</p><h1>' + esc(t.name) + '</h1><p class="lead">' + esc(t.style) + '</p></div>' +
      '<div class="prose"><h3>実績</h3><p>' + esc(t.record) + '</p><h3>考え方</h3><ul>' + t.ideas.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' +
      '<p class="note"><strong>取り入れること:</strong> ' + esc(t.takeaway) + '</p>' +
      '<h3>関連レッスン</h3><ul>' + t.lessons.filter(function (x) { return lessonById[x]; }).map(function (x) { return '<li><a href="#lesson-' + x + '">' + esc(lessonById[x].t) + '</a></li>'; }).join('') + '</ul>' +
      '<h3>もとにした資料</h3><ul class="sources">' + t.sources.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>' +
      '<nav class="pager"><a href="#traders">← 一覧へ</a><span></span></nav></article>';
  }

  /* ---- 用語集 ---- */
  function viewGlossary() {
    var cats = [];
    K.glossary.forEach(function (g) { if (cats.indexOf(g.cat) < 0) cats.push(g.cat); });
    return '<div class="page-head"><h1>用語集</h1><p class="lead">' + K.glossary.length + '語。上の検索窓から、別名(例: 消費者物価指数 → CPI)でも探せます。</p></div>' +
      cats.map(function (cat) {
        return '<section><h2>' + esc(cat) + '</h2><dl class="gloss">' + K.glossary.filter(function (g) { return g.cat === cat; }).map(function (g) {
          return '<div><dt><button type="button" class="term" data-term="' + esc(g.name) + '">' + esc(g.name) + '</button></dt><dd>' + esc(g.def) + '</dd></div>';
        }).join('') + '</dl></section>';
      }).join('');
  }

  /* ---- 復習 ---- */
  var session = null;
  function viewReview() {
    var due = dueList(), learned = Object.keys(state.srs).length;
    var h = '<div class="page-head"><h1>復習</h1><p class="lead">解いた問題は、正解するたびに 1日 → 3日 → 7日 → 16日 → 35日 と間隔を広げて出題します。間違えると最初に戻ります。忘れかけた頃に思い出すのが、最も記憶に残る方法です。</p></div>';
    h += '<section><div class="tiles three"><div class="tile static"><strong>今日の復習</strong><span>' + (due.length ? due.length + '問が出題待ちです。' : learned ? '今日の分は終わっています。' : 'レッスンの確認問題を解くと、ここに入ります。') + '</span>' +
      (due.length ? '<button type="button" class="btn" data-review="due">始める</button>' : '') + '</div>' +
      '<div class="tile static"><strong>ランダム10問</strong><span>確認問題 全' + questions.length + '問から出題。まだ読んでいない範囲の腕試しにも。</span><button type="button" class="btn ghost" data-review="random">始める</button></div>' +
      '<div class="tile static"><strong>ケース演習</strong><span>相場の状況を読んで、どう動くかを選びます。全' + K.cases.length + '問から10問。</span><button type="button" class="btn ghost" data-review="case">始める</button></div>' +
      '<div class="tile static"><strong>用語カード</strong><span>説明を読んで用語を当てます。全' + termCards.length + '語から10問。</span><button type="button" class="btn ghost" data-review="term">始める</button></div>' +
      '<div class="tile static"><strong>チャート当てクイズ</strong><span>注釈を消したチャートを見て、形の名前を当てます。10問。</span><button type="button" class="btn ghost" data-review="chart">始める</button></div></div></section>';
    var boxes = [0, 0, 0, 0, 0, 0];
    Object.keys(state.srs).forEach(function (id) { if (qById[id]) boxes[state.srs[id].box]++; });
    if (learned) {
      h += '<section><h2>定着の状況</h2><p class="sub">右へ進むほど、長く覚えている問題です。確認問題・ケース演習・用語カードの合計です。</p><div class="boxes">' + boxes.map(function (n, i) {
        return '<div><span class="box-n">' + n + '</span><span class="box-l">' + (i === 0 ? 'やり直し' : GAPS[i] + '日後') + '</span></div>';
      }).join('') + '</div></section>';
    }
    h += '<div id="session"></div>';
    return h;
  }
  function startSession(kind) {
    var items;
    var wrap = function (q) { return { q: q }; }, ch = kind.split('-').slice(1).join('-');
    var fresh = function (list) { // まだ解いていないもの、次に定着の浅いものを優先
      return shuffle(list).sort(function (a, b) { return (state.srs[a.id] ? state.srs[a.id].box + 1 : 0) - (state.srs[b.id] ? state.srs[b.id].box + 1 : 0); }).slice(0, 10);
    };
    if (kind === 'due') items = shuffle(dueList()).slice(0, 20).map(function (id) { return { q: qById[id] }; });
    else if (kind === 'random') items = shuffle(questions).slice(0, 10).map(wrap);
    else if (kind === 'term') items = shuffle(fresh(termCards)).map(wrap);
    else if (kind.indexOf('case') === 0) items = shuffle(fresh(K.cases.filter(function (c) { return !ch || c.ch === ch; }))).map(wrap);
    else if (kind.indexOf('test-') === 0) {
      var pool = questions.filter(function (q) { return q.lesson.stage.id === ch; }), cs = shuffle(K.cases.filter(function (c) { return c.ch === ch; })).slice(0, 4);
      items = shuffle(cs.concat(shuffle(pool).slice(0, 10 - cs.length))).map(wrap);
    } else {
      var pool = K.charts.filter(function (c) { return c.quiz; });
      items = shuffle(pool).slice(0, 10).map(function (c) {
        var wrong = shuffle(pool.filter(function (x) { return x !== c; })).slice(0, 3).map(function (x) { return x.name; });
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
        note = score >= 8 ? ' 合格です。' : ' 合格は8問以上。間違えた問題は復習に入りました。該当するレッスンを読み直してから、もう一度挑戦してください。';
      }
      box.innerHTML = '<section class="quiz"><h2>おつかれさまでした</h2><p>' + s.items.length + '問中 ' + s.right + '問正解。' + note + '</p><a class="btn" href="' + (location.hash || '#review') + '" data-reload="1">戻る</a></section>';
      session = null; return;
    }
    var it = s.items[s.i];
    var qh = quizHTML(it.q, s.i, s.items.length);
    if (it.chart) qh = qh.replace('data-qid="undefined"', '').replace('<p class="q-t">', '<figure class="fig"><div class="chart" data-chart="' + it.chart.id + '" data-plain="1"></div></figure><p class="q-t">');
    box.innerHTML = '<section class="quiz" id="session-quiz">' + (it.q.lesson ? '<p class="crumb">出典: <a href="#lesson-' + it.q.lesson.id + '">' + esc(it.q.lesson.t) + '</a></p>' : it.q.kind === 'case' ? '<p class="crumb">ケース演習 ・ ' + esc(stageById[it.q.ch].title) + '</p>' : it.q.kind === 'term' ? '<p class="crumb">用語カード ・ ' + esc(it.q.term.cat) + '</p>' : '') + qh +
      '<div class="quiz-next" hidden><button type="button" class="btn" id="next-q">' + (s.i + 1 < s.items.length ? '次の問題' : '結果を見る') + '</button>' +
      (it.chart ? ' <a href="#chart-' + it.chart.id + '">このチャートの解説を見る</a>' : '') + '</div></section>';
    drawCharts(box);
    box.scrollIntoView({ block: 'start' });
  }

  /* ---- ツール ---- */
  function viewTools() {
    var h = '<div class="page-head"><h1>ツール</h1><p class="lead">知識を判断に変えるための道具です。学習の進み具合は、このブラウザの中だけに保存されます。</p></div>';
    // ポジションサイズ
    h += '<section class="tool" id="tool-size"><h2>ポジションサイズ計算機</h2><p class="sub">1回の取引で失ってよい額から、買う株数を逆算します。<a href="#lesson-position-size">考え方のレッスン</a></p>' +
      '<div class="form">' +
      '<label>市場<select id="ps-mkt"><option value="jp">日本株(100株単位)</option><option value="us">米国株(1株単位)</option></select></label>' +
      field('ps-cap', '資金(円)', 3000000, 10000) + field('ps-risk', '1回の許容リスク(%)', 1, 0.1) +
      field('ps-entry', '買値', 2000, 0.01, 'ps-unit') + field('ps-stop', '損切り価格', 1880, 0.01, 'ps-unit2') +
      '<label id="ps-fx-wrap" hidden>為替(1ドル=円)<input type="number" id="ps-fx" value="150" step="0.1" inputmode="decimal"></label></div>' +
      '<div class="result" id="ps-out" aria-live="polite"></div></section>';
    // 期待値シミュレーター
    h += '<section class="tool" id="tool-sim"><h2>期待値シミュレーター</h2><p class="sub">勝率と損益比が同じでも、1回のリスクで資産の揺れは大きく変わります。乱数で200通りの未来を作り、その広がりを見ます。<a href="#lesson-expectancy">考え方のレッスン</a></p>' +
      '<div class="form">' + field('sim-win', '勝率(%)', 40, 1) + field('sim-rr', '平均利益 ÷ 平均損失', 3, 0.1) + field('sim-risk', '1回のリスク(資金の%)', 1, 0.1) + field('sim-n', '取引回数', 100, 10) + '</div>' +
      '<p><button type="button" class="btn ghost" id="sim-run">もう一度試す</button></p>' +
      '<div class="result" id="sim-out" aria-live="polite"></div><figure class="fig"><div class="chart" id="sim-chart"></div><figcaption>細い線は個々の試行(30本を表示)、太い線は中央値。開始時の資産を100とした推移。</figcaption></figure></section>';
    // チェックリスト
    h += '<section class="tool"><h2>買う前のチェックリスト</h2><ul class="checklist">' + [
      '相場全体(指数)は上昇トレンドか', '業績の裏付け、または明確な理由(材料)があるか', '株価は上昇トレンド(ステージ2)にあるか', '買い場は自分の型に合っているか。飛びつきではないか',
      '損切り価格を決めたか。買値から8%以内か', '株数は許容リスク(資金の1%前後)から計算したか', '利益目標は損失の2倍以上あるか', '決算発表日を確認したか', '買うと同時に損切りの逆指値を入れるか'
    ].map(function (x, i) { return '<li><label><input type="checkbox" id="ck-' + i + '"> ' + x + '</label></li>'; }).join('') + '</ul></section>';
    h += '<section class="tool"><h2>記録のバックアップ</h2><p class="sub">学習の進み具合と復習の予定は、このブラウザにだけ保存されています。別の端末に移す時は、下の文字列をコピーして、移行先で貼り付けて読み込んでください。</p>' +
      '<textarea id="bk" rows="3" spellcheck="false" aria-label="バックアップ用の文字列"></textarea><p><button type="button" class="btn ghost" id="bk-out">現在の記録を書き出す</button> <button type="button" class="btn ghost" id="bk-in">貼り付けた記録を読み込む</button> <span id="bk-msg" class="form-msg" role="status"></span></p></section>';
    return h;
  }
  function field(id, label, val, step, unitId) {
    return '<label><span>' + label + (unitId ? '<span id="' + unitId + '"></span>' : '') + '</span><input type="number" id="' + id + '" value="' + val + '" step="' + step + '" inputmode="decimal"></label>';
  }

  K.calcSize = function (o) { // {mkt, cap(円), risk(%), entry, stop, fx}
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
    if (r.shares === 0) warn.push('この条件では' + (us ? '1株' : '100株') + 'も買えません。損切りを近くできる買い場を待つか、見送ります。許容リスクを上げて合わせるのは禁物です。');
    if (r.stopPct > 8) warn.push('損切りまで' + r.stopPct.toFixed(1) + '%あります。8%を超える場合は、買うのが遅い(買値が土台から離れすぎている)可能性があります。');
    if (r.pct > 25) warn.push('投資額が資金の' + r.pct.toFixed(0) + '%になります。窓を開けて損切りを飛び越える事故に備え、1銘柄は20〜25%までが目安です。');
    if (o.risk > 2) warn.push('1回のリスクが2%を超えています。連敗時の資産減少が急に大きくなります。');
    out.innerHTML = '<div class="stats"><div><span class="st-n">' + r.shares.toLocaleString() + '<small>株</small></span><span class="st-l">買う株数</span></div>' +
      '<div><span class="st-n">' + yen(r.cost) + '<small>円</small></span><span class="st-l">投資額(資金の' + r.pct.toFixed(1) + '%)</span></div>' +
      '<div><span class="st-n">' + yen(r.loss) + '<small>円</small></span><span class="st-l">損切り時の損失(上限 ' + yen(r.budget) + '円)</span></div>' +
      '<div><span class="st-n">' + r.stopPct.toFixed(1) + '<small>%</small></span><span class="st-l">損切りまでの幅</span></div></div>' +
      '<p class="calc">計算: ' + yen(o.cap) + '円 × ' + o.risk + '% = ' + yen(r.budget) + '円 ÷ 1株あたりの損失 ' + (us ? (o.entry - o.stop).toFixed(2) + 'ドル × ' + o.fx + '円 = ' : '') + yen(r.per) + '円 = ' + r.raw.toFixed(1) + '株' + (us ? '' : ' → 100株単位に切り捨て') + '</p>' +
      warn.map(function (w) { return '<p class="warn"><span class="warn-label">注意</span>' + esc(w) + '</p>'; }).join('');
  }

  K.simulate = function (o, rand) { // {win(%), rr, risk(%), n, paths}
    var paths = [], finals = [], dds = [];
    for (var p = 0; p < o.paths; p++) {
      var eq = 100, peak = 100, dd = 0, d = [100];
      for (var i = 0; i < o.n; i++) {
        eq *= 1 + (rand() < o.win / 100 ? o.rr : -1) * o.risk / 100;
        if (eq > peak) peak = eq;
        dd = Math.max(dd, (peak - eq) / peak * 100);
        d.push(eq);
      }
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
    var r = K.simulate(o, Math.random);
    var be = 100 / (1 + o.rr);
    out.innerHTML = '<div class="stats"><div><span class="st-n ' + (r.exp > 0 ? 'up' : 'down') + '">' + (r.exp > 0 ? '+' : '') + r.exp.toFixed(2) + '<small>R</small></span><span class="st-l">1回あたりの期待値</span></div>' +
      '<div><span class="st-n">' + pct(r.p50) + '</span><span class="st-l">' + o.n + '回後の損益(中央値)</span></div>' +
      '<div><span class="st-n">' + pct(r.p5) + ' 〜 ' + pct(r.p95) + '</span><span class="st-l">運が悪い場合 〜 良い場合(90%の範囲)</span></div>' +
      '<div><span class="st-n">-' + r.dd50.toFixed(0) + '<small>%</small></span><span class="st-l">途中の最大下落(中央値。悪い場合 -' + r.dd95.toFixed(0) + '%)</span></div></div>' +
      '<p class="calc">期待値 = ' + o.win + '% × ' + o.rr + 'R − ' + (100 - o.win) + '% × 1R = ' + r.exp.toFixed(2) + 'R。この損益比で損をしない勝率は ' + be.toFixed(0) + '%以上。' + o.n + '回後に資産が減っている確率は ' + r.lose.toFixed(0) + '%。</p>' +
      (r.exp <= 0 ? '<p class="warn"><span class="warn-label">注意</span>期待値がゼロ以下です。回数を重ねるほど資産が減ります。損切りを小さくするか、利益を伸ばす必要があります。</p>' : '') +
      (r.exp > 0 && r.dd95 > 30 ? '<p class="warn"><span class="warn-label">注意</span>期待値はプラスでも、運が悪いと30%以上の下落を経験します。1回のリスクを下げると、同じ手法でも続けやすくなります。</p>' : '');
    var el = $('#sim-chart');
    el._draw = function (w) {
      var lines = r.paths.slice(0, 30).map(function (d) { return { d: d, cls: 'c-path' }; });
      lines.push({ d: r.med, cls: 'c-median' });
      el.innerHTML = K.renderLines(lines, w, 260, { base: 100, label: '資産の推移', xlabel: '取引回数 0 → ' + o.n });
    };
    drawCharts(el.parentNode);
  }
  function pct(v) { var x = v - 100; return (x >= 0 ? '+' : '') + x.toFixed(0) + '%'; }

  function notFound() { return '<div class="page-head"><h1>ページが見つかりません</h1><p class="lead"><a href="#home">ホームへ戻る</a></p></div>'; }

  /* ================= ルーティング ================= */
  var DOCK_L = [['home', 'ホーム', 'home'], ['course', '章', 'book']];
  var DOCK_M = [['macro', '因果', 'flow'], ['charts', 'チャート', 'candle'], ['traders', '人物', 'person']];
  var MENU = [['home', 'ホーム', 'home', ''], ['course', 'カリキュラム', 'book', '全8章'], ['macro', '因果マップ', 'flow', '金利・CPI・為替'], ['charts', 'チャート図鑑', 'candle', '形と出来高'], ['traders', 'トレーダー研究', 'person', '実績者の考え方'], ['review', '復習', 'redo', '間隔反復とクイズ'], ['tools', 'ツール', 'tool', '株数計算・期待値'], ['glossary', '用語集', 'abc', '']];
  var NAV_OF = { lesson: 'course', chart: 'charts', trader: 'traders' };
  var query = '';
  function dockHTML(cur) {
    var grp = function (list) { return '<div class="dock-group">' + list.map(function (n) { return '<a href="#' + n[0] + '"' + (n[0] === cur ? ' aria-current="page"' : '') + '>' + ico(n[2]) + '<span>' + n[1] + '</span></a>'; }).join('') + '</div>'; };
    var nx = nextLesson(), due = dueList().length;
    var fab = due ? ['#review', '今日の復習を始める', 'redo'] : nx ? ['#lesson-' + nx.id, '続きから学ぶ: ' + nx.t, 'play'] : ['#review', '復習する', 'redo'];
    return grp(DOCK_L) + grp(DOCK_M) + '<a class="fab" href="' + fab[0] + '" aria-label="' + esc(fab[1]) + '" title="' + esc(fab[1]) + '">' + ico(fab[2]) + '</a>';
  }
  function openMenu() {
    $('#sheet-body').innerHTML = '<h2 id="sheet-title">メニュー</h2><ul class="menu">' + MENU.map(function (n) { return '<li><a href="#' + n[0] + '">' + ico(n[2]) + n[1] + '<span>' + n[3] + '</span></a></li>'; }).join('') + '</ul>';
    $('#sheet').hidden = false; $('#sheet-close').focus();
  }
  function route() {
    var hash = (location.hash || '#home').slice(1), cut = hash.indexOf('-'), name = cut < 0 ? hash : hash.slice(0, cut), arg = cut < 0 ? '' : hash.slice(cut + 1);
    var html;
    switch (name) {
      case 'home': html = viewHome(); break;
      case 'course': html = viewCourse(arg); break;
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
    $('#dock').innerHTML = dockHTML(NAV_OF[name] || name);
    var due = dueList().length, badge = $('#due-badge');
    badge.hidden = !due; badge.textContent = due > 99 ? '99+' : due;
    $('#top').classList.toggle('searching', name === 'search');
    if (name !== 'search') { $('#q').value = ''; query = ''; }
    document.documentElement.dataset.candle = state.candle;
    var hero = $('#hero-chart');
    if (hero) hero._draw = function (w) { hero.innerHTML = K.renderSpark(K.labSeries, w, Math.round(Math.max(190, Math.min(300, w * 0.5))), true); };
    if (name === 'charts') labUpdate();
    if (name === 'tools') { sizeUpdate(); simUpdate(); }
    drawCharts(view);
    Array.prototype.forEach.call(view.querySelectorAll('[data-spark]'), function (el) { el.innerHTML = K.renderSpark(chartById[el.dataset.spark], 96, 96); });
    if (name === 'macro' && arg) { var det = $('#macro-detail'); if (det) det.scrollIntoView({ block: 'start' }); }
    else if (name !== 'search') window.scrollTo(0, 0);
  }
  function goSearch(q) {
    query = q; $('#q').value = q;
    if (location.hash === '#search') { view.innerHTML = viewSearch(q); window.scrollTo(0, 0); } else location.hash = '#search';
  }

  /* ================= イベント ================= */
  window.addEventListener('hashchange', route);
  var st;
  $('#q').addEventListener('input', function (e) { clearTimeout(st); var v = e.target.value; st = setTimeout(function () { goSearch(v.trim()); }, 180); });
  $('#search-form').addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(st); goSearch($('#q').value.trim()); });

  document.addEventListener('click', function (e) {
    var t = e.target.closest('#menu-btn,#search-open,#search-close,[data-term],[data-q],.opt,[data-review],#next-q,button[data-candle],#sim-run,#sheet-close,#bk-out,#bk-in,[data-reload]');
    if (!t) { if (e.target.id === 'sheet') closeSheet(); return; }
    if (t.id === 'menu-btn') { openMenu(); return; }
    if (t.id === 'search-open') { $('#top').classList.add('searching'); $('#q').focus(); if (location.hash !== '#search') location.hash = '#search'; return; }
    if (t.id === 'search-close') { if (location.hash === '#search') { if (history.length > 1) history.back(); else location.hash = '#home'; } return; }
    if (t.dataset.term) { openTerm(t.dataset.term); return; }
    if (t.dataset.q) { closeSheet(); goSearch(t.dataset.q); return; }
    if (t.classList.contains('opt')) { answer(t); return; }
    if (t.dataset.review) { startSession(t.dataset.review); return; }
    if (t.id === 'next-q') { session.i++; showSession(); return; }
    if (t.dataset.candle) { state.candle = t.dataset.candle; save(); route(); return; }
        if (t.id === 'sim-run') { simUpdate(); return; }
    if (t.id === 'sheet-close') { closeSheet(); return; }
    if (t.dataset.reload) { e.preventDefault(); route(); return; }
    if (t.id === 'bk-out') { $('#bk').value = JSON.stringify(state); $('#bk').select(); $('#bk-msg').textContent = '書き出しました。全体をコピーして保管してください。'; return; }
    if (t.id === 'bk-in') {
      try {
        var o = JSON.parse($('#bk').value);
        if (!o || typeof o !== 'object' || !o.done || !o.srs) throw new Error('形式');
        state = { done: o.done, srs: o.srs, tests: o.tests || {}, candle: o.candle === 'jp' ? 'jp' : 'us', last: o.last || null }; save();
        $('#bk-msg').textContent = '読み込みました。';
      } catch (err) { $('#bk-msg').textContent = '読み込めませんでした。書き出した文字列を、欠けのないよう全て貼り付けてください。'; }
    }
  });
  document.addEventListener('answered', function (e) {
    var sec = e.target.closest('.quiz');
    if (!sec) return;
    if (sec.id === 'lesson-quiz') lessonAnswered(sec);
    else if (session) { if (e.detail.ok) session.right++; sec.querySelector('.quiz-next').hidden = false; $('#next-q').focus(); }
  });
  document.addEventListener('input', function (e) {
    var id = e.target.id || '';
    if (id.indexOf('ps-') === 0) sizeUpdate();
    else if (id.indexOf('sim-') === 0) simUpdate();
    else if (id.indexOf('lab-') === 0) labUpdate();
  });
  document.addEventListener('change', function (e) { var id = e.target.id || ''; if (id.indexOf('lab-') === 0) labUpdate(); else if (id === 'ps-mkt') { if (e.target.value === 'us') { $('#ps-entry').value = 100; $('#ps-stop').value = 94; } else { $('#ps-entry').value = 2000; $('#ps-stop').value = 1880; } sizeUpdate(); } });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeSheet();
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); $('#search-open').click(); }
  });

  route();
})();
