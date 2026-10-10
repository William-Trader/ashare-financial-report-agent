'use strict';
/**
 * astock.js — A股数据源
 *
 * 主源：东方财富（push2 / push2his / datacenter-web / searchapi）
 * 备源：腾讯 qt.gtimg.cn（GBK，用 iconv 转码）
 *
 * 约定：
 *  - 代码口径：6 位数字。内部 secid：沪（6/688 开头）→ "1.<code>"，深（0/3 开头）→ "0.<code>"
 *  - 东财价格类字段单位是「分」，必须 ÷100（f43=125380 → 1253.80）
 *  - 每个网络请求都有超时（默认 8s，ASTOCK_TIMEOUT_MS 可覆盖）
 *  - 任何失败都返回 {ok:false, error:"中文原因"}，绝不抛异常给路由
 */

const https = require('node:https');
const { execFileSync } = require('node:child_process');

const DEFAULT_TIMEOUT = Number(process.env.ASTOCK_TIMEOUT_MS || 8000);
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

const EM = 'https://push2.eastmoney.com';
const EM_HIS = 'https://push2his.eastmoney.com';
const EM_82 = 'https://82.push2.eastmoney.com';
const EM_TEST = 'https://push2test.eastmoney.com'; // 东财同族镜像，2026-09-22 实测可用
const EM_DC = 'https://datacenter-web.eastmoney.com';
const EM_SEARCH = 'https://searchapi.eastmoney.com';
const TX = 'https://qt.gtimg.cn';
const TX_KLINE = 'https://web.ifzq.gtimg.cn';

/* 2026-09-22 全源实测（含数据交叉校验）结论：
   ① 东财 push2 / push2his / 82.push2 / push2delay 全为 000（不可用）
   ② 东财 push2test 虽然可达，但**历史 K 线是污染数据**（600519 出现 350/370/405 这种价格，
      还凭空多一根周六「涨停」K 线），**只有最新两根与腾讯/新浪一致** ⇒ 不可当主源
   ③ 腾讯 与 新浪 在 09-11→09-22 逐日逐字段一致、无幻影行 ⇒ 以腾讯为主源
   ⇒ 行情/K线：腾讯优先 → 东财降为末位；push2test 不再用于 K 线。 */
const EM_QUOTE_HOSTS = [EM, EM_TEST]; // 实时行情：push2test 的实时字段实测正确，仅作末位兜底
const EM_KLINE_HOSTS = [EM_HIS, EM]; // K 线：**不含 push2test**（历史被污染）

const SEARCH_TOKEN = 'D43BF722C8E33BDC906FB84D85E326E8';

/* ------------------------------------------------------------------ */
/* HTTP 基础                                                           */
/* ------------------------------------------------------------------ */

/** 返回原始 Buffer（不做编码假设），失败抛带中文 code 的 Error */
function request(url, { timeout = DEFAULT_TIMEOUT, headers = null } = {}) {
  return new Promise((resolve, reject) => {
    let done = false;
    const finish = (fn, arg) => {
      if (done) return;
      done = true;
      fn(arg);
    };
    let req;
    try {
      req = https.get(
        url,
        {
          timeout,
          headers: Object.assign(
            {
              'User-Agent': UA,
              Accept: '*/*',
              'Accept-Language': 'zh-CN,zh;q=0.9',
              Referer: 'https://quote.eastmoney.com/',
            },
            headers || {}
          ),
        },
        (res) => {
          const chunks = [];
          res.on('data', (c) => chunks.push(c));
          res.on('end', () => {
            const buf = Buffer.concat(chunks);
            if (res.statusCode !== 200) {
              finish(reject, Object.assign(new Error(`HTTP_${res.statusCode}`), { kind: 'http', status: res.statusCode }));
              return;
            }
            finish(resolve, buf);
          });
          res.on('error', (e) => finish(reject, e));
        }
      );
    } catch (e) {
      finish(reject, e);
      return;
    }
    req.on('timeout', () => {
      req.destroy();
      finish(reject, Object.assign(new Error('TIMEOUT'), { kind: 'timeout' }));
    });
    req.on('error', (e) => finish(reject, e));
  });
}

function zhError(e, label) {
  if (!e) return `${label}失败`;
  if (e.kind === 'timeout' || e.message === 'TIMEOUT') return `${label}超时（${DEFAULT_TIMEOUT / 1000}s 未响应）`;
  if (e.kind === 'http' || /^HTTP_/.test(e.message)) {
    const code = e.status || String(e.message).replace('HTTP_', '');
    return `${label}返回 HTTP ${code}`;
  }
  if (e.code === 'ENOTFOUND' || e.code === 'EAI_AGAIN') return `${label}域名解析失败（本机 DNS 或网络不通）`;
  if (e.code === 'ECONNREFUSED') return `${label}连接被拒绝`;
  if (e.code === 'ECONNRESET') return `${label}连接被重置`;
  return `${label}失败：${e.message || '未知错误'}`;
}

async function getJSON(url, { timeout, label = '数据源', headers } = {}) {
  const buf = await request(url, { timeout, headers });
  const text = buf.toString('utf8');
  try {
    return JSON.parse(text);
  } catch {
    throw Object.assign(new Error('BAD_JSON'), { kind: 'parse', zh: `${label}返回了非 JSON 内容（可能被拦截）` });
  }
}

/** 腾讯接口是 GBK：优先 iconv 转码，缺 iconv 就如实报错，不瞎解码 */
function gbkToUtf8(buf) {
  try {
    const out = execFileSync('iconv', ['-f', 'GBK', '-t', 'UTF-8'], {
      input: buf,
      maxBuffer: 8 * 1024 * 1024,
      timeout: 5000,
    });
    return out.toString('utf8');
  } catch (e) {
    if (e.code === 'ENOENT') {
      throw Object.assign(new Error('NO_ICONV'), {
        zh: '腾讯备源需要 iconv 解码 GBK，但本机没有 iconv（apt install glibc-bin / yum install glibc-common）',
      });
    }
    throw Object.assign(new Error('GBK_DECODE'), { zh: '腾讯备源 GBK 解码失败（iconv 报错）' });
  }
}

/* ------------------------------------------------------------------ */
/* 字段工具                                                            */
/* ------------------------------------------------------------------ */

