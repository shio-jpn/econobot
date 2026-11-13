/* データの整合性と検索の動作確認。実行: node learn/tests/check.js */
'use strict';
var fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
var root = path.join(__dirname, '..');
var store = {};
var noop = function () {};
var el = function () { return { addEventListener: noop, dataset: {}, style: {}, classList: { add: noop, toggle: noop }, querySelectorAll: function () { return []; }, querySelector: function () { return null; }, scrollIntoView: noop, focus: noop, set innerHTML(v) {}, value: '' }; };
var win = { addEventListener: noop, scrollTo: noop, localStorage: { getItem: function (k) { return store[k] || null; }, setItem: function (k, v) { store[k] = v; } } };
var ctx = { window: win, document: { querySelector: el, querySelectorAll: function () { return []; }, addEventListener: noop, documentElement: { dataset: {} }, activeElement: { tagName: 'BODY' } }, location: { hash: '' }, localStorage: win.localStorage, setTimeout: setTimeout, clearTimeout: clearTimeout, console: console };
vm.createContext(ctx);
var html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
html.match(/<script src="([^"]+)"/g).map(function (s) { return s.slice(13, -1); }).forEach(function (f) {
  vm.runInContext(fs.readFileSync(path.join(root, f), 'utf8'), ctx, { filename: f });
});
var K = win.KABU, n = 0;
function ok(name, fn) { fn(); n++; console.log('ok - ' + name); }

var lessons = [].concat.apply([], K.stages.map(function (s) { return s.lessons; }));
var ids = {}; lessons.forEach(function (l) { ids[l.id] = 1; });
var charts = {}; K.charts.forEach(function (c) { charts[c.id] = c; });
var terms = {}; K.glossary.forEach(function (g) { terms[g.name] = 1; });

