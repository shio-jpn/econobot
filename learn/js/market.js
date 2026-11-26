/* 株トレ道場 - 実データの分析
   data/market.json(毎朝のBotがFREDの公的統計から書き出す)を読み、指数の状態と「今日の値動きの型」を判定する。
   ここにある判定は、値動きの組み合わせから典型的な原因を当てはめた目安で、原因を断定するものではない。 */
(function () {
  'use strict';
  var K = (window.KABU = window.KABU || {});
  var M = (K.mkt = {});

  M.ORDER = ['SP500', 'NASDAQCOM', 'DJIA', 'NIKKEI225', 'DGS10', 'DGS2', 'T10Y2Y', 'DEXJPUS', 'DTWEXBGS', 'VIXCLS', 'VXVCLS', 'DCOILWTICO', 'BAMLH0A0HYM2', 'NFCI', 'WALCL'];
  M.RATE_KINDS = { yield: 1, spread: 1, gauge: 1 };

  /* 読み込み。無ければ null(この画面はデータ無しの説明に切り替える) */
  var loading = null;
  M.load = function () {
    if (loading) return loading;
    if (typeof fetch !== 'function') return (loading = Promise.resolve(null));
    loading = fetch('data/market.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return d && d.series && Object.keys(d.series).length ? d : null; })
      .catch(function () { return null; });
    return loading;
  };

  /* 深掘り分析(data/analysis.json)。無ければ null */
  var aLoading = null;
  M.loadAnalysis = function () {
    if (aLoading) return aLoading;
    if (typeof fetch !== 'function') return (aLoading = Promise.resolve(null));
    aLoading = fetch('data/analysis.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return d && d.features && Object.keys(d.features).length ? d : null; })
      .catch(function () { return null; });
    return aLoading;
  };

  function avg(a, from, to) { var s = 0; for (var i = from; i < to; i++) s += a[i]; return s / (to - from); }
  function smaAt(v, n) { return v.length >= n ? avg(v, v.length - n, v.length) : null; }
  function rsiLast(v, n) {
    if (v.length <= n) return null;
    var g = 0, l = 0, i;
    for (i = 1; i <= n; i++) { var d = v[i] - v[i - 1]; if (d > 0) g += d; else l -= d; }
    g /= n; l /= n;
    for (i = n + 1; i < v.length; i++) { var e = v[i] - v[i - 1]; g = (g * (n - 1) + Math.max(e, 0)) / n; l = (l * (n - 1) + Math.max(-e, 0)) / n; }
    return l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }

  /* 1つの系列の状態。rows: [[日付, 値], ...] 古い順 */
  M.stats = function (rows, kind) {
    var v = rows.map(function (r) { return r[1]; }), n = v.length;
    if (n < 2) return null;
    var rate = !!M.RATE_KINDS[kind];
    var ch = function (k) { if (n <= k) return null; return rate ? v[n - 1] - v[n - 1 - k] : (v[n - 1] / v[n - 1 - k] - 1) * 100; };
    var last = v[n - 1], s50 = smaAt(v, 50), s200 = smaAt(v, 200);
    var s200prev = n >= 221 ? avg(v, n - 221, n - 21) : null;
    var win = v.slice(Math.max(0, n - 252)), hi = Math.max.apply(null, win), lo = Math.min.apply(null, win);
    var rets = [];
    for (var i = Math.max(1, n - 20); i < n; i++) rets.push(Math.log(v[i] / v[i - 1]));
    var mean = rets.reduce(function (a, b) { return a + b; }, 0) / (rets.length || 1);
    var sd = Math.sqrt(rets.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / Math.max(1, rets.length - 1));
    var st = {
      date: rows[n - 1][0], prevDate: rows[n - 2][0], last: last, rate: rate, kind: kind,
      d1: ch(1), d5: ch(5), d21: ch(21), d63: ch(63),
      sma20: smaAt(v, 20), sma50: s50, sma200: s200,
      slope200: s200 != null && s200prev != null ? (s200 / s200prev - 1) * 100 : null,
      rsi: rsiLast(v, 14), high: hi, low: lo,
      fromHigh: (last / hi - 1) * 100, fromLow: (last / lo - 1) * 100,
      vol20: rate ? null : sd * Math.sqrt(252) * 100
    };
    st.stage = kind === 'index' || kind === 'fx' ? M.stage(st) : null;
    return st;
  };

  /* ステージ(トレンドの局面)の目安 */
  M.stage = function (st) {
    if (st.rate || st.sma50 == null || st.sma200 == null) return null;
    var up = st.slope200 != null && st.slope200 > 0;
    if (st.last > st.sma50 && st.sma50 > st.sma200 && up) return { id: 2, name: '上昇トレンド(ステージ2)', cls: 'up' };
    if (st.last < st.sma50 && st.sma50 < st.sma200 && st.slope200 != null && st.slope200 < 0) return { id: 4, name: '下降トレンド(ステージ4)', cls: 'down' };
    if (st.last > st.sma200 && !up) return { id: 3, name: '上昇の勢いが鈍化(ステージ3の可能性)', cls: 'warn' };
    if (st.last < st.sma200 && up) return { id: 3, name: '200日線割れ(トレンド転換の警戒)', cls: 'warn' };
    return { id: 1, name: '方向感の乏しい横ばい', cls: 'flat' };
  };

  /* 人が読める説明 */
  M.describe = function (st) {
    if (!st || st.rate) return [];
    var out = [];
    var rel = function (ma, name) { if (ma == null) return; var d = (st.last / ma - 1) * 100; out.push(name + 'の' + (d >= 0 ? '上' : '下') + '(' + (d >= 0 ? '+' : '') + d.toFixed(1) + '%)'); };
    rel(st.sma50, '50日平均'); rel(st.sma200, '200日平均');
    if (st.slope200 != null) out.push('200日平均は' + (st.slope200 > 0.3 ? '上向き' : st.slope200 < -0.3 ? '下向き' : 'ほぼ横ばい'));
    if (st.rsi != null) out.push('RSI ' + st.rsi.toFixed(0) + (st.rsi >= 70 ? '(強い上昇・過熱気味)' : st.rsi <= 30 ? '(売られすぎ)' : ''));
    out.push('52週高値から' + st.fromHigh.toFixed(1) + '%');
    if (st.vol20 != null) out.push('直近20日の値動きの大きさ 年率' + st.vol20.toFixed(0) + '%');
    return out;
  };

  /* 今日の値動きの型。株・金利・ドル・VIX・信用スプレッドの同じ日の変化から当てはめる */
  M.regime = function (data) {
    var S = data.series, get = function (id) { return S[id] ? M.stats(S[id].rows, S[id].kind) : null; };
    var eq = get('SP500') || get('NASDAQCOM') || get('DJIA');
    if (!eq || eq.d1 == null) return null;
    var same = function (st) { return st && st.date === eq.date ? st : null; };
    var y10 = same(get('DGS10')), y2 = same(get('DGS2')), vix = same(get('VIXCLS')), hy = same(get('BAMLH0A0HYM2')), fx = same(get('DEXJPUS'));
    var e = eq.d1, y = y10 ? y10.d1 * 100 : null, v = vix ? vix.d1 : null, h = hy ? hy.d1 * 100 : null, usd = fx ? fx.d1 : null;
    var f = function (x, d, u) { return x == null ? '未公表' : (x >= 0 ? '+' : '') + x.toFixed(d) + u; };
    var facts = ['株(S&P500など) ' + f(e, 2, '%'), '米10年金利 ' + f(y, 0, 'bp'), 'VIX ' + f(v, 1, 'pt'), 'ドル円 ' + f(usd, 2, '%'), 'ハイイールド債スプレッド ' + f(h, 0, 'bp')];
    var r;
    if (Math.abs(e) < 0.3) r = { id: 'quiet', title: '方向感の乏しい日', text: '指数の動きが小さく、相場を動かす大きな材料は効いていません。こういう日は、指数より業種ごと・銘柄ごとの差(決算や個別の材料)を見ると、資金の向かう先が分かります。', lessons: ['daily-read', 'relative-strength'] };
    else if (e < 0) {
      if (y != null && y >= 5) r = { id: 'rate-up-down', title: 'インフレ・金利上昇型の下げ', text: '株安と同時に長期金利が上昇しています。物価指標の上振れ、タカ派的な発言、国債の需給悪化など、利下げ期待が後退する材料が考えられます。高PERの成長株・小型株が最も影響を受けやすい型です。', lessons: ['daily-read', 'rates', 'inflation', 'central-banks'] };
      else if (y != null && y <= -5 && ((v != null && v >= 2) || (h != null && h >= 10))) r = { id: 'risk-off', title: 'リスクオフ(景気・信用不安)型の下げ', text: '株安と同時に金利が低下し、恐怖指数や信用スプレッドが上昇しています。景気悪化の指標、信用不安、地政学など、安全資産への逃避が起きている型です。日本株は円高が重なりやすく、二重の逆風になります。', lessons: ['daily-read', 'risk-on-off', 'jobs', 'liquidity'] };
      else if (y != null && y <= -5) r = { id: 'growth-scare', title: '景気懸念型の下げ', text: '株安と金利低下が同時に起きています。景気の減速を示す材料が意識されている可能性があります。景気敏感株・小型株が弱く、ディフェンシブが相対的に強くなりやすい型です。', lessons: ['daily-read', 'cycle', 'jobs'] };
      else r = { id: 'equity-specific', title: '株固有の要因による下げ', text: '金利や為替は大きく動いていません。大型株の決算、規制、オプションの満期や指数の入れ替えなどの需給、利益確定など、株式市場の中の要因が考えられます。どの業種・銘柄に下げが集中したかを確認します。', lessons: ['daily-read', 'supply-demand', 'earnings'] };
    } else {
      if (y != null && y <= -5) r = { id: 'easing-rally', title: '金利低下(緩和期待)型の上昇', text: '株高と同時に長期金利が低下しています。物価の落ち着き、ハト派的な発言など、利下げ期待が高まる材料が考えられます。成長株・小型株・不動産が最も恩恵を受けやすい型です。', lessons: ['daily-read', 'rates', 'inflation'] };
      else if (y != null && y >= 5) r = { id: 'growth-rally', title: '景気期待型の上昇', text: '株高と同時に金利も上昇しています。景気の強さを示す材料が好感されている型です。景気敏感株・銀行・小型株が強くなりやすく、金利に敏感な高PER株は相対的に伸びにくくなります。', lessons: ['daily-read', 'cycle', 'macro-quadrant'] };
      else r = { id: 'relief-rally', title: '不安の後退・株固有の要因による上昇', text: '金利や為替は大きく動かずに株が上がっています。好決算、イベント通過による不安の後退、売られすぎからの買い戻しなどが考えられます。指数を主導した業種と、相場の幅(値上がり銘柄の多さ)を確認します。', lessons: ['daily-read', 'priced-in', 'earnings'] };
    }
    var notes = [];
    if (y10 && y2 && y10.d1 != null && y2.d1 != null) {
      var d10 = y10.d1 * 100, d2 = y2.d1 * 100;
      if (d10 - d2 >= 5 && d10 > 0) notes.push('長期金利が短期金利より大きく上昇(ベア・スティープ化)。財政やインフレへの不安、国債の需給が意識されている可能性。高PER株に逆風。');
      if (d2 - d10 >= 5 && d2 < 0) notes.push('短期金利が長期金利より大きく低下(ブル・スティープ化)。市場が利下げを急いで織り込んでいる。景気悪化への警戒を示すことがある。');
      if (d2 - d10 >= 5 && d2 > 0) notes.push('短期金利が長期金利より大きく上昇(ベア・フラット化)。利上げ観測、または利下げ期待の後退。');
    }
    if (v != null && vix.last >= 30) notes.push('VIXが30以上。恐怖が強い状態。1日の値動きの目安は約' + (vix.last / 16).toFixed(1) + '%。株数を減らして対応する局面。');
    if (fx == null && S.DEXJPUS) notes.push('ドル円は公的統計の公表が数日遅れるため、この日の値はまだありません。');
    r.facts = facts; r.notes = notes; r.date = eq.date;
    return r;
  };

  /* AIに渡す要約(数値と判定だけ。推測は含めない) */
  M.context = function (data) {
    var lines = ['データの日付(更新時刻): ' + data.updated, '出典: ' + (data.source || 'FRED')];
    M.ORDER.forEach(function (id) {
      var s = data.series[id]; if (!s) return;
      var st = M.stats(s.rows, s.kind); if (!st) return;
      var fx = function (x, d) { return x == null ? '-' : (x >= 0 ? '+' : '') + x.toFixed(d); };
      var u = st.rate ? '%pt' : '%';
      lines.push(s.name + '(' + st.date + '): ' + st.last + ' 前日比' + fx(st.d1, st.rate ? 2 : 2) + u + ' 5日' + fx(st.d5, 2) + u + ' 1か月' + fx(st.d21, 2) + u +
        (st.rate ? '' : ' / ' + M.describe(st).join('、') + (st.stage ? ' / ' + st.stage.name : '')));
    });
    var r = M.regime(data);
    if (r) lines.push('アプリの判定(目安): ' + r.title + '。' + r.notes.join(' '));
    if (data.headline) lines.push('当日のニュースの見出し(AI要約): ' + data.headline);
    (data.points || []).forEach(function (p) { lines.push('ニュースの要点: ' + p.text); });
    return lines.join('\n');
  };

  /* チャート演習(実データ): ある日までを見せ、その後20営業日の結果を隠す */
  M.drillCase = function (rows, rand, hold) {
    hold = hold || 20;
    var n = rows.length, look = 160, pre = 60;
    if (n < look + hold + 210) return null;
    var cut = 210 + Math.floor(rand() * (n - hold - 210 - look)) + look;
    var win = rows.slice(cut - look - pre, cut + hold + 1);
    var v0 = rows[cut][1], v1 = rows[cut + hold][1], ret = (v1 / v0 - 1) * 100;
    var ans = ret > 2 ? 'up' : ret < -2 ? 'down' : 'flat';
    return { win: win, pre: pre, split: look + pre, ret: ret, ans: ans, stats: M.stats(rows.slice(0, cut + 1), 'index'), date: rows[cut][0] };
  };
  /* 何も考えずに同じ答えを続けた場合の的中率(基準率) */
  M.baseRates = function (rows, hold) {
    hold = hold || 20;
    var c = { up: 0, down: 0, flat: 0 }, n = 0;
    for (var i = 0; i + hold < rows.length; i += 5) {
      var r = (rows[i + hold][1] / rows[i][1] - 1) * 100;
      c[r > 2 ? 'up' : r < -2 ? 'down' : 'flat']++; n++;
    }
    return { up: c.up / n * 100, down: c.down / n * 100, flat: c.flat / n * 100, n: n };
  };
})();
