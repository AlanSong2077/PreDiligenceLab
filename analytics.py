"""
analytics.py  —  股票行情分析模块
数据源优先级：东方财富 API（push2.eastmoney.com / push2his.eastmoney.com）
             → 失败自动 fallback 到 yfinance（雅虎财经）
支持 美股 / 港股 / A股，内置重试机制
"""

import math
import datetime
import time
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────

PERIODS = {
    "7天":   7,
    "30天":  30,
    "90天":  90,
    "180天": 180,
    "360天": 360,
}

# 东方财富市场代码
# A股上交所=1, 深交所=0, 港股=116, 美股=105(纳斯达克)/106(纽交所)/107(美交所)
_EMF_MARKET_CN_SH = "1"
_EMF_MARKET_CN_SZ = "0"
_EMF_MARKET_HK    = "116"
_EMF_MARKET_US    = "105"   # 先试105，失败再试106/107

# K线字段：日期,开,收,高,低,成交量(手),成交额,振幅,涨跌幅,涨跌额,换手率
_KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"

# 实时快照字段
_SPOT_FIELDS = (
    "f43,f44,f45,f46,f47,f48,"   # 最新价,最高,最低,今开,成交量,成交额
    "f57,f58,"                    # 代码,名称
    "f116,f117,"                  # 总市值,流通市值
    "f162,f163,f164,"             # 市盈率TTM,市净率,市销率
    "f168,f169,f170,f171,"        # 换手率,涨跌额,涨跌幅%,振幅%
    "f60,f71,"                    # 昨收,均价
    "f191,f192,"                  # 委比,委差
    "f177,f178"                   # 52周最高,52周最低
)

# 东方财富连通性缓存：None=未知, True=可用, False=不可用
import threading as _threading
_EMF_AVAILABLE: bool | None = None
_EMF_CHECK_TS: float = 0.0
_EMF_CHECK_TTL: float = 120.0   # 2分钟内不重复探测
_EMF_LOCK = _threading.Lock()   # 保护并发写入


# ─────────────────────────────────────────────────────────────
# HTTP Session（带重试）
# ─────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://",  adapter)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.eastmoney.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


_SESSION = _make_session()


def _get(url: str, timeout: int = 5) -> dict:
    """GET 请求，返回 JSON dict，失败返回 {}"""
    global _SESSION
    try:
        r = _SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        # 重建 session 再试一次
        _SESSION = _make_session()
        try:
            r = _SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}


def _emf_reachable() -> bool:
    """
    快速探测东方财富接口是否可达（带缓存，2分钟内只探测一次，线程安全）。
    用一个轻量请求（茅台快照）判断，超时 4s 即认为不可达。
    """
    global _EMF_AVAILABLE, _EMF_CHECK_TS
    now = time.time()
    # 先不加锁读一次，大多数情况下缓存命中直接返回
    if _EMF_AVAILABLE is not None and (now - _EMF_CHECK_TS) < _EMF_CHECK_TTL:
        return _EMF_AVAILABLE

    with _EMF_LOCK:
        # 加锁后再检查一次，防止多线程同时探测
        now = time.time()
        if _EMF_AVAILABLE is not None and (now - _EMF_CHECK_TS) < _EMF_CHECK_TTL:
            return _EMF_AVAILABLE

        probe_url = (
            "https://push2.eastmoney.com/api/qt/stock/get"
            "?secid=1.600519&fields=f43"
        )
        try:
            r = requests.get(probe_url, timeout=4, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.eastmoney.com/",
            })
            data = r.json().get("data") or {}
            _EMF_AVAILABLE = data.get("f43") is not None
        except Exception:
            _EMF_AVAILABLE = False

        _EMF_CHECK_TS = now
        return _EMF_AVAILABLE


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────

def _to_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _emf_price(v) -> float | None:
    """东方财富价格字段除以100"""
    f = _to_float(v)
    return round(f / 100, 4) if f is not None else None


def _pct_change(start, end) -> float | None:
    if start and end and start != 0:
        return round((end - start) / abs(start) * 100, 2)
    return None


# ─────────────────────────────────────────────────────────────
# 区间统计（通用，东方财富和 yfinance 共用）
# ─────────────────────────────────────────────────────────────