/** 东财缺数据时给 "-" / "" / null，统一转成 null */
function num(v) {
  if (v === null || v === undefined || v === '' || v === '-' || v === '--') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** 东财「分」→ 元 */
function fen(v) {
  const n = num(v);
  return n === null ? null : round(n / 100, 4);
}

/** 东财比率字段（本身是百分数×100）→ 百分数 */
function pct100(v) {
  const n = num(v);
  return n === null ? null : round(n / 100, 4);
}

function round(n, d = 2) {
  if (n === null || n === undefined || !Number.isFinite(n)) return null;
  const p = 10 ** d;
  return Math.round(n * p) / p;
}

function normCode(input) {
  const s = String(input == null ? '' : input).trim();
  const m = s.match(/(\d{6})/);
  return m ? m[1] : null;
}

/** 沪（6/688）→ 1.；深（0/3）→ 0. */
function secid(code) {
  const c = normCode(code);
  if (!c) return null;
  const prefix = c[0] === '6' ? '1' : '0';
  return `${prefix}.${c}`;
}

/** 腾讯前缀：沪 6→sh，深 0/3→sz */
function txPrefix(code) {
  const c = normCode(code);
  if (!c) return null;
  return c[0] === '6' ? 'sh' : 'sz';
}

function marketOf(code) {
  const c = normCode(code) || '';
  return c[0] === '6' ? '沪' : '深';
}

/* ------------------------------------------------------------------ */
/* 1) 实时行情  /api/astock/quote                                       */
/* ------------------------------------------------------------------ */

const QUOTE_FIELDS = 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170';

async function eastmoneyQuote(code) {
  const sid = secid(code);
  if (!sid) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  let j = null;
  let lastErr = null;
  for (const base of EM_QUOTE_HOSTS) {
    try {
      const j2 = await getJSON(`${base}/api/qt/stock/get?secid=${sid}&fields=${QUOTE_FIELDS}`, {
        label: '东财行情接口',
      });
      if (j2 && j2.data && j2.data.f57) {
        j = j2;
        break;
      }
    } catch (e) {
      lastErr = e;
    }
  }
  if (!j) {
    if (lastErr) throw lastErr;
    return { ok: false, error: `东财未返回 ${code} 的行情（代码可能不存在或已退市）` };
  }
  const d = j && j.data;
  if (!d || !d.f57) {
    return { ok: false, error: `东财未返回 ${code} 的行情（代码可能不存在或已退市）` };
  }
  const price = fen(d.f43);
  if (price === null || price === 0) {
    return { ok: false, error: `东财返回的 ${code} 价格为 0（停牌或代码有误）` };
  }
  return {
    ok: true,
    source: 'eastmoney',
    code: String(d.f57),
    name: d.f58 || '',
    price,
    prevClose: fen(d.f60),
    open: fen(d.f46),
    high: fen(d.f44),
    low: fen(d.f45),
    change: fen(d.f169),
    changePct: pct100(d.f170),
    volume: num(d.f47), // 手
    amount: num(d.f48), // 元
    turnoverPct: pct100(d.f168),
    pe: pct100(d.f162),
    pb: pct100(d.f167),
    marketCap: num(d.f116), // 元
    floatMarketCap: num(d.f117),
    ts: Date.now(),
  };
}

async function tencentQuote(code) {
  const p = txPrefix(code);
  if (!p) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  const url = `${TX}/q=${p}${code}`;
  const buf = await request(url, { timeout: DEFAULT_TIMEOUT });
  const text = gbkToUtf8(buf);
  const m = text.match(/="([^"]*)"/);
  if (!m) return { ok: false, error: `腾讯备源未返回 ${code} 的行情` };
  const t = m[1].split('~');
  if (t.length < 45) return { ok: false, error: `腾讯备源数据不完整（${t.length} 字段）` };
  const price = num(t[3]);
  if (price === null || price === 0) return { ok: false, error: `腾讯备源 ${code} 价格为 0（停牌或代码有误）` };
  const amountWan = num(t[37]); // 成交额（万元）
  return {
    ok: true,
    source: 'tencent',
    code: t[2] || code,
    name: t[1] || '',
    price: round(price, 4),
    prevClose: num(t[4]),
    open: num(t[5]),
    high: num(t[33]),
    low: num(t[34]),
    change: num(t[31]),
    changePct: num(t[32]),
    volume: num(t[6]), // 手
    amount: amountWan === null ? null : amountWan * 10000,
    turnoverPct: num(t[38]),
    pe: num(t[39]),
    pb: num(t[46]),
    marketCap: num(t[45]) === null ? null : round(num(t[45]) * 1e8, 0), // 亿元 → 元
    floatMarketCap: num(t[44]) === null ? null : round(num(t[44]) * 1e8, 0),
    ts: Date.now(),
  };
}

/** 东财优先，失败自动降级腾讯 */
async function quote(code) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  let primaryErr = '';
  // 主源改为腾讯：东财 push2 组当前全线不可用，push2test 历史数据被污染，不宜作主源
  try {
    const r = await tencentQuote(c);
    if (r.ok) return r;
    primaryErr = r.error || '腾讯未返回数据';
  } catch (e) {
    primaryErr = e.zh || zhError(e, '腾讯行情接口');
  }
  try {
    const r = await eastmoneyQuote(c);
    if (r.ok) {
      r.fallbackFrom = 'tencent';
      r.fallbackReason = primaryErr;
      return r;
    }
    return { ok: false, error: `${primaryErr}；东财备源也失败：${r.error}` };
  } catch (e) {
    return { ok: false, error: `${primaryErr}；东财备源也失败：${e.zh || zhError(e, '东财行情接口')}` };
  }
}

/* ------------------------------------------------------------------ */
/* 2) K线  /api/astock/kline                                            */
/* ------------------------------------------------------------------ */

const KLT_ALLOWED = new Set(['1', '5', '15', '30', '60', '101', '102', '103']);

