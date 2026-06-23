"""
web_search.py  —  轻量级网页搜索模块
数据源优先级（国内可用）：
  中文：百度新闻（主力）→ 东方财富搜索接口（补充）→ 搜狗新闻（备用）
  英文：Bing News → Yahoo Finance
无需 API Key，纯 requests + re 实现。
"""

import re
import json
import requests
from urllib.parse import quote

_HEADERS_ZH = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

_HEADERS_EN = {
    **_HEADERS_ZH,
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    """去除 HTML 标签和常见实体"""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&(?:nbsp|ensp|emsp);', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;',  '<', text)
    text = re.sub(r'&gt;',  '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&[a-z]+;', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _clean_title(t: str) -> str:
    """清理标题：去标签、去首尾空白、去 <em> 高亮标记"""
    t = re.sub(r'</?em>', '', t)
    return _strip_tags(t).strip()


def _is_noise(title: str) -> bool:
    """过滤导航/UI 噪音"""
    noise = ['搜狗', '百度', 'Bing', 'Microsoft', '登录', '注册',
             'function(', 'var ', '©', 'Cookie', '隐私政策',
             '用户协议', '下载APP', '客户端']
    if len(title) < 6 or len(title) > 150:
        return True
    return any(n in title for n in noise)


# ─────────────────────────────────────────────────────────────
# 数据源1：百度新闻（主力，中文）
# ─────────────────────────────────────────────────────────────

def _fetch_baidu_news(keyword: str, timeout: int = 10) -> list[dict]:
    """
    百度新闻搜索，返回 [{"title", "snippet", "source", "url"}]
    """
    items = []
    try:
        url = (
            f"https://news.baidu.com/ns"
            f"?word={quote(keyword)}&tn=news&from=news&cl=2&pn=0&rn=15&ct=1"
        )
        r = requests.get(url, headers=_HEADERS_ZH, timeout=timeout)
        r.raise_for_status()
        html = r.text

        seen = set()
        # 百度新闻结构：<h3 class="c-title"> 或 <a class="news-title-font">
        # 策略1：找 h3 标题
        for m in re.finditer(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL):
            title = _clean_title(m.group(1))
            if not title or _is_noise(title):
                continue
            key = title[:30]
            if key in seen:
                continue
            seen.add(key)
            # 尝试找紧随的摘要
            pos = m.end()
            snippet_m = re.search(r'<p[^>]*>(.*?)</p>', html[pos:pos+800], re.DOTALL)
            snippet = _clean_title(snippet_m.group(1)) if snippet_m else ""
            # 尝试找来源
            src_m = re.search(r'class="[^"]*source[^"]*"[^>]*>(.*?)<', html[pos:pos+500], re.DOTALL)
            source = _clean_title(src_m.group(1)) if src_m else "百度新闻"
            items.append({"title": title, "snippet": snippet[:120], "source": source, "url": ""})

        # 策略2：找 <a> 标签中的新闻标题（备用）
        if len(items) < 5:
            for m in re.finditer(
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]{10,120})</a>',
                html
            ):
                url_link, title = m.group(1), m.group(2).strip()
                if _is_noise(title):
                    continue
                key = title[:30]
                if key in seen:
                    continue
                seen.add(key)
                items.append({"title": title, "snippet": "", "source": "百度新闻", "url": url_link})

    except Exception:
        pass
    return items[:12]


# ─────────────────────────────────────────────────────────────
# 数据源2：东方财富搜索接口（补充，中文）
# ─────────────────────────────────────────────────────────────

def _fetch_emf_search(keyword: str, timeout: int = 8) -> list[dict]:
    """
    东方财富文章搜索接口，返回 [{"title", "snippet", "source", "url"}]
    """
    items = []
    try:
        param = {
            "uid": "",
            "keyword": keyword,
            "type": ["cmsArticle"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticle": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": 15,
                    "preTag": "",
                    "postTag": "",
                }
            }
        }
        url = (
            "https://search-api-web.eastmoney.com/search/jsonp"
            f"?cb=jQuery&param={quote(json.dumps(param, ensure_ascii=False))}&cb=jQuery"
        )
        r = requests.get(url, headers=_HEADERS_ZH, timeout=timeout)
        r.raise_for_status()
        # 响应是 jQuery(...) 包裹的 JSONP
        text = r.text
        m = re.search(r'jQuery\((.*)\)\s*$', text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            articles = (
                data.get("result", {})
                    .get("cmsArticle", {})
                    .get("data", []) or []
            )
            seen = set()
            for art in articles:
                title = _clean_title(art.get("title", ""))
                if not title or _is_noise(title):
                    continue
                key = title[:30]
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    "title": title,
                    "snippet": _clean_title(art.get("digest", ""))[:120],
                    "source": art.get("mediaName", "东方财富"),
                    "url": art.get("url", ""),
                })
    except Exception:
        pass
    return items[:12]