def _period_stats(df: pd.DataFrame, days: int) -> dict:
    if df is None or df.empty:
        return {}
    sub = df.tail(days)
    if sub.empty:
        return {}

    close  = sub["Close"]
    volume = sub["Volume"] if "Volume" in sub.columns else None
    high   = sub["High"]
    low    = sub["Low"]

    start_price = float(close.iloc[0])
    end_price   = float(close.iloc[-1])
    pct         = _pct_change(start_price, end_price)

    # 年化波动率 = 日收益率标准差 × √252
    daily_std = float(close.pct_change().std())
    ann_vol   = round(daily_std * (252 ** 0.5) * 100, 2)

    result = {
        "start_price":  round(start_price, 4),
        "end_price":    round(end_price, 4),
        "pct_change":   pct,
        "period_high":  round(float(high.max()), 4),
        "period_low":   round(float(low.min()), 4),
        "volatility":   ann_vol,   # 年化波动率（%）
    }

    if volume is not None and not volume.empty:
        result["avg_volume"]   = int(volume.mean())
        result["total_volume"] = int(volume.sum())
        result["max_volume"]   = int(volume.max())

    daily_ret = close.pct_change().dropna()
    result["up_days"]   = int((daily_ret > 0).sum())
    result["down_days"] = int((daily_ret < 0).sum())

    return result


# ─────────────────────────────────────────────────────────────
# 东方财富 K线 → DataFrame
# ─────────────────────────────────────────────────────────────

def _fetch_kline(secid: str, start: str = "20230101") -> pd.DataFrame | None:
    """
    secid: 如 "1.600584" / "116.00700" / "105.AAPL"
    start: YYYYMMDD
    返回 DataFrame(Date, Open, Close, High, Low, Volume, Turnover, PctChange, TurnoverRate)
    """
    end = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y%m%d")
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2={_KLINE_FIELDS2}"
        f"&klt=101&fqt=1&beg={start}&end={end}"
    )
    data = _get(url).get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        return None

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            rows.append({
                "Date":         parts[0],
                "Open":         float(parts[1]),
                "Close":        float(parts[2]),
                "High":         float(parts[3]),
                "Low":          float(parts[4]),
                "Volume":       float(parts[5]),   # 手
                "Turnover":     float(parts[6]),   # 元
                "Amplitude":    float(parts[7]) if len(parts) > 7 else None,
                "PctChange":    float(parts[8]) if len(parts) > 8 else None,
                "PctChangeAmt": float(parts[9]) if len(parts) > 9 else None,
                "TurnoverRate": float(parts[10]) if len(parts) > 10 else None,
            })
        except (ValueError, IndexError):
            continue

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    return df


# ─────────────────────────────────────────────────────────────
# 东方财富 实时快照
# ─────────────────────────────────────────────────────────────

def _fetch_spot(secid: str) -> dict:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields={_SPOT_FIELDS}"
    )
    return _get(url).get("data") or {}


def _parse_spot(d: dict) -> dict:
    """
    把东方财富 spot 字段映射为标准 snapshot dict。
    东方财富所有数值字段均放大了100倍存储，需统一除以100。
    """
    def p(v, extra_div=1):
        """除以100（价格放大）再除以 extra_div"""
        f = _to_float(v)
        if f is None:
            return None
        result = round(f / 100 / extra_div, 6)
        # 过滤无效极值
        if abs(result) > 1e12 or math.isnan(result):
            return None
        return result

    def raw(v):
        """不除以100的原始值（成交量、市值等）"""
        f = _to_float(v)
        if f is None:
            return None
        if abs(f) > 1e18 or math.isnan(f):
            return None
        return f

    snap = {}
    # 价格类（÷100）
    snap["current_price"]  = p(d.get("f43"))
    snap["52w_high"]       = p(d.get("f177"))
    snap["52w_low"]        = p(d.get("f178"))
    snap["high"]           = p(d.get("f44"))
    snap["low"]            = p(d.get("f45"))
    snap["open"]           = p(d.get("f46"))
    snap["prev_close"]     = p(d.get("f60"))
    snap["change_amt"]     = p(d.get("f169"))

    # 百分比类（÷100，结果为 % 数值，如 2.35 表示 2.35%）
    snap["change_pct"]     = p(d.get("f170"))   # 涨跌幅 %
    snap["turnover_rate"]  = p(d.get("f168"))   # 换手率 %
    snap["amplitude"]      = p(d.get("f171"))   # 振幅 %

    # 估值倍数（÷100）
    snap["pe_ttm"]         = p(d.get("f162"))
    snap["pb"]             = p(d.get("f163"))
    snap["price_to_sales"] = p(d.get("f164"))

    # 成交量/市值（原始值，单位：手/元）
    snap["volume"]         = raw(d.get("f47"))
    snap["turnover"]       = raw(d.get("f48"))
    snap["market_cap"]     = raw(d.get("f116"))
    snap["float_cap"]      = raw(d.get("f117"))

    # 估值为 0 视为无数据
    for k in ("pe_ttm", "pb", "price_to_sales"):
        if snap.get(k) == 0.0:
            snap[k] = None

    return snap


