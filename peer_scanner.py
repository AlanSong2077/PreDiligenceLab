"""
peer_scanner.py  —  同行业公司扫描模块
数据源：东方财富板块成分股 API
相似度计算：市值规模 + 估值倍数 + 涨跌相关性（规则打分）
LLM 增强：可选，生成相似原因说明
"""

import math, time, re, json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logger import get_logger

_log = get_logger(__name__)

# 近30日收盘价序列字段（东方财富 clist 接口支持 f135~f164 为近N日收盘价，但不稳定）
# 改用 f3（今日涨跌幅）序列近似：此处保留原字段，相关系数通过历史K线计算
_CORR_DAYS = 30


# ─────────────────────────────────────────────────────────────
# HTTP Session
# ─────────────────────────────────────────────────────────────

def _make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.4,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.eastmoney.com/",
        "Accept":  "application/json",
    })
    return s

_SESSION = _make_session()

def _get(url, timeout=10):
    global _SESSION
    try:
        r = _SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        _log.debug("_get first attempt failed: %s  url=%s", e, url)
        _SESSION = _make_session()
        try:
            r = _SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e2:
            _log.warning("_get failed: %s  url=%s", e2, url)
            return None


# ─────────────────────────────────────────────────────────────
# 获取股票基本信息（用于相似度计算）
# ─────────────────────────────────────────────────────────────

def _get_stock_info(secid: str) -> dict:
    """获取单只股票的快照数据"""
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields=f43,f57,f58,f100,f116,f117,f162,f163,f164,f127,f128,f3"
    )
    r = _get(url, timeout=8)
    if not r:
        return {}
    try:
        d = r.json().get("data") or {}
        def p(v):
            f = float(v) if v is not None else None
            if f is None or math.isnan(f) or math.isinf(f): return None
            return round(f / 100, 4)
        def raw(v):
            f = float(v) if v is not None else None
            if f is None or math.isnan(f) or math.isinf(f): return None
            return f
        return {
            "code":        str(d.get("f57", "")),
            "name":        str(d.get("f58", "")),
            "industry":    str(d.get("f127", "") or d.get("f100", "")),
            "price":       p(d.get("f43")),
            "change_pct":  p(d.get("f3")),
            "market_cap":  raw(d.get("f116")),
            "float_cap":   raw(d.get("f117")),
            "pe":          p(d.get("f162")),
            "pb":          p(d.get("f163")),
            "ps":          p(d.get("f164")),
        }
    except Exception:
        return {}


def _build_secid(code: str, market: str) -> str:
    if market == "CN":
        return f"1.{code}" if code.startswith(("6","5","9")) else f"0.{code}"
    elif market == "HK":
        return f"116.{code.zfill(5)}"
    else:
        return f"105.{code.upper()}"


# ─────────────────────────────────────────────────────────────
# 获取同行业成分股（东方财富板块成分股 API）
# ─────────────────────────────────────────────────────────────

def _get_industry_name(code: str, market: str) -> tuple:
    """返回 (industry_name, secid)"""
    secid = _build_secid(code, market)
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f100,f127,f128"
    r = _get(url, timeout=8)
    if r:
        try:
            d = r.json().get("data") or {}
            ind = d.get("f127") or d.get("f100") or ""
            return str(ind), secid
        except Exception:
            pass
    return "", secid


def _search_bk_code(industry_name: str) -> str:
    """搜索行业板块代码"""
    if not industry_name:
        return ""
    # 东方财富行业板块列表
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
        "&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14"
    )
    r = _get(url, timeout=8)
    if r:
        try:
            diff = r.json().get("data", {}).get("diff") or []
            # 精确匹配
            for item in diff:
                if item.get("f14", "") == industry_name:
                    return item.get("f12", "")
            # 模糊匹配（前3字）
            for item in diff:
                name = item.get("f14", "")
                if industry_name[:3] in name or name[:3] in industry_name:
                    return item.get("f12", "")
        except Exception:
            pass
    return ""


def _get_peers_from_bk(bk_code: str, limit: int = 30) -> list:
    """从板块代码获取成分股列表"""
    if not bk_code:
        return []
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get"
        f"?pn=1&pz={limit}&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
        f"&fltt=2&invt=2&fid=f20&fs=b:{bk_code}"
        f"&fields=f2,f3,f12,f14,f20,f116,f117,f162,f163,f164"
    )
    r = _get(url, timeout=10)
    if not r:
        return []
    try:
        diff = r.json().get("data", {}).get("diff") or []
        peers = []
        for item in diff:
            code = str(item.get("f12", ""))
            name = str(item.get("f14", ""))
            if not code or not name:
                continue
            def p(v):
                f = float(v) if v is not None else None
                if f is None or math.isnan(f) or math.isinf(f): return None
                return round(f / 100, 4)
            def raw(v):
                f = float(v) if v is not None else None
                if f is None or math.isnan(f) or math.isinf(f): return None
                return f
            peers.append({
                "code":       code,
                "name":       name,
                "price":      p(item.get("f2")),
                "change_pct": p(item.get("f3")),
                "market_cap": raw(item.get("f116")) or raw(item.get("f20")),
                "float_cap":  raw(item.get("f117")),
                "pe":         p(item.get("f162")),
                "pb":         p(item.get("f163")),
                "ps":         p(item.get("f164")),
            })
        return peers
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# 相似度计算（规则打分，0-100）
# ─────────────────────────────────────────────────────────────