async function kline(code, klt = '101', limit = 120) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  const k = KLT_ALLOWED.has(String(klt)) ? String(klt) : '101';
  const lim = Math.min(Math.max(Number(limit) || 120, 1), 1000);

  // ★ 主源（日/周/月）：腾讯。实测与新浪逐日逐字段一致、无幻影行；
  //   东财 push2/push2his 当前全线 000，push2test 历史被污染 ⇒ 不能让它先撞超时
  const period0 = k === '101' ? 'day' : k === '102' ? 'week' : k === '103' ? 'month' : null;
  if (period0) {
    try {
      const tx0 = `${txPrefix(c)}${c}`;
      const j0 = await getJSON(
        `${TX_KLINE}/appstock/app/fqkline/get?param=${tx0},${period0},,,${lim},qfq`,
        { label: '腾讯K线接口' }
      );
      const node0 = j0 && j0.data && j0.data[tx0];
      const rows0 = node0 ? node0[period0] || node0[`qfq${period0}`] : null;
      if (rows0 && rows0.length) {
        const bars0 = rows0.map((r) => ({
          t: r[0],
          o: num(r[1]),
          c: num(r[2]),
          h: num(r[3]),
          l: num(r[4]),
          v: num(r[5]),
          amt: num(r[6]),
        }));
        const cut = bars0.slice(-lim);
        return {
          ok: true,
          source: 'tencent',
          code: c,
          name: (node0 && node0.qt && node0.qt[tx0] && node0.qt[tx0][1]) || '',
          bars: cut,
          items: cut,
          klines: cut,
          ts: Date.now(),
        };
      }
    } catch {
      /* 腾讯不通 → 落到下面的东财 → 腾讯备源流程 */
    }
  }

  // 主源：东财（一次取全史再截尾，东财该端点忽略 lmt 参数）
  try {
    const sid = secid(c);
    const qs =
      `/api/qt/stock/kline/get?secid=${sid}&klt=${k}&fqt=1&beg=0&end=20500101` +
      `&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57`;
    let j = null;
    let lastErr2 = null;
    for (const base of EM_KLINE_HOSTS) {
      try {
        const j2 = await getJSON(`${base}${qs}`, { label: '东财K线接口' });
        if (j2 && j2.data && j2.data.klines && j2.data.klines.length) {
          j = j2;
          break;
        }
      } catch (e) {
        lastErr2 = e;
      }
    }
    if (!j) throw lastErr2 || Object.assign(new Error('EMPTY'), { zh: `东财未返回 ${c} 的 K 线` });
    const d = j && j.data;
    const rows = (d && d.klines) || [];
    if (!rows.length) throw Object.assign(new Error('EMPTY'), { zh: `东财未返回 ${c} 的K线（代码有误或周期无数据）` });
    const bars = rows
      .map((line) => {
        const p = String(line).split(',');
        if (p.length < 7) return null;
        return {
          t: p[0],
          o: num(p[1]),
          h: num(p[3]),
          l: num(p[4]),
          c: num(p[2]),
          v: num(p[5]),
          amt: num(p[6]),
        };
      })
      .filter(Boolean);
    return { ok: true, source: 'eastmoney', code: c, name: (d && d.name) || '', bars: bars.slice(-lim), items: bars.slice(-lim), klines: bars.slice(-lim) };
  } catch (e) {
    const primaryErr = e.zh || zhError(e, '东财K线接口');
    // 备源：腾讯（日/周/月）
    try {
      const period = k === '101' ? 'day' : k === '102' ? 'week' : k === '103' ? 'month' : null;
      if (!period) return { ok: false, error: `${primaryErr}；腾讯备源仅支持日/周/月，分钟线不可用` };
      const url = `${TX_KLINE}/appstock/app/fqkline/get?param=${txPrefix(c)}${c},${period},,,${lim},qfq`;
      const j = await getJSON(url, { label: '腾讯K线备源' });
      const node = j && j.data && j.data[`${txPrefix(c)}${c}`];
      const rows = node ? node[period] || node[`qfq${period}`] : null;
      if (!rows || !rows.length) return { ok: false, error: `${primaryErr}；腾讯备源也无数据` };
      const bars = rows.map((r) => ({
        t: r[0],
        o: num(r[1]),
        c: num(r[2]),
        h: num(r[3]),
        l: num(r[4]),
        v: num(r[5]),
        amt: null,
      }));
      return { ok: true, source: 'tencent', code: c, name: (node && node.qt && node.qt[`${txPrefix(c)}${c}`] && node.qt[`${txPrefix(c)}${c}`][1]) || '', bars: bars.slice(-lim), items: bars.slice(-lim), klines: bars.slice(-lim), fallbackFrom: 'eastmoney', fallbackReason: primaryErr };
    } catch (e2) {
      return { ok: false, error: `${primaryErr}；腾讯备源也失败：${e2.zh || zhError(e2, '腾讯K线备源')}` };
    }
  }
}

/* ------------------------------------------------------------------ */
/* 3) 资金流  /api/astock/fundflow                                      */
/*                                                                      */
/* 2026-09-22 实测：东财 push2 那组主机（push2 / push2his / 82.push2 /   */
/* push2delay）对任何客户端都返回 000（TLS 能建连、读不到数据），同域的   */
/* datacenter-web / quote / searchapi 正常；本机 Mac 同测也 000 ⇒ 上游   */
/* 那组主机的问题。因此资金流按「同口径优先」排四层兜底：                  */
/*   T1 东财 fflow kline（push2his / push2 / 82.push2 / push2test 轮换   */
/*      + 每台重试）—— 同口径、带完整历史                                */
/*   T2 东财 datacenter-web「主力资金」报表 —— 同口径（实测 PRIME_INFLOW */
/*      与 fflow 主力净额逐元相同）、仅当日一行、无中/小单                */
/*   T3 新浪 MoneyFlow —— 真实数据但**异口径**（主动买卖分层），           */
/*      必须带 note 声明，不可与东财口径直接比较                          */
/*   T4 当日分时主动买卖近似 —— 估算值，estimated:true，绝不冒充真实资金流 */
/* 任一层失败只影响自己：返回 ok:false + 中文原因，绝不抛给路由。          */
/* ------------------------------------------------------------------ */

/** 东财 fflow 主机轮换表：前两台为生产主机，后两台为实测仍可用的同族镜像 */
const FFLOW_HOSTS = [
  { tag: 'push2test', base: EM_TEST }, // 实测可用镜像：放第一位，避免先等三个超时
  { tag: 'push2his', base: EM_HIS },
  { tag: 'push2', base: EM },
  { tag: '82.push2', base: EM_82 },
];

/** 整层轮换的总预算（所有主机都挂时不必把每个超时都等满） */
const FFLOW_BUDGET_MS = Number(process.env.ASTOCK_FFLOW_BUDGET_MS || 12000);

/** 主机亲和缓存：记住刚用通的那台，短时间内优先它（省掉每次都先撞死主机的 1s+） */
const HOST_AFFINITY_TTL_MS = Number(process.env.ASTOCK_HOST_AFFINITY_MS || 60000);
let hostAffinity = { tag: null, at: 0 };