# ─────────────────────────────────────────────────────────────
# yfinance fallback — 统一转换为与东方财富相同的 snapshot/df 格式
# ─────────────────────────────────────────────────────────────

def _yf_ticker(code: str, market: str) -> str:
    """把内部代码转换为 yfinance ticker 格式"""
    if market == "US":
        return code.upper()
    if market == "HK":
        # 港股：补零到4位 + .HK（yfinance 用4位）
        return code.lstrip("0").zfill(4) + ".HK"
    # CN A股：6开头→上交所.SS，其余→深交所.SZ
    if code.startswith(("6", "5", "9")):
        return code + ".SS"
    return code + ".SZ"


def _yf_snapshot(info: dict) -> dict:
    """把 yfinance info dict 转换为标准 snapshot dict"""
    def safe(v):
        f = _to_float(v)
        return f if f and abs(f) < 1e15 else None

    snap = {}
    snap["current_price"]  = safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    snap["52w_high"]       = safe(info.get("fiftyTwoWeekHigh"))
    snap["52w_low"]        = safe(info.get("fiftyTwoWeekLow"))
    snap["high"]           = safe(info.get("dayHigh") or info.get("regularMarketDayHigh"))
    snap["low"]            = safe(info.get("dayLow") or info.get("regularMarketDayLow"))
    snap["open"]           = safe(info.get("open") or info.get("regularMarketOpen"))
    snap["prev_close"]     = safe(info.get("previousClose") or info.get("regularMarketPreviousClose"))

    # 涨跌幅：yfinance 给的是小数（0.0235 = 2.35%），转成百分比数值
    chg = safe(info.get("regularMarketChangePercent"))
    snap["change_pct"]     = round(chg * 100, 2) if chg is not None else None

    snap["pe_ttm"]         = safe(info.get("trailingPE"))
    snap["pb"]             = safe(info.get("priceToBook"))
    snap["price_to_sales"] = safe(info.get("priceToSalesTrailing12Months"))

    snap["market_cap"]     = safe(info.get("marketCap"))
    snap["float_cap"]      = safe(info.get("floatShares"))   # 流通股数，非市值，仅作参考
    snap["volume"]         = safe(info.get("volume") or info.get("regularMarketVolume"))
    snap["turnover"]       = None   # yfinance 不直接给成交额

    # 额外财务指标（东方财富没有，yfinance 独有）
    snap["trailing_pe"]    = safe(info.get("trailingPE"))
    snap["forward_pe"]     = safe(info.get("forwardPE"))
    snap["ev_ebitda"]      = safe(info.get("enterpriseToEbitda"))
    snap["total_revenue"]  = safe(info.get("totalRevenue"))
    snap["eps_ttm"]        = safe(info.get("trailingEps"))
    snap["roe"]            = safe(info.get("returnOnEquity"))
    snap["roa"]            = safe(info.get("returnOnAssets"))
    snap["profit_margin"]  = safe(info.get("profitMargins"))
    snap["op_margin"]      = safe(info.get("operatingMargins"))
    snap["revenue_growth"] = safe(info.get("revenueGrowth"))
    snap["earnings_growth"]= safe(info.get("earningsGrowth"))
    snap["debt_to_equity"] = safe(info.get("debtToEquity"))
    snap["current_ratio"]  = safe(info.get("currentRatio"))
    snap["free_cashflow"]  = safe(info.get("freeCashflow"))
    snap["insider_pct"]    = safe(info.get("heldPercentInsiders"))
    snap["inst_pct"]       = safe(info.get("heldPercentInstitutions"))
    snap["dividend_yield"] = safe(info.get("dividendYield"))
    snap["payout_ratio"]   = safe(info.get("payoutRatio"))

    # 过滤估值为 0
    for k in ("pe_ttm", "pb", "price_to_sales", "trailing_pe", "forward_pe"):
        if snap.get(k) == 0.0:
            snap[k] = None

    return snap


