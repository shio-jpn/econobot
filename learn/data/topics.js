/* トピック(項目)別の整理。章の順番ではなく、知りたいことから引けるようにする。
   1つのレッスンが複数のトピックに入ってよい。最初に入ったトピックが、そのレッスンの「本籍」になる。 */
(function () {
  'use strict';
  var K = (window.KABU = window.KABU || {});

  K.areas = [
    { id: 'market', name: '市場を読む', en: 'MACRO', note: '金利・物価・為替・相場心理。今日の値動きの理由を読み解く' },
    { id: 'company', name: '企業を読む', en: 'FUNDAMENTAL', note: '決算・評価・業種・需給。何を買うかを決める' },
    { id: 'chart', name: 'チャートを読む', en: 'TECHNICAL', note: 'トレンド・出来高・パターン・指標。いつ買い、いつ売るか' },
    { id: 'risk', name: '守る', en: 'RISK', note: '損切り・サイズ・期待値・検証。退場しない仕組み' },
    { id: 'strategy', name: '攻める', en: 'STRATEGY', note: '成長株・決算・売買の技術・相場環境' },
    { id: 'base', name: '基盤', en: 'BASE', note: '取引の仕組み・税金・心理・習慣' }
  ];

  K.topics = [
    { id: 'outlook', area: 'market', name: '相場の見通しを立てる', lessons: ['outlook-method', 'money-flow', 'short-sellers', 'scenario-thinking', 'macro-quadrant', 'intermarket'] },
    { id: 'bears', area: 'market', name: '弱気筋・空売り筋の視点', lessons: ['short-sellers', 'shorting', 'market-history', 'blowups'] },
    { id: 'daily', area: 'market', name: '今日の相場を読む', lessons: ['daily-read', 'priced-in', 'macro-events', 'intermarket', 'risk-on-off', 'jp-drivers'] },
    { id: 'rates', area: 'market', name: '金利と中央銀行', lessons: ['rates', 'central-banks', 'bonds', 'liquidity'] },
    { id: 'econ', area: 'market', name: '物価・雇用・景気', lessons: ['inflation', 'jobs', 'cycle', 'macro-quadrant', 'indicator-guide'] },
    { id: 'fx', area: 'market', name: '為替・商品・日米の違い', lessons: ['fx', 'jp-vs-us', 'jp-drivers', 'risk-on-off'] },
    { id: 'history', area: 'market', name: '歴史と相場の局面', lessons: ['market-history', 'tops-bottoms', 'blowups'] },

    { id: 'earnings', area: 'company', name: '決算と業績', lessons: ['statements', 'earnings', 'growth', 'earnings-quality', 'estimate-revisions', 'disclosure-guide'] },
    { id: 'valuation', area: 'company', name: '企業価値と評価', lessons: ['valuation', 'valuation-practice', 'business-model', 'story'] },
    { id: 'sector', area: 'company', name: '業種とテーマ', lessons: ['sector-guide', 'index-sector', 'leaders'] },
    { id: 'flow', area: 'company', name: '需給と市場の仕組み', lessons: ['supply-demand', 'microstructure', 'derivatives'] },
    { id: 'research', area: 'company', name: '銘柄の探し方と調べ方', lessons: ['research-process', 'screening-recipes', 'small-cap-growth', 'watchlist'] },

    { id: 'trend', area: 'chart', name: 'トレンドと移動平均', lessons: ['candles', 'trend', 'moving-average', 'multi-timeframe', 'relative-strength'] },
    { id: 'volume', area: 'chart', name: '支持・抵抗と出来高', lessons: ['support-resistance', 'volume', 'volume-advanced'] },
    { id: 'pattern', area: 'chart', name: 'チャートパターン', lessons: ['continuation', 'base-quality', 'reversal', 'bearish-patterns'] },
    { id: 'indicator', area: 'chart', name: 'インジケーター', lessons: ['oscillators', 'volatility-tools'] },
    { id: 'scenario', area: 'chart', name: '先を読む・売りの合図', lessons: ['scenario-thinking', 'sell-signals', 'tops-bottoms'] },

    { id: 'stop', area: 'risk', name: '損切り', lessons: ['stop-loss', 'stop-practice'] },
    { id: 'size', area: 'risk', name: 'サイズとポートフォリオ', lessons: ['position-size', 'diversification', 'portfolio-heat', 'pyramiding'] },
    { id: 'math', area: 'risk', name: '期待値・統計・検証', lessons: ['expectancy', 'trade-math', 'edge-validation', 'drawdown', 'factors'] },
    { id: 'survive', area: 'risk', name: '退場しないために', lessons: ['blowups', 'margin', 'drawdown'] },

    { id: 'growth', area: 'strategy', name: '成長株とモメンタム', lessons: ['growth-momentum', 'high-return-setups', 'leaders', 'factors'] },
    { id: 'execution', area: 'strategy', name: '買い方と売り方', lessons: ['entries', 'selling', 'pyramiding', 'sell-signals'] },
    { id: 'event', area: 'strategy', name: '決算・イベントの売買', lessons: ['earnings-play', 'macro-events'] },
    { id: 'derivs', area: 'strategy', name: '空売り・オプション', lessons: ['shorting', 'options-pro', 'derivatives'] },
    { id: 'regime', area: 'strategy', name: '相場環境と年間の戦い方', lessons: ['market-regime', 'annual-playbook'] },
    { id: 'styles', area: 'strategy', name: 'スタイルと時間軸', lessons: ['styles', 'day-trading', 'small-cap-growth'] },

    { id: 'mechanics', area: 'base', name: '株と取引の仕組み', lessons: ['what-moves', 'orders', 'orders-advanced', 'jp-vs-us', 'index-sector', 'margin'] },
    { id: 'tax', area: 'base', name: '税金と制度', lessons: ['tax', 'tax-practice'] },
    { id: 'mind', area: 'base', name: '心理・習慣・プロセス', lessons: ['how-to-learn', 'reality', 'biases', 'journal', 'routine', 'trading-plan', 'process-review'] }
  ];

  /* 章(内部の分類)から領域への対応。ケース演習の振り分けに使う */
  K.stageArea = { start: 'base', basics: 'base', macro: 'market', fundamentals: 'company', technical: 'chart', risk: 'risk', strategy: 'strategy', mind: 'base', pro: 'strategy' };

  /* チャート演習(学習用の型): どこで隠し、その後どちらへ動いたか */
  K.drillCuts = {
    'trend-up': [66, 'up'], 'sr-flip': [70, 'up'], 'double-top': [55, 'down'], 'double-bottom': [52, 'up'],
    'head-shoulders': [64, 'down'], 'inv-head-shoulders': [64, 'up'], 'asc-triangle': [53, 'up'], 'bull-flag': [39, 'up'],
    'cup-handle': [74, 'up'], 'vcp': [73, 'up'], 'breakout-fail': [55, 'down'], 'climax': [55, 'down'],
    'pullback': [81, 'up'], 'gap-up': [56, 'up'], 'distribution': [64, 'down'], 'high-tight-flag': [54, 'up'],
    'shakeout': [54, 'up'], 'desc-triangle': [54, 'down'], 'bear-flag': [40, 'down']
  };

  /* チャート演習で選ぶ根拠(何を見て判断したか) */
  K.drillReasons = [
    ['trend', 'トレンドの向き(高値・安値の切り上げ/切り下げ)'],
    ['ma', '移動平均線の向きと、株価の位置'],
    ['level', '支持線・抵抗線・ネックラインの位置'],
    ['volume', '出来高の増減'],
    ['contraction', '値幅の収縮(締まり)'],
    ['momentum', '勢いの変化(RSI・値動きの角度)'],
    ['extended', '移動平均線からの離れすぎ(過熱)']
  ];
})();