/** 把刚用通的主机提到最前（过期的亲和不看）；死的仍会在它后面按序轮换 */
function orderHosts(hosts) {
  const fresh = hostAffinity.tag && Date.now() - hostAffinity.at < HOST_AFFINITY_TTL_MS;
  if (!fresh) return hosts;
  const idx = hosts.findIndex((h) => h.tag === hostAffinity.tag);
  if (idx <= 0) return hosts;
  return [hosts[idx]].concat(hosts.slice(0, idx), hosts.slice(idx + 1));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 单次失败的短中文原因（用于拼「哪台主机怎么挂的」） */
function shortErr(e) {
  if (!e) return '失败';
  if (e.kind === 'timeout' || e.message === 'TIMEOUT') return '超时';
  if (e.kind === 'http' || /^HTTP_/.test(e.message)) return `HTTP ${e.status || String(e.message).replace('HTTP_', '')}`;
  if (e.code === 'ENOTFOUND' || e.code === 'EAI_AGAIN') return '域名解析失败';
  if (e.code === 'ECONNREFUSED') return '连接被拒绝';
  if (e.code === 'ECONNRESET') return '连接被重置';
  if (e.zh) return e.zh;
  return e.message || '未知错误';
}

/**
 * 按主机轮换 + 每台重试，返回第一个「可取用」的结果。
 * accept(json) 为假时视为该次无有效数据，继续重试/换主机。
 * 全挂则抛 Error，其 zh 是可读中文原因（含每台主机的失败摘要）。
 */
async function getJSONRotating(hosts, pathOf, { label, attempts = 2, timeout = DEFAULT_TIMEOUT, budgetMs = FFLOW_BUDGET_MS, backoffMs = 200, accept = null } = {}) {
  const started = Date.now();
  const parts = [];
  for (const h of orderHosts(hosts)) {
    let firstErr = null;
    let tried = 0;
    for (let i = 1; i <= attempts; i++) {
      if (Date.now() - started > budgetMs) {
        parts.push(`${h.tag} 未及尝试（本层已用满 ${Math.round(budgetMs / 1000)}s）`);
        throw Object.assign(new Error('ROTATE_BUDGET'), { zh: `${label}：${parts.join(' → ')}` });
      }
      tried += 1;
      try {
        const json = await getJSON(h.base + pathOf(h), { label, timeout });
        if (accept && !accept(json)) {
          if (!firstErr) firstErr = '无有效数据';
          if (i < attempts) await sleep(backoffMs);
          continue;
        }
        hostAffinity = { tag: h.tag, at: Date.now() };
        return { json, host: h.tag, tried };
      } catch (e) {
        if (!firstErr) firstErr = shortErr(e);
        if (i < attempts) await sleep(backoffMs);
      }
    }
    parts.push(`${h.tag} ${firstErr || '无有效数据'}${tried > 1 ? `×${tried}` : ''}`);
  }
  throw Object.assign(new Error('ALL_HOSTS_FAILED'), { zh: `${label}：${parts.join(' → ')}` });
}

/** 两个字段相减（缺一个就 null，不编 0） */
function diffOrNull(a, b) {
  const x = num(a);
  const y = num(b);
  return x === null || y === null ? null : round(x - y, 2);
}

/** 用当日成交额算「主力净占比」；拿不到成交额就给 null，不编数字 */
async function netPctOf(code, mainNet) {
  try {
    const q = await quote(code);
    if (q.ok && q.amount && mainNet !== null && mainNet !== undefined) {
      return round((mainNet / q.amount) * 100, 4);
    }
  } catch {
    /* 成交额拿不到不影响资金流本身 */
  }
  return null;
}

/**
 * T1：东财 fflow 日线（当日 + 历史），主机轮换 + 重试。
 * push2test 是东财同族镜像：实测 klines 与 push2his 逐字相同（600519 2026-09-22 主力 -70,101,392，
 * 与 datacenter-web 的 PRIME_INFLOW 完全一致），故可作为同口径兜底。
 */
async function fundflowEastmoney(code, lmt = 60) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  const sid = secid(c);
  const limit = Math.min(Math.max(Number(lmt) || 60, 1), 200);
  try {
    const qs = `/api/qt/stock/fflow/kline/get?secid=${sid}&klt=101&lmt=${limit}` +
      '&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56';
    const { json: j, host } = await getJSONRotating(FFLOW_HOSTS, () => qs, {
      label: '东财资金流接口',
      accept: (x) => !!(x && x.data && x.data.klines && x.data.klines.length),
    });
    const d = j.data;
    const rows = d.klines;
    // 每行：日期,主力净额,小单净额,中单净额,大单净额,超大单净额
    const parsed = rows.map((line) => {
      const p = String(line).split(',');
      return {
        t: p[0],
        main: num(p[1]),
        small: num(p[2]),
        medium: num(p[3]),
        large: num(p[4]),
        super: num(p[5]),
      };
    });
    const last = parsed[parsed.length - 1];
    return {
      ok: true,
      source: 'eastmoney',
      host,
      code: c,
      name: (d && d.name) || '',
      date: last.t,
      main: { net: last.main, netPct: await netPctOf(c, last.main) },
      super: { net: last.super },
      large: { net: last.large },
      medium: { net: last.medium },
      small: { net: last.small },
      history: parsed.map((r) => ({ t: r.t, mainNet: r.main })),
      ts: Date.now(),
    };
  } catch (e) {
    return { ok: false, error: e.zh || zhError(e, '东财资金流接口') };
  }
}

/**
 * T2：东财 datacenter-web「主力资金」报表（RPT_DMSK_TS_STOCKNEW）。
 * 同口径：实测 600519 2026-09-22 PRIME_INFLOW = -70,101,392 = fflow 主力净额；
 * 超大单/大单 = 流入 - 流出，与 fflow 逐元相同。
 * 限制：该报表只有**当日一行**（无历史），且不提供中单/小单（给 null，不用 0 冒充）。
 */