def _yf_history(yf_ticker_str: str) -> pd.DataFrame | None:
    """用 yfinance 拉取近2年日K，返回标准 DataFrame"""
    try:
        import yfinance as yf
        tk = yf.Ticker(yf_ticker_str)
        df = tk.history(period="2y", interval="1d", auto_adjust=True)
        if df is None or df.empty:
            return None
        # 统一列名（yfinance 已是 Open/High/Low/Close/Volume）
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index.tz_localize(None) if df.index.tzinfo else df.index)
        df = df.sort_index()
        return df
    except Exception:
        return None


def _yf_info(yf_ticker_str: str) -> dict:
    """用 yfinance 拉取 info dict"""
    try:
        import yfinance as yf
        return yf.Ticker(yf_ticker_str).info or {}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────
# A股
# ─────────────────────────────────────────────────────────────

def _cn_secid(code: str) -> str:
    """根据代码前缀判断上交所/深交所"""
    if code.startswith(("6", "5", "9")):
        return f"1.{code}"
    return f"0.{code}"


def fetch_cn_analytics(code: str) -> dict:
    result = {
        "market": "CN", "ticker": code,
        "snapshot": {}, "periods": {}, "history_df": None, "error": None,
        "source": "eastmoney",
    }
    secid = _cn_secid(code)
    emf_ok = _emf_reachable()

    if emf_ok:
        # ── 东方财富路径 ──
        try:
            d = _fetch_spot(secid)
            if d:
                result["snapshot"] = _parse_spot(d)
            else:
                emf_ok = False
        except Exception as e:
            result["error"] = f"快照错误: {e}"
            emf_ok = False

        if emf_ok:
            try:
                start = (datetime.date.today() - datetime.timedelta(days=730)).strftime("%Y%m%d")
                df = _fetch_kline(secid, start)
                if df is not None and not df.empty:
                    result["history_df"] = df
                    for label, days in PERIODS.items():
                        result["periods"][label] = _period_stats(df, days)
                else:
                    emf_ok = False
            except Exception:
                emf_ok = False

    if not emf_ok:
        # ── yfinance fallback ──
        result["source"] = "yfinance"
        yft = _yf_ticker(code, "CN")
        info = _yf_info(yft)
        if info:
            result["snapshot"] = _yf_snapshot(info)
        df = _yf_history(yft)
        if df is not None and not df.empty:
            result["history_df"] = df
            for label, days in PERIODS.items():
                result["periods"][label] = _period_stats(df, days)
            result["error"] = None
        else:
            result["error"] = f"东方财富不可达，yfinance 也未能获取 {code} 数据"

    return result


# ─────────────────────────────────────────────────────────────
# 港股
# ─────────────────────────────────────────────────────────────

def fetch_hk_analytics(code: str) -> dict:
    result = {
        "market": "HK", "ticker": code,
        "snapshot": {}, "periods": {}, "history_df": None, "error": None,
        "source": "eastmoney",
    }
    stock_code = code.zfill(5)
    secid = f"{_EMF_MARKET_HK}.{stock_code}"
    emf_ok = _emf_reachable()

    if emf_ok:
        try:
            d = _fetch_spot(secid)
            if d:
                result["snapshot"] = _parse_spot(d)
            else:
                emf_ok = False
        except Exception as e:
            result["error"] = f"快照错误: {e}"
            emf_ok = False

        if emf_ok:
            try:
                start = (datetime.date.today() - datetime.timedelta(days=730)).strftime("%Y%m%d")
                df = _fetch_kline(secid, start)
                if df is not None and not df.empty:
                    result["history_df"] = df
                    for label, days in PERIODS.items():
                        result["periods"][label] = _period_stats(df, days)
                else:
                    emf_ok = False
            except Exception:
                emf_ok = False

    if not emf_ok:
        result["source"] = "yfinance"
        yft = _yf_ticker(code, "HK")
        info = _yf_info(yft)
        if info:
            result["snapshot"] = _yf_snapshot(info)
        df = _yf_history(yft)
        if df is not None and not df.empty:
            result["history_df"] = df
            for label, days in PERIODS.items():
                result["periods"][label] = _period_stats(df, days)
            result["error"] = None
        else:
            result["error"] = f"东方财富不可达，yfinance 也未能获取 {code} 数据"

    return result


