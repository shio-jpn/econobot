/* SCOA-A 自動生成問題(数理・論理)。各生成関数は {q, ch(先頭が正解), e, fig?} を返す。 */
window.SCOA_GEN = { 数理: [], 論理: [] };
(function () {
  const R = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
  const pick = (a) => a[R(0, a.length - 1)];
  const shuffle = (a) => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = R(0, i); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const gcd = (a, b) => (b ? gcd(b, a % b) : Math.abs(a));
  const fr = (n, d) => { if (d < 0) { n = -n; d = -d; } const g = gcd(n, d) || 1; n /= g; d /= g; return d === 1 ? String(n) : n + '/' + d; };
  const sg = (n) => (n < 0 ? '− ' + -n : '+ ' + n); // 符号つき表記
  const C2 = (n, r) => { let x = 1; for (let i = 0; i < r; i++) x = (x * (n - i)) / (i + 1); return Math.round(x); };

  /* 正解と誤答候補から5択を作る。足りなければ null(呼び出し側で作り直す) */
  function opts(ans, cands) {
    const out = [String(ans)];
    for (const c of shuffle(cands)) { const s = String(c); if (!out.includes(s) && out.length < 5) out.push(s); }
    return out.length === 5 ? out : null;
  }
  /* 数値の5択。よくある誤答 cands を優先し、残りは正解の近くの値で埋める */
  function nopts(ans, cands, o) {
    o = o || {};
    const step = o.step || 1, f = o.fmt || ((v) => String(v)), min = o.min === undefined ? 1 : o.min;
    const out = [f(ans)];
    const add = (v) => { if (v < min || !Number.isInteger(v)) return; const s = f(v); if (!out.includes(s) && out.length < 5) out.push(s); };
    shuffle(cands || []).slice(0, 3).forEach(add);
    const m = R(0, 4);
    for (let i = 0; i < 5; i++) add(ans + (i - m) * step);
    for (let k = 1; out.length < 5 && k < 30; k++) { add(ans + k * step); add(ans - k * step); }
    return out.length === 5 ? out : null;
  }
  const M = (c, f) => window.SCOA_GEN['数理'].push({ c, f });
  const L = (c, f) => window.SCOA_GEN['論理'].push({ c, f });

  /* ===================== 数理 ===================== */
  M('四則演算', () => {
    if (R(0, 1)) {
      const a = R(12, 48), b = R(3, 9), c = R(4, 12), d = R(5, 30), ans = a + b * c - d;
      return { q: `${a} + ${b} × ${c} − ${d} を計算しなさい。`, ch: nopts(ans, [(a + b) * c - d, a + b * (c - d)], { min: -999 }), e: `かけ算を先に計算する。${b} × ${c} = ${b * c}。${a} + ${b * c} − ${d} = ${ans}。` };
    }
    const a = R(3, 9), k = R(4, 12), c = R(3, 9), d = R(2, 8), ans = k + c * d;
    return { q: `${a * k} ÷ ${a} + ${c} × ${d} を計算しなさい。`, ch: nopts(ans, [(k + c) * d, k * c + d]), e: `わり算・かけ算を先に計算する。${a * k} ÷ ${a} = ${k}、${c} × ${d} = ${c * d}。${k} + ${c * d} = ${ans}。` };
  });
  M('分数・小数', () => {
    const ds = [2, 3, 4, 5, 6, 8], b = pick(ds), d = pick(ds.filter((x) => x !== b)), a = R(1, b - 1), c = R(1, d - 1);
    if (R(0, 2)) {
      const n = a * d + c * b, dn = b * d;
      return { q: `${a}/${b} + ${c}/${d} を計算しなさい。`, ch: opts(fr(n, dn), [fr(a + c, b + d), fr(n + 1, dn), fr(n - 1, dn), fr(a * c, dn), fr(n, dn * 2), fr(n + 2, dn)]), e: `通分する。${a}/${b} = ${a * d}/${dn}、${c}/${d} = ${c * b}/${dn}。和は ${n}/${dn}${fr(n, dn) !== n + '/' + dn ? ' = ' + fr(n, dn) : ''}。分母どうし・分子どうしを足すのは誤り。` };
    }
    return { q: `${a}/${b} ÷ ${c}/${d} を計算しなさい。`, ch: opts(fr(a * d, b * c), [fr(a * c, b * d), fr(b * c, a * d), fr(a * d + 1, b * c), fr(a + d, b + c), fr(a * d, b * c + 1), fr(a * d + 2, b * c)]), e: `わる数の逆数をかける。${a}/${b} × ${d}/${c} = ${a * d}/${b * c}${fr(a * d, b * c) !== a * d + '/' + b * c ? ' = ' + fr(a * d, b * c) : ''}。` };
  });
  M('四則逆算', () => {
    const x = R(3, 15), a = R(2, 9), b = R(1, 20);
    if (R(0, 1)) { const c = x * a - b; return { q: `□ × ${a} − ${b} = ${c} の□に入る数はどれか。`, ch: nopts(x, [Math.round((c - b) / a), c + b]), e: `□ × ${a} = ${c} + ${b} = ${c + b}。□ = ${c + b} ÷ ${a} = ${x}。` }; }
    const c = R(2, 9), xx = a * c - b; if (xx < 1) return null;
    return { q: `(□ + ${b}) ÷ ${a} = ${c} の□に入る数はどれか。`, ch: nopts(xx, [a * c + b, c - b]), e: `□ + ${b} = ${c} × ${a} = ${a * c}。□ = ${a * c} − ${b} = ${xx}。` };
  });
  M('一次方程式', () => {
    const x = pick([-6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]), a = R(3, 8), c = R(1, a - 1), b = R(1, 20), d = (a - c) * x - b; if (d === 0) return null;
    return { q: `方程式 ${a}x − ${b} = ${c === 1 ? '' : c}x ${sg(d)} を解きなさい。`, ch: nopts(x, [-x, (d - b) / (a - c)].filter(Number.isInteger), { min: -99, fmt: (v) => 'x = ' + v }), e: `xの項を左辺、数を右辺に移項する。${a}x − ${c === 1 ? '' : c}x = ${d} + ${b} より ${a - c}x = ${d + b}。x = ${x}。` };
  });
  M('連立方程式(つるかめ算)', () => {
    if (R(0, 1)) {
      const x = R(2, 9), y = R(2, 9), n = x + y, legs = 2 * x + 4 * y;
      return { q: `つるとかめが合わせて${n}匹いて、足の数の合計は${legs}本である。かめは何匹いるか。`, ch: nopts(y, [x, n - y + 1], { fmt: (v) => v + '匹' }), e: `全部つるだとすると足は 2 × ${n} = ${2 * n}本。実際との差 ${legs} − ${2 * n} = ${legs - 2 * n}本は、かめ1匹につき2本ずつ増える分。${legs - 2 * n} ÷ 2 = ${y}匹。` };
    }
    const a = pick([120, 150, 180]), b = pick([60, 80, 90]), x = R(2, 9), y = R(2, 9), n = x + y, t = a * x + b * y;
    return { q: `1個${a}円のりんごと1個${b}円のみかんを合わせて${n}個買ったところ、代金は${t}円だった。りんごは何個買ったか。`, ch: nopts(x, [y], { fmt: (v) => v + '個' }), e: `全部みかんだとすると ${b} × ${n} = ${b * n}円。実際との差 ${t} − ${b * n} = ${t - b * n}円。りんご1個につき ${a} − ${b} = ${a - b}円増えるので、${t - b * n} ÷ ${a - b} = ${x}個。` };
  });
  M('二次方程式', () => {
    const v = [-7, -6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6, 7]; let p = pick(v), q = pick(v); if (p === q || p === -q) return null; if (p > q) [p, q] = [q, p];
    const Bc = -(p + q), Cc = p * q, f = (m, n) => `x = ${Math.min(m, n)}, ${Math.max(m, n)}`;
    const eq = `x² ${Bc === 1 ? '+ ' : Bc === -1 ? '− ' : sg(Bc)}x ${sg(Cc)} = 0`;
    const fac = (r) => (r > 0 ? `(x − ${r})` : `(x + ${-r})`);
    return { q: `二次方程式 ${eq} を解きなさい。`, ch: opts(f(p, q), [f(-p, -q), f(p, -q), f(-p, q), f(p + 1, q), f(p, q + 1), f(p - 1, q)]), e: `左辺を因数分解すると ${fac(p)}${fac(q)} = 0。よって ${f(p, q)}。(かけて ${Cc}、足して ${p + q} になる2数を探す)` };
  });
  M('不等式', () => {
    const a = R(2, 6), k = R(2, 9), r = R(0, a - 1), b = R(1, 10), c = a * k + r - b; if (c < 1) return null;
    return { q: `不等式 ${a}x − ${b} > ${c} を満たす最小の整数 x はどれか。`, ch: nopts(k + 1, [k, k + 2]), e: `${a}x > ${c} + ${b} = ${c + b} より x > ${fr(c + b, a)}${r ? '(= ' + (Math.round(((c + b) / a) * 100) / 100) + ')' : ''}。これを満たす最小の整数は ${k + 1}。${r ? '' : '(「>」なので ' + k + ' 自身は含まない)'}` };
  });
  M('数列', () => {
    const t = R(0, 4); let a = [], e, nx;
    if (t === 0) { const s = R(1, 20), d = pick([3, 4, 6, 7, 8, 9, -3, -4]); const s0 = d < 0 ? s + 40 : s; for (let i = 0; i < 6; i++) a.push(s0 + d * i); e = `等差数列。${d > 0 ? d + 'ずつ増えている' : -d + 'ずつ減っている'}。`; }
    else if (t === 1) { const s = R(1, 5), r = pick([2, 3]); for (let i = 0; i < 6; i++) a.push(s * Math.pow(r, i)); e = `等比数列。前の数を${r}倍している。`; }
    else if (t === 2) { const s = R(1, 9), d0 = R(1, 4), dd = R(1, 3); let v = s, d = d0; for (let i = 0; i < 6; i++) { a.push(v); v += d; d += dd; } e = `階差数列。差が ${d0}, ${d0 + dd}, ${d0 + 2 * dd}, … と${dd}ずつ増えている。`; }
    else if (t === 3) { let x = R(1, 4), y = R(2, 6); for (let i = 0; i < 6; i++) { a.push(x); [x, y] = [y, x + y]; } e = '前の2つの数の和が次の数になっている(フィボナッチ型)。'; }
    else { const k = R(0, 5), s = R(1, 4); for (let i = 0; i < 6; i++) a.push((s + i) * (s + i) + k); e = `${s}², ${s + 1}², ${s + 2}², … ${k ? 'にそれぞれ' + k + 'を足した数' : 'と平方数が並んでいる'}。`; }
    nx = a[5];
    return { q: `次の数列の□に入る数はどれか。\n${a.slice(0, 5).join(', ')}, □`, ch: nopts(nx, [a[4] + (a[4] - a[3]), a[4] * 2 - a[2]], { min: -99 }), e: e + ` よって□ = ${nx}。` };
  });
  M('割合・損益', () => {
    const t = R(0, 2);
    if (t === 0) {
      const c = R(5, 30) * 100, p = pick([20, 25, 30, 40, 50]), q = pick([10, 20]), list = (c * (100 + p)) / 100, sale = (list * (100 - q)) / 100;
      if (!Number.isInteger(sale)) return null; const ans = sale - c;
      return { q: `原価${c}円の品物に${p}%の利益を見込んで定価をつけたが、売れないので定価の${q}%引きで売った。利益は何円か。`, ch: nopts(ans, [(c * (p - q)) / 100, list - c].filter(Number.isInteger), { step: c / 100 >= 10 ? 20 : 10, min: -9999, fmt: (v) => v + '円' }), e: `定価 = ${c} × ${(100 + p) / 100} = ${list}円。売値 = ${list} × ${(100 - q) / 100} = ${sale}円。利益 = ${sale} − ${c} = ${ans}円。(${p}% − ${q}% = ${p - q}% と計算するのは誤り)` };
    }
    if (t === 1) {
      const whole = R(4, 40) * 10, p = pick([5, 15, 20, 25, 35, 40, 60, 75]), part = (whole * p) / 100; if (!Number.isInteger(part)) return null;
      return { q: `${part}人は${whole}人の何%か。`, ch: nopts(p, [100 - p], { step: 5, fmt: (v) => v + '%' }), e: `割合 = 比べる量 ÷ もとにする量 = ${part} ÷ ${whole} = ${p / 100}。よって ${p}%。` };
    }
    const price = R(8, 60) * 100, p = pick([15, 20, 25, 30, 35]), ans = (price * (100 - p)) / 100;
    return { q: `定価${price}円の商品を${p}%引きで買うと、代金は何円か。`, ch: nopts(ans, [(price * p) / 100, price - p], { step: price / 100 >= 20 ? 100 : 50, fmt: (v) => v + '円' }), e: `${p}%引き = 定価の${100 - p}%。${price} × ${(100 - p) / 100} = ${ans}円。` };
  });
  M('速さ', () => {
    const t = R(0, 3);
    if (t === 0) { const a = R(3, 6), b = R(3, 6), h = R(2, 5), d = (a + b) * h; return { q: `${d}km離れた2地点から、Aは時速${a}km、Bは時速${b}kmで同時に向かい合って出発した。2人が出会うのは何時間後か。`, ch: nopts(h, [], { fmt: (v) => v + '時間後' }), e: `向かい合って進むと、1時間に ${a} + ${b} = ${a + b}km ずつ近づく。${d} ÷ ${a + b} = ${h}時間後。` }; }
    if (t === 1) { const a = pick([60, 70, 80]), diff = pick([20, 30, 40, 60]), b = a + diff, m = R(2, 12), ans = (a * m) / diff; if (!Number.isInteger(ans)) return null; return { q: `兄が分速${a}mで家を出発した${m}分後に、弟が分速${b}mで同じ道を追いかけた。弟が兄に追いつくのは、弟が出発してから何分後か。`, ch: nopts(ans, [m], { fmt: (v) => v + '分後' }), e: `弟が出発するとき、兄は ${a} × ${m} = ${a * m}m 先にいる。1分に ${b} − ${a} = ${diff}m ずつ縮まるので、${a * m} ÷ ${diff} = ${ans}分後。` }; }
    if (t === 2) { const [a, b, ans] = pick([[40, 60, 48], [30, 60, 40], [20, 30, 24], [60, 90, 72], [4, 12, 6], [10, 15, 12], [3, 6, 4], [12, 24, 16]]); return { q: `ある道のりを、行きは時速${a}km、帰りは時速${b}kmで往復した。往復の平均の速さは時速何kmか。`, ch: nopts(ans, [(a + b) / 2], { fmt: (v) => '時速' + v + 'km' }), e: `平均の速さ = 往復の道のり ÷ 往復の時間。片道を${a * b / gcd(a, b)}kmとすると、時間は ${b / gcd(a, b)} + ${a / gcd(a, b)} = ${(a + b) / gcd(a, b)}時間。${2 * a * b / gcd(a, b)} ÷ ${(a + b) / gcd(a, b)} = ${ans}。単純に (${a} + ${b}) ÷ 2 = ${(a + b) / 2} とするのは誤り。` }; }
    const v = pick([36, 42, 48, 54, 60, 72]), m = pick([10, 20, 25, 40, 45, 50]), ans = (v * m) / 60; if (!Number.isInteger(ans)) return null;
    return { q: `時速${v}kmで走る自動車が${m}分間に進む道のりは何kmか。`, ch: nopts(ans, [], { fmt: (v2) => v2 + 'km' }), e: `${m}分 = ${fr(m, 60)}時間。道のり = 速さ × 時間 = ${v} × ${fr(m, 60)} = ${ans}km。` };
  });
  M('濃度', () => {
    if (R(0, 1)) {
      const a = R(2, 8), b = R(10, 20), x = R(1, 5) * 100, y = R(1, 5) * 100, salt = (a * x + b * y) / 100, ans = (salt / (x + y)) * 100; if (!Number.isInteger(ans)) return null;
      return { q: `${a}%の食塩水${x}gと${b}%の食塩水${y}gを混ぜると、何%の食塩水になるか。`, ch: nopts(ans, [(a + b) / 2].filter(Number.isInteger), { fmt: (v) => v + '%' }), e: `食塩の量は ${x} × ${a / 100} + ${y} × ${b / 100} = ${(a * x) / 100} + ${(b * y) / 100} = ${salt}g。全体は ${x + y}g。${salt} ÷ ${x + y} × 100 = ${ans}%。` };
    }
    const a = pick([10, 12, 15, 20]), x = R(1, 4) * 100, w = R(1, 6) * 50, salt = (a * x) / 100, ans = (salt / (x + w)) * 100; if (!Number.isInteger(ans)) return null;
    return { q: `${a}%の食塩水${x}gに水を${w}g加えると、何%の食塩水になるか。`, ch: nopts(ans, [], { fmt: (v) => v + '%' }), e: `食塩の量は ${x} × ${a / 100} = ${salt}g で変わらない。全体は ${x} + ${w} = ${x + w}g。${salt} ÷ ${x + w} × 100 = ${ans}%。` };
  });
  M('仕事算', () => {
    const [a, b, ans] = pick([[6, 3, 2], [10, 15, 6], [12, 6, 4], [20, 30, 12], [12, 4, 3], [24, 8, 6], [18, 9, 6], [20, 5, 4], [30, 6, 5], [40, 10, 8], [15, 30, 10], [12, 24, 8]]);
    return { q: `ある仕事を仕上げるのに、Aさん1人では${a}日、Bさん1人では${b}日かかる。2人で一緒にすると何日で仕上がるか。`, ch: nopts(ans, [(a + b) / 2, Math.abs(a - b)].filter(Number.isInteger), { fmt: (v) => v + '日' }), e: `全体の仕事量を1とすると、1日にAは 1/${a}、Bは 1/${b} できる。2人では 1/${a} + 1/${b} = ${fr(a + b, a * b)}。よって 1 ÷ ${fr(a + b, a * b)} = ${ans}日。` };
  });
  M('確率', () => {
    const t = R(0, 2);
    if (t === 0) { const k = R(3, 11), w = k <= 7 ? k - 1 : 13 - k; return { q: `大小2つのさいころを同時に投げるとき、出た目の和が${k}になる確率はどれか。`, ch: opts(fr(w, 36), [fr(w + 1, 36), fr(w - 1, 36), fr(1, 6), fr(w, 12), fr(1, 12), fr(w + 2, 36), fr(1, 36)].filter((s) => s !== '0')), e: `目の出方は全部で 6 × 6 = 36通り。和が${k}になるのは${w}通り。確率は ${w}/36${fr(w, 36) !== w + '/36' ? ' = ' + fr(w, 36) : ''}。` }; }
    if (t === 1) { const r = R(2, 5), w = R(2, 5), n = r + w, num = C2(r, 2), den = C2(n, 2); return { q: `赤玉${r}個と白玉${w}個が入った袋から、同時に2個の玉を取り出すとき、2個とも赤玉である確率はどれか。`, ch: opts(fr(num, den), [fr(r, n), fr(r * r, n * n), fr(num + 1, den), fr(C2(w, 2), den), fr(r * w, den), fr(1, n), fr(num, den + 1)]), e: `2個の取り出し方は全部で ${n}C2 = ${den}通り。2個とも赤玉は ${r}C2 = ${num}通り。確率は ${num}/${den}${fr(num, den) !== num + '/' + den ? ' = ' + fr(num, den) : ''}。` }; }
    const v = pick([['ちょうど2枚が表になる', 3, '表が2枚となるのは(表表裏)(表裏表)(裏表表)の3通り'], ['少なくとも1枚が表になる', 7, '全部裏になる1通りを除く 8 − 1 = 7通り'], ['3枚とも同じ面になる', 2, '(表表表)(裏裏裏)の2通り'], ['ちょうど1枚が表になる', 3, '表が1枚となるのは3通り']]);
    return { q: `3枚の硬貨を同時に投げるとき、${v[0]}確率はどれか。`, ch: opts(fr(v[1], 8), ['1/2', '1/8', '3/8', '7/8', '1/4', '5/8', '3/4', '1/3'].filter((s) => s !== fr(v[1], 8))), e: `表裏の出方は全部で 2 × 2 × 2 = 8通り。${v[2]}。確率は ${fr(v[1], 8)}。` };
  });
  M('場合の数', () => {
    const t = R(0, 2), n = R(5, 9);
    if (t === 0) { const r = R(2, 3), ans = C2(n, r); return { q: `${n}人の中から${r}人の委員を選ぶ方法は何通りあるか。`, ch: nopts(ans, [r === 2 ? n * (n - 1) : n * (n - 1) * (n - 2), n * r], { fmt: (v) => v + '通り' }), e: `選ぶ順番は関係ないので組合せ。${n}C${r} = ${r === 2 ? `${n} × ${n - 1} ÷ 2` : `${n} × ${n - 1} × ${n - 2} ÷ 6`} = ${ans}通り。` }; }
    if (t === 1) { const ans = n * (n - 1); return { q: `${n}人の中から委員長と副委員長を1人ずつ選ぶ方法は何通りあるか。`, ch: nopts(ans, [ans / 2, n * n, n * 2], { fmt: (v) => v + '通り' }), e: `役職が異なるので順列。委員長の選び方が${n}通り、副委員長は残りの${n - 1}通り。${n} × ${n - 1} = ${ans}通り。` }; }
    const m = R(3, 5), f = [0, 1, 2, 6, 24, 120][m];
    return { q: `${m}人が横一列に並ぶ並び方は何通りあるか。`, ch: nopts(f, [m * m, m * (m - 1), f / 2, f * 2], { fmt: (v) => v + '通り' }), e: `${m}! = ${Array.from({ length: m }, (_, i) => m - i).join(' × ')} = ${f}通り。` };
  });
  M('図形', () => {
    const t = R(0, 5);
    if (t === 0) { const [a, b, c] = pick([[3, 4, 5], [5, 12, 13], [6, 8, 10], [8, 15, 17], [9, 12, 15], [12, 16, 20]]); return { q: `直角をはさむ2辺の長さが${a}cmと${b}cmの直角三角形の斜辺の長さは何cmか。`, ch: nopts(c, [a + b, b + 1], { fmt: (v) => v + 'cm' }), e: `三平方の定理より 斜辺² = ${a}² + ${b}² = ${a * a} + ${b * b} = ${c * c}。斜辺 = ${c}cm。` }; }
    if (t === 1) { const n = R(5, 12), ans = 180 * (n - 2); return { q: `${n}角形の内角の和は何度か。`, ch: nopts(ans, [180 * n, 360], { step: 180, fmt: (v) => v + '度' }), e: `n角形の内角の和 = 180 × (n − 2)。180 × ${n - 2} = ${ans}度。` }; }
    if (t === 2) { const r = R(2, 9); return { q: `半径${r}cmの円の面積はどれか。円周率はπとする。`, ch: opts(r * r + 'π cm²', [2 * r + 'π cm²', r + 'π cm²', 2 * r * r + 'π cm²', 4 * r * r + 'π cm²', r * r + 1 + 'π cm²', r * r * 3 + 'π cm²']), e: `円の面積 = 半径 × 半径 × π = ${r} × ${r} × π = ${r * r}π cm²。(${2 * r}π は円周の長さ)` }; }
    if (t === 3) { const n = pick([5, 6, 8, 9, 10, 12]), ans = 360 / n; return { q: `正${n}角形の1つの外角の大きさは何度か。`, ch: nopts(ans, [180 - ans, 180 / n].filter(Number.isInteger), { step: n > 8 ? 6 : 12, fmt: (v) => v + '度' }), e: `多角形の外角の和は常に360度。正${n}角形では 360 ÷ ${n} = ${ans}度。(1つの内角は ${180 - ans}度)` }; }
    if (t === 4) { const a = R(2, 9), ans = 6 * a * a; return { q: `1辺の長さが${a}cmの立方体の表面積は何cm²か。`, ch: nopts(ans, [a * a * a, 4 * a * a, a * a], { step: a, fmt: (v) => v + 'cm²' }), e: `1つの面は ${a} × ${a} = ${a * a}cm²。面は6つあるので ${a * a} × 6 = ${ans}cm²。` }; }
    const b = R(4, 16), h = R(3, 12); if ((b * h) % 2) return null; const ans = (b * h) / 2;
    return { q: `底辺が${b}cm、高さが${h}cmの三角形の面積は何cm²か。`, ch: nopts(ans, [b * h, b + h], { fmt: (v) => v + 'cm²' }), e: `三角形の面積 = 底辺 × 高さ ÷ 2 = ${b} × ${h} ÷ 2 = ${ans}cm²。` };
  });
  M('数の大小', () => {
    const pool = []; [3, 4, 5, 6, 7, 8, 9].forEach((d) => { for (let n = 1; n < d; n++) if (gcd(n, d) === 1) pool.push({ s: n + '/' + d, v: n / d }); });
    for (let i = 31; i <= 89; i += R(2, 4)) pool.push({ s: (i / 100).toFixed(2), v: i / 100 });
    const cand = shuffle(pool.filter((x) => x.v > 0.3 && x.v < 0.9)), sel = [];
    for (const x of cand) { if (sel.every((y) => Math.abs(y.v - x.v) > 0.012) && sel.length < 5) sel.push(x); }
    if (sel.length < 5) return null;
    const big = R(0, 1); sel.sort((a, b) => (big ? b.v - a.v : a.v - b.v));
    return { q: `次の数のうち、最も${big ? '大きい' : '小さい'}ものはどれか。`, ch: sel.map((x) => x.s), e: `小数に直して比べる。${sel.map((x) => (x.s.includes('/') ? `${x.s} ≒ ${x.v.toFixed(3)}` : x.s)).join('、')}。最も${big ? '大きい' : '小さい'}のは ${sel[0].s}。` };
  });
  M('n進法', () => {
    if (R(0, 1)) { const n = R(9, 45), bs = n.toString(2); return { q: `2進法で表された数 ${bs} を10進法で表すといくつか。`, ch: nopts(n, []), e: `各桁は右から 1, 2, 4, 8, 16, 32 の位。${bs.split('').map((c, i) => (c === '1' ? Math.pow(2, bs.length - 1 - i) : null)).filter((x) => x).join(' + ')} = ${n}。` }; }
    const n = R(9, 31), f = (v) => v.toString(2);
    return { q: `10進法の ${n} を2進法で表すとどれか。`, ch: nopts(n, [], { fmt: f }), e: `2で割り続けて余りを下から並べる。または ${n} = ${f(n).split('').map((c, i) => (c === '1' ? Math.pow(2, f(n).length - 1 - i) : null)).filter((x) => x).join(' + ')} なので ${f(n)}。` };
  });
  M('約数・倍数', () => {
    const g = pick([2, 3, 4, 5, 6, 8, 9, 12]), pr = pick([[2, 3], [3, 4], [2, 5], [3, 5], [4, 5], [2, 7], [3, 7], [1, 4], [5, 6]]), a = g * pr[0], b = g * pr[1], l = g * pr[0] * pr[1];
    if (R(0, 1)) return { q: `${a} と ${b} の最大公約数はいくつか。`, ch: nopts(g, [l, pr[0], pr[1]].filter((v) => v > 1)), e: `${a} = ${g} × ${pr[0]}、${b} = ${g} × ${pr[1]}。共通する約数のうち最大のものは ${g}。` };
    return { q: `${a} と ${b} の最小公倍数はいくつか。`, ch: nopts(l, [a * b, g, l * 2].filter((v) => v !== l), { step: g }), e: `${a} = ${g} × ${pr[0]}、${b} = ${g} × ${pr[1]}。最小公倍数 = ${g} × ${pr[0]} × ${pr[1]} = ${l}。` };
  });
  M('年齢算', () => {
    const t = R(2, 12), c2 = R(8, 16), k = pick([2, 3]), c = c2 - t, f = k * c2 - t; if (c < 1 || f - c < 18 || f > 60) return null;
    return { q: `現在、父は${f}歳、子は${c}歳である。父の年齢が子の年齢の${k}倍になるのは何年後か。`, ch: nopts(t, [], { fmt: (v) => v + '年後' }), e: `x年後とすると ${f} + x = ${k}(${c} + x)。${f} + x = ${k * c} + ${k}x より ${k - 1 === 1 ? '' : k - 1}x = ${f - k * c}。x = ${t}。(${t}年後:父${f + t}歳、子${c + t}歳)` };
  });
  M('平均', () => {
    const n = R(4, 9), a = R(60, 75), b = a + pick([-2, -1, 1, 2]), ans = b * (n + 1) - a * n; if (ans < 0 || ans > 100) return null;
    return { q: `${n}人のテストの平均点は${a}点だった。ここに1人が加わったところ、${n + 1}人の平均点は${b}点になった。加わった1人の点数は何点か。`, ch: nopts(ans, [b, a + (b - a) * n], { fmt: (v) => v + '点' }), e: `合計点で考える。${n}人の合計は ${a} × ${n} = ${a * n}点、${n + 1}人の合計は ${b} × ${n + 1} = ${b * (n + 1)}点。差の ${b * (n + 1)} − ${a * n} = ${ans}点が加わった人の点数。` };
  });
  M('比', () => {
    const [a, b] = pick([[2, 3], [3, 4], [3, 5], [2, 5], [4, 5], [1, 3], [5, 7], [3, 7]]), u = R(2, 12) * 10, sum = (a + b) * u;
    return { q: `${sum}円を兄と弟で ${b}:${a} の比に分けると、弟の取り分は何円か。`, ch: nopts(a * u, [b * u, sum / 2, sum / b].filter(Number.isInteger), { step: u, fmt: (v) => v + '円' }), e: `全体を ${b} + ${a} = ${a + b} 等分すると、1つ分は ${sum} ÷ ${a + b} = ${u}円。弟は ${a}つ分なので ${u} × ${a} = ${a * u}円。` };
  });
  M('時計算', () => {
    const h = R(1, 11), m = pick([0, 10, 20, 30, 40, 50]); let d = Math.abs(30 * h - 5.5 * m); if (d > 180) d = 360 - d; if (d === 0) return null;
    return { q: `時計が${h}時${m ? m + '分' : 'ちょうど'}を指しているとき、長針と短針のつくる角のうち小さいほうは何度か。`, ch: nopts(d, [Math.abs(30 * h - 6 * m) > 180 ? 360 - Math.abs(30 * h - 6 * m) : Math.abs(30 * h - 6 * m)].filter((v) => v > 0), { step: 5, fmt: (v) => v + '度' }), e: `短針は1時間に30度(1分に0.5度)、長針は1分に6度進む。12時の位置から、短針は 30 × ${h} + 0.5 × ${m} = ${30 * h + 0.5 * m}度、長針は 6 × ${m} = ${6 * m}度。差は ${Math.abs(30 * h - 5.5 * m)}度${Math.abs(30 * h - 5.5 * m) > 180 ? ' → 小さいほうは 360 − ' + Math.abs(30 * h - 5.5 * m) + ' = ' + d + '度' : ''}。` };
  });
  M('平方根', () => {
    const list = [[8, '2√2'], [12, '2√3'], [18, '3√2'], [20, '2√5'], [27, '3√3'], [32, '4√2'], [45, '3√5'], [48, '4√3'], [50, '5√2'], [72, '6√2'], [75, '5√3']];
    if (R(0, 1)) { const x = pick(list), k = parseInt(x[1]), r = x[0] / (k * k); return { q: `√${x[0]} を a√b の形(bはできるだけ小さい自然数)で表すとどれか。`, ch: opts(x[1], list.filter((y) => y[1] !== x[1]).map((y) => y[1])), e: `${x[0]} = ${k * k} × ${r} = ${k}² × ${r} なので、√${x[0]} = ${k}√${r}。` }; }
    const [a, b, ans] = pick([[2, 8, 4], [3, 12, 6], [2, 18, 6], [3, 27, 9], [5, 20, 10], [2, 32, 8], [6, 24, 12], [2, 50, 10]]);
    return { q: `√${a} × √${b} を計算しなさい。`, ch: nopts(ans, [a * b, a + b]), e: `√${a} × √${b} = √${a * b} = ${ans}。(${ans}² = ${a * b})` };
  });
  M('式の計算', () => {
    const a = pick([-6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 7]), b = pick([-5, -4, -3, -2, 2, 3, 4, 5, 6]); if (a + b === 0) return null;
    const f = (B, Cc) => `x² ${B === 0 ? '' : (Math.abs(B) === 1 ? (B > 0 ? '+ ' : '− ') : sg(B)) + 'x '}${sg(Cc)}`.replace(/\s+/g, ' ');
    const p = (r) => (r > 0 ? `(x + ${r})` : `(x − ${-r})`);
    return { q: `${p(a)}${p(b)} を展開しなさい。`, ch: opts(f(a + b, a * b), [f(a + b, -a * b), f(a * b, a + b), f(a - b, a * b), f(-(a + b), a * b), f(a + b, a + b), f(a + b + 1, a * b)]), e: `(x + a)(x + b) = x² + (a + b)x + ab。xの係数は ${a < 0 ? '(' + a + ')' : a} + ${b < 0 ? '(' + b + ')' : b} = ${a + b}、定数項は ${a < 0 ? '(' + a + ')' : a} × ${b < 0 ? '(' + b + ')' : b} = ${a * b}。よって ${f(a + b, a * b)}。` };
  });

  /* ===================== 論理 ===================== */
  const PROPS = [['犬が好きな人', '犬が好きでない人'], ['早起きする人', '早起きしない人'], ['健康な人', '健康でない人'], ['読書が好きな人', '読書が好きでない人'], ['数学が得意な人', '数学が得意でない人'], ['英語が得意な人', '英語が得意でない人'], ['運動が好きな人', '運動が好きでない人'], ['料理が得意な人', '料理が得意でない人'], ['音楽が好きな人', '音楽が好きでない人'], ['旅行が好きな人', '旅行が好きでない人'], ['几帳面な人', '几帳面でない人'], ['コーヒーを飲む人', 'コーヒーを飲まない人']];
  const pred = (s) => s.replace(/な人$/, 'である').replace(/人$/, '');
  const st = (p, q) => `${p}は、${pred(q)}`;
  L('命題・対偶', () => {
    const [P, Q] = shuffle(PROPS);
    return { q: `「${st(P[0], Q[0])}」が正しいとき、確実にいえるものはどれか。`, ch: opts(st(Q[1], P[1]), [st(Q[0], P[0]), st(P[1], Q[1]), st(P[0], Q[1]), st(P[1], Q[0])]), e: `ある命題が正しいとき、必ず正しいといえるのは「対偶」だけ。「AならばB」の対偶は「BでないならばAでない」。逆「BならばA」や裏「AでないならばBでない」は正しいとは限らない。` };
  });
  L('三段論法', () => {
    const [P, Q, Rr] = shuffle(PROPS);
    return { q: `次の2つが正しいとき、確実にいえるものはどれか。\n・${st(P[0], Q[0])}\n・${st(Q[0], Rr[0])}`, ch: opts(st(Rr[1], P[1]), [st(Rr[0], P[0]), st(P[1], Rr[1]), st(Q[0], P[0]), st(Rr[0], Q[0]), st(P[1], Q[1])]), e: `2つをつなぐと「${st(P[0], Rr[0])}」(三段論法)。その対偶「${st(Rr[1], P[1])}」も確実に正しい。逆や裏は正しいとは限らない。` };
  });
  L('集合', () => {
    const both = R(3, 12), a = both + R(4, 15), b = both + R(4, 15), none = R(2, 10), n = a + b - both + none;
    const [X, Y] = pick([['犬', '猫'], ['英語', '数学'], ['野球', 'サッカー'], ['電車', 'バス'], ['新聞', '雑誌']]);
    const verb = { 犬: 'を飼っている', 英語: 'が得意な', 野球: 'が好きな', 電車: 'を利用する', 新聞: 'を読んでいる' }[X];
    if (R(0, 1)) return { q: `${n}人に調査したところ、${X}${verb}人は${a}人、${Y}${verb}人は${b}人、両方にあてはまる人は${both}人だった。どちらにもあてはまらない人は何人か。`, ch: nopts(none, [n - a - b + 2 * both, both].filter((v) => v > 0), { fmt: (v) => v + '人', min: 0 }), e: `少なくとも一方にあてはまる人は ${a} + ${b} − ${both} = ${a + b - both}人(両方の人を二重に数えないよう引く)。どちらでもない人は ${n} − ${a + b - both} = ${none}人。` };
    const only = a + b - 2 * both;
    return { q: `${n}人に調査したところ、${X}${verb}人は${a}人、${Y}${verb}人は${b}人、どちらにもあてはまらない人は${none}人だった。両方にあてはまる人は何人か。`, ch: nopts(both, [only, a + b - n].filter((v) => v > 0), { fmt: (v) => v + '人' }), e: `少なくとも一方にあてはまる人は ${n} − ${none} = ${n - none}人。${a} + ${b} = ${a + b} は両方の人を2回数えているので、両方の人は ${a + b} − ${n - none} = ${both}人。` };
  });
  L('サイコロ', () => {
    let d = { top: 1, bottom: 6, front: 2, back: 5, right: 3, left: 4 };
    const roll = { 右: (x) => ({ top: x.left, right: x.top, bottom: x.right, left: x.bottom, front: x.front, back: x.back }), 左: (x) => ({ top: x.right, left: x.top, bottom: x.left, right: x.bottom, front: x.front, back: x.back }), 奥: (x) => ({ top: x.front, back: x.top, bottom: x.back, front: x.bottom, left: x.left, right: x.right }), 手前: (x) => ({ top: x.back, front: x.top, bottom: x.front, back: x.bottom, left: x.left, right: x.right }) };
    const opp = { 右: '左', 左: '右', 奥: '手前', 手前: '奥' }, n = R(2, 3), moves = [], log = [];
    for (let i = 0; i < n; i++) { const m = pick(Object.keys(roll).filter((k) => !moves.length || k !== opp[moves[moves.length - 1]])); moves.push(m); d = roll[m](d); log.push(`${m}へ転がす→上面${d.top}`); }
    const face = pick([['上面', 'top'], ['上面', 'top'], ['底面', 'bottom'], ['手前の面', 'front']]);
    return { q: `向かい合う面の目の和が7のサイコロが、上面1・手前の面2・右の面3の向きで置いてある。これを${moves.map((m) => m + 'へ1回').join('、')}、すべらないように転がしたとき、${face[0]}の目はどれか。`, ch: shuffle([1, 2, 3, 4, 5, 6].filter((v) => v !== d[face[1]])).slice(0, 4).reduce((a, v) => a.concat(String(v)), [String(d[face[1]])]), e: `最初は 上1・底6・手前2・奥5・右3・左4。右へ転がすと左の面が上に、左へ転がすと右の面が上に、奥へ転がすと手前の面が上に、手前へ転がすと奥の面が上にくる。${log.join('、')}。最後は 上${d.top}・底${d.bottom}・手前${d.front}・奥${d.back}・右${d.right}・左${d.left}。` };
  });
  L('暗号', () => {
    const words = ['CAT', 'DOG', 'SUN', 'PEN', 'BOX', 'MAP', 'CUP', 'HAT', 'BED', 'KEY', 'SEA', 'SKY', 'BOOK', 'DESK', 'FISH', 'MOON'];
    const sh = (w, k) => w.split('').map((ch) => String.fromCharCode(((ch.charCodeAt(0) - 65 + k + 26) % 26) + 65)).join('');
    const k = pick([1, 2, 3, -1, -2]), [w1, w2] = shuffle(words);
    return { q: `ある暗号で「${w1}」を「${sh(w1, k)}」と表す。同じ規則で「${w2}」はどう表されるか。`, ch: opts(sh(w2, k), [-3, -2, -1, 1, 2, 3, 4].filter((x) => x !== k).map((x) => sh(w2, x)).concat([w2.split('').reverse().join('')])), e: `各文字をアルファベット順で${Math.abs(k)}文字${k > 0 ? '後ろ' : '前'}にずらしている(${w1[0]}→${sh(w1, k)[0]})。${w2} → ${sh(w2, k)}。` };
  });
  L('曜日', () => {
    const W = ['日', '月', '火', '水', '木', '金', '土'], w = R(0, 6);
    if (R(0, 1)) { const n = R(20, 200), ans = W[(w + n) % 7]; return { q: `今日は${W[w]}曜日である。${n}日後は何曜日か。`, ch: opts(ans + '曜日', W.filter((x) => x !== ans).map((x) => x + '曜日')), e: `曜日は7日ごとに同じになる。${n} ÷ 7 = ${Math.floor(n / 7)} 余り ${n % 7}。${W[w]}曜日の${n % 7}日後は${ans}曜日。` }; }
    const d1 = R(1, 9), d2 = R(15, 30), ans = W[(w + d2 - d1) % 7];
    return { q: `ある月の${d1}日が${W[w]}曜日のとき、同じ月の${d2}日は何曜日か。`, ch: opts(ans + '曜日', W.filter((x) => x !== ans).map((x) => x + '曜日')), e: `${d2} − ${d1} = ${d2 - d1}日後。${d2 - d1} ÷ 7 = ${Math.floor((d2 - d1) / 7)} 余り ${(d2 - d1) % 7}。${W[w]}曜日の${(d2 - d1) % 7}日後は${ans}曜日。` };
  });
  L('魔方陣', () => {
    let g = [[2, 7, 6], [9, 5, 1], [4, 3, 8]];
    const rot = (m) => m[0].map((_, i) => m.map((r) => r[i]).reverse());
    for (let i = R(0, 3); i > 0; i--) g = rot(g);
    if (R(0, 1)) g = g.map((r) => r.slice().reverse());
    const k = R(0, 6); g = g.map((r) => r.map((v) => v + k));
    const j = R(0, 2), Ssum = g[0][0] + g[0][1] + g[0][2], ans = g[2][j], top = g[0][2 - j], ctr = g[1][1];
    const cell = (r, c) => (r === 0 || (r === 1 && c === 1) ? String(g[r][c]).padStart(2, ' ') : r === 2 && c === j ? ' X' : '__');
    const fig = [0, 1, 2].map((r) => [0, 1, 2].map((c) => cell(r, c)).join(' │ ')).join('\n');
    return { q: `図は、縦・横・斜めのどの列も3つの数の和が等しくなる魔方陣である(__ は空欄)。X に入る数はどれか。`, fig, ch: nopts(ans, [g[2][2 - j], ctr], { min: 0 }), e: `1行目の和は ${g[0].join(' + ')} = ${Ssum}。X は${j === 1 ? '中央の縦の列' : '斜めの列'}(${top}・${ctr}・X)にあり、この和も${Ssum}なので、X = ${Ssum} − ${top} − ${ctr} = ${ans}。` };
  });
})();
