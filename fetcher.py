"""
fetcher.py  —  股票年报 & 财报日期查询核心模块
支持：美股(SEC EDGAR 10-K)、港股(HKEXnews)、A股(巨潮资讯)
"""

import re
import os
import json
import time
import datetime
import calendar
import requests
from pathlib import Path

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

HEADERS_XHR = {
    **HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# ─────────────────────────────────────────────
# 市场识别（统一从 market_utils 导入）
# ─────────────────────────────────────────────
from market_utils import detect_market, normalize_code, _SUFFIX_RE, _SUFFIX_MARKET  # noqa: F401


# ─────────────────────────────────────────────
# 美股  —  SEC EDGAR
# ─────────────────────────────────────────────

def _edgar_cik(ticker: str) -> tuple[str, str]:
    """通过 ticker 查 CIK 和公司名"""
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "PreDiligenceLab/1.0 121917266+AlanHermitSoong@users.noreply.github.com"},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        for item in data.values():
            if item.get("ticker", "").upper() == ticker.upper():
                return str(item["cik_str"]).zfill(10), item.get("title", ticker)
    except requests.exceptions.SSLError as e:
        import logging
        logging.getLogger(__name__).error("SSL 证书验证失败，请检查网络或证书: %s", e)
        return "__SSL_ERROR__", str(e)
    except requests.exceptions.ConnectionError as e:
        import logging
        logging.getLogger(__name__).error("网络连接失败: %s", e)
        return "__CONN_ERROR__", str(e)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("SEC CIK 查询异常: %s", e)
    return "", ""


def fetch_us_annual_reports(ticker: str, save_dir: Path, max_count: int = 3) -> dict:
    result = {
        "market": "美股 (US)",
        "ticker": ticker,
        "company": "",
        "filings": [],          # 年报 + 季报混合列表
        "next_earnings": None,
        "next_earnings_type": "",   # 新增：下次财报类型（季报/年报）
        "next_earnings_source": "",
        "error": None,
    }

    cik, company = _edgar_cik(ticker)
    if not cik:
        result["error"] = f"未找到 {ticker} 的 SEC CIK，请确认股票代码"
        return result
    if cik.startswith("__SSL_ERROR__"):
        result["error"] = f"网络 SSL 证书错误，无法连接 SEC 服务器。请检查网络连接后重试。\n详情: {company}"
        return result
    if cik.startswith("__CONN_ERROR__"):
        result["error"] = f"无法连接 SEC 服务器，请检查网络连接。\n详情: {company}"
        return result

    result["company"] = company

    try:
        sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(
            sub_url,
            headers={"User-Agent": "PreDiligenceLab/1.0 121917266+AlanHermitSoong@users.noreply.github.com"},
            timeout=15
        )
        sub = r.json()
        if not result["company"]:
            result["company"] = sub.get("name", ticker)

        filings_data = sub.get("filings", {}).get("recent", {})
        forms        = filings_data.get("form", [])
        dates        = filings_data.get("filingDate", [])
        accessions   = filings_data.get("accessionNumber", [])
        primary_docs = filings_data.get("primaryDocument", [])

        # 年报（10-K / 20-F）和季报（10-Q）分别收集
        annual_filings  = []
        quarter_filings = []
        for i, form in enumerate(forms):
            acc = accessions[i].replace("-", "")
            doc = primary_docs[i] if i < len(primary_docs) else ""
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(cik)}/{acc}/{doc}"
            )
            entry = {
                "form": form,
                "date": dates[i],
                "title": f"{form} — {dates[i]}",
                "url": filing_url,
                "accession": accessions[i],
                "downloaded": False,
            }
            if form in ("10-K", "10-K/A", "20-F"):
                if len(annual_filings) < max_count:
                    annual_filings.append(entry)
            elif form in ("10-Q", "10-Q/A"):
                if len(quarter_filings) < max_count:
                    quarter_filings.append(entry)
            # 两类都够了就停
            if len(annual_filings) >= max_count and len(quarter_filings) >= max_count:
                break

        # 合并：年报在前，季报在后
        result["filings"] = annual_filings + quarter_filings

    except Exception as e:
        result["error"] = f"SEC EDGAR 查询失败: {e}"
        return result

    # 下次财报日期（Yahoo Finance）
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        cal = tk.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            ed = cal.loc["Earnings Date"]
            dates_list = ed.tolist() if hasattr(ed, 'tolist') else [ed]
            today = datetime.date.today()
            future = [d for d in dates_list if hasattr(d, 'date') and d.date() >= today]
            if future:
                result["next_earnings"] = future[0].strftime("%Y-%m-%d")
                result["next_earnings_source"] = "Yahoo Finance"
                # 判断是季报还是年报（美股通常每季度披露）
                result["next_earnings_type"] = _guess_us_report_type(ticker, future[0])
    except Exception:
        pass

    return result