def _fetch_30d_returns(secid: str) -> list:
    """
    拉取近30个交易日的日收益率序列（东方财富K线接口）。
    返回 list[float]，失败返回空列表。
    """
    import datetime as _dt
    start = (_dt.date.today() - _dt.timedelta(days=60)).strftime("%Y%m%d")
    end   = (_dt.date.today() + _dt.timedelta(days=1)).strftime("%Y%m%d")
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53&klt=101&fqt=1&beg={start}&end={end}"
    )
    r = _get(url, timeout=6)
    if not r:
        return []
    try:
        klines = (r.json().get("data") or {}).get("klines") or []
        closes = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 3:
                try:
                    closes.append(float(parts[2]))
                except ValueError:
                    pass
        if len(closes) < 2:
            return []
        returns = [(closes[i] - closes[i-1]) / closes[i-1]
                   for i in range(1, len(closes))]
        return returns[-_CORR_DAYS:]
    except Exception:
        return []


def _pearson_corr(a: list, b: list) -> float | None:
    """计算两个等长序列的皮尔逊相关系数，长度不足返回 None"""
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    num   = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    denom = (sum((x-ma)**2 for x in a) * sum((x-mb)**2 for x in b)) ** 0.5
    if denom == 0:
        return None
    return round(num / denom, 3)


def _similarity_score(target: dict, peer: dict,
                      target_returns: list = None) -> tuple:
    """
    返回 (score: float, reasons: list[str])
    score 范围 0-100
    权重：市值35 + PE25 + PB20 + 30日收益率相关系数20
    """
    score   = 0.0
    reasons = []

    # 1. 市值规模相似度（权重 35）
    tc = target.get("market_cap")
    pc = peer.get("market_cap")
    if tc and pc and tc > 0 and pc > 0:
        ratio = min(tc, pc) / max(tc, pc)
        score += ratio * 35
        if ratio > 0.7:
            reasons.append(f"市值规模相近（{_fmt_cap(pc)}）")
        elif ratio > 0.3:
            reasons.append(f"市值量级相似（{_fmt_cap(pc)}）")

    # 2. PE 估值相似度（权重 25）
    tpe = target.get("pe")
    ppe = peer.get("pe")
    if tpe and ppe and tpe > 0 and ppe > 0:
        ratio = min(tpe, ppe) / max(tpe, ppe)
        score += ratio * 25
        if ratio > 0.7:
            reasons.append(f"PE估值相近（{ppe:.1f}x）")

    # 3. PB 相似度（权重 20）
    tpb = target.get("pb")
    ppb = peer.get("pb")
    if tpb and ppb and tpb > 0 and ppb > 0:
        ratio = min(tpb, ppb) / max(tpb, ppb)
        score += ratio * 20
        if ratio > 0.7:
            reasons.append(f"PB相近（{ppb:.1f}x）")

    # 4. 近30日收益率相关系数（权重 20，替代单日涨跌方向）
    peer_returns = peer.get("_returns30", [])
    if target_returns and peer_returns:
        corr = _pearson_corr(target_returns, peer_returns)
        if corr is not None:
            # 相关系数 [-1,1] → 映射到 [0,20]
            corr_score = max(0.0, corr) * 20
            score += corr_score
            if corr >= 0.6:
                reasons.append(f"近30日走势高度相关（r={corr:.2f}）")
            elif corr >= 0.3:
                reasons.append(f"近30日走势有一定相关性（r={corr:.2f}）")
        else:
            # 数据不足时退化为单日涨跌方向（保底）
            tc2 = target.get("change_pct")
            pc2 = peer.get("change_pct")
            if tc2 is not None and pc2 is not None:
                if (tc2 >= 0) == (pc2 >= 0):
                    score += 10
    else:
        # 无收益率数据时退化为单日涨跌方向
        tc2 = target.get("change_pct")
        pc2 = peer.get("change_pct")
        if tc2 is not None and pc2 is not None:
            if (tc2 >= 0) == (pc2 >= 0):
                score += 15
                reasons.append("今日涨跌方向一致")
            else:
                score += 5

    # 保底：同行业本身就有相关性
    if score < 10:
        score = 10
        reasons.append("同属行业板块")

    return round(score, 1), reasons


def _fmt_cap(v):
    if v is None: return "—"
    if v >= 1e12: return f"{v/1e12:.1f}万亿"
    if v >= 1e8:  return f"{v/1e8:.0f}亿"
    if v >= 1e6:  return f"{v/1e6:.0f}百万"
    return str(int(v))


# ─────────────────────────────────────────────────────────────
# LLM 增强：生成相似原因说明
# ─────────────────────────────────────────────────────────────

