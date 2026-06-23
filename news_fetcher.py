"""
news_fetcher.py  —  消息面分析模块  v2.1
已验证可用数据源：
  1. 东方财富 个股资讯流  (np-listapi, 字段 Art_Title/Art_Code/Art_ShowTime)
  2. 东方财富 财经快讯    (newsapi.eastmoney.com/kuaixun, 字段 title/digest/showtime)
  3. 东方财富 行业板块资讯 (同上，按板块代码过滤)
  4. Yahoo Finance RSS   (美股，修复 <link> 解析)
  5. LLM 情感增强        (可选，需配置 API KEY)

LLM 关键字搜索（NewsKeywordWorker，在 main.py 中）额外接入：
  6. 搜狗新闻 / 搜狗综合搜索  (中文关键词，A股/港股)
  7. Bing News               (英文关键词，美股)
  8. Yahoo Finance 搜索       (英文补充)
  数据源不限于东方财富，保持权威性即可（见 web_search.search_news）
"""

import re, time, datetime, math, json
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────────────────────────
# HTTP Session
# ─────────────────────────────────────────────────────────────

# 东方财富美股 secid 前缀：105=纳斯达克, 106=纽交所, 107=美交所
# 先尝试 106（纽交所），再 105（纳斯达克），再 107
_US_PREFIXES = ["106", "105", "107"]

def _make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.4,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://",  adapter)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://finance.eastmoney.com/",
    })
    return s


def _resolve_us_secid(code: str) -> str:
    """自动探测美股 secid 前缀（106/105/107），返回有效的 secid"""
    code_upper = code.upper()
    for prefix in _US_PREFIXES:
        secid = f"{prefix}.{code_upper}"
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58"
        r = _get(url, timeout=6)
        if r:
            try:
                d = r.json().get("data") or {}
                if d.get("f57"):  # 有股票代码说明找到了
                    return secid
            except Exception:
                pass
    return f"105.{code_upper}"  # 默认回退

_SESSION = _make_session()

def _get(url, timeout=10, extra_headers=None):
    global _SESSION
    try:
        r = _SESSION.get(url, timeout=timeout, headers=extra_headers)
        r.raise_for_status()
        return r
    except Exception:
        _SESSION = _make_session()
        try:
            r = _SESSION.get(url, timeout=timeout, headers=extra_headers)
            r.raise_for_status()
            return r
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────
# 权威度映射
# ─────────────────────────────────────────────────────────────

SOURCE_AUTHORITY = {
    "SEC": 5, "证监会": 5, "港交所": 5, "新华社": 5, "人民日报": 5,
    "Reuters": 5, "Bloomberg": 5, "WSJ": 5,
    "财联社": 4, "东方财富": 4, "第一财经": 4, "证券时报": 4,
    "上海证券报": 4, "中国证券报": 4, "经济观察报": 4,
    "Yahoo Finance": 4, "CNBC": 4, "MarketWatch": 4,
    "新浪财经": 4, "同花顺": 3, "雪球": 3, "格隆汇": 3,
    "界面新闻": 3, "36氪": 3, "Seeking Alpha": 3,
}

def _authority(source: str) -> int:
    for k, v in SOURCE_AUTHORITY.items():
        if k in source:
            return v
    return 2


# ─────────────────────────────────────────────────────────────
# 情感 & 风险关键词
# ─────────────────────────────────────────────────────────────

_BULLISH_KW = [
    "增长","盈利","超预期","利好","上涨","突破","创新高","扩张","合作","中标",
    "获批","回购","分红","增持","上调","买入","涨停","大涨","新高","提高",
    "beat","surge","rally","upgrade","buy","outperform","record","profit",
    "growth","dividend","acquisition","partnership","raise","beat",
]
_BEARISH_KW = [
    "下跌","亏损","低于预期","利空","风险","下调","减持","卖出","诉讼","罚款",
    "调查","违规","退市","暴跌","崩盘","危机","跌停","大跌","亏损","下滑",
    "miss","drop","fall","downgrade","sell","underperform","loss","lawsuit",
    "fine","investigation","recall","layoff","debt","decline","cut",
]
_MARKET_RISK_KW = [
    "宏观","利率","通胀","汇率","贸易战","关税","地缘","衰退","美联储","央行",
    "政策","监管","竞争","市场份额","macro","rate","inflation","tariff",
    "geopolit","recession","fed","regulation","competition",
]
_FIN_RISK_KW = [
    "债务","负债","现金流","亏损","减值","商誉","财务造假","审计","会计",
    "资金链","流动性","偿债","debt","leverage","cashflow","impairment",
    "goodwill","audit","accounting","liquidity","default",
]
_TECH_RISK_KW = [
    "技术","研发","专利","侵权","产品缺陷","召回","故障","竞争对手","替代",
    "颠覆","过时","芯片","供应链","technology","patent","defect","recall",
    "competitor","disrupt","obsolete","chip","supply chain",
]

