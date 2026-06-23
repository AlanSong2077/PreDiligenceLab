"""
market_utils.py — 市场识别与代码规范化工具
统一来源，避免 main.py / fetcher.py 各自维护一套逻辑。

公开接口：
    detect_market(code)   → "US" | "HK" | "CN"
    normalize_code(code, market) → 纯净代码（无后缀）
    detect_market_from_str(s)    → 从市场名称字符串推断（"美股" → "US" 等）
"""

import re

# ── 后缀 → 市场映射 ────────────────────────────────────────────
_SUFFIX_MARKET: dict[str, str | None] = {
    "HK":     "HK",
    "SS":     "CN",    # 上交所
    "SH":     "CN",    # 上交所别名
    "SZ":     "CN",    # 深交所
    "BJ":     "CN",    # 北交所
    "US":     "US",
    "NYSE":   "US",
    "NASDAQ": "US",
    "AMEX":   "US",
    "OTC":    "US",
    "TW":     None,    # 台股：暂不支持
    "KS":     None,    # 韩股
    "T":      None,    # 东京
}

_SUFFIX_RE = re.compile(
    r"\.(" + "|".join(_SUFFIX_MARKET.keys()) + r")$",
    re.IGNORECASE,
)


def detect_market(code: str) -> str:
    """
    根据股票代码判断市场，返回 "US" | "HK" | "CN"。

    规则优先级：
      1. 带 .HK / .SS / .SH / .SZ / .BJ 等后缀 → 对应市场
      2. 纯数字 4-5 位 → 港股
      3. 纯数字 6 位 → A股
      4. 字母 或 字母+数字 → 美股
    """
    code = code.strip().upper()
    m = _SUFFIX_RE.search(code)
    if m:
        suffix = m.group(1).upper()
        mkt = _SUFFIX_MARKET.get(suffix)
        return mkt if mkt else "US"   # 不支持的市场降级为美股
    clean = _SUFFIX_RE.sub("", code)
    if clean.isdigit() and len(clean) in (4, 5):
        return "HK"
    if clean.isdigit() and len(clean) == 6:
        return "CN"
    return "US"


def normalize_code(code: str, market: str) -> str:
    """剥离后缀，返回交易所可直接使用的纯净代码。"""
    code = code.strip().upper()
    code = _SUFFIX_RE.sub("", code)
    if market == "HK":
        return code.zfill(5)
    return code


def detect_market_from_str(s: str) -> str:
    """
    从市场名称字符串推断市场代码。
    例：'美股' → 'US'，'港股' → 'HK'，'A股' → 'CN'
    """
    if not s:
        return "CN"
    if "US" in s or "美" in s:
        return "US"
    if "HK" in s or "港" in s or "香港" in s:
        return "HK"
    return "CN"
