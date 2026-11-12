/* SCOA-A 学習アプリ本体 */
(() => {
  'use strict';
  const BANK = window.SCOA_BANK || [], GEN = window.SCOA_GEN || {};
  const SUBJ = [
    { k: '言語', cls: 'lang', n: 20, d: '語彙・熟語・ことわざ・敬語・文学史' },
    { k: '数理', cls: 'math', n: 25, d: '計算・方程式・割合・速さ・確率・図形' },
    { k: '論理', cls: 'logic', n: 25, d: '命題・推論・集合・サイコロ・暗号' },
    { k: '常識', cls: 'gen', n: 25, d: '社会(歴史・地理・政経・時事)と理科' },
    { k: '英語', cls: 'eng', n: 25, d: '同意語・文法・熟語・発音・ことわざ' },
  ];
  const CLS = Object.fromEntries(SUBJ.map((s) => [s.k, s.cls]));
  const MARK = ['①', '②', '③', '④', '⑤'];
  const PACE = 30; // 本番ペース:1問30秒
  const EXAM_SEC = 60 * 60;

  /* ---------- 小道具 ---------- */
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const rnd = (n) => Math.floor(Math.random() * n);
  const shuffle = (a) => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = rnd(i + 1); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const hash = (s) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h.toString(36); };
  const pad = (n) => String(n).padStart(2, '0');
  const dayKey = (t) => { const d = new Date(t); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const WD = ['日', '月', '火', '水', '木', '金', '土'];
  const dayLabel = (k) => { const [y, m, d] = k.split('-').map(Number); const dt = new Date(y, m - 1, d); return `${m}月${d}日(${WD[dt.getDay()]})`; };
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  const mmss = (s) => `${Math.floor(s / 60)}:${pad(s % 60)}`;

  BANK.forEach((q) => { q.id = hash(q.s + '|' + q.q + '|' + (q.fig || '') + '|' + q.ch[0]); });
  const BY_ID = Object.fromEntries(BANK.map((q) => [q.id, q]));

  /* ---------- 保存(端末 + 対応環境ではアカウント) ---------- */
  const KEY = 'scoa-a.v1';
  const Store = {
    days: {}, col: null, cloudIds: new Set(), dirty: new Set(), busy: false, timer: 0, status: 'local', seq: 0,
    load() { try { const o = JSON.parse(localStorage.getItem(KEY) || '{}'); if (o && o.days) this.days = o.days; } catch (e) { /* 保存領域が使えない場合は空で開始 */ } },
    saveLocal() { try { localStorage.setItem(KEY, JSON.stringify({ v: 1, days: this.days })); return true; } catch (e) { return false; } },
    stamp() { return Date.now() * 10 + (this.seq++ % 10); },
    add(rec) { const k = dayKey(rec.t / 10); (this.days[k] = this.days[k] || []).push(rec); this.saveLocal(); this.dirty.add(k); this.flushSoon(); },
    all() { return Object.keys(this.days).sort().flatMap((k) => this.days[k]); },
    flushSoon() { clearTimeout(this.timer); this.timer = setTimeout(() => this.flush(), 3000); },
    async flush() {
      if (!this.col || this.busy) return;
      this.busy = true;
      try {
        while (this.dirty.size) {
          const k = this.dirty.values().next().value; this.dirty.delete(k);
          const recs = this.days[k] || [];
          const parts = Math.max(1, Math.ceil(recs.length / 100));
          for (let i = 0; i < parts; i++) { const id = `day-${k}-${i}`; await this.col.doc(id).set({ date: k, part: i, recs: recs.slice(i * 100, i * 100 + 100) }); this.cloudIds.add(id); }
        }
        this.status = 'cloud';
      } catch (e) { this.status = 'clouderr'; }
      this.busy = false;
    },
    async initCloud() {
      try {
        if (!window.claude || !window.claude.use) return;
        const [db, user] = await Promise.all([window.claude.use('db'), window.claude.use('user')]);
        if (!db || !user) return;
        const uid = await user.id(); if (!uid) return;
        const col = db.collection('data/users/' + uid);
        const snap = await col.limit(1000).get();
        const cloud = {};
        snap.docs.forEach((d) => { this.cloudIds.add(d.id); const b = d.data(); if (b && b.date && Array.isArray(b.recs)) cloud[b.date] = (cloud[b.date] || []).concat(JSON.parse(JSON.stringify(b.recs))); });
        new Set([...Object.keys(cloud), ...Object.keys(this.days)]).forEach((k) => {
          const loc = this.days[k] || [], cl = cloud[k] || [], seen = new Set(cl.map((r) => r.t));
          const extra = loc.filter((r) => !seen.has(r.t));
          if (extra.length || (!cl.length && loc.length)) this.dirty.add(k);
          this.days[k] = cl.concat(extra).sort((a, b) => a.t - b.t);
        });
        this.col = col; this.status = 'cloud'; this.saveLocal(); this.flush();
        if (S.view !== 'quiz') render();
      } catch (e) { /* アカウント保存が使えない場合は端末保存のまま */ }
    },
    async clear() {
      this.days = {}; this.dirty.clear(); this.saveLocal();
      if (this.col) { for (const id of [...this.cloudIds]) { try { await this.col.doc(id).delete(); this.cloudIds.delete(id); } catch (e) { /* 次回に再試行 */ } } }
    },
  };

  /* ---------- 集計 ---------- */
  const recKey = (r) => r.id || 'g:' + hash(r.q + (r.f || ''));
  function latestMap() { const m = new Map(); Store.all().forEach((r) => m.set(recKey(r), r)); return m; }
  function weakRecs(subj) { return [...latestMap().values()].filter((r) => !r.ok && (!subj || r.s === subj) && recToQ(r)); }
  function subjStat(k) { const rs = Store.all().filter((r) => r.s === k); return { n: rs.length, ok: rs.filter((r) => r.ok).length }; }
  function streak() { let n = 0; const d = new Date(); if (!Store.days[dayKey(d)]) d.setDate(d.getDate() - 1); while ((Store.days[dayKey(d)] || []).length) { n++; d.setDate(d.getDate() - 1); } return n; }

  /* ---------- 出題 ---------- */
  function fromBank(b) { return { s: b.s, c: b.c, id: b.id, q: b.q, ch: b.ch, e: b.e, f: b.fig, order: shuffle([0, 1, 2, 3, 4]) }; }
  function fromGen(s, g) { for (let i = 0; i < 60; i++) { const r = g.f(); if (r && r.ch && r.ch.length === 5 && new Set(r.ch).size === 5) return { s, c: g.c, q: r.q, ch: r.ch, e: r.e, f: r.fig, order: shuffle([0, 1, 2, 3, 4]) }; } return null; }
  function recToQ(r) {
    if (r.id) { const b = BY_ID[r.id]; return b ? fromBank(b) : null; }
    return r.q && r.ch ? { s: r.s, c: r.c, q: r.q, ch: r.ch, e: r.e, f: r.f, order: shuffle([0, 1, 2, 3, 4]) } : null;
  }
  function catsOf(subj) {
    const m = new Map();
    BANK.filter((b) => b.s === subj).forEach((b) => m.set(b.c, (m.get(b.c) || 0) + 1));
    (GEN[subj] || []).forEach((g) => { if (!m.has(g.c)) m.set(g.c, '∞'); });
    return [...m.entries()];
  }
  function buildSet(subj, cats, n, order) {
    const inCat = (c) => !cats.length || cats.includes(c);
    let st = BANK.filter((b) => b.s === subj && inCat(b.c));
    const gens = (GEN[subj] || []).filter((g) => inCat(g.c));
    const last = latestMap();
    const rank = (b) => { const r = last.get(b.id); const state = !r ? 0 : r.ok ? 2 : 1; return order === 'weak' ? [1, 0, 2][state] : order === 'new' ? state : 0; };
    st = shuffle(st).sort((a, b) => rank(a) - rank(b));
    let g = gens.length ? Math.round((n * gens.length * 3) / (gens.length * 3 + st.length)) : 0;
    if (st.length < n - g) g = gens.length ? n - st.length : 0;
    const out = st.slice(0, n - g).map(fromBank);
    let pool = [];
    for (let i = 0; i < g; i++) { if (!pool.length) pool = shuffle(gens); const q = fromGen(subj, pool.pop()); if (q) out.push(q); }
    return shuffle(out);
  }
  function buildExam() { return SUBJ.flatMap((s) => { const set = buildSet(s.k, [], s.n, 'rand'); return set; }); }

  /* ---------- 状態 ---------- */
  const S = { view: 'home', setup: null, quiz: null, result: null, day: null, dayFilter: '', confirm: '', msg: '' };
  let tick = 0;
  function go(v) { S.view = v; S.confirm = ''; S.msg = ''; clearInterval(tick); render(); window.scrollTo(0, 0); }

  function startQuiz(qs, mode, title, timed) {
    if (!qs.length) { S.msg = '出題できる問題がありません。'; render(); return; }
    S.quiz = { qs, mode, title, timed, i: 0, picked: null, recs: [], answers: qs.map(() => null), left: mode === 'exam' ? EXAM_SEC : PACE, open: false };
    S.view = 'quiz'; S.confirm = ''; render(); window.scrollTo(0, 0); startTimer();
  }
  function startTimer() {
    clearInterval(tick); const z = S.quiz; if (!z) return;
    if (z.mode === 'exam') { const end = Date.now() + z.left * 1000; tick = setInterval(() => { z.left = Math.max(0, Math.round((end - Date.now()) / 1000)); paintTimer(); if (!z.left) finishExam(); }, 500); }
    else if (z.timed && z.picked === null) { z.left = PACE; const end = Date.now() + PACE * 1000; tick = setInterval(() => { z.left = Math.max(0, Math.round((end - Date.now()) / 1000)); paintTimer(); if (!z.left) answer(-1); }, 250); }
    paintTimer();
  }
  function paintTimer() { const el = $('#timer'), z = S.quiz; if (!el || !z) return; el.textContent = z.mode === 'exam' ? mmss(z.left) : z.left + '秒'; el.classList.toggle('hot', z.mode === 'exam' ? z.left <= 300 : z.left <= 10); }
  function mkRec(q, disp, mode) {
    const u = disp < 0 ? -1 : q.order[disp];
    const r = { t: Store.stamp(), s: q.s, c: q.c, u, ok: u === 0, m: mode };
    if (q.id) r.id = q.id; else { r.q = q.q; r.ch = q.ch; r.e = q.e; if (q.f) r.f = q.f; }
    return r;
  }
  function answer(disp) {
    const z = S.quiz; if (!z || z.picked !== null) return;
    clearInterval(tick); z.picked = disp;
    const r = mkRec(z.qs[z.i], disp, z.mode === 'review' ? 'r' : 'p'); z.recs.push(r); Store.add(r);
    render();
    const fb = $('#feedback'); if (fb && fb.scrollIntoView) fb.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function next() { const z = S.quiz; if (z.i + 1 >= z.qs.length) return finish(); z.i++; z.picked = null; render(); window.scrollTo(0, 0); startTimer(); }
  function finish() { const z = S.quiz; clearInterval(tick); Store.flush(); S.result = { title: z.title, recs: z.recs, mode: z.mode }; S.quiz = null; go('result'); }
  function finishExam() { const z = S.quiz; if (!z) return; clearInterval(tick); z.qs.forEach((q, i) => { const r = mkRec(q, z.answers[i] === null ? -1 : z.answers[i], 'e'); z.recs.push(r); Store.add(r); }); finish(); }

  /* ---------- 部品 ---------- */
  const chip = (s) => `<span class="chip ${CLS[s] || ''}">${esc(s)}</span>`;
  const figHtml = (f) => (f ? `<pre class="fig">${esc(f)}</pre>` : '');
  const qText = (t) => esc(t).replace(/\n/g, '<br>');
  function recItem(r, i) {
    const q = r.id ? BY_ID[r.id] : r; if (!q) return '';
    const ch = q.ch, body = ch.map((c, j) => `<li class="${j === 0 ? 'is-ok' : j === r.u ? 'is-ng' : ''}">${esc(c)}${j === 0 ? '<b>正解</b>' : ''}${j === r.u ? '<b>あなたの回答</b>' : ''}</li>`).join('');
    return `<details class="rec ${r.ok ? 'ok' : 'ng'}"><summary><span class="judge">${r.ok ? '○' : '×'}</span><span class="rec-q">${chip(r.s)}<span class="rec-cat">${esc(r.c)}</span><span class="rec-t">${esc(q.q)}</span></span></summary>
      <div class="rec-body"><p class="q-text">${qText(q.q)}</p>${figHtml(q.fig || q.f)}<ul class="rec-ch">${body}</ul>${r.u < 0 ? '<p class="note">時間切れ・未回答</p>' : ''}<div class="expl"><h4>解説</h4><p>${esc(q.e)}</p></div></div></details>`;
  }
  function scoreBar(ok, n) { return `<div class="bar" role="img" aria-label="正答率${pct(ok, n)}%"><i style="width:${pct(ok, n)}%"></i></div>`; }
  function bySubj(recs) { return SUBJ.map((s) => { const rs = recs.filter((r) => r.s === s.k); return { s, n: rs.length, ok: rs.filter((r) => r.ok).length }; }).filter((x) => x.n); }

  /* ---------- 画面 ---------- */
  function vHome() {
    const today = Store.days[dayKey(Date.now())] || [], all = Store.all(), tk = today.filter((r) => r.ok).length, weak = weakRecs().length;
    const strip = []; const d = new Date(); d.setDate(d.getDate() - 13);
    for (let i = 0; i < 14; i++) { const k = dayKey(d), n = (Store.days[k] || []).length; strip.push(`<i class="lv${n === 0 ? 0 : n < 10 ? 1 : n < 30 ? 2 : 3}" title="${dayLabel(k)} ${n}問"></i>`); d.setDate(d.getDate() + 1); }
    return `<header class="top"><p class="eyebrow">SCOA-A 基礎能力検査</p><h1>きょうの学習</h1></header>
    <section class="today"><div class="today-num"><b>${today.length}</b><span>問</span></div>
      <dl class="today-meta"><div><dt>きょうの正答率</dt><dd>${today.length ? pct(tk, today.length) + '%' : '—'}</dd></div><div><dt>連続学習</dt><dd>${streak()}日</dd></div><div><dt>累計</dt><dd>${all.length}問</dd></div></dl>
      <div class="strip" aria-label="直近14日の学習量">${strip.join('')}</div><p class="strip-cap">直近14日(右端がきょう)</p></section>
    <h2>教科を選ぶ</h2>
    <div class="subjects">${SUBJ.map((s) => { const st = subjStat(s.k); return `<button class="subject ${s.cls}" data-act="setup" data-s="${s.k}"><span class="s-mark" aria-hidden="true">${s.k[0]}</span><span class="s-main"><b>${s.k}</b><small>${s.d}</small>${scoreBar(st.ok, st.n)}</span><span class="s-rate">${st.n ? pct(st.ok, st.n) + '<small>%</small>' : '<small>未学習</small>'}</span></button>`; }).join('')}</div>
    <h2>本番形式・復習</h2>
    <div class="actions"><button class="action" data-act="examintro"><b>模擬試験</b><small>120問・60分。5教科を本番の配分で</small></button>
      <button class="action" data-act="go" data-v="review"><b>苦手を復習</b><small>${weak ? `直近で間違えた問題が${weak}問` : '間違えた問題がここにたまります'}</small></button></div>`;
  }
  function vSetup() {
    const u = S.setup, cats = catsOf(u.s), st = BANK.filter((b) => b.s === u.s).length, hasGen = (GEN[u.s] || []).length;
    const seg = (name, val, items) => `<div class="seg" role="group">${items.map(([v, l]) => `<button class="${String(val) === String(v) ? 'on' : ''}" data-act="set" data-k="${name}" data-v="${v}">${l}</button>`).join('')}</div>`;
    return `<header class="top sub"><button class="back" data-act="go" data-v="home" aria-label="ホームへ戻る">←</button><div><p class="eyebrow">${chip(u.s)}</p><h1>${u.s}の出題設定</h1></div></header>
    <p class="lead">固定問題${st}問${hasGen ? '+ 数値が毎回変わる自動生成問題' : ''}。本番は${SUBJ.find((x) => x.k === u.s).n}問前後が出題されます。</p>
    <h3>分野 <small>(選ばなければ全分野)</small></h3>
    <div class="cats">${cats.map(([c, n]) => `<button class="cat ${u.cats.includes(c) ? 'on' : ''}" data-act="cat" data-c="${esc(c)}">${esc(c)}<small>${n}</small></button>`).join('')}</div>
    <h3>問題数</h3>${seg('n', u.n, [[5, '5問'], [10, '10問'], [20, '20問'], [30, '30問']])}
    <h3>出題順</h3>${seg('order', u.order, [['new', '未出題を優先'], ['weak', '苦手を優先'], ['rand', 'ランダム']])}
    <h3>タイマー</h3>${seg('timed', u.timed ? 1 : 0, [[0, 'なし'], [1, '本番ペース(1問30秒)']])}
    ${S.msg ? `<p class="msg">${esc(S.msg)}</p>` : ''}
    <div class="sticky"><button class="primary" data-act="start">${u.n}問をはじめる</button></div>`;
  }
  function vQuiz() {
    const z = S.quiz, q = z.qs[z.i], exam = z.mode === 'exam', done = z.picked !== null, sel = exam ? z.answers[z.i] : z.picked;
    const choices = q.order.map((orig, d) => {
      let cls = '';
      if (exam) cls = sel === d ? 'sel' : '';
      else if (done) cls = orig === 0 ? 'ok' : sel === d ? 'ng' : 'dim';
      return `<button class="choice ${cls}" data-act="pick" data-d="${d}" ${!exam && done ? 'disabled' : ''}><span class="oval">${MARK[d]}</span><span class="c-text">${esc(q.ch[orig])}</span></button>`;
    }).join('');
    const ok = done && z.picked >= 0 && q.order[z.picked] === 0;
    const fb = !exam && done ? `<section id="feedback" class="feedback ${ok ? 'ok' : 'ng'}"><p class="verdict">${ok ? '○ 正解' : z.picked < 0 ? '× 時間切れ' : '× 不正解'}</p><p class="ans">正解:${MARK[q.order.indexOf(0)]} ${esc(q.ch[0])}</p><div class="expl"><h4>解説</h4><p>${esc(q.e)}</p></div></section>` : '';
    const answered = z.answers.filter((a) => a !== null).length;
    const foot = exam
      ? `<div class="sticky two"><button class="ghost" data-act="prev" ${z.i === 0 ? 'disabled' : ''}>前へ</button>${z.i + 1 < z.qs.length ? '<button class="primary" data-act="enext">次へ</button>' : `<button class="primary" data-act="grade">${S.confirm === 'grade' ? 'もう一度押して採点' : '採点する'}</button>`}</div>`
      : done ? `<div class="sticky"><button class="primary" data-act="next">${z.i + 1 < z.qs.length ? '次の問題へ' : '結果を見る'}</button></div>` : '';
    return `<header class="quizbar"><button class="back" data-act="quit" aria-label="中断する">${S.confirm === 'quit' ? '中断する?' : '×'}</button>
      <div class="progress"><span>${z.i + 1}<small> / ${z.qs.length}</small></span><div class="bar"><i style="width:${((z.i + (done ? 1 : 0)) / z.qs.length) * 100}%"></i></div></div>
      ${exam || z.timed ? `<span id="timer" class="timer">${exam ? mmss(z.left) : z.left + '秒'}</span>` : '<span class="timer off"></span>'}</header>
    ${exam ? `<p class="exam-info">回答済み ${answered} / ${z.qs.length}<button class="link" data-act="grade">${S.confirm === 'grade' ? 'もう一度押して採点' : '終了して採点'}</button></p>` : ''}
    <article class="question"><p class="q-meta">${chip(q.s)}<span>${esc(q.c)}</span></p><p class="q-text">${qText(q.q)}</p>${figHtml(q.f)}</article>
    <div class="choices">${choices}</div>${fb}${foot}`;
  }
  function vResult() {
    const r = S.result, ok = r.recs.filter((x) => x.ok).length, n = r.recs.length, ng = n - ok, bs = bySubj(r.recs);
    return `<header class="top"><p class="eyebrow">${esc(r.title)}</p><h1>結果</h1></header>
    <section class="score"><div class="score-num"><b>${ok}</b><span>/ ${n}問 正解</span></div><p class="score-rate">正答率 ${pct(ok, n)}%</p>${scoreBar(ok, n)}</section>
    ${bs.length > 1 ? `<table class="tbl"><thead><tr><th>教科</th><th>正解</th><th>正答率</th></tr></thead><tbody>${bs.map((x) => `<tr><td>${chip(x.s.k)}</td><td>${x.ok} / ${x.n}</td><td>${pct(x.ok, x.n)}%</td></tr>`).join('')}</tbody></table>` : ''}
    <div class="actions">${ng ? `<button class="action" data-act="retry-result"><b>間違えた${ng}問を解き直す</b><small>正解するまで繰り返すのが近道です</small></button>` : ''}<button class="action" data-act="go" data-v="home"><b>ホームへ戻る</b><small>この結果はきょうの履歴に保存済みです</small></button></div>
    <h2>解答と解説</h2><div class="recs">${r.recs.map(recItem).join('')}</div>`;
  }
  function vHistory() {
    const keys = Object.keys(Store.days).filter((k) => Store.days[k].length).sort().reverse();
    if (!keys.length) return `<header class="top"><p class="eyebrow">日ごとの記録</p><h1>履歴</h1></header><div class="empty"><p>まだ履歴がありません。</p><p>問題を解くと、その日の記録がここに並び、いつでも解き直せます。</p><button class="primary" data-act="go" data-v="home">教科を選んではじめる</button></div>`;
    return `<header class="top"><p class="eyebrow">日ごとの記録</p><h1>履歴</h1></header>
    <div class="days">${keys.map((k) => { const rs = Store.days[k], ok = rs.filter((r) => r.ok).length; return `<button class="day" data-act="day" data-k="${k}"><span class="day-date">${dayLabel(k)}<small>${k.slice(0, 4)}年</small></span><span class="day-main"><b>${rs.length}問</b><span class="day-chips">${bySubj(rs).map((x) => `<span class="chip ${x.s.cls}">${x.s.k} ${x.n}</span>`).join('')}</span>${scoreBar(ok, rs.length)}</span><span class="s-rate">${pct(ok, rs.length)}<small>%</small></span></button>`; }).join('')}</div>`;
  }
  function vDay() {
    const k = S.day, all = Store.days[k] || [], rs = all.filter((r) => !S.dayFilter || r.s === S.dayFilter), ok = rs.filter((r) => r.ok).length, ng = rs.length - ok;
    const subs = bySubj(all);
    return `<header class="top sub"><button class="back" data-act="go" data-v="history" aria-label="履歴へ戻る">←</button><div><p class="eyebrow">${k.slice(0, 4)}年の履歴</p><h1>${dayLabel(k)}</h1></div></header>
    <div class="cats">${[['', 'すべて']].concat(subs.map((x) => [x.s.k, x.s.k])).map(([v, l]) => `<button class="cat ${S.dayFilter === v ? 'on' : ''}" data-act="dayfilter" data-s="${v}">${l}</button>`).join('')}</div>
    <section class="score small"><div class="score-num"><b>${ok}</b><span>/ ${rs.length}問 正解(${pct(ok, rs.length)}%)</span></div>${scoreBar(ok, rs.length)}</section>
    <div class="actions"><button class="action" data-act="redo-day" data-w="ng" ${ng ? '' : 'disabled'}><b>間違えた${ng}問を解き直す</b><small>この日の×だけをもう一度</small></button><button class="action" data-act="redo-day" data-w="all"><b>この日の全${rs.length}問を解き直す</b><small>同じ問題を、選択肢の並びを変えて出題</small></button></div>
    <h2>解いた問題</h2><div class="recs">${rs.slice().reverse().map(recItem).join('')}</div>`;
  }
  function vReview() {
    const weak = weakRecs(), rows = SUBJ.map((s) => ({ s, n: weak.filter((r) => r.s === s.k).length }));
    if (!weak.length) return `<header class="top"><p class="eyebrow">間違えた問題の解き直し</p><h1>復習</h1></header><div class="empty"><p>いま復習が必要な問題はありません。</p><p>間違えた問題は自動でここに集まり、正解すると消えます。日ごとの解き直しは「履歴」からできます。</p><button class="primary" data-act="go" data-v="history">履歴を見る</button></div>`;
    return `<header class="top"><p class="eyebrow">間違えた問題の解き直し</p><h1>復習</h1></header>
    <p class="lead">最後に解いたとき不正解だった問題が${weak.length}問あります。解き直して正解すると、ここから消えます。</p>
    <div class="actions"><button class="action" data-act="redo-weak" data-s=""><b>全教科まとめて復習</b><small>${Math.min(20, weak.length)}問を出題</small></button></div>
    <div class="subjects">${rows.map((x) => `<button class="subject ${x.s.cls}" data-act="redo-weak" data-s="${x.s.k}" ${x.n ? '' : 'disabled'}><span class="s-mark" aria-hidden="true">${x.s.k[0]}</span><span class="s-main"><b>${x.s.k}</b><small>${x.n ? '苦手問題を解き直す' : '苦手問題なし'}</small></span><span class="s-rate">${x.n}<small>問</small></span></button>`).join('')}</div>
    <h2>最近間違えた問題</h2><div class="recs">${weak.sort((a, b) => b.t - a.t).slice(0, 30).map(recItem).join('')}</div>`;
  }
  function vExamIntro() {
    return `<header class="top sub"><button class="back" data-act="go" data-v="home" aria-label="ホームへ戻る">←</button><div><p class="eyebrow">本番形式</p><h1>模擬試験</h1></div></header>
    <p class="lead">本番と同じ120問・60分。1問あたり約30秒です。途中では正誤を表示せず、採点後に全問の解答と解説を確認できます。</p>
    <table class="tbl"><thead><tr><th>教科</th><th>問題数</th></tr></thead><tbody>${SUBJ.map((s) => `<tr><td>${chip(s.k)}</td><td>${s.n}問</td></tr>`).join('')}<tr><td><b>合計</b></td><td><b>120問</b></td></tr></tbody></table>
    <ul class="tips"><li>わからない問題は飛ばし、解ける問題から確実に取る。</li><li>誤答で減点はないので、最後は空欄を残さない。</li><li>結果はきょうの履歴に保存され、あとから解き直せます。</li></ul>
    <div class="sticky"><button class="primary" data-act="exam">60分の模擬試験をはじめる</button></div>`;
  }
  function vSettings() {
    const where = Store.status === 'cloud' ? 'アカウントとこの端末の両方に保存中。別の端末で開いても同じ履歴を使えます。' : Store.status === 'clouderr' ? 'アカウントへの保存に失敗しました。履歴はこの端末には保存されています。' : 'この端末のブラウザに保存中。ブラウザのデータを消去すると履歴も消えるため、ときどきバックアップを取ってください。';
    return `<header class="top"><p class="eyebrow">データと出題について</p><h1>設定</h1></header>
    <h2>履歴の保存先</h2><p class="lead">${where}</p>
    <h2>バックアップ</h2>
    <p class="lead">履歴をテキストにして書き出します。メモアプリなどに貼り付けて保管してください。</p>
    <button class="ghost wide" data-act="export">履歴を書き出す</button>
    <label class="field" for="io">書き出したテキスト / 読み込むテキスト</label>
    <textarea id="io" rows="4" placeholder="ここに書き出されます。読み込むときは、保管したテキストを貼り付けてください。"></textarea>
    <div class="row"><button class="ghost" data-act="copy">コピー</button><button class="ghost" data-act="import">貼り付けたテキストを読み込む</button></div>
    ${S.msg ? `<p class="msg">${esc(S.msg)}</p>` : ''}
    <h2>履歴の消去</h2><button class="danger wide" data-act="wipe">${S.confirm === 'wipe' ? 'もう一度押すとすべて消去します' : 'すべての履歴を消去する'}</button>
    <h2>SCOA-A の出題について</h2>
    <p class="lead">5分野・120問を60分で解く五肢択一の試験です。1問あたり約30秒。内容は中学〜高校の基礎ですが範囲が広く、速く正確に解く力が問われます。下の配分は参考書などで一般的とされるもので、実施先により異なる場合があります。</p>
    <table class="tbl"><thead><tr><th>教科</th><th>目安</th><th>収録</th></tr></thead><tbody>${SUBJ.map((s) => `<tr><td>${chip(s.k)}</td><td>${s.n}問</td><td>${BANK.filter((b) => b.s === s.k).length}問${(GEN[s.k] || []).length ? ' + 自動生成' + GEN[s.k].length + '種' : ''}</td></tr>`).join('')}</tbody></table>`;
  }

  const VIEWS = { home: vHome, setup: vSetup, quiz: vQuiz, result: vResult, history: vHistory, day: vDay, review: vReview, examintro: vExamIntro, settings: vSettings };
  const TABS = [['home', 'ホーム'], ['history', '履歴'], ['review', '復習'], ['settings', '設定']];
  function render() {
    const keep = S.view === 'settings' && $('#io') ? $('#io').value : null;
    $('#app').innerHTML = VIEWS[S.view]();
    if (keep !== null && $('#io')) $('#io').value = keep;
    const tabOf = { setup: 'home', examintro: 'home', result: 'home', day: 'history' }[S.view] || S.view;
    $('#nav').hidden = S.view === 'quiz';
    $('#nav').innerHTML = TABS.map(([v, l]) => `<button class="${tabOf === v ? 'on' : ''}" data-act="go" data-v="${v}" ${tabOf === v ? 'aria-current="page"' : ''}>${l}</button>`).join('');
    document.body.classList.toggle('in-quiz', S.view === 'quiz');
  }

  /* ---------- 操作 ---------- */
  const twice = (key, fn) => { if (S.confirm === key) { S.confirm = ''; fn(); } else { S.confirm = key; render(); } };
  const A = {
    go: (d) => go(d.v),
    setup: (d) => { S.setup = { s: d.s, cats: [], n: 10, order: 'new', timed: false }; go('setup'); },
    cat: (d) => { const c = S.setup.cats, i = c.indexOf(d.c); if (i < 0) c.push(d.c); else c.splice(i, 1); render(); },
    set: (d) => { const u = S.setup; if (d.k === 'n') u.n = +d.v; else if (d.k === 'timed') u.timed = d.v === '1'; else u.order = d.v; render(); },
    start: () => { const u = S.setup; startQuiz(buildSet(u.s, u.cats, u.n, u.order), 'practice', u.s + (u.cats.length ? '(' + u.cats.join('・') + ')' : ''), u.timed); },
    pick: (d) => { const z = S.quiz; if (z.mode === 'exam') { z.answers[z.i] = z.answers[z.i] === +d.d ? null : +d.d; S.confirm = ''; render(); paintTimer(); } else answer(+d.d); },
    next, prev: () => { S.quiz.i--; S.confirm = ''; render(); paintTimer(); window.scrollTo(0, 0); },
    enext: () => { S.quiz.i++; S.confirm = ''; render(); paintTimer(); window.scrollTo(0, 0); },
    grade: () => twice('grade', finishExam),
    quit: () => { const z = S.quiz; if (z.mode !== 'exam' && !z.recs.length) return go('home'); twice('quit', () => { if (z.mode === 'exam') { clearInterval(tick); S.quiz = null; go('home'); } else finish(); }); paintTimer(); },
    examintro: () => go('examintro'),
    exam: () => startQuiz(buildExam(), 'exam', '模擬試験(120問・60分)', true),
    'retry-result': () => startQuiz(S.result.recs.filter((r) => !r.ok).map(recToQ).filter(Boolean), 'review', '解き直し', false),
    day: (d) => { S.day = d.k; S.dayFilter = ''; go('day'); },
    dayfilter: (d) => { S.dayFilter = d.s; render(); },
    'redo-day': (d) => { const seen = new Set(); const rs = (Store.days[S.day] || []).filter((r) => (!S.dayFilter || r.s === S.dayFilter) && (d.w === 'all' || !r.ok)).filter((r) => { const k = recKey(r); if (seen.has(k)) return false; seen.add(k); return true; }); startQuiz(shuffle(rs.map(recToQ).filter(Boolean)), 'review', dayLabel(S.day) + 'の解き直し', false); },
    'redo-weak': (d) => startQuiz(shuffle(weakRecs(d.s)).slice(0, 20).map(recToQ).filter(Boolean), 'review', (d.s || '全教科') + 'の苦手復習', false),
    export: () => { $('#io').value = JSON.stringify({ app: 'scoa-a', v: 1, days: Store.days }); S.msg = '書き出しました。「コピー」を押して保管してください。'; render(); },
    copy: () => { const el = $('#io'); el.select(); const done = (ok) => { S.msg = ok ? 'コピーしました。' : 'コピーできませんでした。テキストを長押しして手動でコピーしてください。'; render(); }; try { navigator.clipboard.writeText(el.value).then(() => done(true), () => done(false)); } catch (e) { done(false); } },
    import: () => {
      try {
        const o = JSON.parse($('#io').value); if (!o || typeof o.days !== 'object') throw 0; let n = 0;
        Object.keys(o.days).forEach((k) => { if (!/^\d{4}-\d{2}-\d{2}$/.test(k) || !Array.isArray(o.days[k])) return; const cur = Store.days[k] || [], seen = new Set(cur.map((r) => r.t)); const add = o.days[k].filter((r) => r && typeof r.t === 'number' && typeof r.s === 'string' && !seen.has(r.t)); if (add.length) { Store.days[k] = cur.concat(add).sort((a, b) => a.t - b.t); Store.dirty.add(k); n += add.length; } });
        Store.saveLocal(); Store.flush(); S.msg = n ? `${n}問分の履歴を読み込みました。` : '新しく読み込む履歴はありませんでした。';
      } catch (e) { S.msg = '読み込めませんでした。書き出したテキスト全体を貼り付けてください。'; }
      render();
    },
    wipe: () => twice('wipe', async () => { await Store.clear(); S.msg = 'すべての履歴を消去しました。'; render(); }),
  };
  document.addEventListener('click', (ev) => { const el = ev.target.closest('[data-act]'); if (!el || el.disabled) return; const f = A[el.dataset.act]; if (f) f(el.dataset); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) Store.flush(); });

  Store.load(); render(); Store.initCloud();
})();
