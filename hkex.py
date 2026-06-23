"""
hkex.py — 港交所（港股）公开数据查询模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
完全免费，无需注册，官方开放接口。
数据来源：
  - https://www1.hkexnews.hk  （披露易）
  - https://www.hkex.com.hk   （港交所行情）

【已验证可用的接口】
  1. 活跃股票列表 JSON（英文）
     https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json
  2. 活跃股票列表 JSON（中文）
     https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json
  3. 披露易搜索页面（公告列表，JS 动态渲染，提供直达链接）
     https://www1.hkexnews.hk/search/titlesearch.xhtml

【注意】
  HKEX 行情 API token 已失效，改用 Yahoo Finance 作为行情备用源。
  本模块提供：
    - 公司基本信息（中英文名称、股票代码）
    - 各类公告的直达链接（用户点击后在浏览器中查看）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re
import time
import datetime
import requests
from typing import Optional

# ── 常量 ──────────────────────────────────────────────────────────────────────
_NEWS_BASE    = "https://www1.hkexnews.hk"
_HKEX_BASE    = "https://www.hkex.com.hk"
_STOCKS_EN    = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
_STOCKS_ZH    = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json"
_DELAY        = 0.3
_MAX_RETRY    = 3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Referer":         "https://www1.hkexnews.hk/",
}

# 公告类别 → 中文说明
CATEGORY_MAP = {
    "AAER": "年度业绩公告",
    "AAFR": "年度财务报告",
    "AIAR": "中期业绩公告",
    "AIFR": "中期财务报告",
    "AMDI": "重大交易",
    "AMDT": "非常重大交易",
    "AMCO": "关联交易",
    "AMVD": "非常重大收购",
    "AMVS": "非常重大出售",
    "ASDP": "股权披露",
    "ASDI": "内幕消息",
    "ASPR": "股价敏感资料",
    "AOTH": "其他公告",
    "ACIR": "公司资料变更",
    "ADIV": "股息公告",
    "AGMN": "股东大会通知",
    "APRX": "委托书",
    "ALST": "上市文件",
    "APRP": "招股章程",
}

# 股票列表缓存（内存）
_CACHE_EN: list = []
_CACHE_ZH: dict = {}   # code -> name_zh


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 内部工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get(url: str, params: dict = None, timeout: int = 20):
    for attempt in range(_MAX_RETRY):
        try:
            r = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "")
            if "json" in ct:
                return r.json()
            return {"_text": r.text, "_status": r.status_code}
        except requests.exceptions.JSONDecodeError:
            return None
        except Exception:
            if attempt < _MAX_RETRY - 1:
                time.sleep(1 + attempt)
    return None


def _fmt_stock_code(code: str) -> str:
    """港股代码标准化：去掉前缀，补零到 5 位"""
    code = code.strip().upper()
    code = re.sub(r"^(HK\.?|\.HK|HKG:|HK:)", "", code)
    code = re.sub(r"\.HK$", "", code)
    try:
        return str(int(code)).zfill(5)
    except ValueError:
        return code


def _load_stock_list() -> list:
    """加载港交所活跃股票列表（英文，约 18000 条，缓存到内存）"""
    global _CACHE_EN
    if _CACHE_EN:
        return _CACHE_EN
    data = _get(_STOCKS_EN)
    if isinstance(data, list):
        _CACHE_EN = data
    return _CACHE_EN


def _load_zh_names() -> dict:
    """加载港交所活跃股票中文名称映射 {code -> name_zh}"""
    global _CACHE_ZH
    if _CACHE_ZH:
        return _CACHE_ZH
    data = _get(_STOCKS_ZH)
    if isinstance(data, list):
        for s in data:
            if isinstance(s, dict):
                c = s.get("c", "")
                n = s.get("n", "")
                if c and n:
                    _CACHE_ZH[c] = n
    return _CACHE_ZH


def _build_disclosure_url(stock_code: str, category: str = "",
                           date_from: str = "", date_to: str = "") -> str:
    """
    构建披露易搜索直达链接。
    日期格式：YYYYMMDD，date_from 默认为 3 年前，date_to 默认为今天。
    """
    try:
        code_int = str(int(stock_code))
    except (ValueError, TypeError):
        code_int = stock_code

    today = datetime.date.today()
    if not date_to:
        date_to = today.strftime("%Y%m%d")
    if not date_from:
        date_from = (today - datetime.timedelta(days=365 * 3)).strftime("%Y%m%d")

    params = (
        f"lang=ZH&market=SEHK&stock_code={code_int}"
        f"&date_from={date_from}&date_to={date_to}"
    )
    if category:
        params += f"&category={category}"
    return f"{_NEWS_BASE}/search/titlesearch.xhtml?{params}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 公司搜索
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def search_company(keyword: str) -> list:
    """
    按股票代码或公司名称搜索港股上市公司。
    返回：[{stock_code, name_en, name_zh, stock_id, disclosure_url, hkex_url}]
    """
    keyword = keyword.strip().upper()
    stocks  = _load_stock_list()
    zh_map  = _load_zh_names()
    results = []

    # 尝试解析为数字代码
    try:
        code_int = int(keyword)
        code_str = str(code_int).zfill(5)
    except ValueError:
        code_int = None
        code_str = None

    for s in stocks:
        if not isinstance(s, dict):
            continue
        c   = s.get("c", "")   # 股票代码，如 "00700"
        n   = s.get("n", "")   # 公司名称（英文）
        sid = s.get("s", 0)    # stockId

        matched = False
        if code_str and c == code_str:
            matched = True
        elif code_int and str(code_int) == c.lstrip("0"):
            matched = True
        elif keyword in n.upper():
            matched = True

        if matched:
            results.append({
                "stock_code":     c,
                "name_en":        n,
                "name_zh":        zh_map.get(c, ""),
                "stock_id":       sid,
                "market":         "SEHK",
                "disclosure_url": _build_disclosure_url(c),
                "hkex_url":       (
                    f"{_HKEX_BASE}/Market-Data/Securities-Prices/Equities/"
                    f"Equities-Quote?sym={int(c)}&sc_lang=zh-HK"
                ),
            })
            if len(results) >= 20:
                break

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 公司基本信息
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_company_info(stock_code: str) -> dict:
    """
    获取港股公司基本信息。
    返回：{name_zh, name_en, stock_code, hkex_url, disclosure_url, ...各类公告链接}
    """
    code     = _fmt_stock_code(stock_code)
    code_int = int(code)
    zh_map   = _load_zh_names()
    stocks   = _load_stock_list()

    # 从英文列表获取基本信息
    name_en  = ""
    stock_id = 0
    for s in stocks:
        if isinstance(s, dict) and s.get("c", "") == code:
            name_en  = s.get("n", "")
            stock_id = s.get("s", 0)
            break

    name_zh = zh_map.get(code, "")

    result = {
        "stock_code":     code,
        "name_zh":        name_zh,
        "name_en":        name_en,
        "stock_id":       stock_id,
        "listing_date":   "",
        "industry":       "",
        "currency":       "HKD",
        "lot_size":       "",
        "issued_shares":  "",
        "market_cap":     "",
        "last_price":     "",
        "change_pct":     "",
        # 官方链接
        "hkex_url":       (
            f"{_HKEX_BASE}/Market-Data/Securities-Prices/Equities/"
            f"Equities-Quote?sym={code_int}&sc_lang=zh-HK"
        ),
        "disclosure_url": _build_disclosure_url(code),
        # 各类公告直达链接
        "annual_report_url":    _build_disclosure_url(code, "AAFR"),
        "interim_report_url":   _build_disclosure_url(code, "AIFR"),
        "annual_result_url":    _build_disclosure_url(code, "AAER"),
        "interim_result_url":   _build_disclosure_url(code, "AIAR"),
        "shareholding_url":     _build_disclosure_url(code, "ASDP"),
        "connected_tx_url":     _build_disclosure_url(code, "AMCO"),
        "major_tx_url":         _build_disclosure_url(code, "AMDI"),
        "insider_info_url":     _build_disclosure_url(code, "ASDI"),
        "dividend_url":         _build_disclosure_url(code, "ADIV"),
        "agm_url":              _build_disclosure_url(code, "AGMN"),
    }

    # 尝试从 Yahoo Finance 获取行情数据（备用）
    try:
        yf_r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{code_int}.HK",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if yf_r.status_code == 200:
            yf_data = yf_r.json()
            meta = (
                yf_data.get("chart", {})
                       .get("result", [{}])[0]
                       .get("meta", {})
            )
            if meta:
                result.update({
                    "last_price":    str(meta.get("regularMarketPrice", "")),
                    "currency":      meta.get("currency", "HKD"),
                    "market_cap":    str(meta.get("marketCap", "")),
                    "exchange_name": meta.get("exchangeName", "SEHK"),
                })
                # Yahoo 有时提供长名称
                long_name = meta.get("longName", "")
                if long_name and not name_en:
                    result["name_en"] = long_name
    except Exception:
        pass

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 公告直达链接（各类别）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_announcement_links(stock_code: str, years: int = 3) -> list:
    """
    生成各类公告的直达链接列表（无需 JS 渲染，直接在浏览器打开）。
    返回：[{category, category_desc, url, date_range}]
    """
    code    = _fmt_stock_code(stock_code)
    today   = datetime.date.today()
    date_to = today.strftime("%Y%m%d")
    date_from = (today - datetime.timedelta(days=365 * years)).strftime("%Y%m%d")

    key_categories = [
        ("",     "全部公告"),
        ("AAFR", "年度财务报告（年报）"),
        ("AAER", "年度业绩公告"),
        ("AIFR", "中期财务报告（中报）"),
        ("AIAR", "中期业绩公告"),
        ("ASDP", "股权披露（大股东变动）"),
        ("AMCO", "关联交易"),
        ("AMDI", "重大交易"),
        ("AMDT", "非常重大交易"),
        ("ASDI", "内幕消息"),
        ("ADIV", "股息公告"),
        ("AGMN", "股东大会通知"),
    ]

    links = []
    for cat_code, cat_desc in key_categories:
        url = _build_disclosure_url(code, cat_code, date_from, date_to)
        links.append({
            "category":      cat_code,
            "category_desc": cat_desc,
            "url":           url,
            "date_range":    (
                f"{date_from[:4]}-{date_from[4:6]}-{date_from[6:]} 至 "
                f"{date_to[:4]}-{date_to[4:6]}-{date_to[6:]}"
            ),
        })

    return links
