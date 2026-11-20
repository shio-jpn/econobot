#!/usr/bin/env node
/* 問題データの検証。使い方: node tools/validate.js  /  node tools/validate.js --find 語句(IDを調べる) */
const path = require('path'), dir = path.join(__dirname, '..');
global.window = {};
['questions.js', 'questions2027.js', 'updates.js', 'gen.js'].forEach((f) => { if (f !== 'questions2027.js' || require('fs').existsSync(path.join(dir, f))) require(path.join(dir, f)); });
const hash = (s) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h.toString(36); };
const idOf = (q) => hash(q.s + '|' + q.q + '|' + (q.fig || '') + '|' + q.ch[0]);
const SUBJ = ['言語', '数理', '論理', '常識', '英語'], errs = [];
const bank = window.SCOA_BANK.map((q) => ({ ...q, src: q.ed ? 'questions' + q.ed + '.js' : 'questions.js' }));
const ups = window.SCOA_UPDATES;
if (!Array.isArray(ups)) errs.push('SCOA_UPDATES が配列ではない');
let prev = '';
(ups || []).forEach((u, i) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(u.date || '')) errs.push(`更新${i}: date が YYYY-MM-DD ではない`);
  if (u.date < prev) errs.push(`更新${i}: 日付が古い順に並んでいない`); prev = u.date;
  if (!u.note) errs.push(`更新${i}: note がない`);
  if (!Array.isArray(u.sources) || !u.sources.length) errs.push(`更新${i}: sources がない`);
  (u.add || []).forEach((q) => bank.push({ ...q, src: 'updates ' + u.date }));
});
const ids = new Map();
bank.forEach((q) => {
  const tag = `[${q.src}] ${String(q.q).slice(0, 30)}`;
  if (!SUBJ.includes(q.s)) return errs.push(tag + ': 教科が不正');
  if (!q.c || !q.q || !q.e) errs.push(tag + ': 分野・問題文・解説のいずれかが空');
  if (!Array.isArray(q.ch) || q.ch.length !== 5 || new Set(q.ch).size !== 5 || q.ch.some((c) => typeof c !== 'string' || !c.trim())) return errs.push(tag + ': 選択肢は重複のない5個の文字列');
  if (q.asof && !/^\d{4}-\d{2}$/.test(q.asof)) errs.push(tag + ': asof は YYYY-MM');
  const id = idOf(q); if (ids.has(id)) errs.push(tag + ': 同じ問題がすでにある'); ids.set(id, q);
});
const retired = new Set();
(ups || []).forEach((u) => (u.retire || []).forEach((id) => { if (!ids.has(id)) errs.push(`更新 ${u.date}: retire のID ${id} が存在しない`); retired.add(id); }));
let genN = 0;
for (const s in window.SCOA_GEN) for (const g of window.SCOA_GEN[s]) { genN++; let ok = 0; for (let i = 0; i < 300; i++) { let r; try { r = g.f(); } catch (e) { errs.push(`自動生成 ${g.c}: ${e.message}`); break; } if (!r) continue; if (r.ch.length !== 5 || new Set(r.ch).size !== 5 || /NaN|undefined/.test(JSON.stringify(r))) { errs.push(`自動生成 ${g.c}: 不正な出力`); break; } ok++; } if (!ok) errs.push(`自動生成 ${g.c}: 1問も作れない`); }
/* ノート:構造と公式計算の往復一致(ある量から他を計算し、元に戻るか) */
let noteN = 0;
if (require('fs').existsSync(path.join(dir, 'notes.js'))) {
  require(path.join(dir, 'notes.js'));
  (window.SCOA_NOTES || []).forEach((n) => {
    noteN++; if (!n.k || !n.cat || !Array.isArray(n.secs) || !n.secs.length) errs.push(`ノート ${n.k}: 形式不備`);
    n.secs.forEach((s) => { if (!s.t || !Array.isArray(s.pts) || !Array.isArray(s.cards)) errs.push(`ノート ${n.k}/${s.t}: 形式不備`); (s.ev || []).forEach((e) => { if (typeof e[0] !== 'number' || !e[1]) errs.push(`ノート ${n.k}/${s.t}: 年表の形式不備`); if (s.y && (e[0] < s.y[0] - 60 || e[0] > s.y[1])) errs.push(`ノート ${n.k}/${s.t}: ${e[0]}年が範囲外`); }); });
    (n.fx || []).forEach((f) => { const vs = f.v.map((x) => x[0]), base = {}; vs.forEach((k, i) => (base[k] = 1.7 + i * 0.9)); const t0 = Object.keys(f.solve)[0]; base[t0] = new Function(...vs, 'return ' + f.solve[t0])(...vs.map((k) => base[k]));
      Object.entries(f.solve).forEach(([k, ex]) => { const r = new Function(...vs, 'return ' + ex)(...vs.map((x) => base[x])); if (!(Math.abs(r - base[k]) <= 1e-6 * Math.max(1, Math.abs(base[k])))) errs.push(`ノート公式 ${f.n}: ${k} の式が一致しない`); }); });
  });
}
console.log('ノート:', noteN + '分野');
const find = process.argv.indexOf('--find');
if (find > 0) { const w = process.argv[find + 1] || ''; bank.filter((q) => (q.q + q.ch.join('') + q.e).includes(w)).forEach((q) => console.log(idOf(q), retired.has(idOf(q)) ? '(引退済)' : '', `[${q.s}/${q.c}]`, q.q, '→', q.ch[0])); process.exit(0); }
const live = bank.filter((q) => !retired.has(idOf(q)) && (q.ed || q.src.startsWith('updates')));
console.log('旧版(2026年版、既定では出題しない):', bank.filter((q) => !q.ed && !q.src.startsWith('updates')).length + '問');
console.log('出題中:', SUBJ.map((s) => `${s}${live.filter((q) => q.s === s).length}`).join(' '), `計${live.length}問 / 引退${retired.size}問 / 自動生成${genN}種 / 更新${(ups || []).length}回(最新 ${prev || 'なし'})`);
if (errs.length) { console.log('NG ' + errs.length + '件'); errs.forEach((e) => console.log(' - ' + e)); process.exit(1); }
console.log('OK');
