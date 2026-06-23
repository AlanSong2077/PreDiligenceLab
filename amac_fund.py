"""
amac_fund.py — 中基协（AMAC）私募基金查询模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
数据来源：https://gs.amac.org.cn/amac-infodisc/api/pof
完全公开，无需注册。

功能：
  1. 按基金名称 / 管理人名称搜索基金
  2. 查询基金基本信息（管理人、托管人、类型、状态、成立日期等）
  3. 查询基金详情（币种、备案阶段、披露情况、诚信提示等）
  4. 查询管理人信息
  5. 查询管理人旗下所有子基金（穿透一层）
  6. 子基金再穿透（如子基金也是管理人，继续查其下属基金）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re
import time
import datetime
import requests
from typing import Optional

# ── 常量（与 amac_scraper.py 保持一致）────────────────────────────────────────
BASE_URL     = "https://gs.amac.org.cn/amac-infodisc/api/pof"
DETAIL_URL   = "https://gs.amac.org.cn/amac-infodisc/res/pof/fund/{fund_id}.html"
PAGE_SIZE    = 100
DELAY_SEC    = 0.3
DETAIL_DELAY = 0.5
MAX_RETRY    = 3

API_HEADERS = {
    "Content-Type":    "application/json",
    "X-Requested-With":"XMLHttpRequest",
    "Referer":         "https://gs.amac.org.cn/amac-infodisc/res/pof/manager/managerList.html",
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":          "application/json, text/javascript, */*; q=0.01",
    "Origin":          "https://gs.amac.org.cn",
}

HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer":    "https://gs.amac.org.cn/amac-infodisc/res/pof/fund/index.html",
}

# 基金类型代码 → 中文
FUND_TYPE_DECODE = {
    "OT0101": "私募证券投资基金",
    "OT0201": "私募股权投资基金",
    "OT0203": "创业投资基金",
    "OT0301": "其他私募投资基金",
    "OT0401": "私募资产配置基金",
}

# 运作状态代码 → 中文
WORKING_STATE_DECODE = {
    "zzyz": "运作中",
    "zcqs": "正常清算",
    "tqqs": "提前清算",
    "yqqs": "延期清算",
    "yzx":  "已注销",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 内部工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _ts2date(ts) -> str:
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            ts / 1000, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _post_api(endpoint: str, page: int, size: int, body: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}?&page={page}&size={size}"
    session = requests.Session()
    for attempt in range(MAX_RETRY):
        try:
            resp = session.post(url, json=body, headers=API_HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < MAX_RETRY - 1:
                time.sleep((attempt + 1) * 2)
            else:
                raise RuntimeError(f"API 请求失败: {url} -> {e}") from e
    return {}


def _fetch_all(endpoint: str, body: dict, label: str = "记录",
               limit: int = 0, progress_cb=None) -> list:
    """分页获取全量数据"""
    first = _post_api(endpoint, 0, PAGE_SIZE, body)
    total = first.get("totalElements", 0)
    total_pages = first.get("totalPages", 1)
    results = list(first.get("content", []))

    for page in range(1, total_pages):
        if limit and len(results) >= limit:
            break
        data = _post_api(endpoint, page, PAGE_SIZE, body)
        batch = data.get("content", [])
        results.extend(batch)
        if progress_cb:
            progress_cb(len(results), total, label)
        time.sleep(DELAY_SEC)

    if limit:
        results = results[:limit]
    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 基金搜索
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def search_fund(keyword: str, limit: int = 20) -> list[dict]:
    """
    按基金名称关键词搜索基金。
    返回：[{fund_id, fund_name, fund_code, manager_name, fund_type,
             working_state, establish_date, record_date}]
    """
    body = {"keyword": keyword}
    raw = _fetch_all("fund", body, label="基金", limit=limit)
    return [_normalize_fund(f) for f in raw]


def search_manager(keyword: str, limit: int = 20) -> list[dict]:
    """
    按管理人名称关键词搜索管理人。
    返回：[{register_no, manager_name, legal_person, primary_type,
             fund_count, register_date, register_province}]
    """
    body = {"keyword": keyword}
    raw = _fetch_all("manager/query", body, label="管理人", limit=limit)
    return [_normalize_manager(m) for m in raw]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 基金详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_fund_detail(fund_id: str) -> dict:
    """
    获取单只基金详情页信息（HTML 解析）。
    返回：{detail_currency, detail_record_stage, detail_manage_type,
            detail_last_update, detail_month_report, detail_quarter_report,
            detail_half_report, detail_year_report, detail_investor_rate,
            detail_credit_info, detail_org_tip, detail_special_tip}
    """
    url = DETAIL_URL.format(fund_id=fund_id)
    detail = {
        "detail_credit_info":    "",
        "detail_org_tip":        "",
        "detail_special_tip":    "",
        "detail_currency":       "",
        "detail_record_stage":   "",
        "detail_manage_type":    "",
        "detail_last_update":    "",
        "detail_month_report":   "",
        "detail_quarter_report": "",
        "detail_half_report":    "",
        "detail_year_report":    "",
        "detail_investor_rate":  "",
    }

    session = requests.Session()
    for attempt in range(MAX_RETRY):
        try:
            resp = session.get(url, headers=HTML_HEADERS, timeout=20)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
            break
        except Exception:
            if attempt < MAX_RETRY - 1:
                time.sleep((attempt + 1) * 2)
            else:
                return detail

    def strip_tags(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s)

    def extract_title_td(label: str, max_len: int = 300) -> str:
        pattern = re.compile(
            r'<td[^>]*class=["\']title["\'][^>]*>\s*' + re.escape(label) +
            r'\s*</td>\s*<td[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE
        )
        m = pattern.search(html)
        return _clean(strip_tags(m.group(1)))[:max_len] if m else ""

    def extract_plain_td(label: str, max_len: int = 200) -> str:
        pattern = re.compile(
            r'<td[^>]*>\s*' + re.escape(label) + r'\s*</td>\s*<td[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE
        )
        m = pattern.search(html)
        return _clean(strip_tags(m.group(1)))[:max_len] if m else ""

    def extract_nested_table(section_label: str, max_len: int = 400) -> str:
        outer = re.compile(
            re.escape(section_label) + r'</td>\s*<td[^>]*>(.*?)</td>\s*</tr>',
            re.DOTALL | re.IGNORECASE
        )
        m = outer.search(html)
        if not m:
            return "无"
        block = m.group(1)
        row_pat = re.compile(
            r'<td[^>]*class=["\']c_b5151d["\'][^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE
        )
        parts = []
        for rm in row_pat.finditer(block):
            sub_title = _clean(strip_tags(rm.group(1)))
            sub_val   = _clean(strip_tags(rm.group(2)))
            if sub_title or sub_val:
                parts.append(f"{sub_title}：{sub_val}" if sub_title else sub_val)
        result = "；".join(parts) if parts else _clean(strip_tags(block))
        return (result or "无")[:max_len]

    detail["detail_credit_info"]    = extract_nested_table("机构诚信信息")
    detail["detail_org_tip"]        = extract_nested_table("机构提示信息")
    special_val = extract_plain_td("基金业协会特别提示（针对基金）:")
    detail["detail_special_tip"]    = special_val or "无"
    detail["detail_currency"]       = extract_title_td("币种:")
    detail["detail_record_stage"]   = extract_title_td("基金备案阶段:")
    detail["detail_manage_type"]    = extract_title_td("管理类型:")
    detail["detail_last_update"]    = extract_title_td("基金信息最后更新时间:")

    for key, label in [
        ("detail_month_report",   "月报:"),
        ("detail_quarter_report", "季报:"),
        ("detail_half_report",    "半年报:"),
        ("detail_year_report",    "年报:"),
    ]:
        detail[key] = extract_plain_td(label, 150)

    rate_pattern = re.compile(
        r'投资者查询账号开立率.*?</td>\s*<td[^>]*>\s*([\d.]+%)\s*</td>',
        re.DOTALL | re.IGNORECASE
    )
    m = rate_pattern.search(html)
    detail["detail_investor_rate"] = m.group(1).strip() if m else ""

    return detail


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 管理人旗下子基金（穿透一层）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_manager_funds(manager_name: str,
                      with_detail: bool = False,
                      limit: int = 0,
                      progress_cb=None) -> dict:
    """
    查询管理人旗下所有子基金。
    manager_name: 管理人名称（支持模糊匹配）
    with_detail:  是否抓取每只基金的详情页
    返回：{manager: {...}, funds: [...]}
    """
    # 1) 搜索管理人
    mgr_list = search_manager(manager_name, limit=10)
    if not mgr_list:
        return {"error": f"未找到管理人：{manager_name}"}

    # 精确匹配优先
    exact = [m for m in mgr_list if m["manager_name"] == manager_name]
    manager = exact[0] if exact else mgr_list[0]

    # 2) 查询该管理人名下基金
    body = {"keyword": manager["manager_name"]}
    raw_funds = _fetch_all("fund", body, label="子基金",
                           limit=limit, progress_cb=progress_cb)
    funds = [_normalize_fund(f) for f in raw_funds]

    # 3) 可选：抓取详情
    if with_detail and funds:
        total = len(funds)
        for i, fund in enumerate(funds):
            fid = fund.get("fund_id", "")
            if fid:
                detail = get_fund_detail(fid)
                fund.update(detail)
            if progress_cb:
                progress_cb(i + 1, total, "基金详情")
            time.sleep(DETAIL_DELAY)

    return {"manager": manager, "funds": funds}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 基金穿透（基金 → 管理人 → 子基金）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_fund_with_sub_funds(fund_keyword: str,
                             with_detail: bool = False,
                             progress_cb=None) -> dict:
    """
    给定基金名称关键词：
      1. 搜索匹配的基金
      2. 找到其管理人
      3. 查询该管理人旗下所有子基金（穿透一层）

    返回：{
        "target_fund":  {...},          # 目标基金基本信息
        "manager":      {...},          # 管理人信息
        "sub_funds":    [...],          # 管理人旗下所有子基金
        "total_sub_funds": N,
    }
    """
    # 1) 搜索目标基金
    funds = search_fund(fund_keyword, limit=10)
    if not funds:
        return {"error": f"未找到基金：{fund_keyword}"}

    # 精确匹配优先
    exact = [f for f in funds if fund_keyword in f["fund_name"]]
    target_fund = exact[0] if exact else funds[0]

    # 2) 获取基金详情（如需要）
    if with_detail and target_fund.get("fund_id"):
        detail = get_fund_detail(target_fund["fund_id"])
        target_fund.update(detail)

    # 3) 查询管理人旗下所有子基金
    manager_name = target_fund.get("manager_name", "")
    if not manager_name:
        return {
            "target_fund": target_fund,
            "manager":     {},
            "sub_funds":   [],
            "total_sub_funds": 0,
        }

    result = get_manager_funds(
        manager_name,
        with_detail=with_detail,
        progress_cb=progress_cb,
    )

    return {
        "target_fund":     target_fund,
        "manager":         result.get("manager", {}),
        "sub_funds":       result.get("funds", []),
        "total_sub_funds": len(result.get("funds", [])),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 数据标准化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _normalize_fund(f: dict) -> dict:
    """将 AMAC API 原始基金数据标准化"""
    fund_type_code = f.get("fundType", "")
    working_state_code = f.get("workingState", "")
    return {
        "fund_id":        f.get("id", ""),
        "fund_name":      f.get("fundName", ""),
        "fund_code":      f.get("fundCode", "") or f.get("id", ""),
        "manager_name":   f.get("managerName", ""),
        "custodian_name": f.get("mandatorName", ""),
        "fund_type":      FUND_TYPE_DECODE.get(fund_type_code, fund_type_code),
        "fund_type_code": fund_type_code,
        "working_state":  WORKING_STATE_DECODE.get(working_state_code, working_state_code),
        "working_state_code": working_state_code,
        "establish_date": _ts2date(f.get("establishDate")),
        "record_date":    _ts2date(f.get("putOnRecordDate")),
        "province":       f.get("province", ""),
        "is_depute":      f.get("isDeputeManage", ""),
        "detail_url":     DETAIL_URL.format(fund_id=f.get("id", "")),
        "_raw":           f,
    }


def _normalize_manager(m: dict) -> dict:
    """将 AMAC API 原始管理人数据标准化"""
    return {
        "register_no":      m.get("registerNo", ""),
        "manager_name":     m.get("managerName", ""),
        "legal_person":     m.get("artificialPersonName", ""),
        "primary_type":     m.get("primaryInvestType", ""),
        "org_form":         m.get("orgForm", ""),
        "member_type":      m.get("memberType", ""),
        "establish_date":   _ts2date(m.get("establishDate")),
        "register_date":    _ts2date(m.get("registerDate")),
        "register_province":m.get("registerProvince", ""),
        "register_city":    m.get("registerCity", ""),
        "register_address": m.get("registerAddress", ""),
        "office_province":  m.get("officeProvince", ""),
        "office_city":      m.get("officeCity", ""),
        "office_address":   m.get("officeAddress", ""),
        "fund_count":       m.get("fundCount", 0),
        "paid_in_capital":  m.get("paidInCapital", 0),
        "subscribed_capital":m.get("subscribedCapital", 0),
        "has_special_tips": bool(m.get("hasSpecialTips")),
        "has_credit_tips":  bool(m.get("hasCreditTips")),
        "_raw":             m,
    }
