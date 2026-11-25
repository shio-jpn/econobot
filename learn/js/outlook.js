/* 株トレ道場 - 相場の見立て
   公的統計(FRED)の数値を、プロが使う7つの視点で採点し、短期・中期の見通し、弱気筋と強気筋の見立て、
   シナリオと注目の価格水準、見立てが変わる条件を組み立てる。
   採点の基準は、実績ある投資家が語ってきた考え方と、よく使われる目安をもとにこのアプリが置いたもので、
   将来を保証するものではない。 */
(function () {
  'use strict';
  var K = (window.KABU = window.KABU || {});
  var M = K.mkt;

  function last(rows) { return rows[rows.length - 1][1]; }
  function ago(rows, k) { return rows.length > k ? rows[rows.length - 1 - k][1] : null; }
  function pctChg(rows, k) { var a = ago(rows, k); return a ? (last(rows) / a - 1) * 100 : null; }
  function ptChg(rows, k) { var a = ago(rows, k); return a == null ? null : last(rows) - a; }
  function minOf(rows, k) { return Math.min.apply(null, rows.slice(-k).map(function (r) { return r[1]; })); }
  function fmt(v, d) { return v == null ? '—' : (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-US') : v.toFixed(d == null ? 2 : d)); }
  function sg(v, d, u) { return v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(d) + (u || ''); }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }

  /* 7つの視点。score は弱気 -2 〜 強気 +2。short は数日〜2週間、mid は1〜3か月への効き方 */
  M.outlook = function (data) {
    var S = data.series, get = function (id) { return S[id] && S[id].rows && S[id].rows.length > 30 ? S[id].rows : null; };
    var spR = get('SP500') || get('NASDAQCOM') || get('DJIA');
    if (!spR || spR.length < 210) return null;
    var spName = S.SP500 ? S.SP500.name : S.NASDAQCOM ? S.NASDAQCOM.name : S.DJIA.name;
    var sp = M.stats(spR, 'index');
    var lenses = [], bear = [], bull = [], changes = [];
    function lens(o) { lenses.push(o); return o; }

    /* 1. トレンド: オニール、ミネルヴィニ、ワインスタイン */
    var tS = 0, tM = 0, tText = [];
    if (sp.stage) {
      if (sp.stage.id === 2) { tM = 2; tText.push('株価が50日・200日平均の上にあり、200日平均も上向き。上昇トレンド(ステージ2)。'); bull.push(spName + 'は上昇トレンドの形を保っている。トレンドフォローの投資家は、この形が崩れるまで売らない。'); }
      else if (sp.stage.id === 4) { tM = -2; tText.push('株価が50日・200日平均の下にあり、平均線も下向き。下降トレンド(ステージ4)。'); bear.push(spName + 'は下降トレンド。戻るたびに売られやすく、トレンドフォローの資金は買いに戻らない。'); }
      else if (sp.last > sp.sma200) { tM = -0.5; tText.push('200日平均の上にはあるが、上昇の勢いが鈍っているか、50日平均を割っている。天井圏(ステージ3)か、上昇の中の調整か、判断の分かれ目。'); }
      else { tM = -1; tText.push('200日平均を下回った。長期のトレンドが転換する警戒の局面。'); bear.push('200日平均を割った。多くの機関投資家がリスクを落とす基準の線。'); }
    }
    if (sp.sma20 != null) { var d20 = (sp.last / sp.sma20 - 1) * 100; tS = d20 > 0 ? 0.5 : -0.5; tText.push('短期の20日平均の' + (d20 >= 0 ? '上' : '下') + '(' + sg(d20, 1, '%') + ')。'); }
    lens({ id: 'trend', name: 'トレンド', who: 'オニール / ミネルヴィニ / ワインスタイン', short: tS, mid: tM, text: tText.join(''), lesson: 'trend',
      metric: '50日平均 ' + fmt(sp.sma50) + ' / 200日平均 ' + fmt(sp.sma200) });

    /* 2. 勢いと過熱: 逆張りの目線。行き過ぎは短期の反動を生む */
    var mS = 0, mM = 0, mText = [], d50 = sp.sma50 ? (sp.last / sp.sma50 - 1) * 100 : 0;
    if (sp.rsi >= 75) { mS -= 1; mText.push('RSIが' + sp.rsi.toFixed(0) + 'と過熱。短期的には一服しやすい。ただし強い上昇相場では過熱が続くことも多い。'); bear.push('短期の過熱(RSI ' + sp.rsi.toFixed(0) + ')。買いが一巡すると利益確定の売りが出やすい。'); }
    else if (sp.rsi <= 28) { mS += 1.5; mText.push('RSIが' + sp.rsi.toFixed(0) + 'と売られすぎ。短期的な反発が起きやすい水準。'); bull.push('売られすぎ(RSI ' + sp.rsi.toFixed(0) + ')。空売りの買い戻しで、短期の反発が起きやすい。'); }
    else mText.push('RSIは' + sp.rsi.toFixed(0) + 'で、極端な過熱も売られすぎもない。');
    if (d50 > 7) { mS -= 1; mText.push('50日平均から' + d50.toFixed(1) + '%上に離れており、伸びきり気味。'); }
    else if (d50 < -7) { mS += 1; mText.push('50日平均から' + Math.abs(d50).toFixed(1) + '%下に離れており、下げすぎの反動が出やすい。'); }
    if (sp.d63 != null) { mM = sp.d63 > 3 ? 0.5 : sp.d63 < -5 ? -0.5 : 0; mText.push('3か月の騰落は' + sg(sp.d63, 1, '%') + '。'); }
    lens({ id: 'momentum', name: '勢いと過熱', who: 'リバモア / 逆張りの投資家', short: mS, mid: mM, text: mText.join(''), lesson: 'oscillators',
      metric: 'RSI ' + fmt(sp.rsi, 0) + ' / 50日平均との差 ' + sg(d50, 1, '%') });

    /* 3. 恐怖と保険(オプション市場): VIXの水準と、1か月先と3か月先の予想変動率の関係 */
    var vR = get('VIXCLS'), v3R = get('VXVCLS'), oS = 0, oM = 0, oText = [], oMetric = '';
    if (vR) {
      var vix = last(vR), v5 = ptChg(vR, 5);
      oMetric = 'VIX ' + fmt(vix, 1);
      if (v3R) {
        var ratio = vix / last(v3R); oMetric += ' / VIX÷3か月VIX ' + ratio.toFixed(2);
        if (ratio > 1.05) { oS += 1.5; oM -= 0.5; oText.push('目先の予想変動率が3か月先を上回る「逆転」状態(' + ratio.toFixed(2) + ')。オプション市場がパニック的に保険を買っている。歴史的には、この逆転が解消し始めると短期の底になりやすい。'); bull.push('オプション市場は恐怖のピークに近い形(VIXの期間構造が逆転)。売りが出尽くしやすい局面。'); changes.push('VIX÷3か月VIXが1を下回って0.9へ戻れば、パニックの峠を越えた合図。'); }
        else if (ratio < 0.85 && vix < 14) { oS -= 0.5; oM -= 0.5; oText.push('VIXが低く、期間構造も深い順調な形(' + ratio.toFixed(2) + ')。保険が安く、市場は油断している。上昇は続きやすいが、何かのきっかけで急な下げが起きた時の値幅は大きくなりやすい。'); bear.push('オプション市場の油断(VIX ' + vix.toFixed(1) + ')。保険が安い時ほど、想定外の材料への備えが薄い。'); }
        else oText.push('VIXの期間構造は平常(' + ratio.toFixed(2) + ')。オプション市場に強い恐怖も油断も見られない。');
      } else {
        if (vix >= 30) { oS += 1; oM -= 1; oText.push('VIXが' + vix.toFixed(1) + 'と恐怖が強い状態。短期的には売られすぎからの反発が起きやすい一方、相場の土台は不安定。'); bull.push('VIXが30超。恐怖が強い時は、売りが出尽くしやすい。'); }
        else if (vix < 13) { oM -= 0.5; oText.push('VIXが' + vix.toFixed(1) + 'と低い。保険が安く、油断が広がっている。'); bear.push('VIXが低く、市場が油断している。'); }
        else oText.push('VIXは' + vix.toFixed(1) + 'で平常の範囲。');
      }
      if (v5 != null && v5 >= 5) { oText.push('5日でVIXが' + v5.toFixed(1) + 'ポイント上昇。オプションの売り手が保険の需要に押され、株の値動きが荒くなりやすい。'); oS -= 0.5; }
      if (v5 != null && v5 <= -4 && vix < 22) { oText.push('VIXが5日で' + Math.abs(v5).toFixed(1) + 'ポイント低下。不安が後退し、保険を外す動き(株の買い戻し)が出ている。'); oM += 0.5; }
      oText.push('VIX÷16が1日の予想変動率の目安で、今は約' + (vix / 16).toFixed(1) + '%。');
    }
    lens({ id: 'options', name: '恐怖と保険(オプション市場)', who: 'オプション市場 / ポール・チューダー・ジョーンズ', short: oS, mid: oM, text: oText.join('') || 'データがありません。', lesson: 'options-pro', metric: oMetric || '—' });

    /* 4. 信用: バーリや空売り筋が最も重視する。信用市場は株より先に悪化する */
    var hR = get('BAMLH0A0HYM2'), cS = 0, cM = 0, cText = [], cMetric = '';
    if (hR) {
      var hy = last(hR), h21 = ptChg(hR, 21), h63 = ptChg(hR, 63);
      cMetric = 'ハイイールド債スプレッド ' + hy.toFixed(2) + '%(1か月 ' + sg(h21 * 100, 0, 'bp') + ')';
      if (h21 >= 0.5) { cM = -2; cS = -0.5; cText.push('低格付け社債の上乗せ金利が1か月で' + (h21 * 100).toFixed(0) + 'bp拡大。信用市場が明確に悪化しており、空売り筋が最も警戒する形。'); bear.push('信用スプレッドが急拡大(1か月 +' + (h21 * 100).toFixed(0) + 'bp)。2007年のように、信用の悪化は株の下落に先行することが多い。'); }
      else if (h21 >= 0.25) { cM = -1; cText.push('上乗せ金利が1か月で' + (h21 * 100).toFixed(0) + 'bp拡大。信用市場に警戒の兆し。'); bear.push('信用スプレッドがじわりと拡大。'); }
      else if (h21 <= -0.25) { cM = 1; cText.push('上乗せ金利が1か月で' + Math.abs(h21 * 100).toFixed(0) + 'bp縮小。企業の資金繰りへの不安が後退している。'); bull.push('信用スプレッドが縮小。リスクを取る資金が戻っている。'); }
      else cText.push('信用スプレッドは落ち着いている。信用市場から危険の合図は出ていない。');
      if (hy < 3.2) { cText.push('水準は' + hy.toFixed(2) + '%と歴史的に低く、信用の油断が見られる。バーリのような懐疑派は、こうした「リスクの値段が安すぎる」状態を警戒する。'); cM -= 0.5; }
      if (sp.fromHigh > -3 && h21 >= 0.25) { cText.push('株価は高値圏なのに信用が悪化する「逆行」。天井の前によく見られる形。'); cM -= 0.5; }
      changes.push('ハイイールド債スプレッドが1か月で50bp以上広がれば、中期の見立てを弱気に引き下げる。');
    }
    lens({ id: 'credit', name: '信用', who: 'マイケル・バーリ / 空売り筋', short: cS, mid: cM, text: cText.join('') || 'データがありません。', lesson: 'short-sellers', metric: cMetric || '—' });

    /* 5. 金利と金融政策: ドラッケンミラー「FRBに逆らうな」 */
    var y10 = get('DGS10'), y2 = get('DGS2'), rS = 0, rM = 0, rText = [], rMetric = '';
    if (y10) {
      var c10 = ptChg(y10, 21) * 100, c2 = y2 ? ptChg(y2, 21) * 100 : null;
      rMetric = '米10年 ' + last(y10).toFixed(2) + '%(1か月 ' + sg(c10, 0, 'bp') + ')' + (y2 ? ' / 2年 ' + last(y2).toFixed(2) + '%(' + sg(c2, 0, 'bp') + ')' : '');
      if (c10 >= 40) { rM = -1.5; rText.push('長期金利が1か月で' + c10.toFixed(0) + 'bp上昇。株の割引率が上がり、特に高PERの成長株に強い逆風。'); bear.push('長期金利の急上昇(1か月 +' + c10.toFixed(0) + 'bp)。2022年のように、利益が伸びても評価が下がる環境。'); }
      else if (c10 >= 20) { rM = -0.5; rText.push('長期金利が1か月で' + c10.toFixed(0) + 'bp上昇。株の評価にじわじわ逆風。'); bear.push('長期金利がじわりと上昇(1か月 +' + c10.toFixed(0) + 'bp)。高PER株の評価の重し。'); }
      else if (c10 <= -30) {
        if (sp.d21 < -3) { rM = -0.5; rText.push('長期金利が' + Math.abs(c10).toFixed(0) + 'bp低下しているが、株も下げている。金利低下の理由は景気への不安で、「悪い金利低下」の可能性。'); bear.push('金利と株が同時に下落。景気悪化を心配する動き。'); }
        else { rM = 1; rText.push('長期金利が' + Math.abs(c10).toFixed(0) + 'bp低下し、株も底堅い。金融緩和への期待が株を支えている。'); bull.push('金利低下が株の評価を押し上げている。'); }
      } else rText.push('金利は大きく動いておらず、株への影響は中立。');
      if (y2 && c2 != null && c2 <= -30 && c10 - c2 >= 15) { rM -= 0.5; rText.push('2年金利が10年金利より大きく低下(ブル・スティープ化)。市場が利下げを急いで織り込んでいる。過去の景気後退の多くはこの形で始まった。'); changes.push('2年金利の急低下が続けば、景気後退を警戒して見立てを弱気に。'); }
    }
    lens({ id: 'rates', name: '金利と金融政策', who: 'ドラッケンミラー', short: rS, mid: rM, text: rText.join('') || 'データがありません。', lesson: 'rates', metric: rMetric || '—' });

    /* 6. 流動性: お金の量と借りやすさ */
    var wR = get('WALCL'), nR = get('NFCI'), lM = 0, lText = [], lMetric = [];
    if (wR) { var w = pctChg(wR, 13); lMetric.push('FRBの総資産 3か月 ' + sg(w, 1, '%')); if (w >= 2) { lM += 1; lText.push('FRBの資産が増えており、市場に資金が供給されている。'); bull.push('FRBの資産が拡大し、流動性が増えている。'); } else if (w <= -2) { lM -= 0.5; lText.push('FRBの資産が減っており(量的引き締め)、資金がゆっくり吸い上げられている。'); } else lText.push('FRBの資産は大きく変わっていない。'); }
    if (nR) { var nf = last(nR), nc = ptChg(nR, 4); lMetric.push('金融環境指数 ' + nf.toFixed(2) + '(1か月 ' + sg(nc, 2) + ')'); if (nf > 0) { lM -= 1; lText.push('シカゴ連銀の金融環境指数がプラスで、平均よりお金を借りにくい状態。'); bear.push('金融環境が平均より引き締まっている。'); } else if (nc != null && nc >= 0.15) { lM -= 0.5; lText.push('金融環境が1か月で引き締まる方向に動いた。'); } else if (nc != null && nc <= -0.1) { lM += 0.5; lText.push('金融環境が緩む方向。'); } else lText.push('金融環境は平均より緩い状態を保っている。'); }
    lens({ id: 'liquidity', name: '流動性', who: 'ドラッケンミラー / マクロ投資家', short: 0, mid: lM, text: lText.join('') || 'データがありません(公開版の更新後に表示)。', lesson: 'liquidity', metric: lMetric.join(' / ') || '—' });

    /* 7. ドル: 強すぎるドルは世界のリスク資産の重し */
    var dR = get('DTWEXBGS'), dM = 0, dText = '', dMetric = '';
    if (dR) { var dc = pctChg(dR, 21); dMetric = 'ドル指数 1か月 ' + sg(dc, 1, '%'); if (dc >= 3) { dM = -1; dText = 'ドルが1か月で' + dc.toFixed(1) + '%上昇。世界のドル資金が引き締まり、リスク資産の重し。'; bear.push('ドルの急伸。世界の資金繰りが窮屈になる。'); } else if (dc <= -3) { dM = 0.5; dText = 'ドルが下落し、世界のリスク資産に追い風。'; } else dText = 'ドルは大きく動いていない。'; }
    lens({ id: 'dollar', name: 'ドル', who: 'グローバルマクロ', short: 0, mid: dM, text: dText || 'データがありません(公開版の更新後に表示)。', lesson: 'fx', metric: dMetric || '—' });

    /* バーリ流の過熱チェック: 割高・信用の油断・恐怖の欠如が重なると、懐疑派は売りの準備を始める */
    var over200 = sp.sma200 ? (sp.last / sp.sma200 - 1) * 100 : 0, hyNow = hR ? last(hR) : null, vixNow = vR ? last(vR) : null;
    var froth = [over200 > 12, hyNow != null && hyNow < 3.2, vixNow != null && vixNow < 14, sp.rsi > 70];
    var frothN = froth.filter(Boolean).length;
    var burry = { n: frothN, items: [['200日平均から12%以上の上方乖離', froth[0], '+' + over200.toFixed(1) + '%'], ['信用スプレッドが3.2%未満(リスクの値段が安い)', froth[1], hyNow == null ? '—' : hyNow.toFixed(2) + '%'], ['VIXが14未満(恐怖の欠如)', froth[2], vixNow == null ? '—' : vixNow.toFixed(1)], ['RSIが70超(短期の過熱)', froth[3], sp.rsi.toFixed(0)]] };
    if (frothN >= 3) { bear.push('過熱の条件が' + frothN + 'つ重なっている。バーリのような懐疑派が売りを検討し始める環境。ただし、こうした状態は何か月も続くことがある。'); }

    /* 集計 */
    var shortScore = lenses.reduce(function (a, l) { return a + l.short; }, 0);
    var midScore = lenses.reduce(function (a, l) { return a + l.mid; }, 0) + (frothN >= 3 ? -1 : 0);
    function verdict(sc, span) {
      var up = clamp(Math.round(50 + sc * 6), 20, 80), label;
      if (sc >= 2) label = '上昇が続く可能性が高い'; else if (sc >= 0.75) label = 'やや上昇寄り'; else if (sc > -0.75) label = '方向感が乏しい(中立)'; else if (sc > -2) label = 'やや下落寄り'; else label = '下落が続く可能性が高い';
      return { score: Math.round(sc * 10) / 10, up: up, down: 100 - up, label: label, span: span, cls: sc >= 0.75 ? 'up' : sc <= -0.75 ? 'down' : 'flat' };
    }
    var vS = verdict(shortScore, '数日〜2週間'), vM = verdict(midScore, '1〜3か月');

    /* シナリオと注目の価格水準 */
    var hi = sp.high, lo20 = minOf(spR, 20);
    var pBull = clamp(vM.up - 15, 10, 60), pBear = clamp(vM.down - 15, 10, 60), pBase = 100 - pBull - pBear;
    var scen = [
      { name: '強気シナリオ', p: pBull, cls: 'up', text: '52週高値(' + fmt(hi) + ')を終値で上抜け、新高値を更新。信用と金利が落ち着いたまま、主導株が上昇を続ける。', trigger: '終値で ' + fmt(hi) + ' を上抜け' },
      { name: '基本シナリオ', p: pBase, cls: 'flat', text: sp.last > sp.sma50 ? '50日平均(' + fmt(sp.sma50) + ')を支えに、高値と支持線の間で上下しながら方向を探る。' : '50日平均(' + fmt(sp.sma50) + ')が上値を抑え、200日平均(' + fmt(sp.sma200) + ')との間で揉み合う。', trigger: fmt(Math.min(sp.sma50, sp.sma200)) + '〜' + fmt(hi) + ' の範囲' },
      { name: '弱気シナリオ', p: pBear, cls: 'down', text: (sp.last > sp.sma200 ? '直近20日の安値(' + fmt(lo20) + ')と50日平均を割り込み、200日平均(' + fmt(sp.sma200) + ')まで下げる。' : '直近20日の安値(' + fmt(lo20) + ')を割り込み、下落が加速する。') + '信用スプレッドの拡大が伴えば、下げは深くなる。', trigger: '終値で ' + fmt(Math.min(lo20, sp.sma50)) + ' を割り込む' }
    ];
    changes.unshift(spName + 'が終値で200日平均(' + fmt(sp.sma200) + ')を' + (sp.last > sp.sma200 ? '割り込めば、中期の見立てを弱気に切り替える。' : '回復すれば、中期の見立てを中立以上に引き上げる。'));
    changes.push('52週高値(' + fmt(hi) + ')を出来高を伴って上抜け、信用スプレッドも落ち着いていれば、強気の見立てを強める。');

    /* 日本株 */
    var nk = get('NIKKEI225'), fxR = get('DEXJPUS'), jp = null;
    if (nk && nk.length > 210) {
      var ns = M.stats(nk, 'index'), fxc = fxR ? pctChg(fxR, 21) : null, lines = [];
      lines.push('日経平均は' + (ns.stage ? ns.stage.name : '判定不可') + '。50日平均の' + (ns.last > ns.sma50 ? '上' : '下') + '、RSI ' + ns.rsi.toFixed(0) + '。');
      if (fxc != null) lines.push('ドル円は1か月で' + sg(fxc, 1, '%') + (fxc > 1.5 ? '(円安)。輸出株には追い風。' : fxc < -1.5 ? '(円高)。輸出株の重しになり、株安と円高が重なると下げが大きくなりやすい。' : '。為替の影響は中立。'));
      lines.push('米国株の見立て(中期: ' + vM.label + ')は、翌朝の日本株の方向に強く影響する。特に半導体など値がさ株。');
      jp = { stage: ns.stage, text: lines.join('') };
    }

    return { date: sp.date, name: spName, sp: sp, lenses: lenses, short: vS, mid: vM, bear: bear, bull: bull, scenarios: scen, changes: changes, burry: burry, jp: jp };
  };

  /* AIに渡す材料(数値と採点結果だけ) */
  M.outlookContext = function (data, o) {
    var lines = ['# 採点結果(アプリの規則による目安)', '対象: ' + o.name + '(' + o.date + ')', '短期(' + o.short.span + '): ' + o.short.label + '、スコア' + o.short.score + '、上昇の目安' + o.short.up + '%', '中期(' + o.mid.span + '): ' + o.mid.label + '、スコア' + o.mid.score + '、上昇の目安' + o.mid.up + '%'];
    o.lenses.forEach(function (l) { lines.push('- ' + l.name + '(' + l.who + '): 短期' + sg(l.short, 1) + ' 中期' + sg(l.mid, 1) + ' / ' + l.metric + ' / ' + l.text); });
    lines.push('過熱チェック(バーリ流): ' + o.burry.n + '/4 ' + o.burry.items.map(function (x) { return x[0] + '=' + (x[1] ? '該当' : '非該当') + '(' + x[2] + ')'; }).join('、'));
    o.scenarios.forEach(function (s) { lines.push('シナリオ ' + s.name + ' ' + s.p + '%: ' + s.text); });
    if (o.jp) lines.push('日本株: ' + o.jp.text);
    return lines.join('\n') + '\n\n# 市場データ\n' + M.context(data);
  };
})();
