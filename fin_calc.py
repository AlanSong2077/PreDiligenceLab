"""
fin_calc.py — 财务计算器后端（重构版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
设计原则：
  1. 用户只需输入财报上能直接找到的 9 个基本科目（单位：万元，全程统一）
  2. 所有派生指标由系统自动推算，不要求用户手动填写
  3. 行业基准支持两种模式：
       a. 按行业名称拉取东方财富板块成分股（原有逻辑）
       b. 指定若干 A 股/港股/美股代码，直接拉取这些公司的财务数据作为基准
  4. 计算口径严格对齐财报定义，注释说明出处

输入字段（9 个，全部来自财报，单位统一为万元）：
  revenue          营业收入（利润表第一行）
  cogs             营业成本（利润表，= 营业收入 - 毛利润）
  operating_profit 营业利润（利润表）
  net_profit       净利润（归母，利润表最后）
  total_assets     资产总计（资产负债表）
  current_assets   流动资产合计（资产负债表）
  current_liab     流动负债合计（资产负债表）
  total_liab       负债合计（资产负债表）
  equity           归属母公司股东权益合计（资产负债表）

可选补充（填了更准，不填系统估算）：
  inventory        存货（资产负债表，用于速动比率/存货周转）
  ar               应收账款（资产负债表，用于应收周转）
  interest_exp     财务费用-利息支出（利润表附注，用于利息保障）
  da               折旧与摊销（现金流量表附注，用于 EBITDA）
  market_cap       总市值（万元，用于 PE/PB/PS；不填则不计算估值）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math
import statistics
from typing import Optional
from logger import get_logger

_log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# 指标元数据
# ─────────────────────────────────────────────────────────────

# (显示名, 单位, 越高越好?)
METRIC_META = {
    # 规模
    "revenue":         ("营业收入",       "万元", True),
    "gross_profit":    ("毛利润",         "万元", True),
    "net_profit_abs":  ("净利润",         "万元", True),
    # 盈利能力
    "gross_margin":    ("毛利率",         "%",   True),
    "operating_margin":("营业利润率",     "%",   True),
    "net_margin":      ("净利率",         "%",   True),
    "roe":             ("ROE",            "%",   True),
    "roa":             ("ROA",            "%",   True),
    "ebitda_margin":   ("EBITDA率",       "%",   True),
    # 偿债能力
    "current_ratio":   ("流动比率",       "x",   True),
    "quick_ratio":     ("速动比率",       "x",   True),
    "debt_ratio":      ("资产负债率",     "%",   False),
    "interest_cover":  ("利息保障倍数",   "x",   True),
    # 运营效率
    "ar_days":         ("应收账款天数",   "天",  False),
    "inv_days":        ("存货周转天数",   "天",  False),
    "asset_turnover":  ("总资产周转率",   "x",   True),
    # 现金流
    "cfo_to_revenue":  ("经营现金流/营收", "%",  True),
    "cfo_to_netprofit":("现金含量",       "x",   True),
    # 估值（需市值）
    "pe":              ("PE",             "x",   False),
    "pb":              ("PB",             "x",   False),
    "ps":              ("PS",             "x",   False),
}

METRIC_GROUPS = {
    "规模": ["revenue", "gross_profit", "net_profit_abs"],
    "盈利能力": ["gross_margin", "operating_margin", "net_margin",
                 "roe", "roa", "ebitda_margin"],
    "偿债能力": ["current_ratio", "quick_ratio", "debt_ratio", "interest_cover"],
    "运营效率": ["ar_days", "inv_days", "asset_turnover"],
    "现金流": ["cfo_to_revenue", "cfo_to_netprofit"],
    "估值参考": ["pe", "pb", "ps"],
}

# 绝对健康区间（无行业数据时使用）
# (lower_warn, lower_ok, upper_ok, upper_warn)  None = 不设限
HEALTH_RANGES = {
    "revenue":          (0,    None, None, None),
    "gross_profit":     (0,    None, None, None),
    "net_profit_abs":   (0,    None, None, None),
    "gross_margin":     (10,   20,   None, None),
    "operating_margin": (0,    5,    None, None),
    "net_margin":       (0,    5,    40,   None),
    "roe":              (0,    8,    30,   None),
    "roa":              (0,    3,    20,   None),
    "ebitda_margin":    (0,    10,   50,   None),
    "current_ratio":    (0.8,  1.5,  4.0,  None),
    "quick_ratio":      (0.5,  1.0,  3.0,  None),
    "debt_ratio":       (None, None, 60,   80),
    "interest_cover":   (1.0,  2.0,  None, None),
    "ar_days":          (None, None, 60,   120),
    "inv_days":         (None, None, 90,   180),
    "asset_turnover":   (0.2,  0.5,  None, None),
    "cfo_to_revenue":   (0,    5,    None, None),
    "cfo_to_netprofit": (0.5,  1.0,  None, None),
    "pe":               (0,    10,   50,   100),
    "pb":               (0,    1,    8,    15),
    "ps":               (0,    0.5,  10,   20),
}


# ─────────────────────────────────────────────────────────────
# 0. 健康得分映射（0-100，用于雷达图，无需行业数据）
# ─────────────────────────────────────────────────────────────

# 雷达图展示的指标子集（选 8 个最具代表性的，覆盖四大维度）
RADAR_KEYS = [
    "gross_margin",     # 盈利
    "net_margin",       # 盈利
    "roe",              # 盈利
    "current_ratio",    # 偿债
    "debt_ratio",       # 偿债
    "asset_turnover",   # 运营
    "ar_days",          # 运营
    "pe",               # 估值（有市值时显示，否则用 roa 替代）
]
RADAR_FALLBACK = "roa"   # pe 无值时的替代指标


def health_score(key: str, value: float) -> float:
    """
    将单个指标值映射到 0-100 的健康得分。

    映射规则（基于 HEALTH_RANGES）：
      越高越好指标（higher_better=True）：
        value >= upper_ok(若有) 或 value >= lo_ok*3  → 100
        value >= lo_ok                               → 线性插值 50-100
        value >= lo_warn                             → 线性插值 20-50
        value <  lo_warn                             → 0-20

      越低越好指标（higher_better=False）：
        value <= lo_ok(若有) 或 极小值               → 100
        value <= hi_ok                               → 线性插值 50-100
        value <= hi_warn                             → 线性插值 20-50
        value >  hi_warn                             → 0-20
    """
    if value is None:
        return 50.0

    meta = METRIC_META.get(key)
    rng  = HEALTH_RANGES.get(key)
    if not meta or not rng:
        return 50.0

    _, _, higher_better = meta
    lo_warn, lo_ok, hi_ok, hi_warn = rng

    def _lerp(v, v_lo, v_hi, s_lo, s_hi):
        """线性插值，v 在 [v_lo, v_hi] 之间映射到 [s_lo, s_hi]"""
        if v_hi == v_lo:
            return (s_lo + s_hi) / 2
        t = (v - v_lo) / (v_hi - v_lo)
        t = max(0.0, min(1.0, t))
        return s_lo + t * (s_hi - s_lo)

    if higher_better:
        # 越高越好：lo_warn / lo_ok 是下限
        lw = lo_warn if lo_warn is not None else 0
        lk = lo_ok   if lo_ok   is not None else lw * 2
        # 上限：hi_ok 若有，否则用 lo_ok * 3 作为满分线
        top = hi_ok if hi_ok is not None else (lk * 3 if lk > 0 else 100)

        if value >= top:
            return 100.0
        elif value >= lk:
            return _lerp(value, lk, top, 50, 100)
        elif lo_warn is not None and value >= lw:
            return _lerp(value, lw, lk, 20, 50)
        else:
            # 低于 warn 下限
            floor = lw * 0.5 if lw > 0 else -abs(lk)
            return _lerp(value, floor, lw if lo_warn is not None else lk, 0, 20)
    else:
        # 越低越好：hi_ok / hi_warn 是上限
        hk = hi_ok   if hi_ok   is not None else float("inf")
        hw = hi_warn if hi_warn is not None else hk * 1.5

        if value <= 0:
            return 100.0
        elif hi_ok is not None and value <= hk:
            # 低于 ok 上限：满分区
            return _lerp(value, 0, hk, 100, 50)
        elif value <= hw:
            return _lerp(value, hk, hw, 50, 20)
        else:
            return _lerp(value, hw, hw * 2, 20, 0)


def radar_scores(metrics: dict, benchmarks: dict) -> dict:
    """
    计算雷达图各维度得分（0-100）。

    有对标数据时：
      越高越好指标 → 百分位（本公司值在对标公司中排第几%）
      越低越好指标 → 100 - 百分位（越低越好，排名越靠前得分越高）

    无对标数据时：
      退回 health_score() 绝对健康得分

    返回：{key: score(0-100), ...}  只包含 RADAR_KEYS 中有值的指标
    """
    result = {}

    # 确定实际展示的键（pe 无值时用 roa 替代）
    keys = []
    for k in RADAR_KEYS:
        if k == "pe" and metrics.get(k) is None:
            if metrics.get(RADAR_FALLBACK) is not None:
                keys.append(RADAR_FALLBACK)
        elif metrics.get(k) is not None:
            keys.append(k)
    keys = list(dict.fromkeys(keys))[:8]

    for k in keys:
        value = metrics.get(k)
        if value is None:
            continue

        meta = METRIC_META.get(k)
        if not meta:
            continue
        _, _, higher_better = meta

        peers = [x for x in benchmarks.get(k, []) if x is not None]

        if len(peers) >= 3:
            # ── 有对标数据：用百分位 ──────────────────────────
            pct = _percentile(peers, value)
            score = pct if higher_better else (100.0 - pct)
        else:
            # ── 无对标数据：用绝对健康分 ──────────────────────
            score = health_score(k, value)

        result[k] = round(score, 1)

    return result


# ─────────────────────────────────────────────────────────────
# 1. 财务指标计算
# ─────────────────────────────────────────────────────────────

def calculate_metrics(inputs: dict) -> dict:
    """
    根据财报基本科目计算所有财务指标。

    必填（来自财报，单位统一为万元）：
      revenue          营业收入
      cogs             营业成本
      operating_profit 营业利润
      net_profit       净利润（归母）
      total_assets     资产总计
      current_assets   流动资产合计
      current_liab     流动负债合计
      total_liab       负债合计
      equity           归母股东权益合计

    可选：
      inventory        存货（不填则速动比率 = 流动比率，存货周转天数 = None）
      ar               应收账款（不填则应收周转天数 = None）
      interest_exp     利息支出（不填则利息保障倍数 = None）
      da               折旧与摊销（不填则 EBITDA = 营业利润 估算）
      market_cap       总市值（万元，不填则 PE/PB/PS = None）

    返回：{metric_key: value_or_None, ...}
    """

    def _g(key, default=None):
        v = inputs.get(key, default)
        if v is None:
            return None
        try:
            f = float(v)
            return f if math.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    def _pct(num, denom):
        """百分比 = num/denom × 100，保留 2 位小数"""
        if num is None or denom is None or denom == 0:
            return None
        return round(num / denom * 100, 2)

    def _ratio(num, denom, places=4):
        """倍数 = num/denom，保留 places 位小数"""
        if num is None or denom is None or denom == 0:
            return None
        return round(num / denom, places)

    # ── 读取基本科目 ──────────────────────────────────────────
    rev   = _g("revenue")           # 营业收入
    cogs  = _g("cogs")              # 营业成本
    op    = _g("operating_profit")  # 营业利润
    np_   = _g("net_profit")        # 净利润（归母）
    ta    = _g("total_assets")      # 资产总计
    ca    = _g("current_assets")    # 流动资产合计
    cl    = _g("current_liab")      # 流动负债合计
    tl    = _g("total_liab")        # 负债合计
    eq    = _g("equity")            # 归母股东权益合计

    # 可选科目
    inv   = _g("inventory", 0) or 0   # 存货（默认 0）
    ar    = _g("ar", 0) or 0          # 应收账款（默认 0）
    int_e = _g("interest_exp")        # 利息支出
    da    = _g("da")                  # 折旧与摊销
    mc    = _g("market_cap")          # 总市值
    cfo   = _g("cfo")                 # 经营活动现金流净额

    # ── 派生科目 ─────────────────────────────────────────────
    # 毛利润 = 营业收入 - 营业成本
    gp = (rev - cogs) if (rev is not None and cogs is not None) else None

    # EBIT = 营业利润（口径：利润表营业利润，已扣除折旧摊销）
    # 若用户未填营业利润，用净利润 + 利息支出估算
    ebit = op
    if ebit is None and np_ is not None and int_e is not None:
        ebit = np_ + int_e

    # EBITDA = EBIT + 折旧与摊销
    # 若无 DA，用营业利润代替（偏保守，会低估）
    ebitda = None
    if ebit is not None and da is not None:
        ebitda = ebit + da
    elif ebit is not None:
        ebitda = ebit  # 无 DA 时 EBITDA ≈ EBIT（注：实际偏低）

    r = {}

    # ── 规模（绝对值） ────────────────────────────────────────
    r["revenue"]        = round(rev, 2) if rev is not None else None
    r["gross_profit"]   = round(gp,  2) if gp  is not None else None
    r["net_profit_abs"] = round(np_, 2) if np_ is not None else None

    # ── 盈利能力 ──────────────────────────────────────────────
    # 毛利率 = 毛利润 / 营业收入
    r["gross_margin"] = _pct(gp, rev)

    # 营业利润率 = 营业利润 / 营业收入
    r["operating_margin"] = _pct(op, rev)

    # 净利率 = 净利润 / 营业收入
    r["net_margin"] = _pct(np_, rev)

    # ROE = 净利润 / 归母股东权益（杜邦分析口径：期末权益，简化版）
    # 严格口径应用期初期末平均，但财报单期数据通常用期末
    r["roe"] = _pct(np_, eq)

    # ROA = 净利润 / 资产总计（期末，简化口径）
    r["roa"] = _pct(np_, ta)

    # EBITDA 利润率 = EBITDA / 营业收入
    r["ebitda_margin"] = _pct(ebitda, rev)

    # ── 偿债能力 ──────────────────────────────────────────────
    # 流动比率 = 流动资产 / 流动负债
    r["current_ratio"] = _ratio(ca, cl)

    # 速动比率 = (流动资产 - 存货) / 流动负债
    quick_assets = (ca - inv) if ca is not None else None
    r["quick_ratio"] = _ratio(quick_assets, cl)

    # 资产负债率 = 负债合计 / 资产总计
    r["debt_ratio"] = _pct(tl, ta)

    # 利息保障倍数 = EBIT / 利息支出
    # 注：利息支出为 0 时不计算（无有息负债，该指标无意义）
    if int_e and int_e > 0:
        r["interest_cover"] = _ratio(ebit, int_e)
    else:
        r["interest_cover"] = None

    # ── 运营效率 ──────────────────────────────────────────────
    # 应收账款周转天数 = 应收账款 / 营业收入 × 365
    # 口径：用营业收入（而非赊销收入，因财报通常不单独披露赊销）
    if ar and ar > 0 and rev:
        r["ar_days"] = round(ar / rev * 365, 1)
    else:
        r["ar_days"] = None

    # 存货周转天数 = 存货 / 营业成本 × 365
    # 口径：分母用营业成本（标准口径），而非营业收入
    if inv and inv > 0 and cogs and cogs > 0:
        r["inv_days"] = round(inv / cogs * 365, 1)
    else:
        r["inv_days"] = None

    # 总资产周转率 = 营业收入 / 资产总计（次/年）
    r["asset_turnover"] = _ratio(rev, ta)

    # ── 现金流质量 ────────────────────────────────────────────
    # 经营现金流/营收 = CFO / 营业收入 × 100
    r["cfo_to_revenue"]   = _pct(cfo, rev)
    # 现金含量 = CFO / 净利润（> 1 说明利润质量高）
    if cfo is not None and np_ is not None and np_ != 0:
        r["cfo_to_netprofit"] = _ratio(cfo, np_)
    else:
        r["cfo_to_netprofit"] = None

    # ── 估值（需市值）────────────────────────────────────────
    # PE = 总市值 / 净利润（TTM 口径；此处用年报净利润）
    # 净利润为负时 PE 无意义，返回 None
    if mc and np_ and np_ > 0:
        r["pe"] = _ratio(mc, np_)
    else:
        r["pe"] = None

    # PB = 总市值 / 归母股东权益
    r["pb"] = _ratio(mc, eq)

    # PS = 总市值 / 营业收入
    r["ps"] = _ratio(mc, rev)

    return r


# ─────────────────────────────────────────────────────────────
# 2. 行业代表公司代码表 + 基准数据实时拉取
# ─────────────────────────────────────────────────────────────

# 各行业代表公司（龙头 + 次龙头，5-8 家）
INDUSTRY_PEERS: dict[str, list[str]] = {
    "半导体":    ["603501","002371","688012","688981","002049","688256","600703"],
    "软件开发":  ["600588","002410","300033","688111","300496","002065","300036"],
    "计算机设备":["000977","002230","300308","002456","688041","300782"],
    "通信设备":  ["000063","002281","300308","600498","002396","300628"],
    "医疗器械":  ["300760","688271","300015","600763","002223","300677","688321"],
    "生物制品":  ["600276","300347","688180","688363","300122","002007"],
    "化学制药":  ["600276","000538","600196","002001","600436","002603"],
    "新能源":    ["300750","002594","601012","600438","002129","688599"],
    "光伏设备":  ["601012","600438","688599","002129","300274","688223","002459"],
    "储能":      ["300750","300274","002074","300014","688819","603659"],
    "汽车整车":  ["002594","600104","000625","601238","000550","601633"],
    "汽车零部件":["600741","002920","601689","002050","603799"],
    "新能源汽车":["002594","300750","601127","601633","000625"],
    "消费电子":  ["002475","000725","002241","603501","300433"],
    "家用电器":  ["000333","000651","600690","002508","002035"],
    "银行":      ["601398","601288","601988","601328","600036","601166","600016"],
    "证券":      ["600030","000776","601688","600999","601211","601901"],
    "保险":      ["601318","601628","601601","601336","600061"],
    "房地产开发":["000002","600048","001979","600606","000069","600383"],
    "建筑装饰":  ["601668","601186","601390","600970","002271","603338"],
    "食品饮料":  ["600519","000858","002304","603288","600887","002557","000895"],
    "白酒":      ["600519","000858","002304","000568","000596","603369","600809"],
    "零售":      ["601933","000759","002024","600694","002251","603708"],
    "化工":      ["600309","002648","600346","002493","000792","600028"],
    "钢铁":      ["600019","601005","000709","600808","601003","000932"],
    "有色金属":  ["600362","601600","000630","600547","601899","002460"],
    "物流":      ["002352","600233","002468","603056","002120"],
    "航空":      ["601111","600115","600029","000897","600004","600009"],
    "港口":      ["601872","600026","601919","000905","600018","000507"],
}


def fetch_industry_benchmarks(industry_name: str = "",
                               peer_codes: list = None) -> dict:
    """
    获取行业基准数据，两条明确路径：

    路径 A（选择行业）：
      传入 industry_name，从 INDUSTRY_PEERS 查出代码，实时拉取最新财务数据。

    路径 B（指定对标公司）：
      传入 peer_codes（如 ["600519", "000858"]），实时拉取这些公司的数据。

    返回：{metric_key: [values...], ...}  以及  peer_names: {code: name}
    """
    import requests

    empty: dict[str, list] = {k: [] for k in METRIC_META}

    codes_to_fetch: list[str] = []

    # ── 路径 B：指定股票代码 ──────────────────────────────────
    if peer_codes:
        codes_to_fetch = list(peer_codes)

    # ── 路径 A：行业名称 → 代码表 ────────────────────────────
    elif industry_name and industry_name in INDUSTRY_PEERS:
        codes_to_fetch = INDUSTRY_PEERS[industry_name]
        _log.info("行业基准（实时）：%s，%d 家公司", industry_name, len(codes_to_fetch))

    if not codes_to_fetch:
        return empty

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.eastmoney.com/",
    })
    benchmarks: dict[str, list] = {k: [] for k in METRIC_META}
    _fetch_by_codes(sess, codes_to_fetch, benchmarks)
    return benchmarks


def _search_bk_code(sess, industry_name: str) -> str:
    """通过行业名称搜索东方财富板块代码"""
    # 尝试多个备用域名
    _BK_URLS = [
        ("https://push2ex.eastmoney.com/getTopicList"
         "?ut=bd1d9ddb04089700cf9c27f6f7426281&dpt=wbkzb&Pageindex=0&pagesize=200"
         "&js=var+IS_TOPIC_LIST&type=0"),
        ("https://push2.eastmoney.com/api/qt/clist/get"
         "?pn=1&pz=200&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
         "&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14"),
    ]
    for url in _BK_URLS:
        try:
            r = sess.get(url, timeout=8)
            body = r.json()
            # push2ex 格式
            diff = (body.get("data") or {}).get("diff") or body.get("diff") or []
            if not diff:
                # push2 格式
                diff = (body.get("data") or {}).get("diff") or []
            for item in diff:
                name = item.get("f14") or item.get("name", "")
                if industry_name[:3] in name or name[:3] in industry_name:
                    code = item.get("f12") or item.get("code", "")
                    _log.info("行业匹配：%s → %s", industry_name, code)
                    return code
        except Exception as e:
            _log.warning("_search_bk_code(%s) failed: %s", url[:40], e)
    return ""


def _fetch_bk_member_codes(sess, bk_code: str, limit: int) -> list:
    """拉取板块成分股代码列表"""
    try:
        url = (
            f"https://push2.eastmoney.com/api/qt/clist/get"
            f"?pn=1&pz={limit}&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
            f"&fltt=2&invt=2&fid=f20&fs=b:{bk_code}"
            f"&fields=f12,f13"
        )
        r = sess.get(url, timeout=10)
        diff = r.json().get("data", {}).get("diff") or []
        # f12=代码, f13=市场(1=上海,0=深圳)
        codes = []
        for item in diff:
            code = str(item.get("f12", "")).zfill(6)
            mkt  = item.get("f13", 0)
            codes.append(f"{'SH' if mkt == 1 else 'SZ'}{code}")
        return codes
    except Exception as e:
        _log.warning("_fetch_bk_member_codes failed: %s", e)
        return []


def _fetch_by_codes(sess, codes: list, benchmarks: dict):
    """
    批量拉取指定股票代码的财务指标（东方财富 datacenter 接口）。
    每次最多 50 个，自动分批。
    """
    # 将代码统一为东方财富格式：600519.SH / 000858.SZ
    def _fmt(code: str) -> str:
        code = code.strip().upper()
        # 已带市场后缀
        if "." in code:
            return code
        # 纯数字：A 股
        if code.isdigit():
            c = code.zfill(6)
            return f"{c}.{'SH' if c.startswith(('6', '9')) else 'SZ'}"
        # 港股 / 美股 直接返回
        return code

    fmt_codes = [_fmt(c) for c in codes if c]

    # 分批（每批 50 个）
    batch_size = 50
    for i in range(0, len(fmt_codes), batch_size):
        batch = fmt_codes[i: i + batch_size]
        _fetch_fin_batch(sess, batch, benchmarks)


def _fetch_fin_batch(sess, codes: list, benchmarks: dict):
    """
    批量拉取财务指标，填充 benchmarks。

    东方财富 datacenter 接口已改版，原字段名失效。
    现改用三个报表组合拉取，并自行计算派生比率：

      RPT_DMSK_FN_BALANCE  → CURRENT_RATIO, DEBT_ASSET_RATIO,
                              TOTAL_ASSETS, INVENTORY, ACCOUNTS_RECE
      RPT_DMSK_FN_INCOME   → TOTAL_OPERATE_INCOME, OPERATE_COST,
                              OPERATE_PROFIT, PARENT_NETPROFIT
      RPT_LICO_FN_CPD      → XSMLL(毛利率%), WEIGHTAVG_ROE(ROE%)

    派生计算：
      net_margin      = PARENT_NETPROFIT / TOTAL_OPERATE_INCOME × 100
      operating_margin= OPERATE_PROFIT   / TOTAL_OPERATE_INCOME × 100
      roa             = PARENT_NETPROFIT / TOTAL_ASSETS × 100
      asset_turnover  = TOTAL_OPERATE_INCOME / TOTAL_ASSETS
      ar_days         = ACCOUNTS_RECE / TOTAL_OPERATE_INCOME × 365
      inv_days        = INVENTORY / OPERATE_COST × 365
    """
    BASE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    HEADERS  = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://data.eastmoney.com/",
    }

    def _safe_float(v):
        try:
            f = float(v)
            return f if math.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    def _classify_code(c: str):
        """
        识别股票代码市场类型，返回 (pure_code, secucode, market)
        market: 'A' | 'HK'
        A 股：600519 -> 600519.SH，000001 -> 000001.SZ
        港股：00700 / 700 / 00700.HK -> 00700.HK
        """
        c = c.strip().upper()
        # 已带后缀
        if c.endswith(".HK"):
            num = c[:-3].zfill(5)
            return num, f"{num}.HK", "HK"
        if "." in c:
            # 已是 A 股 SECUCODE 格式
            num = c.split(".")[0].zfill(6)
            return num, c, "A"
        # 纯数字：港股通常 5 位以内，A 股 6 位
        digits = c.lstrip("0") or "0"
        if len(c) <= 5 or (len(c) == 6 and c.startswith("0") and int(digits) <= 9999):
            # 港股：补零到 5 位
            num = c.zfill(5)
            return num, f"{num}.HK", "HK"
        # A 股
        num = c.zfill(6)
        suffix = "SH" if num.startswith(("6", "9")) else "SZ"
        return num, f"{num}.{suffix}", "A"

    def _fetch_report(report_name, columns, secucode_list, sort_col="REPORT_DATE"):
        """拉取单个报表，返回 {pure_code: row_dict}，每家公司取最新一条"""
        if not secucode_list:
            return {}
        cols = columns if "SECUCODE" in columns else "SECUCODE," + columns
        code_str = ",".join(f'"{c}"' for c in secucode_list)
        params = {
            "reportName":  report_name,
            "columns":     cols,
            "filter":      f"(SECUCODE in ({code_str}))",
            "pageNumber":  "1",
            "pageSize":    str(len(secucode_list) * 2),
            "sortColumns": sort_col,
            "sortTypes":   "-1",
            "source":      "WEB",
            "client":      "WEB",
        }
        try:
            r = sess.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
            rows = (r.json().get("result") or {}).get("data") or []
            result = {}
            for row in rows:
                sc = str(row.get("SECUCODE") or "")
                # A 股 key 用 6 位纯数字；港股 key 用 5 位纯数字
                if sc.endswith(".HK"):
                    key = sc[:-3].zfill(5)
                else:
                    key = str(row.get("SECURITY_CODE") or sc.split(".")[0]).zfill(6)
                if key not in result:
                    result[key] = row
            return result
        except Exception as e:
            _log.warning("_fetch_report(%s) failed: %s", report_name, e)
            return {}

    def _fetch_hk_report(report_name, columns, hk_secucodes, sort_col="REPORT_DATE"):
        """港股专用：同接口但 filter 用 SECUCODE in (...) 港股格式"""
        return _fetch_report(report_name, columns, hk_secucodes, sort_col)

    # 分类：A 股 / 港股
    a_codes:  list[tuple] = []   # (pure, secucode)
    hk_codes: list[tuple] = []   # (pure, secucode)
    for c in codes:
        pure, sc, mkt = _classify_code(c)
        if mkt == "HK":
            hk_codes.append((pure, sc))
        else:
            a_codes.append((pure, sc))

    a_secucodes  = [sc for _, sc in a_codes]
    hk_secucodes = [sc for _, sc in hk_codes]

    # ── A 股：拉取三个报表 ────────────────────────────────────
    balance_data = _fetch_report(
        "RPT_DMSK_FN_BALANCE",
        "SECUCODE,SECURITY_CODE,REPORT_DATE,CURRENT_RATIO,DEBT_ASSET_RATIO,"
        "TOTAL_ASSETS,TOTAL_LIABILITIES,TOTAL_EQUITY,INVENTORY,ACCOUNTS_RECE",
        a_secucodes,
    )
    income_data = _fetch_report(
        "RPT_DMSK_FN_INCOME",
        "SECUCODE,SECURITY_CODE,REPORT_DATE,TOTAL_OPERATE_INCOME,OPERATE_COST,"
        "OPERATE_PROFIT,PARENT_NETPROFIT",
        a_secucodes,
    )
    cpd_data = _fetch_report(
        "RPT_LICO_FN_CPD",
        "SECUCODE,SECURITY_CODE,REPORTDATE,XSMLL,WEIGHTAVG_ROE",
        a_secucodes,
        sort_col="REPORTDATE",
    )

    # ── 港股：拉取三个报表（同接口，SECUCODE 格式为 00700.HK）────
    hk_balance = _fetch_hk_report(
        "RPT_DMSK_FN_BALANCE",
        "SECUCODE,SECURITY_CODE,REPORT_DATE,CURRENT_RATIO,DEBT_ASSET_RATIO,"
        "TOTAL_ASSETS,TOTAL_LIABILITIES,TOTAL_EQUITY,INVENTORY,ACCOUNTS_RECE",
        hk_secucodes,
    )
    hk_income = _fetch_hk_report(
        "RPT_DMSK_FN_INCOME",
        "SECUCODE,SECURITY_CODE,REPORT_DATE,TOTAL_OPERATE_INCOME,OPERATE_COST,"
        "OPERATE_PROFIT,PARENT_NETPROFIT",
        hk_secucodes,
    )
    hk_cpd = _fetch_hk_report(
        "RPT_LICO_FN_CPD",
        "SECUCODE,SECURITY_CODE,REPORTDATE,XSMLL,WEIGHTAVG_ROE",
        hk_secucodes,
        sort_col="REPORTDATE",
    )

    # _peer_rows: [{code, name, metric_key: value, ...}, ...]  供表格展示
    if "_peer_rows" not in benchmarks:
        benchmarks["_peer_rows"] = []

    def _pct(num, denom):
        if num is None or denom is None or denom == 0:
            return None
        v = num / denom * 100
        return v if math.isfinite(v) else None

    def _ratio(num, denom):
        if num is None or denom is None or denom == 0:
            return None
        v = num / denom
        return v if math.isfinite(v) else None

    def _fmt_date(raw) -> str:
        """将 '2026-03-31 00:00:00' 格式化为 '2026-03-31'"""
        if not raw:
            return ""
        return str(raw)[:10]

    # 合并 A 股 + 港股代码列表统一处理
    all_codes = [(pure, "A") for pure, _ in a_codes] + [(pure, "HK") for pure, _ in hk_codes]

    loaded = 0
    for code, mkt in all_codes:
        if mkt == "HK":
            bal = hk_balance.get(code, {})
            inc = hk_income.get(code, {})
            cpd = hk_cpd.get(code, {})
            source_label = "东方财富·港股"
        else:
            bal = balance_data.get(code, {})
            inc = income_data.get(code, {})
            cpd = cpd_data.get(code, {})
            source_label = "东方财富·A股"

        # 公司名称：用 SECUCODE 值（如 600519.SH / 00700.HK）
        secucode_val = (bal.get("SECUCODE") or inc.get("SECUCODE")
                        or cpd.get("SECUCODE") or f"{code}.??")
        name = secucode_val

        # 报告期（优先取资产负债表日期）
        report_date = _fmt_date(
            bal.get("REPORT_DATE") or inc.get("REPORT_DATE")
            or cpd.get("REPORTDATE") or ""
        )

        # ── 直接字段 ──────────────────────────────────────────
        # CURRENT_RATIO：API 返回的是"倍数 × 100"（如 706 表示 7.06 倍）
        _cr_raw       = _safe_float(bal.get("CURRENT_RATIO"))
        current_ratio = (_cr_raw / 100.0) if _cr_raw is not None else None
        debt_ratio    = _safe_float(bal.get("DEBT_ASSET_RATIO"))
        total_assets  = _safe_float(bal.get("TOTAL_ASSETS"))
        inventory     = _safe_float(bal.get("INVENTORY"))
        ar            = _safe_float(bal.get("ACCOUNTS_RECE"))

        revenue    = _safe_float(inc.get("TOTAL_OPERATE_INCOME"))
        cogs       = _safe_float(inc.get("OPERATE_COST"))
        op_profit  = _safe_float(inc.get("OPERATE_PROFIT"))
        net_profit = _safe_float(inc.get("PARENT_NETPROFIT"))

        gross_margin = _safe_float(cpd.get("XSMLL"))
        roe          = _safe_float(cpd.get("WEIGHTAVG_ROE"))

        # ── 派生计算 ──────────────────────────────────────────
        gross_profit     = (revenue - cogs) if (revenue and cogs) else None
        net_margin       = _pct(net_profit, revenue)
        operating_margin = _pct(op_profit,  revenue)
        roa              = _pct(net_profit, total_assets)
        asset_turnover   = _ratio(revenue,  total_assets)
        ar_days  = (_ratio(ar, revenue) * 365) if (ar and revenue) else None
        inv_days = (_ratio(inventory, cogs) * 365) if (inventory and cogs) else None

        # ── 写入 benchmarks（聚合列表） ───────────────────────
        def _append(key, val):
            if val is not None and math.isfinite(val):
                benchmarks[key].append(round(val, 4))

        # 规模（万元，接口单位为元，需 ÷ 10000）
        rev_wan = round(revenue / 10000, 2)      if revenue      else None
        gp_wan  = round(gross_profit / 10000, 2) if gross_profit else None
        np_wan  = round(net_profit / 10000, 2)   if net_profit   else None
        _append("revenue",        rev_wan)
        _append("gross_profit",   gp_wan)
        _append("net_profit_abs", np_wan)

        _append("gross_margin",     gross_margin)
        _append("operating_margin", operating_margin)
        _append("net_margin",       net_margin)
        _append("roe",              roe)
        _append("roa",              roa)
        _append("current_ratio",    current_ratio)
        _append("debt_ratio",       debt_ratio)
        _append("asset_turnover",   asset_turnover)
        _append("ar_days",          ar_days)
        _append("inv_days",         inv_days)

        # ── 写入 _peer_rows（逐行，供表格） ───────────────────
        row: dict = {
            "_code":        code,
            "_name":        name,
            "_report_date": report_date,   # 数据时间
            "_source":      source_label,  # 数据来源
        }
        row["revenue"]          = rev_wan
        row["gross_profit"]     = gp_wan
        row["net_profit_abs"]   = np_wan
        row["gross_margin"]     = round(gross_margin, 2)     if gross_margin     is not None else None
        row["operating_margin"] = round(operating_margin, 2) if operating_margin is not None else None
        row["net_margin"]       = round(net_margin, 2)       if net_margin       is not None else None
        row["roe"]              = round(roe, 2)              if roe              is not None else None
        row["roa"]              = round(roa, 2)              if roa              is not None else None
        row["current_ratio"]    = round(current_ratio, 2)   if current_ratio    is not None else None
        row["debt_ratio"]       = round(debt_ratio, 2)       if debt_ratio       is not None else None
        row["asset_turnover"]   = round(asset_turnover, 3)  if asset_turnover   is not None else None
        row["ar_days"]          = round(ar_days, 1)          if ar_days          is not None else None
        row["inv_days"]         = round(inv_days, 1)         if inv_days         is not None else None
        # PE/PB/PS 先占位，后面批量拉行情后填充
        row["pe"] = None
        row["pb"] = None
        row["ps"] = None
        benchmarks["_peer_rows"].append(row)

        if any(v is not None for v in [gross_margin, roe, current_ratio, debt_ratio]):
            loaded += 1

    _log.info("_fetch_fin_batch: %d/%d 家公司数据已加载", loaded, len(all_codes))

    # ── 批量拉取实时行情，补充 PE/PB/PS ──────────────────────
    _fetch_valuation_batch(sess, benchmarks)


# ─────────────────────────────────────────────────────────────
# 2.5 实时行情补充：PE / PB / PS
# ─────────────────────────────────────────────────────────────

def _fetch_valuation_batch(sess, benchmarks: dict):
    """
    对 benchmarks["_peer_rows"] 里的每家公司，逐个调用
    push2.eastmoney.com/api/qt/stock/get（与 analytics._fetch_spot 完全一致），
    字段：
      f162 = 市盈率 TTM（×100）
      f163 = 市净率 PB（×100）
      f164 = 市销率 PS（×100）
      f116 = 总市值（元，未放大）
      f58  = 公司名称
    写回 row["pe/pb/ps/_market_cap_wan"] 及 benchmarks 聚合列表。
    """
    peer_rows = benchmarks.get("_peer_rows", [])
    if not peer_rows:
        return

    # fltt=2 时接口直接返回真实值，无需 ÷100
    def _p(v):
        try:
            f = float(v)
            if not math.isfinite(f) or f == 0:
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    def _raw(v):
        try:
            f = float(v)
            return f if math.isfinite(f) and f > 0 else None
        except (TypeError, ValueError):
            return None

    # 构造 secid：A 股 1.600519 / 0.000858，港股 116.00700
    def _to_secid(code: str) -> str:
        code = code.strip().upper()
        if code.endswith(".HK") or (len(code) <= 5 and code.isdigit()):
            return f"116.{code.replace('.HK','').zfill(5)}"
        num = code.zfill(6)
        return f"{'1' if num.startswith(('6','9')) else '0'}.{num}"

    # 复用 analytics._SESSION（带重试机制），比裸 sess 更稳定
    try:
        from analytics import _SESSION as _ana_sess, _make_session as _ana_make
    except Exception:
        _ana_sess = sess
        _ana_make = None

    def _ana_get(url: str) -> dict:
        nonlocal _ana_sess
        try:
            return _ana_sess.get(url, timeout=10).json().get("data") or {}
        except Exception:
            # session 断了就重建再试一次
            if _ana_make:
                _ana_sess = _ana_make()
            try:
                return _ana_sess.get(url, timeout=10).json().get("data") or {}
            except Exception:
                return {}

    _FIELDS = "f58,f116,f162,f163,f164"
    ok = 0
    for row in peer_rows:
        secid = _to_secid(row["_code"])
        try:
            url = (
                "https://push2.eastmoney.com/api/qt/stock/get"
                f"?fltt=2&secid={secid}&fields={_FIELDS}"
            )
            d = _ana_get(url)

            # 更新公司真实名称
            real_name = d.get("f58") or ""
            if real_name:
                row["_name"] = real_name

            pe = _p(d.get("f162"))   # PE-TTM
            pb = _p(d.get("f163"))   # PB
            ps = _p(d.get("f164"))   # PS

            # 总市值（元 → 万元）
            mc_yuan = _raw(d.get("f116"))
            mc_wan  = round(mc_yuan / 10000, 2) if mc_yuan else None

            row["pe"] = pe
            row["pb"] = pb
            row["ps"] = ps
            row["_market_cap_wan"] = mc_wan

            # 写入聚合列表
            for key, val in [("pe", pe), ("pb", pb), ("ps", ps)]:
                if val is not None:
                    benchmarks[key].append(val)

            _log.debug("valuation %s: pe=%s pb=%s ps=%s mc_wan=%s", secid, pe, pb, ps, mc_wan)
            ok += 1
        except Exception as e:
            _log.warning("_fetch_valuation_batch %s failed: %s", secid, e)

    _log.info("_fetch_valuation_batch: PE/PB/PS 补充完成 %d/%d 家", ok, len(peer_rows))


# ─────────────────────────────────────────────────────────────
# 3. 百分位计算
# ─────────────────────────────────────────────────────────────

def _percentile(data: list, value: float) -> float:
    """
    计算 value 在 data 中的百分位（0–100）。
    定义：严格小于 value 的比例 × 100。
    空列表返回 50（中性值）。
    """
    if not data:
        return 50.0
    below = sum(1 for x in data if x < value)
    return round(below / len(data) * 100, 1)


# ─────────────────────────────────────────────────────────────
# 4. 比对分析
# ─────────────────────────────────────────────────────────────

def analyze_vs_industry(metrics: dict, benchmarks: dict) -> dict:
    """
    将计算出的指标与行业基准比对，输出分析结果。

    返回：{
        metric_key: {
            "value":         float,
            "display_name":  str,
            "unit":          str,
            "higher_better": bool,
            "median":        float | None,
            "mean":          float | None,
            "p25":           float | None,
            "p75":           float | None,
            "percentile":    float | None,
            "judgment":      str,
            "detail":        str,
            "peers_n":       int,
        }
    }
    """
    result = {}

    for key, value in metrics.items():
        if value is None:
            continue
        meta = METRIC_META.get(key)
        if not meta:
            continue
        display_name, unit, higher_better = meta

        peers = [x for x in benchmarks.get(key, []) if x is not None]
        peers_n = len(peers)

        # 统计量
        median = round(statistics.median(peers), 4) if peers else None
        mean   = round(statistics.mean(peers),   4) if peers else None
        p25    = round(sorted(peers)[int(len(peers) * 0.25)], 4) if peers else None
        p75    = round(sorted(peers)[int(len(peers) * 0.75)], 4) if peers else None
        pct    = _percentile(peers, value) if peers else None

        judgment = "正常"
        detail   = ""

        if peers and pct is not None:
            # ── 有行业数据：用百分位判断 ──────────────────────
            if higher_better:
                if pct >= 80:
                    judgment = "偏高（优秀）"
                    detail = f"高于 {pct:.0f}% 的同行，表现优秀"
                elif pct >= 50:
                    judgment = "正常"
                    detail = f"高于 {pct:.0f}% 的同行，处于中等偏上水平"
                elif pct >= 20:
                    judgment = "偏低"
                    detail = f"仅高于 {pct:.0f}% 的同行，低于行业中位数"
                else:
                    judgment = "偏低（需关注）"
                    detail = f"仅高于 {pct:.0f}% 的同行，显著低于行业水平"
            else:
                # 越低越好
                if pct <= 20:
                    judgment = "偏低（优秀）"
                    detail = f"低于 {100 - pct:.0f}% 的同行，控制良好"
                elif pct <= 50:
                    judgment = "正常"
                    detail = f"低于 {100 - pct:.0f}% 的同行，处于中等偏优水平"
                elif pct <= 80:
                    judgment = "偏高"
                    detail = f"高于 {pct:.0f}% 的同行，高于行业中位数"
                else:
                    judgment = "偏高（需关注）"
                    detail = f"高于 {pct:.0f}% 的同行，显著高于行业水平"
        else:
            # ── 无行业数据：用绝对区间判断 ────────────────────
            rng = HEALTH_RANGES.get(key)
            if rng:
                lo_warn, lo_ok, hi_ok, hi_warn = rng
                if hi_warn is not None and value > hi_warn:
                    judgment = "极高（需关注）"
                    detail = f"超过警戒上限 {hi_warn}{unit}"
                elif hi_ok is not None and value > hi_ok:
                    judgment = "偏高"
                    detail = f"高于参考上限 {hi_ok}{unit}"
                elif lo_warn is not None and value < lo_warn:
                    judgment = "极低（需关注）"
                    detail = f"低于警戒下限 {lo_warn}{unit}"
                elif lo_ok is not None and value < lo_ok:
                    judgment = "偏低"
                    detail = f"低于参考下限 {lo_ok}{unit}"
                else:
                    judgment = "正常"
                    detail = "处于参考区间内"

        result[key] = {
            "value":         value,
            "display_name":  display_name,
            "unit":          unit,
            "higher_better": higher_better,
            "median":        median,
            "mean":          mean,
            "p25":           p25,
            "p75":           p75,
            "percentile":    pct,
            "judgment":      judgment,
            "detail":        detail,
            "peers_n":       peers_n,
        }

    return result


# ─────────────────────────────────────────────────────────────
# 5. 主入口
# ─────────────────────────────────────────────────────────────

def run_analysis(inputs: dict,
                 industry_name: str = "",
                 peer_codes: list = None) -> dict:
    """
    完整分析流程：计算指标 → 拉取行业基准 → 比对分析。

    peer_codes 优先级高于 industry_name / bk_code。

    返回：{
        "metrics":    {key: value},
        "benchmarks": {key: [values]},
        "analysis":   {key: {...}},
        "groups":     METRIC_GROUPS,
        "industry":   str,
        "peer_codes": list,
        "error":      str | None,
    }
    """
    result = {
        "inputs":     inputs,          # 原始输入，供 CSV 导出使用
        "metrics":    {},
        "benchmarks": {},
        "analysis":   {},
        "groups":     METRIC_GROUPS,
        "industry":   industry_name,
        "peer_codes": peer_codes or [],
        "error":      None,
    }

    try:
        result["metrics"] = calculate_metrics(inputs)
    except Exception as e:
        result["error"] = f"指标计算失败：{e}"
        return result

    try:
        result["benchmarks"] = fetch_industry_benchmarks(
            industry_name=industry_name,
            peer_codes=peer_codes,
        )
    except Exception as e:
        _log.warning("fetch_industry_benchmarks error: %s", e)
        result["benchmarks"] = {k: [] for k in METRIC_META}

    try:
        result["analysis"] = analyze_vs_industry(
            result["metrics"], result["benchmarks"]
        )
    except Exception as e:
        result["error"] = f"比对分析失败：{e}"

    return result