# ─────────────────────────────────────────────────────────────
# 美股
# ─────────────────────────────────────────────────────────────

def fetch_us_analytics(ticker: str) -> dict:
    result = {
        "market": "US", "ticker": ticker,
        "snapshot": {}, "periods": {}, "history_df": None, "error": None,
        "source": "eastmoney",
    }
    emf_ok = _emf_reachable()

    if emf_ok:
        # 美股尝试多个市场代码（105=纳斯达克, 106=纽交所, 107=美交所）
        snap = {}
        df   = None
        for mkt in ["105", "106", "107"]:
            secid = f"{mkt}.{ticker.upper()}"
            try:
                d = _fetch_spot(secid)
                if d and d.get("f43") is not None:
                    snap = _parse_spot(d)
                    break
            except Exception:
                pass
            time.sleep(0.1)

        for mkt in ["105", "106", "107"]:
            secid = f"{mkt}.{ticker.upper()}"
            try:
                start = (datetime.date.today() - datetime.timedelta(days=730)).strftime("%Y%m%d")
                df = _fetch_kline(secid, start)
                if df is not None and not df.empty:
                    break
            except Exception:
                pass
            time.sleep(0.1)

        if snap or (df is not None and not df.empty):
            result["snapshot"] = snap
            if df is not None and not df.empty:
                result["history_df"] = df
                for label, days in PERIODS.items():
                    result["periods"][label] = _period_stats(df, days)
        else:
            emf_ok = False

    if not emf_ok:
        # ── yfinance fallback ──
        result["source"] = "yfinance"
        yft = _yf_ticker(ticker, "US")
        info = _yf_info(yft)
        if info:
            result["snapshot"] = _yf_snapshot(info)
        df = _yf_history(yft)
        if df is not None and not df.empty:
            result["history_df"] = df
            for label, days in PERIODS.items():
                result["periods"][label] = _period_stats(df, days)
            result["error"] = None
        else:
            result["error"] = f"东方财富不可达，yfinance 也未能获取 {ticker} 数据"

    return result


# ─────────────────────────────────────────────────────────────
# 统一入口
# ─────────────────────────────────────────────────────────────

def fetch_analytics(code: str, market: str) -> dict:
    """
    market: 'US' | 'HK' | 'CN'
    东方财富优先；若接口不可达则自动 fallback 到 yfinance。
    """
    if market == "US":
        return fetch_us_analytics(code)
    elif market == "HK":
        return fetch_hk_analytics(code)
    else:
        return fetch_cn_analytics(code)


# ─────────────────────────────────────────────────────────────
# 格式化展示辅助（供外部引用）
# ─────────────────────────────────────────────────────────────

SNAPSHOT_LABELS = {
    "pe_ttm":         ("市盈率(TTM)",      "2f",   "估值"),
    "price_to_sales": ("市销率(PS)",       "2f",   "估值"),
    "pb":             ("市净率(PB)",       "2f",   "估值"),
    "market_cap":     ("总市值",           "big",  "规模"),
    "float_cap":      ("流通市值",         "big",  "规模"),
    "current_price":  ("当前价格",         "2f",   "价格"),
    "change_pct":     ("今日涨跌幅",       "pct1", "价格"),
    "52w_high":       ("52周最高",         "2f",   "价格"),
    "52w_low":        ("52周最低",         "2f",   "价格"),
    "volume":         ("今日成交量",       "big",  "成交"),
    "turnover":       ("成交额",           "big",  "成交"),
    "turnover_rate":  ("换手率",           "pct1", "成交"),
    "amplitude":      ("今日振幅",         "pct1", "价格"),
}

PERIOD_LABELS = {
    "start_price":  "期初价格",
    "end_price":    "期末价格",
    "pct_change":   "区间涨跌幅",
    "period_high":  "区间最高",
    "period_low":   "区间最低",
    "volatility":   "日均波动率",
    "avg_volume":   "日均成交量",
    "total_volume": "区间总成交量",
    "max_volume":   "单日最大成交量",
    "up_days":      "上涨天数",
    "down_days":    "下跌天数",
}