# 否定词前缀：命中关键词前10字符内若含否定词，则该关键词不计分
_NEGATION_ZH = ("\u4e0d", "\u672a", "\u65e0", "\u975e", "\u6ca1", "\u5c1a\u672a", "\u5e76\u975e", "\u4e0d\u662f", "\u4e0d\u4f1a", "\u4e0d\u5c06")
_NEGATION_EN = ("no ", "not ", "non-", "without ", "never ", "neither ", "nor ",
                "isn't", "aren't", "won't", "doesn't")


def _has_negation(text: str, keyword: str) -> bool:
    """检查关键词前是否有否定词（前10个字符内）"""
    idx = text.find(keyword.lower())
    if idx < 0:
        return False
    prefix = text[max(0, idx - 10): idx]
    for neg in _NEGATION_ZH + _NEGATION_EN:
        if neg in prefix:
            return True
    return False


def _classify(title: str, summary: str = "") -> tuple:
    text = (title + " " + summary).lower()
    # 带否定词检测：关键词前有否定词则不计分
    bull = sum(1 for k in _BULLISH_KW if k.lower() in text and not _has_negation(text, k))
    bear = sum(1 for k in _BEARISH_KW if k.lower() in text and not _has_negation(text, k))
    sentiment = "bullish" if bull > bear else ("bearish" if bear > bull else "neutral")
    risk_type = None
    if bear > 0:
        fm = sum(1 for k in _FIN_RISK_KW    if k.lower() in text)
        tm = sum(1 for k in _TECH_RISK_KW   if k.lower() in text)
        mm = sum(1 for k in _MARKET_RISK_KW if k.lower() in text)
        mx = max(fm, tm, mm)
        if mx > 0:
            if fm == mx:   risk_type = "financial"
            elif tm == mx: risk_type = "tech"
            else:          risk_type = "market"
        else:
            risk_type = "market"
    return sentiment, risk_type


def _relevance(title: str, keywords: list) -> float:
    if not keywords:
        return 0.5
    text = title.lower()
    hits = sum(1 for k in keywords if k.lower() in text)
    return min(1.0, hits / max(1, len(keywords) * 0.3))


def _parse_time(s: str):
    if not s:
        return None
    s = str(s).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y%m%d",
    ):
        try:
            dt = datetime.datetime.strptime(s[:len(fmt)], fmt)
            return dt.replace(tzinfo=None)
        except Exception:
            continue
    return None


def _score(item: dict) -> float:
    auth = item.get("authority", 1) / 5.0
    rel  = item.get("relevance", 0.5)
    pt   = item.get("pub_time")
    now  = datetime.datetime.now()
    if pt:
        hours_ago = max(0, (now - pt).total_seconds() / 3600)
        freshness = math.exp(-hours_ago / 72)
    else:
        freshness = 0.3
    return auth * 0.4 + freshness * 0.35 + rel * 0.25


def _dedup(items: list) -> list:
    seen, out = set(), []
    for it in items:
        key = it.get("title", "")[:30].strip()
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _make_item(title, url, source, pub_time_str, digest="", relevance=0.8):
    pt = _parse_time(pub_time_str)
    sent, rtype = _classify(title, digest)
    return {
        "title":     title,
        "url":       url,
        "source":    source,
        "pub_time":  pt,
        "authority": _authority(source),
        "relevance": relevance,
        "sentiment": sent,
        "risk_type": rtype,
        "summary":   digest[:120],
    }


# ─────────────────────────────────────────────────────────────
# 数据源 1：东方财富 个股资讯流
# 实测字段：Art_Title, Art_Code, Art_ShowTime, Art_Url
# ─────────────────────────────────────────────────────────────

# 缓存美股 secid，避免重复探测
_US_SECID_CACHE: dict = {}