def _llm_peer_reasons(target_info: dict, peers: list, llm_cfg: dict) -> list:
    """用 LLM 为 TOP 同行业公司生成相似原因说明"""
    if not llm_cfg or not llm_cfg.get("api_key"):
        return peers
    if not peers:
        return peers

    try:
        from llm_client import LLMClient
        client = LLMClient(llm_cfg)

        top5 = peers[:5]
        target_desc = (
            f"目标公司：{target_info.get('name','')}（{target_info.get('code','')}），"
            f"行业：{target_info.get('industry','')}，"
            f"市值：{_fmt_cap(target_info.get('market_cap'))}，"
            f"PE：{target_info.get('pe','—')}，PB：{target_info.get('pb','—')}"
        )
        peers_desc = "\n".join(
            f"{i+1}. {p['name']}（{p['code']}）市值{_fmt_cap(p.get('market_cap'))} "
            f"PE={p.get('pe','—')} PB={p.get('pb','—')} 今日{p.get('change_pct','—')}%"
            for i, p in enumerate(top5)
        )
        prompt = (
            f"{target_desc}\n\n"
            f"以下是同行业竞争对手，请为每家公司生成一句话（30字内）说明与目标公司的相似之处或竞争关系：\n"
            f"{peers_desc}\n\n"
            f"返回JSON数组，每个元素：{{\"index\":1, \"reason\":\"...\"}}\n"
            f"只返回JSON，不要其他内容。"
        )
        resp = client.chat(prompt, max_tokens=600)
        if resp:
            m = re.search(r"\[.*\]", resp, re.DOTALL)
            if m:
                results = json.loads(m.group())
                for r in results:
                    idx = r.get("index", 0) - 1
                    if 0 <= idx < len(top5) and r.get("reason"):
                        top5[idx]["llm_reason"] = r["reason"]
    except Exception:
        pass
    return peers


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────

def scan_peers(code: str, market: str,
               company_name: str = "",
               top_n: int = 15,
               llm_cfg: dict = None) -> dict:
    """
    扫描同行业公司。
    返回：
    {
        "target": {code, name, industry, market_cap, pe, pb, ...},
        "peers":  [{code, name, score, reasons, llm_reason, ...}, ...],
        "industry_name": str,
        "bk_code": str,
        "error": str | None,
    }
    """
    result = {
        "target":        {},
        "peers":         [],
        "industry_name": "",
        "bk_code":       "",
        "error":         None,
    }

    # 1. 获取目标股票信息
    secid = _build_secid(code, market)
    target_info = _get_stock_info(secid)
    if not target_info:
        _log.warning("scan_peers: 无法获取 %s 基本信息，东方财富 API 可能不可达", code)
        result["error"] = (
            f"无法获取 {code} 的基本信息。"
            f"同行业扫描依赖东方财富 API，"
            f"在境外网络下可能不可达。请尝试使用代理或切换网络后重试。"
        )
        return result

    if company_name and not target_info.get("name"):
        target_info["name"] = company_name
    target_info["code"]   = code
    target_info["market"] = market
    result["target"] = target_info

    # 2. 获取行业信息
    ind_name, _ = _get_industry_name(code, market)
    if not ind_name:
        ind_name = target_info.get("industry", "")
    result["industry_name"] = ind_name

    # 3. 搜索板块代码
    bk_code = _search_bk_code(ind_name)
    result["bk_code"] = bk_code

    if not bk_code:
        _log.warning("scan_peers: 未找到行业板块代码 code=%s ind=%s", code, ind_name)
        result["error"] = (
            f"未找到行业板块代码（行业：{ind_name or '未知'}）。"
            f"可能是东方财富 API 不可达，或该股票所属行业在板块列表中无匹配。"
        )
        return result

    # 4. 获取成分股
    raw_peers = _get_peers_from_bk(bk_code, limit=50)
    if not raw_peers:
        _log.warning("scan_peers: 板块 %s 成分股为空", bk_code)
        result["error"] = (
            f"板块 {bk_code}（{ind_name}）成分股为空。"
            f"可能是东方财富 API 返回了空数据，请稍后重试。"
        )
        return result

    # 5. 拉取目标股票近30日收益率（用于相关系数计算）
    target_returns = _fetch_30d_returns(secid)

    # 6. 过滤掉目标股票自身，拉取 peer 收益率，计算相似度
    scored = []
    for peer in raw_peers:
        if peer.get("code") == code:
            continue
        # 为 peer 拉取30日收益率（A股，市场代码同目标）
        peer_secid = _build_secid(peer["code"], market)
        peer["_returns30"] = _fetch_30d_returns(peer_secid)
        score, reasons = _similarity_score(target_info, peer, target_returns)
        peer["score"]   = score
        peer["reasons"] = reasons
        # 清理内部字段，不暴露给 UI
        peer.pop("_returns30", None)
        scored.append(peer)

    # 7. 按相似度排序
    scored.sort(key=lambda x: x["score"], reverse=True)
    result["peers"] = scored[:top_n]

    # 8. LLM 增强原因说明
    if llm_cfg and llm_cfg.get("api_key") and llm_cfg.get("enabled"):
        result["peers"] = _llm_peer_reasons(target_info, result["peers"], llm_cfg)

    return result