def _guess_us_report_type(ticker: str, next_date: datetime.date) -> str:
    """根据财年结束月份推断下次财报是季报还是年报"""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        fiscal_year_end = info.get("fiscalYearEnd", "")  # 如 "December"
        month_map = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12,
        }
        fy_end_month = month_map.get(fiscal_year_end, 12)
        # 用 calendar.monthrange 取真实月末日
        last_day = calendar.monthrange(next_date.year, fy_end_month)[1]
        fy_end = datetime.date(next_date.year, fy_end_month, last_day)
        delta = abs((next_date - fy_end).days)
        if delta <= 75:
            return "年报 (10-K)"
    except Exception:
        pass
    return "季报 (10-Q)"


_WIN_ILLEGAL = re.compile(r'[\\/:*?"<>|]')

def _safe_filename(s: str) -> str:
    """过滤 Windows 非法文件名字符"""
    return _WIN_ILLEGAL.sub('_', s)


def download_us_filing(filing: dict, save_dir: Path) -> tuple[bool, str]:
    try:
        url = filing["url"]
        r = requests.get(
            url,
            headers={"User-Agent": "PreDiligenceLab/1.0 121917266+AlanHermitSoong@users.noreply.github.com"},
            timeout=60, stream=True
        )
        r.raise_for_status()
        ct  = r.headers.get("Content-Type", "")
        ext = ".pdf" if "pdf" in ct else ".htm"
        fname = _safe_filename(f"{filing.get('form','10-K')}_{filing['date']}{ext}")
        fpath = save_dir / fname
        with open(fpath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True, str(fpath)
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# 港股  —  HKEXnews (披露易) + akshare
# ─────────────────────────────────────────────

def fetch_hk_annual_reports(code: str, save_dir: Path, max_count: int = 3) -> dict:
    result = {
        "market": "港股 (HK)",
        "ticker": code,
        "company": "",
        "filings": [],          # 年报 + 中期报告混合列表
        "next_earnings": None,
        "next_earnings_type": "",   # 新增：年报 / 中期报告
        "next_earnings_source": "",
        "error": None,
    }

    stock_code = code.zfill(5)

    # 1. 获取公司名（akshare）
    try:
        import akshare as ak
        df = ak.stock_hk_company_profile_em(symbol=stock_code)
        if not df.empty:
            result["company"] = df.iloc[0].get("公司名称", "")
    except Exception:
        pass

    # 2. 查询报告列表（HKEXnews）—— 年报 + 中期报告各取 max_count 条
    def _hkex_query(t2code: str, form_label: str) -> list:
        """通用 HKEXnews 查询，返回 filing 列表"""
        filings = []
        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            session.get("https://www1.hkexnews.hk/search/titlesearch.xhtml", timeout=10)
            r = session.post(
                "https://www1.hkexnews.hk/search/titlesearch.xhtml",
                data={
                    "lang": "ZH", "category": "0", "market": "SEHK",
                    "searchType": "1", "documentNo": "", "stockId": stock_code,
                    "from": "", "to": "", "MB-Daterange": "0", "title": "",
                    "t1code": "40000", "t2Gcode": "-2", "t2code": t2code,
                    "rowRange": "ALL", "action": "getResult",
                },
                headers={
                    **HEADERS_XHR,
                    "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                timeout=20
            )
            ct = r.headers.get("Content-Type", "")
            if "json" in ct:
                items = r.json().get("result", [])
                for item in items[:max_count]:
                    file_link = item.get("FILE_LINK", "")
                    if file_link and not file_link.startswith("http"):
                        file_link = "https://www1.hkexnews.hk" + file_link
                    filings.append({
                        "form": form_label,
                        "date": item.get("DATE_TIME", "")[:10],
                        "title": item.get("TITLE", form_label),
                        "url": file_link,
                        "downloaded": False,
                    })
                    if not result["company"] and item.get("STOCK_NAME"):
                        result["company"] = item["STOCK_NAME"]
        except Exception:
            pass
        return filings

    annual_filings = _hkex_query("ANNRPT", "年报")
    interim_filings = _hkex_query("INTRIM", "中期报告")

    # 合并：年报在前，中期报告在后
    result["filings"] = annual_filings + interim_filings

    # 如果完全没有，提供直接链接
    if not result["filings"]:
        result["filings"] = [{
            "form": "年报",
            "date": "—",
            "title": "点击在披露易查看报告",
            "url": (
                f"https://www1.hkexnews.hk/search/titlesearch.xhtml"
                f"?lang=ZH&stockId={stock_code}&t2code=ANNRPT"
            ),
            "downloaded": False,
            "is_link_only": True,
        }]

    # 3. 下次财报日期（Yahoo Finance 优先）
    try:
        import yfinance as yf
        hk_code = code.lstrip("0") or "0"
        tk = yf.Ticker(hk_code + ".HK")
        cal = tk.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            ed = cal.loc["Earnings Date"]
            dates_list = ed.tolist() if hasattr(ed, 'tolist') else [ed]
            today = datetime.date.today()
            future = [d for d in dates_list if hasattr(d, 'date') and d.date() >= today]
            if future:
                result["next_earnings"] = future[0].strftime("%Y-%m-%d")
                result["next_earnings_source"] = "Yahoo Finance"
                result["next_earnings_type"] = _guess_hk_report_type(future[0])
    except Exception:
        pass

    # 港股监管规则兜底（上市规则截止日）
    if not result["next_earnings"]:
        today = datetime.date.today()
        year = today.year
        # (截止日, 报告类型, 来源说明)
        deadlines = [
            (datetime.date(year, 4, 30),     "年报",   f"{year}年 年报披露截止日（上市规则）"),
            (datetime.date(year, 8, 31),     "中期报告", f"{year}年 中期业绩截止日（上市规则）"),
            (datetime.date(year + 1, 4, 30), "年报",   f"{year+1}年 年报披露截止日（上市规则）"),
        ]
        for d, rtype, label in deadlines:
            if d >= today:
                result["next_earnings"] = d.strftime("%Y-%m-%d")
                result["next_earnings_type"] = rtype
                result["next_earnings_source"] = label
                break

    return result


def _guess_hk_report_type(next_date: datetime.date) -> str:
    """根据月份推断港股下次财报类型（港股通常 3-4 月年报，8-9 月中期）"""
    m = next_date.month
    if m in (3, 4, 5):
        return "年报"
    if m in (8, 9, 10):
        return "中期报告"
    return "业绩公告"


def _parse_hkex_html(html: str, result: dict, stock_code: str, max_count: int):
    """从 HKEXnews HTML 中解析年报链接"""
    from html.parser import HTMLParser

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []
            self._in_result = False

        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            if tag == "a" and href and (".pdf" in href.lower() or "annrpt" in href.lower()):
                full = href if href.startswith("http") else "https://www1.hkexnews.hk" + href
                self.links.append(full)

    parser = LinkParser()
    parser.feed(html)

    for i, link in enumerate(parser.links[:max_count]):
        result["filings"].append({
            "form": "年报",
            "date": "—",
            "title": f"年报文件 {i+1}",
            "url": link,
            "downloaded": False,
        })


def download_hk_filing(filing: dict, save_dir: Path) -> tuple[bool, str]:
    if filing.get("is_link_only"):
        return False, "请在浏览器中访问该链接下载"
    try:
        url = filing["url"]
        if not url.startswith("http"):
            return False, "无效下载链接"
        r = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        title = _safe_filename(filing.get("title", "年报")[:40].replace(" ", "_"))
        date  = filing.get("date", "unknown")
        fname = f"HK_{date}_{title}.pdf"
        fpath = save_dir / fname
        with open(fpath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True, str(fpath)
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# A股  —  巨潮资讯 (cninfo.com.cn)
# ─────────────────────────────────────────────

def _cninfo_orgid(code: str) -> tuple[str, str, str]:
    """通过巨潮 API 查询 orgId、公司名、交易所"""
    try:
        r = requests.post(
            "https://www.cninfo.com.cn/new/information/topSearch/query",
            data={"keyWord": code, "maxNum": "5"},
                headers={
                    **HEADERS_XHR,
                    "Referer": "https://www.cninfo.com.cn/new/index",
                },
            timeout=10
        )
        items = r.json()
        for item in items:
            if item.get("code") == code:
                exchange = "sse" if item.get("type", "").startswith("sh") else "szse"
                return item.get("orgId", ""), item.get("zwjc", ""), exchange
        if items:
            item = items[0]
            exchange = "sse" if item.get("type", "").startswith("sh") else "szse"
            return item.get("orgId", ""), item.get("zwjc", ""), exchange
    except Exception:
        pass
    return "", "", ""


def fetch_cn_annual_reports(code: str, save_dir: Path, max_count: int = 3) -> dict:
    result = {
        "market": "A股 (CN)",
        "ticker": code,
        "company": "",
        "filings": [],          # 年报 + 半年报 + 季报混合列表
        "next_earnings": None,
        "next_earnings_type": "",   # 新增：年报 / 半年报 / 季报
        "next_earnings_source": "",
        "error": None,
    }

    org_id, company, exchange = _cninfo_orgid(code)
    result["company"] = company

    if not org_id:
        result["error"] = f"未找到 {code} 的巨潮信息，请确认股票代码"
        return result

    def _cninfo_query(category: str, form_label: str,
                      keep_kw: list, skip_kw: list) -> list:
        """通用巨潮查询，返回 filing 列表"""
        filings = []
        try:
            r = requests.post(
                "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                data={
                    "stock": f"{code},{org_id}",
                    "tabName": "fulltext",
                    "pageSize": "10",
                    "pageNum": "1",
                    "column": exchange,
                    "category": category,
                    "plate": "", "seDate": "", "searchkey": "",
                    "secid": "", "sortName": "", "sortType": "",
                    "isHLtitle": "true",
                },
                headers={
                    **HEADERS_XHR,
                    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
                },
                timeout=15
            )
            announcements = r.json().get("announcements") or []
            for ann in announcements:
                title = ann.get("announcementTitle", "")
                if not any(kw in title for kw in keep_kw):
                    continue
                if any(kw in title for kw in skip_kw):
                    continue
                adj_url = ann.get("adjunctUrl", "")
                ts = ann.get("announcementTime", 0)
                if isinstance(ts, (int, float)) and ts > 1e10:
                    date_str = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
                else:
                    date_str = str(ts)[:10]
                pdf_url = f"http://static.cninfo.com.cn/{adj_url}" if adj_url else ""
                filings.append({
                    "form": form_label,
                    "date": date_str,
                    "title": title,
                    "url": pdf_url,
                    "downloaded": False,
                })
                if len(filings) >= max_count:
                    break
        except Exception:
            pass
        return filings

    skip_common = ["摘要", "英文", "更正", "补充", "取消"]

    # 年报
    annual = _cninfo_query(
        "category_ndbg_szsh", "年报",
        keep_kw=["年度报告", "年报"],
        skip_kw=skip_common,
    )
    # 半年报
    interim = _cninfo_query(
        "category_bndbg_szsh", "半年报",
        keep_kw=["半年度报告", "半年报", "中期报告"],
        skip_kw=skip_common,
    )
    # 季报（一季报 + 三季报）
    quarterly = _cninfo_query(
        "category_sjdbg_szsh", "季报",
        keep_kw=["季度报告", "季报", "一季报", "三季报"],
        skip_kw=skip_common,
    )

    # 合并：年报 → 半年报 → 季报
    result["filings"] = annual + interim + quarterly

    if result["error"] is None and not result["filings"]:
        result["error"] = "巨潮资讯未返回报告，请稍后重试"

    # 下次财报日期（A股监管规定截止日，精确到报告类型）
    today = datetime.date.today()
    year  = today.year
    # (截止日, 报告类型, 来源说明)
    deadlines = [
        (datetime.date(year, 4, 30),     "年报",  f"{year}年 年报披露截止日（证监会规定）"),
        (datetime.date(year, 8, 31),     "半年报", f"{year}年 半年报披露截止日（证监会规定）"),
        (datetime.date(year, 10, 31),    "三季报", f"{year}年 三季报披露截止日（证监会规定）"),
        (datetime.date(year + 1, 1, 31), "业绩预告", f"{year}年 业绩预告截止日（证监会规定）"),
        (datetime.date(year + 1, 4, 30), "年报",  f"{year+1}年 年报披露截止日（证监会规定）"),
    ]
    for d, rtype, label in deadlines:
        if d >= today:
            result["next_earnings"] = d.strftime("%Y-%m-%d")
            result["next_earnings_type"] = rtype
            result["next_earnings_source"] = label
            break

    return result


def download_cn_filing(filing: dict, save_dir: Path) -> tuple[bool, str]:
    try:
        url = filing["url"]
        if not url.startswith("http"):
            return False, "无效下载链接"
        r = requests.get(
            url,
            headers={**HEADERS, "Referer": "https://www.cninfo.com.cn/"},
            timeout=60, stream=True
        )
        r.raise_for_status()
        title = _safe_filename(filing.get("title", "年报")[:40].replace(" ", "_"))
        date  = filing.get("date", "unknown")
        fname = f"CN_{date}_{title}.pdf"
        fpath = save_dir / fname
        with open(fpath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True, str(fpath)
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# 统一入口
# ─────────────────────────────────────────────

def query_stock(code: str, save_dir: str = None) -> dict:
    code   = code.strip().upper()
    market = detect_market(code)
    norm   = normalize_code(code, market)

    if save_dir is None:
        save_dir = Path.home() / "Downloads" / "PreDiligenceLab"
    else:
        save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if market == "US":
        return fetch_us_annual_reports(norm, save_dir)
    elif market == "HK":
        return fetch_hk_annual_reports(norm, save_dir)
    else:
        return fetch_cn_annual_reports(norm, save_dir)


def download_filing(filing: dict, market: str, save_dir: str) -> tuple[bool, str]:
    p = Path(save_dir)
    p.mkdir(parents=True, exist_ok=True)
    if market == "US":
        return download_us_filing(filing, p)
    elif market == "HK":
        return download_hk_filing(filing, p)
    else:
        return download_cn_filing(filing, p)