async function fundflowDatacenter(code) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  try {
    const filter = encodeURIComponent(`(SECURITY_CODE="${c}")`);
    const url = `${EM_DC}/api/data/v1/get?reportName=RPT_DMSK_TS_STOCKNEW&columns=ALL&pageSize=1&filter=${filter}`;
    const j = await getJSON(url, {
      label: '东财主力资金报表',
      headers: { Referer: 'https://data.eastmoney.com/' },
    });
    const row = (j && j.result && j.result.data && j.result.data[0]) || null;
    if (!row) throw Object.assign(new Error('EMPTY'), { zh: `东财主力资金报表未返回 ${c} 的数据` });
    const main = num(row.PRIME_INFLOW);
    if (main === null) throw Object.assign(new Error('EMPTY'), { zh: `东财主力资金报表的 ${c} 缺主力净额字段` });
    const date = String(row.TRADE_DATE || '').slice(0, 10);
    return {
      ok: true,
      source: 'eastmoney',
      host: 'datacenter-web',
      code: c,
      name: row.SECURITY_NAME_ABBR || '',
      date,
      main: { net: main, netPct: await netPctOf(c, main) },
      super: { net: diffOrNull(row.SUPERDEAL_INFLOW, row.SUPERDEAL_OUTFLOW) },
      large: { net: diffOrNull(row.BIGDEAL_INFLOW, row.BIGDEAL_OUTFLOW) },
      medium: null,
      small: null,
      history: date ? [{ t: date, mainNet: main }] : [],
      note: '来自东财「主力资金」报表（与 fflow 主力同口径）；该报表只给当日一行，且不提供中单/小单',
      ts: Date.now(),
    };
  } catch (e) {
    return { ok: false, error: e.zh || zhError(e, '东财主力资金报表') };
  }
}

/**
 * T3：新浪 MoneyFlow（真实数据，但**口径与东财不同**，必须带 note 声明）。
 * 实测口径：r0=超大单 / r1=大单 / r2=中单 / r3=小单；主力 = r0_net + r1_net。
 * ⚠️ 恒等式 netamount = r0_net + r1_net + r2_net + r3_net ⇒ netamount 是「全部净额」，
 *    不是主力净额（旧实现按 netamount 当主力是错的）。同日可差到反号
 *    （600519 2026-09-22：东财主力 -70,101,392，新浪 r0+r1 = +176,284,203）。
 * 参数要点：daima 必须带 sh/sz 前缀（不带前缀返回 []）。
 * 方法选 `ssl_qsfx_lscjfb`（返回 r0..r3 全分层）；`ssl_qsfx_zjlrqs` 只给 r0_net，
 * 算不出「主力 = 超大 + 大」，已不用。
 */
async function fundflowSina(code, lmt = 60) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  const want = Math.min(Math.max(Number(lmt) || 60, 1), 60);
  const tx = `${txPrefix(c)}${c}`; // sh600519 / sz002246
  const url =
    'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/' +
    `MoneyFlow.ssl_qsfx_lscjfb?page=1&num=${want}&sort=opendate&asc=0&daima=${tx}`;
  try {
    const j = await getJSON(url, {
      label: '新浪资金流接口',
      headers: { Referer: 'https://finance.sina.com.cn/' },
    });
    const rows = Array.isArray(j) ? j : [];
    if (!rows.length) throw Object.assign(new Error('EMPTY'), { zh: `新浪未返回 ${c} 的资金流（daima 需带 sh/sz 前缀）` });
    const parsed = rows
      .map((r) => {
        const sp = num(r.r0_net);
        const lg = num(r.r1_net);
        return {
          t: String(r.opendate || ''),
          super: sp,
          large: lg,
          medium: num(r.r2_net),
          small: num(r.r3_net),
          main: sp === null && lg === null ? null : round((sp || 0) + (lg || 0), 2),
        };
      })
      .filter((r) => r.t && r.main !== null);
    if (!parsed.length) throw Object.assign(new Error('EMPTY'), { zh: `新浪未返回 ${c} 的分层资金流` });
    parsed.sort((a, b) => (a.t < b.t ? -1 : 1)); // 旧→新，与东财 history 一致
    const last = parsed[parsed.length - 1];
    let name = '';
    try {
      const q = await quote(c); // 腾讯行情可用，仅取名称
      if (q.ok) name = q.name || '';
    } catch {
      /* 名称拿不到不影响资金流 */
    }
    return {
      ok: true,
      source: 'sina',
      host: 'vip.stock.finance.sina.com.cn',
      code: c,
      name,
      date: last.t,
      main: { net: last.main, netPct: await netPctOf(c, last.main) },
      super: { net: last.super },
      large: { net: last.large },
      medium: { net: last.medium },
      small: { net: last.small },
      history: parsed.map((r) => ({ t: r.t, mainNet: r.main })),
      note: '新浪口径（主动买卖分层，主力=超大单+大单）；与东财口径不是同一口径，不可直接比较',
      ts: Date.now(),
    };
  } catch (e) {
    return { ok: false, error: e.zh || zhError(e, '新浪资金流接口') };
  }
}

/**
 * T4：近似估算（最后一层）。东财 / 新浪资金流都不可用时，用**当日分时**逐分钟按价格方向
 * 归类主动买卖：主动净额 = Σ(价升分钟成交额) − Σ(价降分钟成交额)。
 * 用的是真实分时数据，但它是「主动买卖净额」近似，**不是东财主力净额口径**——
 * 实测 600519 2026-09-22：本近似 +1.10 亿 / 新浪主动净额 +1.86 亿 / 东财主力 −0.70 亿。
 * 因此固定带 estimated:true + note，前端显示「估算」徽标，绝不冒充真实资金流。
 * ⚠️ 腾讯分时的 vol / amt 是**当日累计值**（末点 24582 手 / 30.90 亿 = 全天），
 *    必须逐点作差才是每分钟增量；直接累加会放大两个数量级。
 */
async function fundflowMinuteEstimate(code) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  try {
    const m = await minute(c);
    if (!m.ok || !m.points || m.points.length < 2) {
      throw Object.assign(new Error('EMPTY'), {
        zh: `无可用分时数据，无法近似资金流（${(m && m.error) || '未知原因'}）`,
      });
    }
    const pts = m.points;
    // 每分钟增量：优先用累计成交额作差，缺失时退回 累计量(手)×100×价
    const inc = (i) => {
      const a = pts[i].amt;
      const b = pts[i - 1].amt;
      if (a !== null && b !== null && a >= b) return a - b;
      const va = pts[i].vol;
      const vb = pts[i - 1].vol;
      if (va !== null && vb !== null && va >= vb && pts[i].price !== null) return (va - vb) * 100 * pts[i].price;
      return null;
    };
    let buy = 0;
    let sell = 0;
    for (let i = 1; i < pts.length; i++) {
      const amt = inc(i);
      if (amt === null || amt <= 0) continue;
      const d = (pts[i].price || 0) - (pts[i - 1].price || 0);
      if (d > 0) buy += amt;
      else if (d < 0) sell += amt;
      else {
        buy += amt / 2;
        sell += amt / 2;
      }
    }
    if (!(buy + sell)) throw Object.assign(new Error('EMPTY'), { zh: `分时数据无法归类主动买卖（${c}）` });
    const mainNet = round(buy - sell, 2);
    return {
      ok: true,
      source: 'minute-estimate',
      host: 'qt.gtimg.cn/minute',
      code: c,
      name: m.name || '',
      date: m.date,
      main: { net: mainNet, netPct: await netPctOf(c, mainNet) },
      super: null,
      large: null,
      medium: null,
      small: null,
      history: m.date ? [{ t: m.date, mainNet }] : [],
      estimated: true,
      activeBuy: round(buy, 2),
      activeSell: round(sell, 2),
      note: '估算值：东财与新浪资金流源均不可用，改用当日分时逐分钟主动买卖归类（主动买 − 主动卖）近似；与东财主力口径不同，非真实资金流数据',
      ts: Date.now(),
    };
  } catch (e) {
    return { ok: false, error: e.zh || zhError(e, '资金流近似估算') };
  }
}