def _fetch_emf_stock_news(code: str, market: str, limit: int = 30) -> list:
    if market == "CN":
        secid = f"1.{code}" if code.startswith(("6","5","9")) else f"0.{code}"
    elif market == "HK":
        secid = f"116.{code.zfill(5)}"
    else:
        if code.upper() not in _US_SECID_CACHE:
            _US_SECID_CACHE[code.upper()] = _resolve_us_secid(code)
        secid = _US_SECID_CACHE[code.upper()]

    url = (
        f"https://np-listapi.eastmoney.com/comm/web/getListInfo"
        f"?client=web&type=1&mTypeAndCode={secid}"
        f"&pageSize={limit}&pageIndex=1"
    )
    items = []
    r = _get(url, timeout=12)
    if not r:
        return items
    try:
        data = r.json()
        lst  = data.get("data", {}).get("list") or []
        for art in lst:
            title = art.get("Art_Title", "").strip()
            if not title:
                continue
            art_code = art.get("Art_Code", "")
            link     = art.get("Art_Url") or (
                f"http://finance.eastmoney.com/a/{art_code}.html" if art_code else ""
            )
            show_time = art.get("Art_ShowTime", "")
            items.append(_make_item(title, link, "东方财富", show_time, relevance=0.9))
    except Exception:
        pass
    return items


# ─────────────────────────────────────────────────────────────
# 数据源 2：东方财富 财经快讯（全市场热点，按关键词过滤）
# 实测字段：title, digest, showtime, url_w
# ─────────────────────────────────────────────────────────────

def _fetch_emf_kuaixun(keywords: list, limit: int = 50) -> list:
    url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html"
    r = _get(url, timeout=10)
    if not r:
        return []
    items = []
    try:
        m = re.match(r"var ajaxResult=(.*)", r.text, re.DOTALL)
        if not m:
            return []
        d    = json.loads(m.group(1))
        lst  = d.get("LivesList") or []
        for art in lst[:limit]:
            title  = art.get("title", "").strip()
            digest = art.get("digest", "").strip()
            if not title:
                continue
            rel = _relevance(title + " " + digest, keywords)
            if rel < 0.05 and keywords:
                continue
            link = art.get("url_w") or art.get("url_unique", "")
            show_time = art.get("showtime", "")
            items.append(_make_item(title, link, "东方财富快讯", show_time, digest, rel))
    except Exception:
        pass
    return items


# ─────────────────────────────────────────────────────────────
# 数据源 3：东方财富 行业板块资讯
# 先查板块代码，再拉板块资讯流
# ─────────────────────────────────────────────────────────────

def _get_industry_info(code: str, market: str) -> tuple:
    """返回 (industry_name, bk_code)，bk_code 如 'BK0477'"""
    if market == "CN":
        secid = f"1.{code}" if code.startswith(("6","5","9")) else f"0.{code}"
    elif market == "HK":
        secid = f"116.{code.zfill(5)}"
    else:
        if code.upper() not in _US_SECID_CACHE:
            _US_SECID_CACHE[code.upper()] = _resolve_us_secid(code)
        secid = _US_SECID_CACHE[code.upper()]

    # 获取行业名（f127）和地域板块（f128）
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields=f57,f58,f100,f127,f128"
    )
    r = _get(url, timeout=8)
    if r:
        try:
            d = r.json().get("data") or {}
            ind_name = d.get("f127") or d.get("f100") or ""
            return str(ind_name), ""
        except Exception:
            pass

    return "", ""


def _search_bk_code(industry_name: str) -> str:
    """通过行业名搜索东方财富板块代码"""
    if not industry_name:
        return ""
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get"
        f"?pn=1&pz=50&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
        f"&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14"
    )
    r = _get(url, timeout=8)
    if r:
        try:
            diff = r.json().get("data", {}).get("diff") or []
            for item in diff:
                name = item.get("f14", "")
                if industry_name[:3] in name or name[:3] in industry_name:
                    return item.get("f12", "")
        except Exception:
            pass
    return ""