ok('アプリ本体が読み込める(章ごとの画面を組み立てられる)', function () { assert.strictEqual(typeof K.search, 'function'); assert.strictEqual(typeof K.renderSpark, 'function'); assert(K.renderSpark(K.labSeries, 300, 150, true).indexOf('NaN') < 0); });
ok('レッスンのIDは重複せず、URLに使える文字だけ', function () {
  assert.strictEqual(Object.keys(ids).length, lessons.length);
  lessons.concat(K.charts, K.macro, K.traders, K.stages).forEach(function (x) { assert(/^[a-z0-9-]+$/.test(x.id), x.id); });
});
ok('全レッスンに本文と2問以上の確認問題(4択・解説つき)がある', function () {
  lessons.forEach(function (l) {
    assert(l.body.length > 300, l.id);
    assert(l.quiz.length >= 2, l.id);
    l.quiz.forEach(function (q) { assert.strictEqual(q.a.length, 4, l.id); assert(q.e, l.id); assert.strictEqual(new Set(q.a).size, 4, l.id + ' 選択肢の重複'); });
  });
});
ok('応用・実戦レッスンが5つの章に入り、ケース演習は章にひもづく', function () {
  ['macro', 'fundamentals', 'technical', 'risk', 'strategy'].forEach(function (id) {
    var st = K.stages.filter(function (x) { return x.id === id; })[0];
    assert(st.lessons.filter(function (l) { return l.lv; }).length >= 4, id);
    assert(K.cases.filter(function (c) { return c.ch === id; }).length >= 4, id);
  });
  var seen = {};
  K.cases.forEach(function (c) { assert(!seen[c.id] && /^c-[a-z-]+$/.test(c.id), c.id); seen[c.id] = 1; assert.strictEqual(new Set(c.a).size, 4, c.id); assert(c.e && c.q, c.id); });
  lessons.forEach(function (l) { assert(!l.lv || l.lv === '応用' || l.lv === '実戦', l.id); });
});
ok('本文が参照するチャートと図は存在する', function () {
  lessons.forEach(function (l) {
    (l.body.match(/\{chart:([\w-]+)\}/g) || []).forEach(function (m) { assert(charts[m.slice(7, -1)], l.id + ' ' + m); });
    (l.body.match(/\{candles:([\w-]+)\}/g) || []).forEach(function (m) { assert(K.candleFigs[m.slice(9, -1)], l.id + ' ' + m); });
  });
});
ok('因果マップとトレーダー研究の関連レッスンは存在する', function () {
  K.macro.concat(K.traders).forEach(function (x) { x.lessons.forEach(function (id) { assert(ids[id], x.id + ' -> ' + id); }); });
  K.macro.forEach(function (m) { m.effects.forEach(function (e) { assert(['up', 'down', 'mixed'].indexOf(e[1]) >= 0, m.id); }); });
});
ok('用語は重複せず、関連語はすべて用語集にある', function () {
  assert.strictEqual(Object.keys(terms).length, K.glossary.length);
  K.glossary.forEach(function (g) { g.rel.forEach(function (r) { assert(terms[r], g.name + ' -> ' + r); }); });
});
ok('チャートは描画でき、価格は常に正で高値>=安値', function () {
  K.charts.concat([K.labSeries]).forEach(function (c) {
    var d = K.buildSeries(c);
    d.forEach(function (k) { assert(k.l > 0 && k.h >= Math.max(k.o, k.c) && k.l <= Math.min(k.o, k.c) && k.v > 0, c.id); });
    (c.marks || []).concat(c.lines || []).forEach(function (m) { assert(m[0] < d.length, c.id + ' 注釈が範囲外'); });
    var svg = K.renderChart(c, { w: 360 });
    assert(svg.indexOf('NaN') < 0 && svg.indexOf('undefined') < 0, c.id);
  });
});
function top(q, type) { var h = K.search(q).hits; if (type) h = h.filter(function (x) { return x.d.type === type; }); return h.length ? h[0].d.title : null; }
ok('検索: 用語そのもの', function () { assert.strictEqual(top('CPI'), 'CPI'); assert.strictEqual(top('損切り'), '損切り'); });
ok('検索: 別名・表記ゆれ(正式名称、全角、ひらがな、小文字)', function () {
  assert.strictEqual(top('消費者物価指数'), 'CPI');
  assert.strictEqual(top('ＣＰＩ'), 'CPI');
  assert.strictEqual(top('cpi'), 'CPI');
  assert.strictEqual(top('ろーそく足'), 'ローソク足');
  assert.strictEqual(top('ロスカット'), '損切り');
});
ok('検索: 関連する内容(レッスン・因果マップ・チャート・人物)も出る', function () {
  var h = K.search('金利').hits, types = {};
  h.forEach(function (x) { types[x.d.type] = 1; });
  assert(types.term && types.lesson && types.macro && types.trader);
  assert.strictEqual(top('金利', 'lesson'), '金利と株価');
  assert(/金利が下がる|金利が上がる/.test(top('金利', 'macro')));
  assert.strictEqual(top('VCP', 'chart'), 'VCP(ボラティリティ収縮パターン)');
  assert.strictEqual(top('片山', 'trader'), '片山 晃');
  assert.strictEqual(top('テスタ', 'trader'), 'テスタ');
  assert(K.search('消費者物価指数').hits.some(function (x) { return x.d.type === 'macro' && /CPI/.test(x.d.title); }));
});
ok('検索: 複数語は両方を含むものに絞り、該当なしは空', function () {
  assert(/円安/.test(top('円安 輸出', 'macro')));
  assert.strictEqual(K.search('zzzqqq').hits.length, 0);
  assert.strictEqual(K.search('   ').hits.length, 0);
});
ok('ポジションサイズ: 日本株は100株単位に切り捨て、米国株は為替換算', function () {
  var jp = K.calcSize({ mkt: 'jp', cap: 3000000, risk: 1, entry: 2000, stop: 1880 });
  assert.strictEqual(jp.shares, 200); assert.strictEqual(jp.loss, 24000); assert.strictEqual(jp.cost, 400000);
  var us = K.calcSize({ mkt: 'us', cap: 3000000, risk: 1, entry: 100, stop: 94, fx: 150 });
  assert.strictEqual(us.shares, 33); assert.strictEqual(us.loss, 33 * 6 * 150);
});
ok('期待値の計算', function () {
  var r = K.simulate({ win: 35, rr: 4, risk: 1, n: 50, paths: 20 }, Math.random);
  assert(Math.abs(r.exp - 0.75) < 1e-9); assert.strictEqual(r.med.length, 51);
});
console.log('\n' + n + '件のチェックに合格。レッスン ' + lessons.length + ' / 問題 ' + lessons.reduce(function (a, l) { return a + l.quiz.length; }, 0) + ' / 用語 ' + K.glossary.length + ' / 因果マップ ' + K.macro.length + ' / チャート ' + K.charts.length + ' / 人物 ' + K.traders.length + ' / ケース ' + K.cases.length);