/** 资金流统一入口：东财同口径（轮换+重试）→ 东财报表 → 新浪 → 估算 */
async function fundflow(code, lmt = 60) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  const reasons = [];
  const tiers = [
    ['东财 fflow', () => fundflowEastmoney(c, lmt)],
    ['东财主力资金报表', () => fundflowDatacenter(c, lmt)],
    ['新浪 MoneyFlow', () => fundflowSina(c, lmt)],
    ['分时主动买卖近似', () => fundflowMinuteEstimate(c)],
  ];
  for (const [label, run] of tiers) {
    let r = null;
    try {
      r = await run();
    } catch (e) {
      reasons.push(`${label}：${e.zh || zhError(e, label)}`);
      continue;
    }
    if (r && r.ok) {
      if (reasons.length) {
        r.fallbackFrom = 'eastmoney';
        r.fallbackReason = reasons.join('；');
      }
      return r;
    }
    reasons.push(`${label}：${(r && r.error) || '不可用'}`);
  }
  return { ok: false, error: `资金流四层数据源全部失败 —— ${reasons.join('；')}` };
}

/* ------------------------------------------------------------------ */
/* 4) 财务  /api/astock/finance                                         */
/* ------------------------------------------------------------------ */

async function debtRatioMap(secucode) {
  const map = new Map();
  try {
    const url =
      `${EM_DC}/api/data/v1/get?reportName=RPT_F10_FINANCE_GBALANCE&columns=ALL` +
      `&filter=${encodeURIComponent(`(SECUCODE="${secucode}")`)}&pageSize=8&sortColumns=REPORT_DATE&sortTypes=-1`;
    const j = await getJSON(url, { label: '东财资产负债表接口', timeout: DEFAULT_TIMEOUT });
    const rows = (j && j.result && j.result.data) || [];
    for (const row of rows) {
      const assets = num(row.TOTAL_ASSETS);
      const liab = num(row.TOTAL_LIABILITIES);
      if (!assets || liab === null) continue;
      const period = String(row.REPORT_DATE || '').slice(0, 10);
      if (period) map.set(period, round((liab / assets) * 100, 2));
    }
  } catch {
    /* 拿不到就留空 map，字段给 null，不编 */
  }
  return map;
}

/** 现金流量表（RPT_DMSK_FN_CASHFLOW）→ Map<报告期, {ocf, capex}>；失败返回空 Map，绝不影响主报表 */
async function cashflowMap(code) {
  const out = new Map();
  try {
    const filter = encodeURIComponent(`(SECURITY_CODE="${code}")`);
    const url =
      `${EM_DC}/api/data/v1/get?reportName=RPT_DMSK_FN_CASHFLOW&columns=ALL&filter=${filter}` +
      `&pageSize=8&sortColumns=REPORT_DATE&sortTypes=-1`;
    const j = await getJSON(url, { label: '东财现金流接口' });
    const rows = (j && j.result && j.result.data) || [];
    for (const r of rows) {
      const period = String(r.REPORT_DATE || '').slice(0, 10);
      if (!period) continue;
      out.set(period, { ocf: num(r.NETCASH_OPERATE), capex: num(r.CONSTRUCT_LONG_ASSET) });
    }
  } catch {
    /* 现金流拿不到不影响主报表 */
  }
  return out;
}

async function finance(code) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  try {
    const filter = encodeURIComponent(`(SECURITY_CODE="${c}")`);
    const url =
      `${EM_DC}/api/data/v1/get?reportName=RPT_LICO_FN_CPD&columns=ALL&filter=${filter}` +
      `&pageSize=8&sortColumns=REPORTDATE&sortTypes=-1`;
    const j = await getJSON(url, { label: '东财财务接口' });
    const rows = (j && j.result && j.result.data) || [];
    if (!rows.length) throw Object.assign(new Error('EMPTY'), { zh: `东财未返回 ${c} 的财务数据` });
    const debtMap = await debtRatioMap(`${c}${c[0] === '6' ? '.SH' : '.SZ'}`);
    // 现金流（经营现金流 / 资本开支）：估值模块（DCF）需要；单独一个源，失败不影响主报表
    const cfMap = await cashflowMap(c);
    const reports = rows.map((r) => {
      const period = String(r.REPORTDATE || '').slice(0, 10);
      const cf = cfMap.get(period) || {};
      return {
        period,
        reportName: r.DATATYPE || '',
        revenue: num(r.TOTAL_OPERATE_INCOME),
        revenueYoy: num(r.YSTZ),
        netProfit: num(r.PARENT_NETPROFIT),
        netProfitYoy: num(r.SJLTZ),
        eps: num(r.BASIC_EPS),
        roe: num(r.WEIGHTAVG_ROE),
        grossMargin: num(r.XSMLL),
        debtRatio: debtMap.get(period) ?? null,
        bps: num(r.BPS),
        ocf: cf.ocf === undefined ? null : cf.ocf, // 经营活动现金流净额（元）
        capex: cf.capex === undefined ? null : cf.capex, // 购建固定资产等支付现金（元，资本开支近似）
      };
    });
    return {
      ok: true,
      source: 'eastmoney',
      code: c,
      name: rows[0].SECURITY_NAME_ABBR || '',
      reports,
      items: reports, // 别名：兼容按 items[] 读取的消费方（如 v3 估值模块）
      ts: Date.now(),
    };
  } catch (e) {
    return { ok: false, error: e.zh || zhError(e, '东财财务接口') };
  }
}

/* ------------------------------------------------------------------ */
/* 5) 搜索  /api/astock/search                                          */
/* ------------------------------------------------------------------ */