def _fetch_emf_industry_news(bk_code: str, industry_name: str, limit: int = 20) -> list:
    """拉取行业板块资讯"""
    items = []

    # 方式1：用板块代码拉资讯流
    if bk_code:
        secid = f"90.{bk_code}"
        url = (
            f"https://np-listapi.eastmoney.com/comm/web/getListInfo"
            f"?client=web&type=1&mTypeAndCode={secid}"
            f"&pageSize={limit}&pageIndex=1"
        )
        r = _get(url, timeout=10)
        if r:
            try:
                lst = r.json().get("data", {}).get("list") or []
                for art in lst:
                    title = art.get("Art_Title", "").strip()
                    if not title:
                        continue
                    art_code = art.get("Art_Code", "")
                    link = art.get("Art_Url") or f"http://finance.eastmoney.com/a/{art_code}.html"
                    items.append(_make_item(title, link, "东方财富", art.get("Art_ShowTime",""), relevance=0.75))
            except Exception:
                pass

    # 方式2：从快讯中按行业名过滤
    if len(items) < 5 and industry_name:
        kw_items = _fetch_emf_kuaixun([industry_name], limit=80)
        for it in kw_items:
            if it.get("relevance", 0) > 0.1:
                items.append(it)

    return items[:limit]


# ─────────────────────────────────────────────────────────────
# 数据源 4：Yahoo Finance RSS（美股）
# 修复：<link> 在 RSS 2.0 中是文本节点，不是属性
# ─────────────────────────────────────────────────────────────

def _fetch_yahoo_rss(ticker: str, limit: int = 20) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    # Yahoo RSS 需要标准浏览器 UA，单独传入
    yahoo_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Referer": "https://finance.yahoo.com/",
    }
    r = _get(url, timeout=12, extra_headers=yahoo_headers)
    if not r:
        return []
    items = []
    try:
        # Yahoo RSS 的 <link> 是紧跟在 <title> 后的文本节点（非标准），用正则提取更稳
        text = r.text
        # 先尝试 XML 解析
        root = ET.fromstring(r.content)
        channel = root.find("channel")
        if channel is None:
            return items
        for entry in (channel.findall("item") or [])[:limit]:
            title = (entry.findtext("title") or "").strip()
            # <link> 在 RSS 2.0 里是文本节点
            link_el = entry.find("link")
            if link_el is not None and link_el.text:
                link = link_el.text.strip()
            else:
                # 有些 Yahoo RSS 把链接放在 <guid>
                link = (entry.findtext("guid") or "").strip()
            pub   = entry.findtext("pubDate") or ""
            desc  = (entry.findtext("description") or "")[:120]
            if not title:
                continue
            items.append(_make_item(title, link, "Yahoo Finance", pub, desc, relevance=0.9))
    except Exception:
        # XML 解析失败时用正则
        try:
            for m in re.finditer(
                r"<item>.*?<title><!\[CDATA\[(.*?)\]\]></title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>",
                text, re.DOTALL
            ):
                title, link, pub = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                items.append(_make_item(title, link, "Yahoo Finance", pub, relevance=0.9))
                if len(items) >= limit:
                    break
        except Exception:
            pass
    return items


# ─────────────────────────────────────────────────────────────
# 数据源 5：LLM 情感增强（可选）
# ─────────────────────────────────────────────────────────────

def _llm_enhance_news(items: list, code: str, company: str, llm_cfg: dict) -> list:
    """
    用 LLM 对新闻列表做情感分析和摘要增强。
    llm_cfg: {"provider": "openai"|"deepseek"|"qwen", "api_key": str, "base_url": str}
    """
    if not llm_cfg or not llm_cfg.get("api_key"):
        return items
    if not items:
        return items

    try:
        from llm_client import LLMClient
        client = LLMClient(llm_cfg)

        # 批量处理，每次最多10条
        batch = items[:10]
        titles = "\n".join(f"{i+1}. {it['title']}" for i, it in enumerate(batch))
        prompt = (
            f"以下是关于股票 {code}（{company}）的新闻标题列表，"
            f"请对每条新闻进行分析，返回JSON数组，每个元素包含：\n"
            f"- index: 序号(1开始)\n"
            f"- sentiment: bullish/bearish/neutral\n"
            f"- risk_type: market/financial/tech/null\n"
            f"- summary_zh: 一句话中文摘要(20字内)\n\n"
            f"新闻列表：\n{titles}\n\n"
            f"只返回JSON数组，不要其他内容。"
        )
        resp = client.chat(prompt, max_tokens=800)
        if resp:
            # 提取JSON
            m = re.search(r"\[.*\]", resp, re.DOTALL)
            if m:
                results = json.loads(m.group())
                for r in results:
                    idx = r.get("index", 0) - 1
                    if 0 <= idx < len(batch):
                        if r.get("sentiment") in ("bullish", "bearish", "neutral"):
                            batch[idx]["sentiment"] = r["sentiment"]
                        if r.get("risk_type") in ("market", "financial", "tech"):
                            batch[idx]["risk_type"] = r["risk_type"]
                        if r.get("summary_zh"):
                            batch[idx]["summary"] = r["summary_zh"]
                        batch[idx]["llm_enhanced"] = True
    except Exception:
        pass
    return items


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────

