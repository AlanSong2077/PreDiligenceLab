"""
biz_lookup.py — 工商信息尽调后端（重构版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
数据来源（全部公开免费，无需登录）：

  1. 东方财富搜索 API  searchapi.eastmoney.com
     - 通过公司名称/关键词搜索股票代码（A股/港股/美股）

  2. 新浪财经公司资料  money.finance.sina.com.cn
     - 上市公司基本信息（名称/成立日期/注册资本/注册地址/董事会秘书等）

  3. 东方财富 F10 公司概况  datacenter-web.eastmoney.com
     - 上市公司行业/主营业务/员工人数等补充信息

  4. 全国法院失信被执行人  zxgk.court.gov.cn
     - 失信被执行人查询（企业名称）

  5. 中国裁判文书网  wenshu.court.gov.cn
     - 企业相关裁判文书

注意：
  - 国家企业信用信息公示系统（gsxt.gov.cn）已启用 Cloudflare 防护，
    直接请求返回 521，无法访问。
  - 非上市公司仅能查询失信/裁判文书，基本工商信息需用户自行查询。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re
import time
import json
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logger import get_logger

_log = get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# HTTP Session
# ─────────────────────────────────────────────────────────────

def _make_session(referer: str = "") -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if referer:
        s.headers["Referer"] = referer
    return s


# ─────────────────────────────────────────────────────────────
# 1. 东方财富搜索：公司名称 → 股票代码
# ─────────────────────────────────────────────────────────────

_EM_SEARCH_URL = (
    "https://searchapi.eastmoney.com/api/suggest/get"
    "?input={keyword}&type=14"
    "&token=D43BF722C8E33BDC906FB84D85E326E8&count=10"
)

def search_stock_code(company_name: str, timeout: int = 8) -> list:
    """
    通过公司名称/关键词搜索股票代码。
    返回列表，每项：{code, name, market, quote_id}
    """
    sess = _make_session("https://www.eastmoney.com/")
    try:
        import urllib.parse
        url = _EM_SEARCH_URL.format(keyword=urllib.parse.quote(company_name))
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        items = (data.get("QuotationCodeTable") or {}).get("Data") or []
        result = []
        for it in items[:10]:
            result.append({
                "code":     it.get("Code", ""),
                "name":     it.get("Name", ""),
                "market":   it.get("SecurityTypeName", ""),
                "quote_id": it.get("QuoteID", ""),
                "classify": it.get("Classify", ""),
            })
        return result
    except Exception as e:
        _log.warning("search_stock_code failed: %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# 2. 新浪财经：上市公司基本信息
# ─────────────────────────────────────────────────────────────

_SINA_CORP_URL = (
    "https://money.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{code}.phtml"
)

def _sina_corp_info(stock_code: str, timeout: int = 12) -> dict:
    """
    通过股票代码查询新浪财经公司资料。
    返回：{name, est_date, reg_capital, reg_address, biz_scope,
           legal_person, secretary, phone, email, listing_date,
           listing_market, industry, employees}
    """
    sess = _make_session("https://finance.sina.com.cn/")
    try:
        url = _SINA_CORP_URL.format(code=stock_code)
        r = sess.get(url, timeout=timeout)
        r.raise_for_status()
        html = r.content.decode("gb2312", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        # 找主要信息表格（通常是第3或第4个表格）
        info = {}
        tables = soup.find_all("table")
        for tbl in tables:
            rows = tbl.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                # 解析 key-value 对（每行通常是 label | value | label | value）
                for i in range(0, len(cells) - 1, 2):
                    key = cells[i].rstrip("：:").strip()
                    val = cells[i + 1].strip() if i + 1 < len(cells) else ""
                    if key and val and len(key) < 20:
                        info[key] = val

        # 字段映射
        result = {
            "name":           info.get("公司名称", ""),
            "est_date":       info.get("成立日期", ""),
            "reg_capital":    info.get("注册资本", ""),
            "reg_address":    info.get("注册地址", ""),
            "biz_scope":      info.get("经营范围", "")[:500],
            "legal_person":   info.get("法定代表人", info.get("董事长", "")),
            "secretary":      info.get("董事会秘书", ""),
            "phone":          info.get("公司电话", ""),
            "email":          info.get("公司电子邮箱", ""),
            "listing_date":   info.get("上市日期", ""),
            "listing_market": info.get("上市市场", ""),
            "industry":       info.get("所属行业", info.get("行业", "")),
            "employees":      info.get("员工人数", ""),
            "stock_code":     stock_code,
            "credit_code":    info.get("统一社会信用代码", ""),
            "status":         "上市公司",
        }
        return result
    except Exception as e:
        _log.warning("_sina_corp_info(%s) failed: %s", stock_code, e)
        return {}


# ─────────────────────────────────────────────────────────────
# 3. 东方财富 F10：补充公司概况
# ─────────────────────────────────────────────────────────────

def _em_company_profile(quote_id: str, timeout: int = 10) -> dict:
    """
    通过东方财富 datacenter 拉取公司概况补充信息。
    quote_id 格式：1.600519（市场.代码）
    """
    sess = _make_session("https://data.eastmoney.com/")
    try:
        # 拆分市场和代码
        parts = quote_id.split(".")
        if len(parts) != 2:
            return {}
        mkt, code = parts

        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?reportName=RPT_F10_ORG_BASICINFO"
            "&columns=ALL"
            f"&filter=(SECURITY_CODE=\"{code}\")"
            "&pageNumber=1&pageSize=1&source=WEB&client=WEB"
        )
        r = sess.get(url, timeout=timeout)
        d = r.json()
        rows = (d.get("result") or {}).get("data") or []
        if not rows:
            return {}
        row = rows[0]
        return {
            "main_business": row.get("MAIN_BUSINESS", ""),
            "employees":     row.get("EMP_NUM", ""),
            "website":       row.get("ORG_WEB", ""),
            "province":      row.get("ORG_PROVINCE", ""),
            "city":          row.get("ORG_CITY", ""),
        }
    except Exception as e:
        _log.warning("_em_company_profile failed: %s", e)
        return {}


# ─────────────────────────────────────────────────────────────
# 4. 全国法院失信被执行人
# ─────────────────────────────────────────────────────────────

_COURT_DISHONEST_API = "https://zxgk.court.gov.cn/zhzxgk/queryZxr.do"

def query_dishonest(name: str, timeout: int = 10) -> list:
    """
    查询失信被执行人（企业名称或自然人姓名）。
    返回列表，每项：{name, case_code, court, publish_date, reason}
    """
    sess = _make_session("https://zxgk.court.gov.cn/")
    try:
        sess.get("https://zxgk.court.gov.cn/zhzxgk/", timeout=6)
        time.sleep(0.3)
        payload = {
            "pName":       name,
            "pCardNum":    "",
            "pProvince":   "0",
            "currentPage": "1",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }
        r = sess.post(_COURT_DISHONEST_API, data=payload,
                      headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        rows = data.get("result") or data.get("data") or []
        result = []
        for row in rows[:20]:
            result.append({
                "name":         row.get("iname", name),
                "case_code":    row.get("caseCode", ""),
                "court":        row.get("courtName", ""),
                "publish_date": row.get("publishDate", ""),
                "reason":       row.get("performance", ""),
            })
        return result
    except Exception as e:
        _log.warning("query_dishonest failed: %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# 5. 中国裁判文书网
# ─────────────────────────────────────────────────────────────

_WENSHU_API = "https://wenshu.court.gov.cn/website/parse/rest.q4w"

def query_court_cases(name: str, timeout: int = 12) -> list:
    """
    查询企业相关裁判文书（近期，最多20条）。
    返回列表，每项：{title, case_no, court, date, doc_type, url}
    """
    sess = _make_session("https://wenshu.court.gov.cn/")
    try:
        sess.get("https://wenshu.court.gov.cn/", timeout=6)
        time.sleep(0.5)
        payload = {
            "pageNum":   "1",
            "pageSize":  "20",
            "sortType":  "1",
            "ciphertext": "",
            "queryCondition": json.dumps([
                {"key": "searchWord", "value": name}
            ]),
            "cfg": "com.lawyee.judge.dc.parse.dto.SearchDataDsoDTO@@queryDoc",
            "__RequestVerificationToken": "",
        }
        r = sess.post(_WENSHU_API, data=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        rows = (data.get("Result") or
                data.get("result") or
                (data.get("data") or {}).get("list") or [])
        result = []
        for row in rows[:20]:
            result.append({
                "title":    row.get("案件名称") or row.get("title", ""),
                "case_no":  row.get("案号")    or row.get("caseNo", ""),
                "court":    row.get("法院名称") or row.get("court", ""),
                "date":     row.get("裁判日期") or row.get("date", ""),
                "doc_type": row.get("文书类型") or row.get("docType", ""),
                "url": (
                    "https://wenshu.court.gov.cn/website/wenshu/181107ANFZ0BXSK4/"
                    f"index.html?docId={row.get('文书ID') or row.get('docId','')}"
                ),
            })
        return result
    except Exception as e:
        _log.warning("query_court_cases failed: %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# 主入口：综合尽调
# ─────────────────────────────────────────────────────────────

def full_due_diligence(company_name: str, timeout: int = 20) -> dict:
    """
    对目标企业执行综合工商尽调。

    流程：
      1. 东方财富搜索 → 找股票代码（上市公司）
      2. 新浪财经 → 公司基本信息（上市公司）
      3. 东方财富 F10 → 补充主营业务/员工数等
      4. 失信被执行人查询
      5. 裁判文书查询
      6. 自动生成风险标记

    返回：
    {
        "basic":       {...},   # 工商基本信息
        "candidates":  [...],   # 搜索到的候选公司列表
        "dishonest":   [...],   # 失信被执行人记录
        "cases":       [...],   # 裁判文书
        "risk_flags":  [...],   # 风险标记列表
        "is_listed":   bool,    # 是否为上市公司
        "error":       str|None,
    }
    """
    result = {
        "basic":      {},
        "candidates": [],
        "dishonest":  [],
        "cases":      [],
        "risk_flags": [],
        "is_listed":  False,
        "error":      None,
    }

    # ── 1. 搜索股票代码 ───────────────────────────────────────
    candidates = search_stock_code(company_name, timeout=timeout)
    result["candidates"] = candidates

    # 找最匹配的上市公司（A股优先）
    best = None
    for c in candidates:
        if c.get("classify") in ("AStock", "HK", "OTCBB"):
            # 名称完全匹配或包含
            if company_name in c["name"] or c["name"] in company_name:
                best = c
                break
    if best is None and candidates:
        best = candidates[0]

    # ── 2. 上市公司：新浪财经公司资料 ────────────────────────
    if best:
        code = best.get("code", "")
        classify = best.get("classify", "")

        if classify == "AStock" and code:
            basic = _sina_corp_info(code, timeout=timeout)
            if basic:
                result["basic"] = basic
                result["is_listed"] = True

                # 补充东方财富 F10 信息
                quote_id = best.get("quote_id", "")
                if quote_id:
                    profile = _em_company_profile(quote_id, timeout=timeout)
                    if profile:
                        result["basic"].update({
                            k: v for k, v in profile.items()
                            if v and not result["basic"].get(k)
                        })
        elif classify == "HK" and code:
            # 港股：基本信息有限
            result["basic"] = {
                "name":     best.get("name", company_name),
                "stock_code": code,
                "market":   "港股",
                "status":   "上市公司（港股）",
            }
            result["is_listed"] = True

    if not result["basic"]:
        result["basic"] = {
            "name":   company_name,
            "status": "未找到上市公司信息（可能为非上市公司）",
            "note":   "非上市公司工商信息请访问 https://www.gsxt.gov.cn 查询",
        }

    # ── 3. 失信被执行人 ───────────────────────────────────────
    result["dishonest"] = query_dishonest(company_name, timeout=timeout)

    # ── 4. 裁判文书 ───────────────────────────────────────────
    result["cases"] = query_court_cases(company_name, timeout=timeout)

    # ── 5. 风险标记 ───────────────────────────────────────────
    flags = []
    if not result["is_listed"]:
        flags.append("⚠️ 未找到上市公司信息，工商基本信息不完整")
    if result["dishonest"]:
        flags.append(f"🔴 存在失信被执行人记录（{len(result['dishonest'])} 条）")
    if len(result["cases"]) >= 5:
        flags.append(f"🟡 裁判文书较多（{len(result['cases'])} 条），存在较高诉讼风险")
    elif result["cases"]:
        flags.append(f"🟡 存在裁判文书记录（{len(result['cases'])} 条）")
    result["risk_flags"] = flags

    return result