# ─────────────────────────────────────────────────────────────
# 数据源3：搜狗新闻（备用，中文）
# ─────────────────────────────────────────────────────────────

def _fetch_sogou_news(keyword: str, timeout: int = 10) -> list[dict]:
    """搜狗新闻，返回 [{"title", "snippet", "source", "url"}]"""
    items = []
    try:
        url = f"https://news.sogou.com/news?query={quote(keyword)}&ie=utf8"
        r = requests.get(url, headers=_HEADERS_ZH, timeout=timeout)
        r.raise_for_status()
        html = r.text
        seen = set()
        for m in re.finditer(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL):
            title = _clean_title(m.group(1))
            if not title or _is_noise(title):
                continue
            key = title[:30]
            if key in seen:
                continue
            seen.add(key)
            items.append({"title": title, "snippet": "", "source": "搜狗新闻", "url": ""})
    except Exception:
        pass
    return items[:8]


# ─────────────────────────────────────────────────────────────
# 数据源4：Bing News（英文）
# ─────────────────────────────────────────────────────────────

def _fetch_google_news_rss(keyword: str, lang: str = "en", timeout: int = 10) -> list[dict]:
    """
    Google News RSS（无需 Key，结构稳定，英中文均可用）
    lang: 'en' | 'zh'
    """
    items = []
    try:
        if lang == "zh":
            url = (
                f"https://news.google.com/rss/search"
                f"?q={quote(keyword)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
            )
            headers = {**_HEADERS_ZH}
        else:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={quote(keyword)}&hl=en-US&gl=US&ceid=US:en"
            )
            headers = {**_HEADERS_EN}

        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        rss = r.text

        seen = set()
        # 提取 <item> 块
        for item_m in re.finditer(r'<item>(.*?)</item>', rss, re.DOTALL):
            item_xml = item_m.group(1)
            # 标题
            t_m = re.search(r'<title>(?:<\!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item_xml, re.DOTALL)
            if not t_m:
                continue
            title = t_m.group(1).strip()
            # 去掉 "- 来源" 后缀（Google News 格式）
            title = re.sub(r'\s*-\s*[^-]{2,40}$', '', title).strip()
            if not title or _is_noise(title) or len(title) < 8:
                continue
            key = title[:30]
            if key in seen:
                continue
            seen.add(key)
            # 来源
            src_m = re.search(r'<source[^>]*>(.*?)</source>', item_xml, re.DOTALL)
            source = src_m.group(1).strip() if src_m else ("Google新闻" if lang == "zh" else "Google News")
            # 链接
            link_m = re.search(r'<link>(.*?)</link>', item_xml, re.DOTALL)
            url_link = link_m.group(1).strip() if link_m else ""
            # 日期
            date_m = re.search(r'<pubDate>(.*?)</pubDate>', item_xml, re.DOTALL)
            pub_date = date_m.group(1).strip() if date_m else ""
            items.append({
                "title": title,
                "snippet": "",
                "source": source,
                "url": url_link,
                "pub_date": pub_date,
            })
    except Exception:
        pass
    return items[:15]


def _fetch_bing_news_en(keyword: str, timeout: int = 10) -> list[dict]:
    """Bing News 英文搜索（多策略适配新版 Bing 结构）"""
    items = []
    try:
        url = (
            f"https://www.bing.com/news/search"
            f"?q={quote(keyword)}&setlang=en-US&count=10&format=RSS"
        )
        # 先尝试 RSS 格式（结构稳定）
        r = requests.get(url, headers=_HEADERS_EN, timeout=timeout)
        r.raise_for_status()
        rss = r.text
        seen = set()

        # RSS <title> 标签
        rss_titles = re.findall(r'<title><!\[CDATA\[(.+?)\]\]></title>', rss)
        if not rss_titles:
            rss_titles = re.findall(r'<title>([^<]{10,150})</title>', rss)
        for t in rss_titles:
            t = t.strip()
            if _is_noise(t) or len(t) < 10:
                continue
            key = t[:30]
            if key not in seen:
                seen.add(key)
                items.append({"title": t, "snippet": "", "source": "Bing News", "url": ""})

        # RSS 失败则回退 HTML
        if len(items) < 3:
            url_html = f"https://www.bing.com/news/search?q={quote(keyword)}&setlang=en-US&count=10"
            r2 = requests.get(url_html, headers=_HEADERS_EN, timeout=timeout)
            html = r2.text
            # 新版 Bing：JSON-LD 或 data-title
            for t in re.findall(r'data-title="([^"]{10,150})"', html):
                key = t[:30]
                if key not in seen and not _is_noise(t):
                    seen.add(key)
                    items.append({"title": t, "snippet": "", "source": "Bing News", "url": ""})
            # <a> class 含 title
            for m in re.finditer(r'<a[^>]+class="[^"]*title[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL):
                title = _clean_title(m.group(1))
                if title and not _is_noise(title) and len(title) >= 10:
                    key = title[:30]
                    if key not in seen:
                        seen.add(key)
                        items.append({"title": title, "snippet": "", "source": "Bing News", "url": ""})

    except Exception:
        pass
    return items[:10]


# ─────────────────────────────────────────────────────────────
# 数据源5：Yahoo Finance（英文补充）
# ─────────────────────────────────────────────────────────────

def _fetch_yahoo_finance_search(keyword: str, timeout: int = 10) -> list[dict]:
    """Yahoo Finance 搜索"""
    items = []
    try:
        url = f"https://finance.yahoo.com/search?p={quote(keyword)}"
        r = requests.get(url, headers=_HEADERS_EN, timeout=timeout)
        r.raise_for_status()
        html = r.text
        seen = set()
        for m in re.finditer(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL):
            title = _clean_title(m.group(1))
            if not title or _is_noise(title) or len(title) < 10:
                continue
            key = title[:30]
            if key not in seen:
                seen.add(key)
                items.append({"title": title, "snippet": "", "source": "Yahoo Finance", "url": ""})
    except Exception:
        pass
    return items[:8]


# ─────────────────────────────────────────────────────────────
# 旧版兼容：search_company_info（同行业搜索用）
# ─────────────────────────────────────────────────────────────

def _extract_text_passages(html: str, keyword: str = "") -> list[str]:
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>',  ' ', html, flags=re.DOTALL | re.IGNORECASE)
    passages = []
    seen = set()
    for m in re.finditer(r'<p[^>]*>(.*?)</p>', html, re.DOTALL):
        text = _strip_tags(m.group(1)).strip()
        if len(text) > 60:
            key = text[:60]
            if key not in seen:
                seen.add(key)
                passages.append(text)
    if keyword:
        for m in re.finditer(re.escape(keyword), html):
            start = max(0, m.start() - 20)
            end   = min(len(html), m.end() + 600)
            chunk = _strip_tags(html[start:end]).strip()
            chunk = re.sub(r'^[^，。！？\w]*', '', chunk)
            if len(chunk) > 80:
                key = chunk[:60]
                if key not in seen:
                    seen.add(key)
                    passages.append(chunk[:800])
    passages.sort(key=lambda x: len(x), reverse=True)
    return passages


def search_company_info(query: str, timeout: int = 12) -> dict:
    """搜索公司/行业信息（中文），优先用百度新闻+东方财富搜索拼接摘要"""
    result = {"query": query, "passages": [], "titles": [], "raw_text": "", "source": "百度新闻", "error": None}
    try:
        # 用新闻搜索接口获取标题列表
        news_items = _fetch_baidu_news(query, timeout=timeout)
        if len(news_items) < 5:
            news_items += _fetch_emf_search(query, timeout=min(timeout, 8))

        titles = []
        seen = set()
        for it in news_items:
            t = it["title"]
            key = t[:30]
            if key not in seen:
                seen.add(key)
                titles.append(t)

        # 摘要：用各条 snippet 拼接
        passages = [it["snippet"] for it in news_items if it.get("snippet") and len(it["snippet"]) > 20][:4]

        result["titles"]   = titles[:10]
        result["passages"] = passages
        parts = []
        if titles:
            parts.append("【相关新闻标题】\n" + "\n".join(f"· {t}" for t in titles[:8]))
        if passages:
            parts.append("【新闻摘要】\n" + "\n\n".join(passages[:3]))
        result["raw_text"] = "\n\n".join(parts)
    except Exception as e:
        result["error"] = str(e)
    return result


def search_company_info_en(query: str, timeout: int = 12) -> dict:
    """英文公司/行业搜索（美股公司），走 Bing"""
    result = {"query": query, "passages": [], "titles": [], "raw_text": "", "source": "Bing Search", "error": None}
    try:
        url = f"https://www.bing.com/search?q={quote(query + ' company business overview')}&setlang=en-US&count=5"
        resp = requests.get(url, headers=_HEADERS_EN, timeout=timeout)
        resp.raise_for_status()
        html = resp.text

        def _is_useful_en(p):
            if len(p) < 50: return False
            noise = ['Bing', 'Microsoft', 'Sign in', 'Privacy', 'Terms', 'function(', 'var ']
            return not any(n in p for n in noise)

        passages = [p for p in _extract_text_passages(html, keyword=query.split()[0] if query.split() else query) if _is_useful_en(p)][:5]
        result["passages"] = passages
        if passages:
            result["raw_text"] = "【Web Search Snippets】\n\n" + "\n\n---\n\n".join(passages[:4])
    except Exception as e:
        result["error"] = str(e)
    return result


def search_for_llm(query: str, lang: str = "auto") -> str:
    """统一入口：根据查询语言自动选择搜索引擎，返回供 LLM 直接使用的参考文本"""
    if lang == "auto":
        zh_chars = len(re.findall(r'[\u4e00-\u9fff]', query))
        lang = "zh" if zh_chars > 0 else "en"
    if lang == "zh":
        r = search_company_info(query)
    else:
        r = search_company_info_en(query)
    return r.get("raw_text", "")


# ─────────────────────────────────────────────────────────────
# 主入口：财经新闻搜索（消息面专用）
# ─────────────────────────────────────────────────────────────

def search_news(keyword: str, stock_code: str = "", market: str = "",
                timeout: int = 12) -> dict:
    """
    搜索财经新闻。
    中文：百度新闻（主力）→ 东方财富搜索（补充）→ 搜狗新闻（备用）
    英文：Bing News → Yahoo Finance
    返回：
    {
        "keyword":  str,
        "items":    [{"title", "snippet", "source", "url"}, ...],
        "raw_text": str,
        "sources":  [str],
        "error":    str | None,
    }
    """
    result = {
        "keyword": keyword,
        "items":   [],
        "raw_text": "",
        "sources": [],
        "error":   None,
    }

    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', keyword))
    is_zh = zh_chars > 0 or market in ("CN", "HK")

    all_items: list[dict] = []
    seen_titles: set[str] = set()

    def _add(new_items: list[dict], source_name: str):
        added = 0
        for it in new_items:
            key = it["title"][:30]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(it)
                added += 1
        if added > 0 and source_name not in result["sources"]:
            result["sources"].append(source_name)

    if is_zh:
        # 1. 百度新闻（主力）
        baidu = _fetch_baidu_news(keyword, timeout=timeout)
        _add(baidu, "百度新闻")

        # 2. 东方财富搜索（补充，目标凑够 10 条）
        if len(all_items) < 10:
            emf = _fetch_emf_search(keyword, timeout=min(timeout, 8))
            _add(emf, "东方财富")

        # 3. Google News RSS 中文（补充）
        if len(all_items) < 8:
            gnews_zh = _fetch_google_news_rss(keyword, lang="zh", timeout=timeout)
            _add(gnews_zh, "Google新闻")

        # 4. 搜狗新闻（备用，凑不够时）
        if len(all_items) < 6:
            sogou = _fetch_sogou_news(keyword, timeout=timeout)
            _add(sogou, "搜狗新闻")

    else:
        # 1. Google News RSS（英文主力）
        gnews = _fetch_google_news_rss(keyword, lang="en", timeout=timeout)
        _add(gnews, "Google News")

        # 2. Bing News 补充
        if len(all_items) < 5:
            bing = _fetch_bing_news_en(keyword, timeout=timeout)
            _add(bing, "Bing News")

        # 3. Yahoo Finance 补充
        if len(all_items) < 5:
            yahoo = _fetch_yahoo_finance_search(keyword, timeout=timeout)
            _add(yahoo, "Yahoo Finance")

    result["items"] = all_items[:15]

    # 拼接供 LLM 阅读的参考文本
    if all_items:
        lines = []
        for i, it in enumerate(all_items[:12], 1):
            line = f"{i}. 【{it['title']}】"
            if it.get("snippet"):
                line += f" — {it['snippet'][:100]}"
            if it.get("source"):
                line += f"（{it['source']}）"
            lines.append(line)
        src_str = "、".join(result["sources"]) if result["sources"] else "网络搜索"
        result["raw_text"] = (
            f"【联网搜索结果 · 来源：{src_str}】\n" + "\n".join(lines)
        )

    return result


def search_news_for_llm(keyword: str, stock_code: str = "", market: str = "") -> str:
    """消息面联网搜索统一入口，返回供 LLM 直接使用的参考文本"""
    r = search_news(keyword, stock_code=stock_code, market=market)
    return r.get("raw_text", "")


# ─────────────────────────────────────────────────────────────
# 一级市场媒体专栏（36氪 / 量子位 / 爱范儿）
# 实现：搜狗 site: 限定搜索，从 data-url 属性提取真实 URL
# ─────────────────────────────────────────────────────────────

_PM_SOURCES = [
    {"name": "36氪",  "site": "36kr.com"},
    {"name": "量子位", "site": "qbitai.com"},
    {"name": "爱范儿", "site": "ifanr.com"},
]

_SOGOU_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.sogou.com/",
}


def _sogou_site_search(keyword: str, site: str, source_name: str,
                       limit: int = 8, timeout: int = 10) -> list[dict]:
    """
    用搜狗 site: 限定搜索指定媒体，返回
    [{"title", "url", "source", "summary", "pub_date_str"}]
    """
    query = f"{keyword} site:{site}"
    try:
        r = requests.get(
            "https://www.sogou.com/web",
            params={"query": query, "num": limit},
            headers=_SOGOU_HEADERS,
            timeout=timeout,
        )
        r.raise_for_status()
    except Exception:
        return []

    html = r.text
    items = []
    seen: set[str] = set()

    # 搜狗把真实 URL 放在 data-url 属性里，标题在相邻的 <h3><a> 里
    # 用 <div class="vrwrap"> 块来配对
    blocks = re.split(r'<div class="vrwrap"', html)
    for block in blocks[1:]:
        # 真实 URL
        url_m = re.search(r'data-url="([^"]+)"', block)
        if not url_m:
            continue
        url = url_m.group(1).strip()
        # 只保留目标域名的链接
        if site not in url:
            continue

        # 标题
        title_m = re.search(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        title = re.sub(r'&[a-z]+;', '', title).strip()
        if not title or len(title) < 4:
            continue
        key = title[:30]
        if key in seen:
            continue
        seen.add(key)

        # 摘要（text-layout div）
        snip_m = re.search(r'<div class="text-layout"[^>]*>(.*?)</div>', block, re.DOTALL)
        summary = ""
        if snip_m:
            summary = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip()
            summary = re.sub(r'\s+', ' ', summary)[:200]

        items.append({
            "title":        title,
            "url":          url,
            "source":       source_name,
            "summary":      summary,
            "pub_date_str": "",
        })
        if len(items) >= limit:
            break

    return items


def search_primary_market(keyword: str = "", timeout: int = 12) -> dict:
    """
    通过搜狗 site: 搜索从 36氪/量子位/爱范儿 获取与 keyword 相关的资讯。

    返回：
    {
        "keyword": str,
        "items":   [{"title", "url", "source", "summary", "pub_date_str"}, ...],
        "sources": [str],
        "error":   str | None,
    }
    """
    result: dict = {
        "keyword": keyword,
        "items":   [],
        "sources": [],
        "error":   None,
    }

    if not keyword:
        result["error"] = "请输入关键词"
        return result

    all_items: list[dict] = []
    seen_titles: set[str] = set()

    for src in _PM_SOURCES:
        items = _sogou_site_search(
            keyword, src["site"], src["name"],
            limit=8, timeout=min(timeout, 10)
        )
        added = 0
        for it in items:
            key = it["title"][:30]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            all_items.append(it)
            added += 1
        if added > 0:
            result["sources"].append(src["name"])

    result["items"] = all_items[:20]
    return result