def fetch_news(code: str, market: str,
               company_name: str = "",
               top_n: int = 10,
               llm_cfg: dict = None) -> dict:
    result = {
        "company_news":  [],
        "industry_news": [],
        "bullish":       [],
        "risks": {"market": [], "financial": [], "tech": []},
        "industry_name": "",
        "sources_ok":    [],
        "sources_fail":  [],
        "error":         None,
    }

    keywords = [k for k in [code, company_name] if k]
    sources_ok, sources_fail = [], []

    # ── 1. 行业信息 ──────────────────────────────────────────
    ind_name, bk_code = "", ""
    try:
        ind_name, _ = _get_industry_info(code, market)
        result["industry_name"] = ind_name
        if ind_name:
            bk_code = _search_bk_code(ind_name)
    except Exception as e:
        sources_fail.append(f"行业信息({e})")

    # ── 2. 个股资讯流 ─────────────────────────────────────────
    all_company = []
    try:
        emf = _fetch_emf_stock_news(code, market, limit=40)
        if emf:
            all_company.extend(emf)
            sources_ok.append(f"东方财富资讯({len(emf)}条)")
        else:
            sources_fail.append("东方财富资讯(0条)")
    except Exception as e:
        sources_fail.append(f"东方财富资讯({e})")

    # ── 3. 快讯关键词过滤 ─────────────────────────────────────
    try:
        kw_items = _fetch_emf_kuaixun(keywords, limit=80)
        if kw_items:
            all_company.extend(kw_items)
            sources_ok.append(f"东方财富快讯({len(kw_items)}条)")
        else:
            sources_fail.append("东方财富快讯(0条)")
    except Exception as e:
        sources_fail.append(f"东方财富快讯({e})")

    # ── 4. 美股 Yahoo RSS ─────────────────────────────────────
    if market == "US":
        try:
            yahoo = _fetch_yahoo_rss(code, limit=20)
            if yahoo:
                all_company.extend(yahoo)
                sources_ok.append(f"Yahoo Finance({len(yahoo)}条)")
            else:
                sources_fail.append("Yahoo Finance(0条)")
        except Exception as e:
            sources_fail.append(f"Yahoo Finance({e})")

    # ── 5. LLM 情感增强 ───────────────────────────────────────
    if llm_cfg and llm_cfg.get("api_key"):
        try:
            all_company = _llm_enhance_news(all_company, code, company_name, llm_cfg)
            sources_ok.append("LLM情感增强")
        except Exception as e:
            sources_fail.append(f"LLM({e})")

    # ── 6. 行业新闻 ───────────────────────────────────────────
    try:
        ind_items = _fetch_emf_industry_news(bk_code, ind_name, limit=20)
        if ind_items:
            result["industry_news"] = _dedup(sorted(ind_items, key=_score, reverse=True))[:15]
            sources_ok.append(f"行业资讯({len(ind_items)}条)")
        else:
            sources_fail.append("行业资讯(0条)")
    except Exception as e:
        sources_fail.append(f"行业资讯({e})")

    # ── 7. 排序去重 ───────────────────────────────────────────
    all_company = _dedup(sorted(all_company, key=_score, reverse=True))
    result["company_news"] = all_company[:top_n]

    # ── 8. 分类 ───────────────────────────────────────────────
    for item in all_company[:30]:
        sent  = item.get("sentiment", "neutral")
        rtype = item.get("risk_type")
        if sent == "bullish":
            result["bullish"].append(item)
        elif sent == "bearish" and rtype:
            result["risks"][rtype].append(item)

    result["bullish"] = result["bullish"][:5]
    for k in result["risks"]:
        result["risks"][k] = result["risks"][k][:5]

    result["sources_ok"]   = sources_ok
    result["sources_fail"] = sources_fail

    total = len(result["company_news"]) + len(result["industry_news"])
    if total == 0:
        result["error"] = "未获取到任何消息，失败源: " + "; ".join(sources_fail[:3])

    return result