async function search(q) {
  const kw = String(q == null ? '' : q).trim();
  if (!kw) return { ok: false, error: '查询关键词为空' };
  try {
    const url =
      `${EM_SEARCH}/api/suggest/get?input=${encodeURIComponent(kw)}&type=14` +
      `&token=${SEARCH_TOKEN}&count=10`;
    const j = await getJSON(url, { label: '东财搜索接口' });
    const data = (j && j.QuotationCodeTable && j.QuotationCodeTable.Data) || [];
    const items = data
      .filter((d) => /^\d{6}$/.test(String(d.Code || '')) && /^[036]/.test(String(d.Code)))
      .map((d) => ({
        code: String(d.Code),
        name: d.Name || '',
        market: marketOf(d.Code),
        type: d.SecurityTypeName || '',
      }));
    return { ok: true, source: 'eastmoney', items, ts: Date.now() };
  } catch (e) {
    return { ok: false, error: e.zh || zhError(e, '东财搜索接口') };
  }
}

/* ------------------------------------------------------------------ */
/* ------------------------------------------------------------------ */
/* 结果缓存（TTL + single-flight）                                      */
/*   2026-09-25 新增。此前行情类端点**零缓存**：公网多访客会把上游     */
/*   打到限流/拒答（同项目 SPEC 里已记过 push2 全系归 000 的教训）。    */
/*   只缓存成功结果：失败不缓存，避免「一次抖动被记住一小时」。        */
/* ------------------------------------------------------------------ */
const CACHE_TTL = {
  quote: Number(process.env.CACHE_QUOTE_MS || 3000),
  market: Number(process.env.CACHE_MARKET_MS || 10000),
  kline: Number(process.env.CACHE_KLINE_MS || 60000),
  minute: Number(process.env.CACHE_MINUTE_MS || 30000),
  finance: Number(process.env.CACHE_FINANCE_MS || 3600000),
  fundflow: Number(process.env.CACHE_FUNDFLOW_MS || 60000),
  search: Number(process.env.CACHE_SEARCH_MS || 300000),
};
const CACHE_MAX_KEYS = Number(process.env.CACHE_MAX_KEYS || 600);
const caches = new Map(); // key -> { at, value }
const inflight = new Map(); // key -> Promise
const cacheHit = { hit: 0, miss: 0, shared: 0 };
function cacheStats() {
  return Object.assign({ keys: caches.size, inflight: inflight.size }, cacheHit);
}
function cacheTrim() {
  if (caches.size <= CACHE_MAX_KEYS) return;
  const arr = Array.from(caches.entries()).sort((a, b) => a[1].at - b[1].at);
  for (let i = 0; i < arr.length - CACHE_MAX_KEYS; i++) caches.delete(arr[i][0]);
}
function withCache(kind, key, fn) {
  const ttl = CACHE_TTL[kind] || 0;
  const k = `${kind}|${key}`;
  const now = Date.now();
  const c = caches.get(k);
  if (ttl > 0 && c && now - c.at < ttl) {
    cacheHit.hit++;
    return Promise.resolve(Object.assign({}, c.value, { cached: true, cacheAgeMs: now - c.at }));
  }
  cacheHit.miss++;
  if (inflight.has(k)) {
    cacheHit.shared++;
    return inflight.get(k);
  }
  const pr = Promise.resolve()
    .then(fn)
    .then((v) => {
      if (ttl > 0 && v && v.ok) {
        caches.set(k, { at: Date.now(), value: v });
        cacheTrim();
      }
      return v;
    })
    .finally(() => inflight.delete(k));
  inflight.set(k, pr);
  return pr;
}

/* ------------------------------------------------------------------ */
/* 大盘指数  /api/astock/market                                      */
/* ------------------------------------------------------------------ */

const INDICES = [
  { secid: '1.000001', code: '000001', name: '上证指数' },
  { secid: '0.399001', code: '399001', name: '深证成指' },
  { secid: '0.399006', code: '399006', name: '创业板指' },
  { secid: '1.000300', code: '000300', name: '沪深300' },
  { secid: '1.000688', code: '000688', name: '科创50' },
];

async function market() {
  const secids = INDICES.map((i) => i.secid).join(',');
  /* 2026-09-25：改成主机轮换（此前只打 push2 一台，它挂了就白等一个超时）。 */
  const hosts = [EM, EM_TEST, EM_82, EM_HIS];
  let lastErr = null;
  for (const h of hosts) {
    const host = h.replace('https://', '');
    try {
      const url = `${h}/api/qt/ulist.np/get?fltt=2&secids=${secids}&fields=f2,f3,f12,f14`;
      const j = await getJSON(url, { label: `东财指数接口(${host})`, timeout: 5000 });
      const raw = j && j.data && j.data.diff;
      const list = Array.isArray(raw) ? raw : raw && typeof raw === 'object' ? Object.values(raw) : [];
      if (!list.length) throw Object.assign(new Error('EMPTY'), { zh: `东财指数接口(${host})未返回指数数据` });
      const byCode = new Map(list.map((d) => [String(d.f12), d]));
      const indices = INDICES.map((i) => {
        const d = byCode.get(i.code);
        return {
          code: i.code,
          name: (d && d.f14) || i.name,
          price: d ? num(d.f2) : null,
          changePct: d ? num(d.f3) : null,
        };
      });
      return { ok: true, source: 'eastmoney', host, ts: Date.now(), indices };
    } catch (e) {
      lastErr = e;
    }
  }
  const e = lastErr || new Error('EMPTY');
  {
    // 备源：腾讯指数（sh000001 / sz399001 …）
    try {
      const qs = ['sh000001', 'sz399001', 'sz399006', 'sh000300', 'sh000688'];
      const url = `${TX}/q=${qs.join(',')}`;
      const buf = await request(url, { timeout: DEFAULT_TIMEOUT });
      const text = gbkToUtf8(buf);
      const lines = text.split('\n').filter(Boolean);
      const indices = lines.map((line) => {
        const m = line.match(/v_(\w+)="([^"]*)"/);
        if (!m) return null;
        const t = m[2].split('~');
        const code = String(t[2] || '').padStart(6, '0');
        const meta = INDICES.find((i) => i.code === code);
        return {
          code,
          name: t[1] || (meta ? meta.name : ''),
          price: num(t[3]),
          changePct: num(t[32]),
        };
      }).filter(Boolean);
      if (!indices.length) throw Object.assign(new Error('EMPTY'), { zh: '腾讯备源也无指数数据' });
      return { ok: true, source: 'tencent', ts: Date.now(), indices, fallbackFrom: 'eastmoney', fallbackReason: e.zh || zhError(e, '东财指数接口') };
    } catch (e2) {
      return { ok: false, error: `${e.zh || zhError(e, '东财指数接口')}；腾讯备源也失败：${e2.zh || zhError(e2, '腾讯指数备源')}` };
    }
  }
}

