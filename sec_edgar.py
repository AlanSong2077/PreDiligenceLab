"""
sec_edgar.py — SEC EDGAR 美股公开数据查询模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
完全免费，无需注册，官方开放 API。
数据来源：https://data.sec.gov / https://efts.sec.gov

功能：
  1. 按公司名称 / Ticker 搜索，获取 CIK
  2. 公司基本信息（SIC 行业、注册州、EIN、地址）
  3. 申报文件列表（10-K / 10-Q / 8-K / DEF 14A / 13F / 13G / 13D）
  4. 股东结构（13F/13G/13D 持仓披露）
  5. 子基金穿透（13F 持仓明细）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re
import time
import datetime
import requests
from typing import Optional
from logger import get_logger

_log = get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────
_BASE        = "https://data.sec.gov"
_EFTS        = "https://efts.sec.gov"
_TICKER_URL  = "https://www.sec.gov/files/company_tickers.json"
_DELAY       = 0.12   # SEC 要求 10 req/s，保守 ~8 req/s
_MAX_RETRY   = 3

_HEADERS = {
    "User-Agent": "PreDiligenceLab/1.0 (alansong2077@gmail.com)",   # SEC 要求标注 User-Agent 含联系方式
    "Accept": "application/json",
}

# SIC 行业代码 → 中文描述（常见行业）
SIC_MAP = {
    "6726": "投资办公室（基金/控股）",
    "6199": "金融服务",
    "6211": "证券经纪商",
    "6282": "投资顾问",
    "6770": "空白支票公司",
    "7372": "预包装软件",
    "7371": "计算机编程服务",
    "3674": "半导体",
    "3711": "汽车整车",
    "2836": "制药",
    "5912": "药品零售",
    "6021": "商业银行",
    "6022": "储蓄机构",
    "6311": "人寿保险",
    "4813": "电话通信",
    "4911": "电力公用事业",
    "1311": "石油天然气勘探",
    "5411": "杂货零售",
    "5731": "电子零售",
}

# 申报类型 → 中文说明
FORM_DESC = {
    "10-K":    "年度报告",
    "10-Q":    "季度报告",
    "8-K":     "重大事项披露",
    "DEF 14A": "股东大会委托书",
    "13F-HR":  "机构持仓报告（季度）",
    "13G":     "大股东被动持仓披露",
    "13D":     "大股东主动持仓披露",
    "SC 13G":  "大股东被动持仓披露",
    "SC 13D":  "大股东主动持仓披露",
    "4":       "内部人交易报告",
    "S-1":     "IPO 注册申请",
    "424B4":   "最终招股说明书",
    "20-F":    "外国私人发行人年报",
    "6-K":     "外国私人发行人半年报/重大事项",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 内部工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get(url: str, params: dict = None, timeout: int = 20) -> dict | list | None:
    """带限流和重试的 GET 请求，返回 JSON 或 None。
    SEC 要求每秒不超过 10 次请求，_DELAY 保守控制在 ~8 req/s。"""
    time.sleep(_DELAY)   # 每次请求前强制间隔，防止触发 SEC 限流
    for attempt in range(_MAX_RETRY):
        try:
            r = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
            if r.status_code == 429:
                wait = 2 ** (attempt + 1)   # 指数退避：2s, 4s, 8s
                _log.warning("SEC API 429 限流，等待 %ds 后重试（第 %d 次）", wait, attempt + 1)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.JSONDecodeError:
            _log.warning("SEC API JSON 解析失败: %s", url)
            return None
        except Exception as e:
            _log.debug("SEC API 请求失败 (attempt %d): %s  url=%s", attempt + 1, e, url)
            if attempt < _MAX_RETRY - 1:
                time.sleep(1 + attempt)
    _log.error("SEC API 请求最终失败: %s", url)
    return None


def _cik_pad(cik: int | str) -> str:
    """CIK 补零到 10 位"""
    return str(int(cik)).zfill(10)


def _ts_to_date(ts_str: str) -> str:
    """EDGAR 日期格式 YYYY-MM-DD，直接返回"""
    return ts_str or ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Ticker / 公司名 → CIK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_TICKER_CACHE: dict = {}   # ticker.upper() → {cik, name, ticker}

def _load_ticker_map() -> dict:
    """加载 SEC 全量 Ticker→CIK 映射（约 12000 条，~1MB，缓存到内存）"""
    global _TICKER_CACHE
    if _TICKER_CACHE:
        return _TICKER_CACHE
    data = _get(_TICKER_URL)
    if not data:
        _log.error("无法加载 SEC Ticker 映射表，可能是网络或 SSL 证书问题")
        return {}
    for item in data.values():
        t = item.get("ticker", "").upper()
        if t:
            _TICKER_CACHE[t] = {
                "cik":    _cik_pad(item["cik_str"]),
                "name":   item.get("title", ""),
                "ticker": t,
            }
    return _TICKER_CACHE


def search_company(keyword: str) -> list[dict]:
    """
    按 Ticker 或公司名称搜索，返回候选列表。
    每项：{cik, name, ticker, match_type}
    """
    keyword = keyword.strip()
    results = []

    # 1) 精确 Ticker 匹配
    tmap = _load_ticker_map()
    upper = keyword.upper()
    if upper in tmap:
        item = dict(tmap[upper])
        item["match_type"] = "ticker_exact"
        results.append(item)
        return results

    # 2) EDGAR 全文搜索（公司名）
    data = _get(
        f"{_EFTS}/LATEST/search-index",
        params={"q": f'"{keyword}"', "dateRange": "custom",
                "startdt": "1993-01-01", "forms": "10-K"},
    )
    seen_cik = set()
    if data and "hits" in data:
        for hit in data["hits"].get("hits", [])[:10]:
            src = hit.get("_source", {})
            cik = _cik_pad(src.get("entity_id", 0))
            if cik in seen_cik:
                continue
            seen_cik.add(cik)
            results.append({
                "cik":        cik,
                "name":       src.get("display_names", [keyword])[0] if src.get("display_names") else keyword,
                "ticker":     src.get("file_date", ""),
                "match_type": "fulltext",
            })

    # 3) 公司名模糊匹配（Ticker 表）
    kw_lower = keyword.lower()
    for t, item in tmap.items():
        if kw_lower in item["name"].lower() and item["cik"] not in seen_cik:
            seen_cik.add(item["cik"])
            r = dict(item)
            r["match_type"] = "name_fuzzy"
            results.append(r)
            if len(results) >= 20:
                break

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 公司基本信息
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_company_info(cik: str) -> dict:
    """
    获取公司基本信息。
    返回字段：name, cik, ticker, sic, sic_desc, state_of_inc,
              state_of_location, fiscal_year_end, ein, category,
              addresses (mailing / business), exchanges, tickers
    """
    cik = _cik_pad(cik)
    data = _get(f"{_BASE}/submissions/CIK{cik}.json")
    if not data:
        return {"error": f"未找到 CIK={cik} 的公司信息"}

    sic = str(data.get("sic", ""))
    sic_desc = SIC_MAP.get(sic, data.get("sicDescription", sic))

    # 地址
    addrs = data.get("addresses", {})
    mailing = addrs.get("mailing", {})
    business = addrs.get("business", {})

    def fmt_addr(a: dict) -> str:
        parts = [a.get("street1",""), a.get("street2",""),
                 a.get("city",""), a.get("stateOrCountry",""), a.get("zipCode","")]
        return ", ".join(p for p in parts if p)

    # Tickers & Exchanges
    tickers_raw = data.get("tickers", [])
    exchanges    = data.get("exchanges", [])

    return {
        "name":             data.get("name", ""),
        "cik":              cik,
        "tickers":          tickers_raw,
        "exchanges":        exchanges,
        "sic":              sic,
        "sic_desc":         sic_desc,
        "state_of_inc":     data.get("stateOfIncorporation", ""),
        "state_of_location":data.get("stateOfIncorporationDescription", ""),
        "fiscal_year_end":  data.get("fiscalYearEnd", ""),
        "ein":              data.get("ein", ""),
        "category":         data.get("category", ""),
        "entity_type":      data.get("entityType", ""),
        "mailing_addr":     fmt_addr(mailing),
        "business_addr":    fmt_addr(business),
        "phone":            data.get("phone", ""),
        "description":      data.get("description", ""),
        "_raw":             data,   # 保留原始数据供穿透使用
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 申报文件列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_filings(cik: str,
                form_types: list[str] = None,
                limit: int = 50) -> list[dict]:
    """
    获取公司申报文件列表。
    form_types: 如 ["10-K","10-Q","8-K"]，None 表示全部
    返回列表，每项：{form, date, description, accession_no, url}
    """
    cik = _cik_pad(cik)
    data = _get(f"{_BASE}/submissions/CIK{cik}.json")
    if not data:
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms       = recent.get("form", [])
    dates       = recent.get("filingDate", [])
    descs       = recent.get("primaryDocument", [])
    accessions  = recent.get("accessionNumber", [])
    doc_descs   = recent.get("primaryDocDescription", [])

    results = []
    for i, form in enumerate(forms):
        if form_types and form not in form_types:
            continue
        acc = accessions[i] if i < len(accessions) else ""
        acc_clean = acc.replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
               f"{acc_clean}/{descs[i]}" if acc and i < len(descs) else "")
        results.append({
            "form":         form,
            "form_desc":    FORM_DESC.get(form, form),
            "date":         dates[i] if i < len(dates) else "",
            "description":  doc_descs[i] if i < len(doc_descs) else "",
            "accession_no": acc,
            "url":          url,
            "viewer_url":   (f"https://www.sec.gov/cgi-bin/browse-edgar?"
                             f"action=getcompany&CIK={int(cik)}&type={form}&dateb=&owner=include&count=10")
                            if not url else "",
        })
        if len(results) >= limit:
            break

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 股东结构（13F / 13G / 13D）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_shareholders(cik: str, limit: int = 30) -> list[dict]:
    """
    获取大股东披露（SC 13G / SC 13D）。
    注意：这是该公司被其他机构持有的披露，需要搜索 EDGAR 全文。
    返回：[{filer_name, form, date, shares_pct, url}]
    """
    cik = _cik_pad(cik)
    # 搜索针对该公司的 13G/13D 申报
    data = _get(
        f"{_EFTS}/LATEST/search-index",
        params={
            "q":       f'"{int(cik)}"',
            "forms":   "SC 13G,SC 13D,SC 13G/A,SC 13D/A",
            "dateRange": "custom",
            "startdt": "2020-01-01",
        }
    )
    results = []
    if not data:
        return results

    for hit in data.get("hits", {}).get("hits", [])[:limit]:
        src = hit.get("_source", {})
        acc = src.get("accession_no", "").replace("-", "")
        cik_filer = src.get("entity_id", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik_filer}/{acc}/"
               if acc and cik_filer else "")
        results.append({
            "filer_name": src.get("display_names", [""])[0] if src.get("display_names") else "",
            "form":       src.get("form_type", ""),
            "date":       src.get("file_date", ""),
            "shares_pct": "",   # 需解析 XML 才能获取，此处留空
            "url":        url,
        })

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 机构持仓穿透（13F-HR）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_13f_holdings(cik: str, latest_only: bool = True) -> list[dict]:
    """
    获取机构投资者的 13F 持仓明细（该机构持有哪些股票）。
    适用于：基金公司、资产管理公司等需要申报 13F 的机构。
    返回：[{issuer_name, cusip, shares, value_usd, pct_of_portfolio, report_date}]
    """
    cik = _cik_pad(cik)
    # 先获取最新 13F 申报
    filings = get_filings(cik, form_types=["13F-HR"], limit=5)
    if not filings:
        return []

    target = filings[0] if latest_only else filings
    if latest_only:
        target = [filings[0]]

    all_holdings = []
    for filing in target:
        acc = filing["accession_no"].replace("-", "")
        if not acc:
            continue

        # 获取申报文件索引
        idx_url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                   f"{acc}/{filing['accession_no']}-index.json")
        idx_data = _get(idx_url)
        if not idx_data:
            continue

        # 找 infotable.xml
        xml_file = None
        for doc in idx_data.get("directory", {}).get("item", []):
            name = doc.get("name", "")
            if "infotable" in name.lower() and name.endswith(".xml"):
                xml_file = name
                break

        if not xml_file:
            continue

        xml_url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                   f"{acc}/{xml_file}")
        try:
            r = requests.get(xml_url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            xml_text = r.text
        except Exception:
            continue

        # 简单正则解析 XML（避免依赖 lxml）
        holdings = _parse_13f_xml(xml_text, filing["date"])
        all_holdings.extend(holdings)
        time.sleep(_DELAY)

    return all_holdings


def _parse_13f_xml(xml: str, report_date: str) -> list[dict]:
    """解析 13F infotable XML，提取持仓明细"""
    results = []
    # 匹配每个 <infoTable> 块
    blocks = re.findall(r"<infoTable>(.*?)</infoTable>", xml, re.DOTALL | re.IGNORECASE)
    for block in blocks:
        def _tag(name: str) -> str:
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else ""

        name    = _tag("nameOfIssuer")
        cusip   = _tag("cusip")
        value   = _tag("value")
        shares  = _tag("sshPrnamt")
        sh_type = _tag("sshPrnamtType")

        try:
            value_int = int(value) * 1000  # 13F 单位是千美元
        except Exception:
            value_int = 0

        try:
            shares_int = int(shares)
        except Exception:
            shares_int = 0

        if name:
            results.append({
                "issuer_name":  name,
                "cusip":        cusip,
                "shares":       shares_int,
                "share_type":   sh_type,
                "value_usd":    value_int,
                "report_date":  report_date,
            })

    # 计算占比
    total_val = sum(h["value_usd"] for h in results)
    for h in results:
        h["pct_of_portfolio"] = (
            round(h["value_usd"] / total_val * 100, 2) if total_val else 0
        )

    # 按持仓市值降序
    results.sort(key=lambda x: -x["value_usd"])
    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 子基金穿透（基金公司 → 旗下子基金）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_fund_series(cik: str) -> list[dict]:
    """
    获取基金公司旗下的所有子基金（Series）。
    适用于：共同基金、ETF 发行人（SIC=6726）。
    返回：[{series_id, series_name, status, classes}]
    """
    cik = _cik_pad(cik)
    data = _get(f"{_BASE}/submissions/CIK{cik}.json")
    if not data:
        return []

    series_list = []
    for s in data.get("series", []):
        classes = []
        for cls in s.get("classes", []):
            classes.append({
                "class_id":   cls.get("classId", ""),
                "class_name": cls.get("name", ""),
                "ticker":     cls.get("ticker", ""),
                "status":     cls.get("status", ""),
            })
        series_list.append({
            "series_id":   s.get("seriesId", ""),
            "series_name": s.get("name", ""),
            "status":      s.get("status", ""),
            "classes":     classes,
            "class_count": len(classes),
        })

    return series_list


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. 综合尽调报告（一次性获取所有关键信息）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_full_dd_report(cik: str) -> dict:
    """
    综合尽调：公司信息 + 最近申报 + 子基金列表（如有）
    返回结构化 dict，供 UI 展示。
    """
    cik = _cik_pad(cik)
    info = get_company_info(cik)
    if "error" in info:
        return info

    # 申报文件（重点类型）
    key_forms = ["10-K", "10-Q", "8-K", "DEF 14A", "13F-HR",
                 "SC 13G", "SC 13D", "20-F", "6-K", "S-1"]
    filings = get_filings(cik, form_types=key_forms, limit=60)

    # 子基金（仅基金公司）
    series = []
    if info.get("sic") in ("6726", "6199", "6282"):
        series = get_fund_series(cik)

    return {
        "info":    info,
        "filings": filings,
        "series":  series,
    }