/* ------------------------------------------------------------------ */
/* 数据源健康检查（/api/health 用，带缓存）                              */
/* ------------------------------------------------------------------ */

let healthCache = { at: 0, value: null };

/* 3.5) 分时  /api/astock/minute                                      */
/*  东财 push2his trends2 当前不可用（2026-09-22 实测返空），改走腾讯分时。 */
async function minute(code) {
  const c = normCode(code);
  if (!c) return { ok: false, error: '股票代码不合法：需要 6 位数字（如 600519）' };
  const tx = `${txPrefix(c)}${c}`; // sh600519 / sz002246
  try {
    return await minuteTencent(c, tx);
  } catch (e) {
    /* 2026-09-25：补东财 trends2 兜底（此前分时是**单源无兜底**，
       腾讯一超时就 502@16s；而资金流第四层又依赖分时 → 连带失效）。 */
    const alt = await minuteEastmoney(c);
    if (alt && alt.ok) {
      alt.fallbackFrom = 'tencent';
      alt.fallbackReason = e.zh || zhError(e, '腾讯分时接口');
      return alt;
    }
    const altMsg = alt && alt.error ? `；东财分时备源也失败：${alt.error}` : '';
    return { ok: false, error: `${e.zh || zhError(e, '腾讯分时接口')}${altMsg}` };
  }
}

async function minuteTencent(c, tx) {
  const j = await getJSON(`${TX_KLINE}/appstock/app/minute/query?code=${tx}`, {
    label: '腾讯分时接口',
  });
  const node = j && j.data && j.data[tx] && j.data[tx].data;
  const rows = (node && node.data) || [];
  if (!rows.length) {
    throw Object.assign(new Error('EMPTY'), { zh: `腾讯未返回 ${c} 的分时数据（可能是非交易日）` });
  }
  // 每行："0930 26.76 5442 14562792.00" = HHMM 价 量(手) 额(元)
  const points = rows
    .map((line) => {
      const p = String(line).trim().split(/\s+/);
      const hhmm = p[0] || '';
      return {
        t: hhmm.length === 4 ? `${hhmm.slice(0, 2)}:${hhmm.slice(2)}` : hhmm,
        price: num(p[1]),
        vol: num(p[2]),
        amt: num(p[3]),
      };
    })
    .filter((x) => x.price > 0);
  if (!points.length) {
    throw Object.assign(new Error('EMPTY'), { zh: `腾讯未返回 ${c} 的有效分时点` });
  }
  const { name, prevClose } = await nameAndPrevClose(c);
  const raw = String((node && node.date) || '');
  const date = /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : raw;
  return { ok: true, source: 'tencent', code: c, name, date, prevClose, points, ts: Date.now() };
}

/** 东财 trends2 分时兜底（主机轮换）；失败返还 {ok:false,error} */
async function minuteEastmoney(c) {
  const sid = secid(c);
  for (const h of [EM_HIS, EM_TEST, EM, EM_82]) {
    const host = h.replace('https://', '');
    try {
      const url = `${h}/api/qt/stock/trends2/get?secid=${sid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f53,f56,f58&iscr=0&ndays=1`;
      const j = await getJSON(url, { label: `东财分时(${host})`, timeout: 5000 });
      const trends = (j && j.data && j.data.trends) || [];
      const points = trends
        .map((line) => {
          const p = String(line).split(',');
          const dt = String(p[0] || '');
          const hhmm = dt.length >= 16 ? dt.slice(11, 16) : dt;
          return { t: hhmm, price: num(p[1]), vol: num(p[2]), amt: num(p[3]) };
        })
        .filter((x) => x.price > 0);
      if (!points.length) throw Object.assign(new Error('EMPTY'), { zh: `东财分时(${host})未返回数据` });
      const { name, prevClose } = await nameAndPrevClose(c);
      const lastDate = String((trends[trends.length - 1] || '').split(',')[0] || '').slice(0, 10);
      return { ok: true, source: 'eastmoney', host, code: c, name, date: lastDate, prevClose, points, ts: Date.now() };
    } catch (e) {
      /* 换下一台 */
    }
  }
  return { ok: false, error: '东财分时四台主机均失败' };
}

/** 名称与昨收（拿不到不影响分时） */
async function nameAndPrevClose(c) {
  try {
    const q = await quote(c);
    if (q.ok) return { name: q.name || '', prevClose: q.prevClose == null ? null : q.prevClose };
  } catch {
    /* 忽略 */
  }
  return { name: '', prevClose: null };
}

async function probeSources({ force = false } = {}) {
  const now = Date.now();
  if (!force && healthCache.value && now - healthCache.at < 60000) return healthCache.value;

  const eastmoney = await eastmoneyQuote('600519')
    .then((r) => !!r.ok)
    .catch(() => false);
  const tencent = await tencentQuote('600519')
    .then((r) => !!r.ok)
    .catch(() => false);

  const value = { eastmoney, tencent, checkedAt: Date.now() };
  healthCache = { at: now, value };
  return value;
}

module.exports = {
  // 对外导出一律过缓存层（TTL 见 CACHE_TTL）；模块内部互相调用不受影响。
  quote: (code) => withCache('quote', normCode(code) || String(code || ''), () => quote(code)),
  kline: (code, klt = '101', limit = 120) =>
    withCache('kline', `${normCode(code) || code}|${klt}|${limit}`, () => kline(code, klt, limit)),
  fundflow: (code, lmt = 60) =>
    withCache('fundflow', `${normCode(code) || code}|${lmt}`, () => fundflow(code, lmt)),
  fundflowEastmoney,
  fundflowDatacenter,
  fundflowSina,
  fundflowMinuteEstimate,
  minute: (code) => withCache('minute', normCode(code) || String(code || ''), () => minute(code)),
  finance: (code) => withCache('finance', normCode(code) || String(code || ''), () => finance(code)),
  search: (kw) => withCache('search', String(kw || '').trim(), () => search(kw)),
  market: () => withCache('market', 'indices', () => market()),
  probeSources,
  secid,
  normCode,
  cacheStats,
  CACHE_TTL,
  // 供测试/调试
  _internal: { request, num, fen, pct100, gbkToUtf8, eastmoneyQuote, tencentQuote, zhError },
};
