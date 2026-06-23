"""
Pre-Diligence Lab — 一级市场投研风控工作台
GUI 主程序 (PyQt6)  v1.4
"""

import sys, os, math, datetime, subprocess, re, webbrowser, json, traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QFrame, QScrollArea,
    QFileDialog, QSizePolicy, QTabWidget, QGridLayout,
    QButtonGroup, QAbstractButton, QHeaderView, QStackedWidget,
    QSpacerItem, QTextEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient, QPalette, QDesktopServices
from PyQt6.QtCore import QUrl

from logger import get_logger
_log = get_logger(__name__)

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.font_manager import FontProperties

# ── 中文字体 ──────────────────────────────────────────────────
def _find_cjk_font():
    for p in [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]:
        if os.path.exists(p):
            return FontProperties(fname=p)
    return None

_CJK = _find_cjk_font()

def _fp(size=10):
    """返回带中文字体的 FontProperties"""
    if _CJK:
        return FontProperties(fname=_CJK.get_file(), size=size)
    return FontProperties(size=size)

def _tk(size=10):
    """返回 matplotlib text kwargs"""
    return {"fontproperties": _fp(size)}

# ── 颜色系统（统一从 theme.py 导入）─────────────────────────
from theme import (
    BG, BG2, SIDEBAR, CARD, CARD2, CARD3,
    ACCENT, ACCENT_H, ACCENT_D, ACCENT_G,
    SUCCESS, WARN, ERR, UP, DN, STAR,
    FG, FG2, FG3,
    BORDER, BORDER2, DIVIDER,
    INPUT_BG, INPUT_BD,
    MPL_BG, MPL_CARD, MPL_GRID, MPL_TEXT, MPL_LINE, MPL_MA20, MPL_MA60,
    FAV_MAX,
)

# 收藏数据持久化路径
FAVORITES_PATH = Path.home() / ".stockreporter" / "favorites.json"
_FAV_CACHE: list | None = None   # 内存缓存，避免每次操作都读文件

# ── 指标说明 ──────────────────────────────────────────────────
TIPS = {
    "区间涨跌幅":       "区间内收盘价从期初到期末的百分比变化",
    "期初价格":         "区间第一个交易日收盘价",
    "期末价格":         "区间最后一个交易日收盘价",
    "区间最高":         "区间内所有交易日最高价的最大值",
    "区间最低":         "区间内所有交易日最低价的最小值",
    "日均波动率":       "每日收益率的标准差（%），衡量价格波动剧烈程度",
    "上涨天数":         "区间内收盘价高于前一日的天数",
    "下跌天数":         "区间内收盘价低于前一日的天数",
    "日均成交量":       "区间内每日平均成交手数（1手=100股）",
    "区间总成交量":     "区间内所有交易日成交量之和",
    "单日最大成交":     "区间内单日成交量峰值",
    "市盈率 PE(TTM)":   "股价/过去12个月每股收益，越低估值越便宜（行业差异大）",
    "市盈率 PE(预测)":  "股价/分析师预测未来12个月每股收益",
    "市销率 PS":        "总市值/年营业收入，适合亏损或低利润率公司估值",
    "市净率 PB":        "股价/每股净资产，<1 可能被低估，高成长股通常>1",
    "EV/EBITDA":        "企业价值/息税折旧摊销前利润，跨资本结构比较常用",
    "总市值":           "当前股价 × 总股本，反映市场对公司整体价值的判断",
    "流通市值":         "当前股价 × 流通股本，可自由交易部分的市值",
    "当前价格":         "最新成交价格",
    "今日涨跌幅":       "今日收盘价相对昨日收盘价的百分比变化",
    "52周最高":         "过去52周（约1年）内的最高成交价",
    "52周最低":         "过去52周（约1年）内的最低成交价",
    "今日振幅":         "(最高价-最低价)/昨收价，衡量当日价格波动范围",
    "今日成交量":       "今日已成交的手数（1手=100股）",
    "成交额":           "今日成交的总金额",
    "换手率":           "今日成交量/流通股本，反映股票活跃程度",
    "EPS(TTM)":         "过去12个月每股收益，正值盈利，负值亏损",
    "净资产收益率 ROE": "净利润/股东权益，衡量股东资金的盈利效率，>15%通常较优",
    "总资产收益率 ROA": "净利润/总资产，衡量公司利用全部资产的盈利能力",
    "净利润率":         "净利润/营业收入，越高说明盈利能力越强",
    "营业利润率":       "营业利润/营业收入，扣除运营成本后的盈利比例",
    "营收增速(YoY)":    "本期营业收入相比去年同期的增长率",
    "净利增速(YoY)":    "本期净利润相比去年同期的增长率",
    "负债权益比":       "总负债/股东权益，越高财务杠杆越大，风险越高",
    "流动比率":         "流动资产/流动负债，>1 说明短期偿债能力较好",
    "自由现金流":       "经营现金流-资本支出，反映公司真实造血能力",
    "内部人持仓比":     "公司高管、董事等内部人员持有股份占总股本比例",
    "机构持仓比":       "基金、保险等机构投资者持有股份占总股本比例",
    "股息率":           "每股年度股息/当前股价，越高现金回报越丰厚",
    "派息比率":         "股息/净利润，反映公司将多少利润以股息形式返还股东",
    "市盈率 PE":        "股价/每股收益，越低估值越便宜（行业差异大）",
    "净资产收益率":     "净利润/股东权益，衡量股东资金的盈利效率",
}


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def cs(radius=10, bg=CARD, border=BORDER):
    return f"background:{bg};border:1px solid {border};border-radius:{radius}px;"

def ls(color=FG, size=12, bold=False):
    return f"color:{color};font-size:{size}px;font-weight:{'700' if bold else '400'};"

# ── 收藏持久化 ────────────────────────────────────────────────
def load_favorites() -> list:
    """加载收藏列表 [{code, market, name}, ...]，优先返回内存缓存"""
    global _FAV_CACHE
    if _FAV_CACHE is not None:
        return _FAV_CACHE
    if FAVORITES_PATH.exists():
        try:
            _FAV_CACHE = json.loads(FAVORITES_PATH.read_text(encoding="utf-8"))
            return _FAV_CACHE
        except Exception:
            pass
    _FAV_CACHE = []
    return _FAV_CACHE

def save_favorites(favs: list):
    global _FAV_CACHE
    _FAV_CACHE = favs          # 同步更新内存缓存
    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_PATH.write_text(json.dumps(favs, ensure_ascii=False, indent=2), encoding="utf-8")

def is_favorite(code: str, market: str) -> bool:
    return any(f["code"] == code and f["market"] == market for f in load_favorites())

def toggle_favorite(code: str, market: str, name: str = "") -> bool:
    """切换收藏状态，返回新状态 True=已收藏；收藏上限 FAV_MAX 条"""
    favs = load_favorites()
    for i, f in enumerate(favs):
        if f["code"] == code and f["market"] == market:
            favs.pop(i); save_favorites(favs); return False
    if len(favs) >= FAV_MAX:
        raise ValueError(f"收藏已达上限 {FAV_MAX} 条，请先取消部分收藏")
    favs.insert(0, {"code": code, "market": market, "name": name})
    save_favorites(favs); return True

def _safe(v, fmt=None):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    if fmt == "pct":   return f"{v*100:.2f}%"
    if fmt == "pct1":  return f"{v:.2f}%"
    if fmt == "2f":    return f"{v:.2f}"
    if fmt == "big":
        if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
        if abs(v) >= 1e8:  return f"{v/1e8:.2f}亿"
        if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
        return f"{int(v):,}"
    if fmt == "vol":
        if abs(v) >= 1e8: return f"{v/1e8:.2f}亿手"
        if abs(v) >= 1e4: return f"{v/1e4:.2f}万手"
        return f"{int(v):,}手"
    return str(v)

# 市场识别统一从 market_utils 导入
from market_utils import detect_market as _auto_market_full, detect_market_from_str as _detect_market, normalize_code as _normalize_code  # noqa: E501

def _auto_market(code: str) -> str:
    """根据代码自动推断市场，封装 market_utils.detect_market"""
    return _auto_market_full(code)


# ═══════════════════════════════════════════════
# 后台线程
# ═══════════════════════════════════════════════

def _track_worker(workers: list, w: QThread):
    """将线程加入 workers 列表，并在 QThread.finished 时自动移除 + deleteLater。
    无论线程正常结束还是异常退出，都能保证引用被释放。"""
    workers.append(w)
    w.finished.connect(lambda: (workers.remove(w) if w in workers else None, w.deleteLater()))


def _friendly_err(e: Exception, context: str = "") -> str:
    """将原始异常转为用户友好文案，同时把堆栈写入日志"""
    _log.error("%s: %s\n%s", context or type(e).__name__, e, traceback.format_exc())
    msg = str(e)
    if "ConnectionError" in type(e).__name__ or "Timeout" in type(e).__name__:
        return "网络连接失败，请检查网络后重试"
    if "HTTPError" in type(e).__name__:
        code_hint = ""
        import re as _re
        m = _re.search(r"(\d{3})", msg)
        if m:
            code_hint = f"（HTTP {m.group(1)}）"
        return f"服务器返回错误{code_hint}，请稍后重试"
    if "JSONDecodeError" in type(e).__name__ or "json" in msg.lower():
        return "数据解析失败，服务器返回了非预期格式"
    if "Timeout" in msg or "timed out" in msg.lower():
        return "请求超时，请检查网络后重试"
    # 截断过长的原始消息
    return msg[:120] if len(msg) > 120 else msg


class QueryWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    def __init__(self, code): super().__init__(); self.code = code
    def run(self):
        try:
            from fetcher import query_stock
            self.finished.emit(query_stock(self.code))
        except Exception as e: self.error.emit(_friendly_err(e, "QueryWorker"))

class AnalyticsWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    def __init__(self, code, market): super().__init__(); self.code=code; self.market=market
    def run(self):
        try:
            from analytics import fetch_analytics
            self.finished.emit(fetch_analytics(self.code, self.market))
        except Exception as e: self.error.emit(_friendly_err(e, "AnalyticsWorker"))

class DownloadWorker(QThread):
    finished = pyqtSignal(bool, str, int)
    def __init__(self, filing, market, save_dir, index):
        super().__init__()
        self.filing=filing; self.market=market; self.save_dir=save_dir; self.index=index
    def run(self):
        try:
            from fetcher import download_filing
            ok, msg = download_filing(self.filing, self.market, self.save_dir)
            self.finished.emit(ok, msg, self.index)
        except Exception as e: self.finished.emit(False, _friendly_err(e, "DownloadWorker"), self.index)

class _SingleCompareWorker(QThread):
    """单只股票的行情拉取线程，供 ComparePanel 并发使用"""
    done = pyqtSignal(str, dict)
    def __init__(self, code, market): super().__init__(); self.code=code; self.market=market
    def run(self):
        try:
            from analytics import fetch_analytics
            self.done.emit(self.code, fetch_analytics(self.code, self.market))
        except Exception as e:
            self.done.emit(self.code, {"error": _friendly_err(e, f"CompareWorker({self.code})") })

class NewsWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    def __init__(self, code, market, company_name=""):
        super().__init__()
        self.code=code; self.market=market; self.company_name=company_name
    def run(self):
        try:
            from news_fetcher import fetch_news
            self.finished.emit(fetch_news(self.code, self.market, self.company_name))
        except Exception as e: self.error.emit(_friendly_err(e, "NewsWorker"))



def _parse_llm_json_array(raw: str) -> list:
    """
    多层兜底解析 LLM 返回的 JSON 数组：
    1. 直接解析
    2. 提取 [...] 块后解析
    3. 逐行提取 {...} 对象后组装
    """
    import json as _json, re as _re
    if not raw:
        return []
    # 层 1：直接解析
    try:
        result = _json.loads(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # 有些模型把数组包在某个 key 里
            for v in result.values():
                if isinstance(v, list):
                    return v
    except Exception:
        pass
    # 层 2：提取最外层 [...] 块
    m = _re.search(r"\[[\s\S]*\]", raw)
    if m:
        try:
            result = _json.loads(m.group())
            if isinstance(result, list):
                return result
        except Exception:
            pass
    # 层 3：逐个提取 {...} 对象
    objects = []
    for m2 in _re.finditer(r"\{[^{}]*\}", raw, _re.DOTALL):
        try:
            obj = _json.loads(m2.group())
            if isinstance(obj, dict):
                objects.append(obj)
        except Exception:
            pass
    return objects


class LLMSearchWorker(QThread):
    """LLM 智能搜索：输入公司描述 -> 推荐上市股票代码"""
    finished = pyqtSignal(list)   # [{code, market, name, reason, confidence}, ...]
    error    = pyqtSignal(str)

    # system prompt：强制 JSON 格式
    _SYSTEM = (
        "你是一个专业的股票分析助手。"
        "你的回答必须是合法的 JSON 数组，不包含任何解释文字、markdown 标记或代码块。"
        "数组中每个元素必须包含以下字段：\n"
        "  code (string): 股票代码，如 AAPL、00700、600519\n"
        "  market (string): 只能是 US、HK、CN 三者之一\n"
        "  name (string): 公司中文名\n"
        "  reason (string): 相似原因，30字以内\n"
        "  confidence (number): 置信度，0.0 到 1.0 之间的小数\n"
        "示例输出：\n"
        '[{"code":"NVDA","market":"US","name":"英伟达","reason":"GPU芯片设计龙头，AI算力核心供应商","confidence":0.95}]'
    )

    def __init__(self, query: str, llm_cfg: dict):
        super().__init__()
        self.query = query
        self.llm_cfg = llm_cfg

    def run(self):
        try:
            from llm_client import LLMClient
            client = LLMClient(self.llm_cfg)
            prompt = (
                f"用户描述：\"{self.query}\"\n\n"
                f"请推荐 3-5 只与上述描述最相似的上市公司股票。\n"
                f"覆盖美国(US)、中国香港(HK)、中国大陆(CN)中最具代表性的标的。\n"
                f"直接返回 JSON 数组，不要任何其他内容。"
            )
            raw = client.chat_json(prompt, system=self._SYSTEM, max_tokens=900)
            results = _parse_llm_json_array(raw)
            # 过滤掉缺少必要字段的条目
            valid = [
                r for r in results
                if isinstance(r, dict)
                and r.get("code") and r.get("market") in ("US", "HK", "CN")
            ]
            if valid:
                self.finished.emit(valid)
            elif results:
                # 有结果但字段不完整，尽量补全后返回
                for r in results:
                    if not r.get("market"):
                        r["market"] = "US"
                    if not r.get("name"):
                        r["name"] = r.get("code", "—")
                self.finished.emit(results)
            else:
                self.error.emit("LLM 未返回有效结果，请换个描述重试")
        except Exception as e:
            self.error.emit(_friendly_err(e, "PeerSearchWorker"))


class NewsKeywordWorker(QThread):
    """消息引擎关键字 LLM 智能搜索（三阶段：联网搜索 → 多源抓取 → LLM 综合分析）"""
    finished = pyqtSignal(list, bool, list)  # (items, from_cache, primary_market_items)
    error    = pyqtSignal(str)

    _SYSTEM = (
        "你是一个专业的财经新闻分析助手。"
        "你的回答必须是合法的 JSON 数组，不包含任何解释文字、markdown 标记或代码块。"
        "数组中每个元素必须包含以下字段：\n"
        "  index (integer): 新闻序号，从 1 开始\n"
        "  relevant (boolean): 是否与关键词相关\n"
        "  summary (string): 一句话中文摘要，20字以内；不相关时填空字符串\n"
        "  sentiment (string): bullish / bearish / neutral\n"
        "示例输出：\n"
        '[{"index":1,"relevant":true,"summary":"美联储宣布降息25个基点","sentiment":"bullish"},'
        '{"index":2,"relevant":false,"summary":"","sentiment":"neutral"}]'
    )

    # 当无本地新闻时，纯靠联网内容让 LLM 生成摘要列表
    _SYSTEM_WEB = (
        "你是一个专业的财经新闻分析助手。"
        "根据下方联网搜索到的内容，提取与关键词最相关的新闻要点，"
        "以 JSON 数组返回，每条包含：\n"
        "  title (string): 新闻标题（来自搜索结果或自行概括，30字以内）\n"
        "  summary (string): 一句话摘要，20字以内\n"
        "  sentiment (string): bullish / bearish / neutral\n"
        "  source (string): 来源媒体名称（如能识别）\n"
        "最多返回 10 条，只返回 JSON 数组，不要其他内容。\n"
        "示例：\n"
        '[{"title":"美联储维持利率不变","summary":"美联储9月会议决定维持利率","sentiment":"neutral","source":"Reuters"}]'
    )

    # 类级别 TTL 缓存：key=(keyword, code, market) → (timestamp, items)
    _cache: dict = {}
    _CACHE_TTL = 300   # 5 分钟

    def __init__(self, keyword: str, code: str, market: str, llm_cfg: dict):
        super().__init__()
        self.keyword = keyword
        self.code = code; self.market = market
        self.llm_cfg = llm_cfg

    def run(self):
        import time as _time
        try:
            from news_fetcher import _fetch_emf_kuaixun, _fetch_yahoo_rss, _dedup, _score, _make_item
            import json as _json

            # ── TTL 缓存命中检查 ──────────────────────────────────────
            _cache_key = (self.keyword, self.code, self.market)
            _cached = NewsKeywordWorker._cache.get(_cache_key)
            if _cached:
                _ts, _items = _cached
                if _time.time() - _ts < NewsKeywordWorker._CACHE_TTL:
                    self.finished.emit(_items, True, [])   # 命中缓存
                    return

            # ── 阶段1：联网搜索（主力数据源）────────────────────────
            # 以联网搜索为主，直接针对关键词搜索，结果最准确
            web_context = ""
            web_items_raw: list[dict] = []
            try:
                from web_search import search_news
                # 关键词搜索与股票完全独立：不传 stock_code，避免搜索 query 被股票代码“污染”
                ws_result = search_news(
                    self.keyword,
                    stock_code="",   # 意图留空：搜索内容由关键词决定，不附加股票代码
                    market=self.market,
                    timeout=10,
                )
                web_context = ws_result.get("raw_text", "")
                web_items_raw = ws_result.get("items", [])
            except Exception:
                pass

            # ── 阶段2：东方财富/Yahoo 作为补充数据源 ─────────────────
            # 只在联网结果不足时才用，且严格用关键词过滤
            emf_items = []
            if len(web_items_raw) < 5:
                emf_items = _fetch_emf_kuaixun([self.keyword], limit=50)
                if self.market == "US":
                    emf_items += _fetch_yahoo_rss(self.code, limit=20)
                emf_items = _dedup(sorted(emf_items, key=_score, reverse=True))[:10]

            # ── 阶段3：LLM 综合分析 ───────────────────────────────────
            if self.llm_cfg and self.llm_cfg.get("api_key"):
                from llm_client import LLMClient
                client = LLMClient(self.llm_cfg)

                # 优先用联网内容让 LLM 生成精准结果
                if web_context:
                    # 股票上下文只在有股票时才展示，避免影响纯关键词搜索
                    stock_ctx = f"当前查看股票：{self.code}\n" if self.code else ""
                    prompt = (
                        f"用户搜索关键词：\"{self.keyword}\"\n"
                        f"{stock_ctx}\n"
                        f"{web_context}\n\n"
                        f"请严格只提取与关键词「{self.keyword}」直接相关的新闻要点。\n"
                        f"不相关的内容一律不要包含。\n"
                        f"直接返回 JSON 数组，不要任何其他内容。"
                    )
                    raw = client.chat_json(prompt, system=self._SYSTEM_WEB, max_tokens=900)
                    results = _parse_llm_json_array(raw)
                    kw_items = []
                    if results:
                        for r in results:
                            if not isinstance(r, dict) or not r.get("title"):
                                continue
                            src = r.get("source") or "网络搜索"
                            it = _make_item(
                                title=r["title"],
                                url="",
                                source=src,
                                pub_time_str="",
                                digest=r.get("summary", ""),
                                relevance=0.9,
                            )
                            it["summary"] = r.get("summary", "")
                            if r.get("sentiment") in ("bullish", "bearish", "neutral"):
                                it["sentiment"] = r["sentiment"]
                            it["llm_enhanced"] = True
                            kw_items.append(it)

                    # 如果联网 LLM 结果不足，再用东方财富补充并过滤
                    if len(kw_items) < 3 and emf_items:
                        batch = emf_items[:10]
                        titles = "\n".join(
                            f"{i+1}. {it['title']}" for i, it in enumerate(batch)
                        )
                        stock_ctx2 = f"（当前股票：{self.code}）" if self.code else ""
                        prompt2 = (
                            f"关键词：\"{self.keyword}\"{stock_ctx2}\n\n"
                            f"以下新闻中，只保留与关键词「{self.keyword}」直接相关的条目，"
                            f"不相关的必须标记 relevant=false。\n"
                            f"直接返回 JSON 数组，不要任何其他内容。\n\n"
                            f"新闻列表：\n{titles}"
                        )
                        raw2 = client.chat_json(prompt2, system=self._SYSTEM, max_tokens=600)
                        results2 = _parse_llm_json_array(raw2)
                        if results2:
                            for r in results2:
                                if not isinstance(r, dict):
                                    continue
                                idx = r.get("index", 0) - 1
                                if 0 <= idx < len(batch):
                                    if r.get("summary"):
                                        batch[idx]["summary"] = r["summary"]
                                    if r.get("sentiment") in ("bullish", "bearish", "neutral"):
                                        batch[idx]["sentiment"] = r["sentiment"]
                                    if r.get("relevant") is False:
                                        batch[idx]["_filtered"] = True
                            kw_items += [it for it in batch if not it.get("_filtered")]

                elif emf_items:
                    # 无联网结果，只用东方财富，严格过滤
                    batch = emf_items[:15]
                    titles = "\n".join(
                        f"{i+1}. {it['title']}" for i, it in enumerate(batch)
                    )
                    stock_ctx3 = f"（当前股票：{self.code}）" if self.code else ""
                    prompt = (
                        f"关键词：\"{self.keyword}\"{stock_ctx3}\n\n"
                        f"以下新闻中，只保留与关键词「{self.keyword}」直接相关的条目，"
                        f"不相关的必须标记 relevant=false，宁可少也不要不相关的。\n"
                        f"直接返回 JSON 数组，不要任何其他内容。\n\n"
                        f"新闻列表：\n{titles}"
                    )
                    raw = client.chat_json(prompt, system=self._SYSTEM, max_tokens=800)
                    results = _parse_llm_json_array(raw)
                    kw_items = list(emf_items)
                    if results:
                        for r in results:
                            if not isinstance(r, dict):
                                continue
                            idx = r.get("index", 0) - 1
                            if 0 <= idx < len(batch):
                                if r.get("summary"):
                                    batch[idx]["summary"] = r["summary"]
                                if r.get("sentiment") in ("bullish", "bearish", "neutral"):
                                    batch[idx]["sentiment"] = r["sentiment"]
                                if r.get("relevant") is False:
                                    batch[idx]["_filtered"] = True
                        kw_items = [it for it in kw_items if not it.get("_filtered")]
                else:
                    kw_items = []

            else:
                # 无 LLM：联网结果直接转为 news item，东方财富作补充
                kw_items = []
                for it_raw in web_items_raw[:10]:
                    if not it_raw.get("title"):
                        continue
                    it = _make_item(
                        title=it_raw["title"],
                        url=it_raw.get("url", ""),
                        source=it_raw.get("source") or "网络搜索",
                        pub_time_str="",
                        digest=it_raw.get("snippet", ""),
                        relevance=0.8,
                    )
                    kw_items.append(it)
                # 补充东方财富（相关性高的）
                for it in emf_items:
                    if it.get("relevance", 0) >= 0.3:
                        kw_items.append(it)

            result = kw_items[:15]

            # 写入 TTL 缓存（LRU 上限 50 条：超出时删除最旧的条目）
            _cache = NewsKeywordWorker._cache
            _cache[_cache_key] = (_time.time(), result)
            if len(_cache) > 50:
                _oldest_key = min(_cache, key=lambda k: _cache[k][0])
                del _cache[_oldest_key]
            self.finished.emit(result, False, [])  # 新鲜数据
        except Exception as e:
            self.error.emit(_friendly_err(e, "NewsKeywordWorker"))


# ═══════════════════════════════════════════════
# 消息引擎面板
# ═══════════════════════════════════════════════

SENT_COLOR = {"bullish": "#34C759", "bearish": "#FF453A", "neutral": "#8E8E93"}
SENT_LABEL = {"bullish": "利好",    "bearish": "利空",    "neutral": "中性"}
RISK_COLOR = {"market": "#FF9F0A",  "financial": "#FF453A", "tech": "#BF5AF2"}
RISK_LABEL = {"market": "市场风险", "financial": "财务风险", "tech": "技术风险"}


class NewsCard(QFrame):
    """单条新闻卡片"""
    def __init__(self, item: dict, show_badge: str = "", parent=None):
        super().__init__(parent)
        self._url = item.get("url", "")
        self._build(item, show_badge)

    def _build(self, item, badge):
        self.setStyleSheet(
            f"NewsCard{{background:{CARD};border:1px solid {BORDER};"
            f"border-left:3px solid {BORDER};border-radius:8px;}}"
            f"NewsCard:hover{{border-color:{ACCENT};"
            f"border-left:3px solid {ACCENT};background:{CARD2};}}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8); lay.setSpacing(4)

        # 顶行：来源 + 权威星 + 时间 + 情感标签
        top = QHBoxLayout(); top.setSpacing(6)

        src_lbl = QLabel(item.get("source", "未知"))
        src_lbl.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        src_lbl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        top.addWidget(src_lbl)

        # 权威度星级
        auth = item.get("authority", 1)
        stars = "★" * auth + "☆" * (5 - auth)
        star_lbl = QLabel(stars)
        star_lbl.setFont(QFont("Arial", 8))
        star_lbl.setStyleSheet(f"color:#FF9F0A;background:transparent;border:none;")
        top.addWidget(star_lbl)

        top.addStretch()

        # 时间：有 pub_time 显示相对时间+绝对日期，无则显示「日期未知」
        pt = item.get("pub_time")
        if pt:
            now = datetime.datetime.now()
            diff = now - pt
            if diff.total_seconds() < 3600:
                time_str = f"{int(diff.total_seconds()//60)}分钟前  {pt.strftime('%m-%d %H:%M')}"
            elif diff.total_seconds() < 86400:
                time_str = f"{int(diff.total_seconds()//3600)}小时前  {pt.strftime('%m-%d %H:%M')}"
            elif diff.days < 7:
                time_str = f"{diff.days}天前  {pt.strftime('%m-%d')}"
            else:
                time_str = pt.strftime("%Y-%m-%d")
        else:
            time_str = "日期未知"
        tl = QLabel(time_str)
        tl.setFont(QFont("Arial", 9))
        tl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        top.addWidget(tl)

        # 情感/风险标签
        if badge:
            bl = QLabel(badge)
            bl.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            color = RISK_COLOR.get(badge, SENT_COLOR.get(
                {v: k for k, v in SENT_LABEL.items()}.get(badge, "neutral"), FG2))
            bl.setStyleSheet(
                f"color:{color};background:rgba(0,0,0,0.3);"
                f"border:1px solid {color};border-radius:4px;padding:0 5px;"
            )
            top.addWidget(bl)

        lay.addLayout(top)

        # 标题
        title = item.get("title", "")
        tl2 = QLabel(title)
        tl2.setFont(QFont("Arial", 11))
        tl2.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        tl2.setWordWrap(True)
        lay.addWidget(tl2)

        # 摘要
        summary = item.get("summary", "").strip()
        if summary:
            sl = QLabel(summary[:100] + ("..." if len(summary) > 100 else ""))
            sl.setFont(QFont("Arial", 9))
            sl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            sl.setWordWrap(True)
            lay.addWidget(sl)

    def mousePressEvent(self, event):
        if self._url and event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mousePressEvent(event)


class NewsSectionWidget(QWidget):
    """带标题的新闻列表区块"""
    def __init__(self, title: str, color: str = ACCENT, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0); self._lay.setSpacing(6)

        # 区块标题
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{CARD2};border-radius:6px;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 6, 12, 6)
        tl = QLabel(title)
        tl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        tl.setStyleSheet(f"color:{color};background:transparent;border:none;")
        hl.addWidget(tl); hl.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setFont(QFont("Arial", 10))
        self._count_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        hl.addWidget(self._count_lbl)
        self._lay.addWidget(hdr)

    def add_items(self, items: list, badge_fn=None):
        self._count_lbl.setText(f"{len(items)} 条")
        if not items:
            empty = QLabel("暂无相关消息")
            empty.setFont(QFont("Arial", 10))
            empty.setStyleSheet(f"color:{FG2};padding:8px 12px;")
            self._lay.addWidget(empty)
            return
        for item in items:
            badge = badge_fn(item) if badge_fn else ""
            card = NewsCard(item, badge)
            self._lay.addWidget(card)


class NewsPanel(QWidget):
    """消息引擎分析标签页"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")
        self._workers = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8); root.setSpacing(8)

        # 刷新按钮行
        top_row = QHBoxLayout(); top_row.setSpacing(8)
        self.refresh_btn = QPushButton("刷新消息")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{FG2};border:1px solid {BORDER};"
            f"border-radius:8px;font-size:11px;padding:0 14px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
            f"QPushButton:disabled{{color:{FG2};}}"
        )
        self.refresh_btn.clicked.connect(self._refresh)
        self.refresh_btn.setEnabled(False)
        top_row.addWidget(self.refresh_btn)

        self.industry_lbl = QLabel("")
        self.industry_lbl.setFont(QFont("Arial", 10))
        self.industry_lbl.setStyleSheet(
            f"color:{ACCENT};background:rgba(79,142,247,0.12);"
            f"border:1px solid rgba(79,142,247,0.3);border-radius:6px;padding:2px 10px;"
        )
        self.industry_lbl.hide()
        top_row.addWidget(self.industry_lbl)
        top_row.addStretch()

        self.sort_lbl = QLabel("排序：权威度 × 时效性")
        self.sort_lbl.setFont(QFont("Arial", 9))
        self.sort_lbl.setStyleSheet(f"color:{FG2};")
        top_row.addWidget(self.sort_lbl)
        root.addLayout(top_row)

        # ── LLM 关键字搜索模块（卡片容器）──────────────────────
        _KW_BG     = f"rgba(79,142,247,0.06)"
        _KW_BORDER = f"rgba(79,142,247,0.28)"

        kw_card = QFrame()
        kw_card.setObjectName("kwCard")
        kw_card.setStyleSheet(
            f"QFrame#kwCard{{background:{_KW_BG};border:1px solid {_KW_BORDER};"
            f"border-radius:12px;}}"
        )
        kw_card_lay = QVBoxLayout(kw_card)
        kw_card_lay.setContentsMargins(12, 8, 12, 10)
        kw_card_lay.setSpacing(6)

        # 卡片标题行
        kw_title_row = QHBoxLayout(); kw_title_row.setSpacing(8)
        kw_icon_lbl = QLabel("◆")
        kw_icon_lbl.setFont(QFont("Arial", 10))
        kw_icon_lbl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        kw_title_row.addWidget(kw_icon_lbl)

        kw_title_lbl = QLabel("LLM 智能搜索")
        kw_title_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        kw_title_lbl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        kw_title_row.addWidget(kw_title_lbl)

        kw_api_tag = QLabel("需配置 API Key")
        kw_api_tag.setFont(QFont("Arial", 9))
        kw_api_tag.setStyleSheet(
            f"color:{FG2};background:{CARD2};"
            f"border:1px solid {BORDER};border-radius:4px;padding:1px 6px;"
        )
        kw_title_row.addWidget(kw_api_tag)
        kw_title_row.addStretch()
        kw_card_lay.addLayout(kw_title_row)

        # 搜索输入行
        kw_row = QHBoxLayout(); kw_row.setSpacing(8)
        self.kw_inp = QLineEdit()
        self.kw_inp.setPlaceholderText("输入关键词，如：AI芯片、降息、并购…")
        self.kw_inp.setFixedHeight(34)
        self.kw_inp.setFont(QFont("Arial", 11))
        self.kw_inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};border:1.5px solid {INPUT_BD};"
            f"border-radius:8px;color:{FG};padding:0 12px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};"
            f"background:rgba(79,142,247,0.04);}}"
        )
        self.kw_inp.returnPressed.connect(self._kw_search)
        kw_row.addWidget(self.kw_inp, 1)

        self.kw_btn = QPushButton("LLM 搜索")
        self.kw_btn.setFixedSize(88, 34)
        self.kw_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kw_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {ACCENT},stop:1 {ACCENT_H});"
            f"color:white;border:none;border-radius:8px;"
            f"font-size:11px;font-weight:600;letter-spacing:0.5px;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {ACCENT_H},stop:1 {ACCENT_D});}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self.kw_btn.clicked.connect(self._kw_search)
        kw_row.addWidget(self.kw_btn)
        kw_card_lay.addLayout(kw_row)
        root.addWidget(kw_card)

        # ── 一级市场搜索模块（独立卡片容器）──────────────────────
        _PM_ORANGE   = "#FF9F0A"
        _PM_ORANGE_H = "#E8900A"
        _PM_ORANGE_D = "#CC7A00"
        _PM_BG       = "rgba(255,159,10,0.06)"
        _PM_BORDER   = "rgba(255,159,10,0.28)"

        pm_card = QFrame()
        pm_card.setObjectName("pmCard")
        pm_card.setStyleSheet(
            f"QFrame#pmCard{{background:{_PM_BG};border:1px solid {_PM_BORDER};"
            f"border-radius:12px;}}"
        )
        pm_card_lay = QVBoxLayout(pm_card)
        pm_card_lay.setContentsMargins(12, 8, 12, 10)
        pm_card_lay.setSpacing(6)

        # 卡片标题行
        pm_title_row = QHBoxLayout(); pm_title_row.setSpacing(8)
        pm_icon_lbl = QLabel("◆")
        pm_icon_lbl.setFont(QFont("Arial", 10))
        pm_icon_lbl.setStyleSheet(f"color:{_PM_ORANGE};background:transparent;border:none;")
        pm_title_row.addWidget(pm_icon_lbl)

        pm_title_lbl = QLabel("一级市场资讯")
        pm_title_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        pm_title_lbl.setStyleSheet(f"color:{_PM_ORANGE};background:transparent;border:none;")
        pm_title_row.addWidget(pm_title_lbl)

        # 信源标签
        for src_name in ("36氪", "量子位", "爱范儿"):
            src_tag = QLabel(src_name)
            src_tag.setFont(QFont("Arial", 9))
            src_tag.setStyleSheet(
                f"color:{_PM_ORANGE};background:rgba(255,159,10,0.12);"
                f"border:1px solid rgba(255,159,10,0.35);border-radius:4px;"
                f"padding:1px 6px;"
            )
            pm_title_row.addWidget(src_tag)

        pm_title_row.addStretch()
        pm_card_lay.addLayout(pm_title_row)

        # 搜索输入行
        pm_row = QHBoxLayout(); pm_row.setSpacing(8)
        self.pm_inp = QLineEdit()
        self.pm_inp.setPlaceholderText("输入公司名或行业词，如：寒武纪、AI芯片、新能源…")
        self.pm_inp.setFixedHeight(34)
        self.pm_inp.setFont(QFont("Arial", 11))
        self.pm_inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};border:1.5px solid {INPUT_BD};"
            f"border-radius:8px;color:{FG};padding:0 12px;}}"
            f"QLineEdit:focus{{border-color:{_PM_ORANGE};"
            f"background:rgba(255,159,10,0.04);}}"
        )
        self.pm_inp.returnPressed.connect(self._pm_search)
        pm_row.addWidget(self.pm_inp, 1)

        self.pm_btn = QPushButton("搜资讯")
        self.pm_btn.setFixedSize(90, 34)
        self.pm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pm_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {_PM_ORANGE},stop:1 {_PM_ORANGE_H});"
            f"color:white;border:none;border-radius:8px;"
            f"font-size:11px;font-weight:600;letter-spacing:0.5px;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {_PM_ORANGE_H},stop:1 {_PM_ORANGE_D});}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self.pm_btn.clicked.connect(self._pm_search)
        pm_row.addWidget(self.pm_btn)
        pm_card_lay.addLayout(pm_row)

        # 一级市场结果区（自适应高度，有结果时展开，最大 280px）
        self.pm_scroll = QScrollArea()
        self.pm_scroll.setWidgetResizable(True)
        self.pm_scroll.setMinimumHeight(72)
        self.pm_scroll.setMaximumHeight(280)
        self.pm_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pm_scroll.setStyleSheet(
            f"QScrollArea{{background:{CARD2};border:1px solid {BORDER};"
            f"border-radius:8px;}}"
            f"QScrollBar:vertical{{background:{CARD2};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER2};border-radius:3px;min-height:24px;}}"
            f"QScrollBar::handle:vertical:hover{{background:{_PM_ORANGE};}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
        )
        self.pm_inner = QWidget()
        self.pm_inner.setStyleSheet("background:transparent;")
        self.pm_lay = QVBoxLayout(self.pm_inner)
        self.pm_lay.setContentsMargins(10, 10, 10, 10)
        self.pm_lay.setSpacing(6)

        # 空状态提示（带图标）
        pm_hint_wrap = QWidget()
        pm_hint_wrap.setStyleSheet("background:transparent;")
        pm_hint_vlay = QVBoxLayout(pm_hint_wrap)
        pm_hint_vlay.setContentsMargins(0, 8, 0, 8)
        pm_hint_vlay.setSpacing(4)
        self.pm_hint = QLabel("输入关键词，搜索 36氪 / 量子位 / 爱范儿 一级市场资讯")
        self.pm_hint.setFont(QFont("Arial", 10))
        self.pm_hint.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        self.pm_hint.setWordWrap(True)
        self.pm_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm_hint_vlay.addWidget(self.pm_hint)
        self.pm_lay.addWidget(pm_hint_wrap)
        self.pm_scroll.setWidget(self.pm_inner)
        pm_card_lay.addWidget(self.pm_scroll)

        root.addWidget(pm_card)

        # 内容滚动区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.inner = QWidget(); self.inner.setStyleSheet("background:transparent;")
        self.inner_lay = QVBoxLayout(self.inner)
        self.inner_lay.setContentsMargins(0, 0, 4, 0); self.inner_lay.setSpacing(14)
        self.inner_lay.addStretch()
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        # 空状态引导区（嵌在 scroll 内容区里，有数据时隐藏）
        self._empty_hint = QWidget()
        self._empty_hint.setStyleSheet("background:transparent;")
        _eh_lay = QVBoxLayout(self._empty_hint)
        _eh_lay.setContentsMargins(0, 32, 0, 0)
        _eh_lay.setSpacing(10)
        _eh_title = QLabel("消息引擎")
        _eh_title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        _eh_title.setStyleSheet(f"color:{FG3};background:transparent;")
        _eh_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _eh_lay.addWidget(_eh_title)
        _eh_desc = QLabel("请先在「年报查询」中搜索股票\n然后切换到此标签查看行业消息、利好利空分析")
        _eh_desc.setFont(QFont("Arial", 10))
        _eh_desc.setStyleSheet(f"color:{FG3};background:transparent;")
        _eh_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _eh_desc.setWordWrap(True)
        _eh_lay.addWidget(_eh_desc)
        _eh_lay.addStretch()
        self.inner_lay.insertWidget(0, self._empty_hint)

        self.hint = QLabel("请先在「年报查询」中搜索股票，然后切换到此标签查看消息引擎分析")
        self.hint.setFont(QFont("Arial", 11))
        self.hint.setStyleSheet(ls(FG2, 11))
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.hide()
        root.addWidget(self.hint)

        self._code = ""; self._market = ""; self._company = ""
        self._llm_cfg = {}
        self._pm_workers = []
        self._last_data: dict = {}   # 缓存最近一次消息引擎数据，供一键分析使用

    def set_llm_cfg(self, cfg: dict):
        self._llm_cfg = cfg

    def load(self, code: str, market: str, company: str = ""):
        self._code = code; self._market = market; self._company = company
        self.refresh_btn.setEnabled(False)
        self.hint.setText(f"正在抓取 {code} 消息引擎数据，请稍候...")
        self.hint.show()
        self._clear()
        self._fetch()

    def _refresh(self):
        if self._code:
            self.load(self._code, self._market, self._company)

    def _fetch(self):
        w = NewsWorker(self._code, self._market, self._company)
        w.finished.connect(self._on_data)
        w.error.connect(self._on_err)
        _track_worker(self._workers, w); w.start()

    def _on_data(self, data):
        self._last_data = data          # 缓存供一键分析读取
        self.hint.hide()
        self.refresh_btn.setEnabled(True)
        ind = data.get("industry_name", "")
        if ind:
            self.industry_lbl.setText(f"行业：{ind}")
            self.industry_lbl.show()
        else:
            self.industry_lbl.hide()
        self._render(data)

    def _on_err(self, msg):
        self.hint.setText(f"加载失败：{msg}")
        self.refresh_btn.setEnabled(True)

    def _kw_search(self):
        kw = self.kw_inp.text().strip()
        if not kw:
            return
        ctx_code   = self._code
        ctx_market = self._market

        # ── LLM / 联网搜索 ────────────────────────────────────────
        if not self._llm_cfg.get("enabled") or not self._llm_cfg.get("api_key"):
            self._kw_search_basic(kw)
            return
        self.kw_btn.setEnabled(False)
        self.kw_btn.setText("搜索中...")
        w = NewsKeywordWorker(kw, ctx_code, ctx_market, self._llm_cfg)
        w.finished.connect(lambda items, cached, pm: self._on_kw_data(kw, items, cached))
        w.error.connect(self._on_kw_err)
        _track_worker(self._workers, w); w.start()

    def _start_pm_worker(self, kw: str):
        """（已废弃，保留兼容）"""
        pass

    def _kw_search_basic(self, kw: str):
        """无 LLM 时：联网搜索（搜狗/Bing）+ 东方财富快讯，独立于当前股票"""
        self.kw_btn.setEnabled(False)
        self.kw_btn.setText("搜索中...")

        class _BasicKwWorker(QThread):
            finished = pyqtSignal(list)
            def __init__(self, keyword):
                super().__init__(); self._kw = keyword
            def run(self):
                try:
                    from news_fetcher import _fetch_emf_kuaixun, _dedup, _score, _make_item
                    from web_search import search_news
                    items = []
                    ws = search_news(self._kw, timeout=10)
                    for it_raw in ws.get("items", []):
                        if not it_raw.get("title"):
                            continue
                        it = _make_item(
                            title=it_raw["title"],
                            url=it_raw.get("url", ""),
                            source=it_raw.get("source") or "网络搜索",
                            pub_time_str="",
                            digest=it_raw.get("snippet", ""),
                            relevance=0.8,
                        )
                        items.append(it)
                    emf = _fetch_emf_kuaixun([self._kw], limit=50)
                    emf = _dedup(sorted(emf, key=_score, reverse=True))[:8]
                    existing = {it["title"][:20] for it in items}
                    for it in emf:
                        if it["title"][:20] not in existing:
                            items.append(it)
                    self.finished.emit(items[:15])
                except Exception:
                    self.finished.emit([])

        w = _BasicKwWorker(kw)
        w.finished.connect(lambda items: self._on_kw_data(kw, items, False))
        _track_worker(self._workers, w); w.start()

    def _on_kw_data(self, kw: str, items: list, from_cache: bool = False):
        import time as _time
        self.kw_btn.setEnabled(True)
        self.kw_btn.setText("LLM 搜索")
        self._remove_kw_section()
        lay = self.inner_lay
        lay.takeAt(lay.count() - 1)  # 移除 stretch
        if from_cache:
            _cache_entry = NewsKeywordWorker._cache.get((kw, self._code, self._market))
            if _cache_entry:
                _remaining = int(NewsKeywordWorker._CACHE_TTL - (_time.time() - _cache_entry[0]))
                _cache_hint = f"  ·  缓存数据（{_remaining}s 后刷新）"
            else:
                _cache_hint = "  ·  缓存数据"
            title = f"关键字搜索：{kw}{_cache_hint}"
        else:
            title = f"关键字搜索：{kw}"
        sec = NewsSectionWidget(title, "#BF5AF2")
        sec.setObjectName("kw_section")
        sec.add_items(items, badge_fn=lambda x: SENT_LABEL.get(x.get("sentiment", "neutral"), ""))
        lay.insertWidget(0, sec)
        lay.addStretch()

    def _on_kw_err(self, msg: str):
        self.kw_btn.setEnabled(True)
        self.kw_btn.setText("LLM 搜索")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "搜索失败", f"关键字搜索出错：{msg}")

    def _remove_kw_section(self):
        """移除之前的关键字搜索结果 section"""
        lay = self.inner_lay
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item and item.widget() and item.widget().objectName() == "kw_section":
                w = lay.takeAt(i).widget()
                if w: w.deleteLater()
                break

    def _remove_pm_section(self):
        """移除之前的一级市场专栏 section（inner_lay 里的，已废弃，保留兼容）"""
        lay = self.inner_lay
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item and item.widget() and item.widget().objectName() == "pm_section":
                w = lay.takeAt(i).widget()
                if w: w.deleteLater()
                break

    def _pm_search(self):
        """一级市场资讯独立搜索"""
        kw = self.pm_inp.text().strip()
        if not kw:
            return
        self.pm_btn.setEnabled(False)
        self.pm_btn.setText("搜索中...")
        # 清空结果区，显示加载提示
        while self.pm_lay.count():
            it = self.pm_lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        loading = QLabel(f"正在搜索「{kw}」...")
        loading.setFont(QFont("Arial", 10))
        loading.setStyleSheet(
            f"color:#FF9F0A;background:rgba(255,159,10,0.08);"
            f"border:1px solid rgba(255,159,10,0.2);border-radius:6px;padding:8px 14px;"
        )
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pm_lay.addWidget(loading)
        self.pm_lay.addStretch()

        class _PMSearchWorker(QThread):
            finished = pyqtSignal(list, str)   # (items, error_msg)
            def __init__(self, keyword):
                super().__init__(); self._kw = keyword
            def run(self):
                try:
                    from web_search import search_primary_market
                    r = search_primary_market(self._kw, timeout=12)
                    self.finished.emit(r.get("items", []), "")
                except Exception as e:
                    self.finished.emit([], str(e))

        w = _PMSearchWorker(kw)
        w.finished.connect(lambda items, err: self._on_pm_result(kw, items, err))
        _track_worker(self._pm_workers, w)
        w.start()

    def _on_pm_result(self, kw: str, items: list, err: str):
        """一级市场搜索结果回调，渲染到 pm_scroll 区域"""
        self.pm_btn.setEnabled(True)
        self.pm_btn.setText("搜资讯")
        # 清空旧内容
        while self.pm_lay.count():
            it = self.pm_lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()

        if err:
            lbl = QLabel(f"搜索失败：{err}")
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet(f"color:{ERR};padding:8px;")
            lbl.setWordWrap(True)
            self.pm_lay.addWidget(lbl)
            self.pm_lay.addStretch()
            return

        if not items:
            lbl = QLabel(f"未找到「{kw}」相关的一级市场资讯")
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet(f"color:{FG3};padding:10px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.pm_lay.addWidget(lbl)
            return

        # 渲染结果卡片
        from news_fetcher import _make_item
        sources = list(dict.fromkeys(it.get("source", "") for it in items))

        # 结果头部：数量徽章 + 信源标签
        hdr_row = QHBoxLayout(); hdr_row.setSpacing(6); hdr_row.setContentsMargins(2, 0, 2, 4)
        count_lbl = QLabel(f"找到 {len(items)} 条")
        count_lbl.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        count_lbl.setStyleSheet(
            f"color:#FF9F0A;background:rgba(255,159,10,0.12);"
            f"border:1px solid rgba(255,159,10,0.3);border-radius:4px;padding:1px 7px;"
        )
        hdr_row.addWidget(count_lbl)
        for src in sources:
            if not src: continue
            stag = QLabel(src)
            stag.setFont(QFont("Arial", 9))
            stag.setStyleSheet(
                f"color:{FG2};background:{CARD2};"
                f"border:1px solid {BORDER};border-radius:4px;padding:1px 6px;"
            )
            hdr_row.addWidget(stag)
        hdr_row.addStretch()
        hdr_w = QWidget(); hdr_w.setStyleSheet("background:transparent;")
        hdr_w.setLayout(hdr_row)
        self.pm_lay.addWidget(hdr_w)

        for pm in items:
            it = _make_item(
                title=pm.get("title", ""),
                url=pm.get("url", ""),
                source=pm.get("source", ""),
                pub_time_str=pm.get("pub_date_str", ""),
                digest=pm.get("summary", ""),
                relevance=0.7,
            )
            card = NewsCard(it, "资讯")
            self.pm_lay.addWidget(card)

    def _render(self, data):
        self._clear()
        self._empty_hint.hide()
        lay = self.inner_lay
        lay.takeAt(lay.count() - 1)  # 移除 stretch

        # ── 行业消息汇总 ──────────────────────────────────────
        ind_items = data.get("industry_news", [])
        ind_name  = data.get("industry_name", "行业")
        sec_ind = NewsSectionWidget(f"行业消息汇总  ·  {ind_name or '行业'}", ACCENT)
        sec_ind.add_items(ind_items, badge_fn=lambda x: SENT_LABEL.get(x.get("sentiment","neutral"),""))
        lay.addWidget(sec_ind)

        # ── TOP10 公司关联消息 ────────────────────────────────
        comp_items = data.get("company_news", [])
        sec_comp = NewsSectionWidget(f"TOP10 公司关联消息  ·  {self._code}", "#64D2FF")
        sec_comp.add_items(comp_items, badge_fn=lambda x: SENT_LABEL.get(x.get("sentiment","neutral"),""))
        lay.addWidget(sec_comp)

        # ── 利好消息 ──────────────────────────────────────────
        bull_items = data.get("bullish", [])
        sec_bull = NewsSectionWidget("利好消息", SUCCESS)
        sec_bull.add_items(bull_items, badge_fn=lambda x: "利好")
        lay.addWidget(sec_bull)

        # ── 风险消息（三类） ──────────────────────────────────
        risks = data.get("risks", {})
        risk_defs = [
            ("market",    "市场风险",  WARN),
            ("financial", "财务风险",  ERR),
            ("tech",      "技术风险",  "#BF5AF2"),
        ]
        for rkey, rlabel, rcolor in risk_defs:
            items = risks.get(rkey, [])
            sec = NewsSectionWidget(rlabel, rcolor)
            sec.add_items(items, badge_fn=lambda x, rl=rlabel: rl)
            lay.addWidget(sec)

        # 数据说明
        note = QLabel(
            "数据来源：东方财富 / 新浪财经 / Yahoo Finance / Reuters  |  "
            "排序权重：权威度 40% + 时效性 35% + 关联度 25%  |  点击标题打开原文"
        )
        note.setFont(QFont("Arial", 9))
        note.setStyleSheet(f"color:{FG2};padding:4px 0;")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch()

    def _clear(self):
        lay = self.inner_lay
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w and w is not self._empty_hint:
                w.deleteLater()
        # 重新插入空状态占位并显示
        self._empty_hint.show()
        lay.insertWidget(0, self._empty_hint)
        lay.addStretch()


# ═══════════════════════════════════════════════
# LLM 设置对话框 & 智能搜索对话框
# ═══════════════════════════════════════════════

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QComboBox, QFormLayout, QMessageBox


class LLMSearchDialog(QDialog):
    """LLM 智能搜索对话框：输入公司描述 -> 推荐上市股票"""
    stock_selected = pyqtSignal(str)   # 用户点击某只股票时 emit 代码

    def __init__(self, llm_cfg: dict, parent=None):
        super().__init__(parent)
        self._llm_cfg = llm_cfg
        self._workers = []
        self.setWindowTitle("LLM 智能搜索")
        self.setMinimumSize(520, 420)
        self.setStyleSheet(f"""
            QDialog{{background:{BG};}}
            QLabel{{color:{FG};background:transparent;border:none;}}
            QLineEdit{{background:{INPUT_BG};color:{FG};border:1px solid {BORDER};
                border-radius:8px;padding:6px 10px;font-size:12px;}}
            QLineEdit:focus{{border-color:{ACCENT};}}
            QPushButton{{background:{ACCENT};color:white;border:none;border-radius:8px;
                padding:6px 16px;font-size:12px;font-weight:600;}}
            QPushButton:hover{{background:{ACCENT_H};}}
            QPushButton:disabled{{background:{CARD2};color:{FG3};}}
            QScrollArea{{background:transparent;border:none;}}
        """)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16); root.setSpacing(12)

        title = QLabel("LLM 智能搜索")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{FG};font-size:14px;font-weight:700;")
        root.addWidget(title)

        desc = QLabel("描述一家公司或业务，AI 将推荐最相似的上市股票（支持未上市公司描述）")
        desc.setFont(QFont("Arial", 10))
        desc.setStyleSheet(f"color:{FG2};font-size:10px;")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # 输入行
        inp_row = QHBoxLayout(); inp_row.setSpacing(8)
        self.query_inp = QLineEdit()
        self.query_inp.setPlaceholderText("例：做半导体芯片设计的公司，主要产品是 GPU")
        self.query_inp.setFixedHeight(36)
        self.query_inp.returnPressed.connect(self._search)
        inp_row.addWidget(self.query_inp, 1)
        self.search_btn = QPushButton("搜索")
        self.search_btn.setFixedSize(72, 36)
        self.search_btn.clicked.connect(self._search)
        inp_row.addWidget(self.search_btn)
        root.addLayout(inp_row)

        # 状态标签
        self.status_lbl = QLabel("")
        self.status_lbl.setFont(QFont("Arial", 10))
        self.status_lbl.setStyleSheet(f"color:{FG2};font-size:10px;")
        root.addWidget(self.status_lbl)

        # 结果滚动区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget(); self.inner.setStyleSheet("background:transparent;")
        self.inner_lay = QVBoxLayout(self.inner)
        self.inner_lay.setContentsMargins(0, 0, 4, 0); self.inner_lay.setSpacing(6)
        self.inner_lay.addStretch()
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        # 关闭按钮（hide 而非 destroy，保留搜索状态）
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{FG2};border:1px solid {BORDER};"
            f"border-radius:8px;padding:6px 16px;font-size:12px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
        )
        close_btn.clicked.connect(self.hide)
        btn_row = QHBoxLayout(); btn_row.addStretch(); btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _search(self):
        query = self.query_inp.text().strip()
        if not query:
            return
        if not self._llm_cfg.get("enabled") or not self._llm_cfg.get("api_key"):
            self.status_lbl.setText("请先在「设置」中配置并启用 LLM API Key")
            self.status_lbl.setStyleSheet(f"color:{WARN};font-size:10px;")
            return
        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中...")
        self.status_lbl.setText(f"正在分析：{query[:40]}...")
        self.status_lbl.setStyleSheet(f"color:{FG2};font-size:10px;")
        self._clear_results()

        w = LLMSearchWorker(query, self._llm_cfg)
        w.finished.connect(self._on_results)
        w.error.connect(self._on_err)
        _track_worker(self._workers, w); w.start()

    def _on_results(self, results: list):
        self.search_btn.setEnabled(True)
        self.search_btn.setText("搜索")
        if not results:
            self.status_lbl.setText("未找到相关股票，请换个描述试试")
            self.status_lbl.setStyleSheet(f"color:{WARN};font-size:10px;")
            return
        self.status_lbl.setText(f"找到 {len(results)} 只相关股票，点击可直接查询")
        self.status_lbl.setStyleSheet(f"color:{SUCCESS};font-size:10px;")
        self._clear_results()
        lay = self.inner_lay
        lay.takeAt(lay.count() - 1)  # 移除 stretch

        for i, item in enumerate(results):
            card = self._make_result_card(i + 1, item)
            lay.addWidget(card)
        lay.addStretch()

    def _make_result_card(self, rank: int, item: dict) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:8px;}}"
            f"QFrame:hover{{border-color:{ACCENT};background:{CARD2};}}"
        )
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(card); lay.setContentsMargins(12, 8, 12, 8); lay.setSpacing(4)

        # 顶行
        top = QHBoxLayout(); top.setSpacing(8)
        rank_lbl = QLabel(f"#{rank}")
        rank_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        rank_lbl.setStyleSheet(f"color:{ACCENT if rank <= 3 else FG2};background:transparent;border:none;")
        top.addWidget(rank_lbl)

        name_lbl = QLabel(item.get("name", "—"))
        name_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        top.addWidget(name_lbl)

        code_lbl = QLabel(f"{item.get('code','')}  ·  {item.get('market','')}")
        code_lbl.setFont(QFont("Arial", 10))
        code_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        top.addWidget(code_lbl)
        top.addStretch()

        conf = item.get("confidence", 0)
        conf_lbl = QLabel(f"{conf*100:.0f}%")
        conf_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        conf_color = SUCCESS if conf >= 0.7 else (WARN if conf >= 0.4 else FG2)
        conf_lbl.setStyleSheet(
            f"color:{conf_color};background:rgba(0,0,0,0.2);"
            f"border:1px solid {conf_color};border-radius:5px;padding:0 6px;"
        )
        top.addWidget(conf_lbl)
        lay.addLayout(top)

        reason = item.get("reason", "")
        if reason:
            r_lbl = QLabel(reason)
            r_lbl.setFont(QFont("Arial", 10))
            r_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            r_lbl.setWordWrap(True)
            lay.addWidget(r_lbl)

        # 点击查询（hide 保留状态，不销毁）
        code = item.get("code", "")
        def _click(event, c=code):
            if event.button() == Qt.MouseButton.LeftButton and c:
                self.stock_selected.emit(c)
                self.hide()
        card.mousePressEvent = _click
        return card

    def _on_err(self, msg: str):
        self.search_btn.setEnabled(True)
        self.search_btn.setText("搜索")
        self.status_lbl.setText(f"搜索失败：{msg}")
        self.status_lbl.setStyleSheet(f"color:{ERR};font-size:10px;")

    def _clear_results(self):
        lay = self.inner_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        lay.addStretch()

    def closeEvent(self, event):
        """关闭窗口时只 hide，保留搜索状态"""
        event.ignore()
        self.hide()

    def keyPressEvent(self, event):
        """Esc 键只 hide，不销毁"""
        from PyQt6.QtCore import Qt as _Qt
        if event.key() == _Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def update_llm_cfg(self, cfg: dict):
        """外部更新 LLM 配置（设置保存后调用）"""
        self._llm_cfg = cfg


class LLMSettingsDialog(QDialog):
    """LLM API 配置对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM 大模型设置")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"""
            QDialog{{background:{BG};}}
            QLabel{{color:{FG};background:transparent;border:none;}}
            QLineEdit{{background:{INPUT_BG};color:{FG};border:1px solid {BORDER};
                border-radius:6px;padding:4px 8px;font-size:12px;}}
            QLineEdit:focus{{border-color:{ACCENT};}}
            QComboBox{{background:{INPUT_BG};color:{FG};border:1px solid {BORDER};
                border-radius:6px;padding:4px 8px;font-size:12px;}}
            QComboBox QAbstractItemView{{background:{CARD};color:{FG};border:1px solid {BORDER};}}
            QPushButton{{background:{ACCENT};color:white;border:none;border-radius:7px;
                padding:6px 18px;font-size:12px;font-weight:600;}}
            QPushButton:hover{{background:{ACCENT_H};}}
            QPushButton:disabled{{background:#3A3D4E;color:{FG2};}}
        """)
        self._build()
        self._load()

    def _build(self):
        from llm_client import PROVIDERS
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16); root.setSpacing(14)

        # 标题
        title = QLabel("大模型配置")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{FG};font-size:14px;font-weight:700;")
        root.addWidget(title)

        desc = QLabel("配置后可在「同行业扫描」中获得 AI 生成的相似原因说明，\n以及消息引擎的智能摘要增强。")
        desc.setFont(QFont("Arial", 10))
        desc.setStyleSheet(f"color:{FG2};font-size:10px;")
        desc.setWordWrap(True)
        root.addWidget(desc)

        form = QFormLayout(); form.setSpacing(10); form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Provider 选择
        self.provider_cb = QComboBox()
        for key, info in PROVIDERS.items():
            self.provider_cb.addItem(info["name"], key)
        self.provider_cb.currentIndexChanged.connect(self._on_provider_change)
        form.addRow("服务商：", self.provider_cb)

        # API Key
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("sk-...")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key：", self.key_edit)

        # Base URL（自定义时显示）
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://api.openai.com/v1")
        self.url_lbl = QLabel("Base URL：")
        form.addRow(self.url_lbl, self.url_edit)

        # 模型名
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("留空使用默认模型")
        form.addRow("模型名称：", self.model_edit)

        root.addLayout(form)

        # 启用开关
        enable_row = QHBoxLayout()
        self.enable_btn = QPushButton("已禁用 — 点击启用")
        self.enable_btn.setCheckable(True)
        self.enable_btn.setChecked(False)
        self.enable_btn.clicked.connect(self._toggle_enable)
        self._update_enable_btn()
        enable_row.addWidget(self.enable_btn)
        enable_row.addStretch()
        root.addLayout(enable_row)

        # 测试连接
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test)
        self.test_result = QLabel("")
        self.test_result.setFont(QFont("Arial", 10))
        self.test_result.setStyleSheet(f"color:{FG2};font-size:10px;")
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        root.addLayout(test_row)

        # 按钮
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load(self):
        from llm_client import load_config, PROVIDERS
        cfg = load_config()
        # 设置 provider
        provider = cfg.get("provider", "openai")
        for i in range(self.provider_cb.count()):
            if self.provider_cb.itemData(i) == provider:
                self.provider_cb.setCurrentIndex(i); break
        self.key_edit.setText(cfg.get("api_key", ""))
        self.url_edit.setText(cfg.get("base_url", ""))
        self.model_edit.setText(cfg.get("model", ""))
        enabled = cfg.get("enabled", False)
        self.enable_btn.setChecked(enabled)
        self._update_enable_btn()
        self._on_provider_change()

    def _on_provider_change(self):
        from llm_client import PROVIDERS
        key = self.provider_cb.currentData()
        is_custom = (key == "custom")
        self.url_lbl.setVisible(is_custom)
        self.url_edit.setVisible(is_custom)
        if not is_custom:
            preset = PROVIDERS.get(key, {})
            if not self.model_edit.text():
                self.model_edit.setPlaceholderText(preset.get("model", ""))

    def _toggle_enable(self):
        self._update_enable_btn()

    def _update_enable_btn(self):
        if self.enable_btn.isChecked():
            self.enable_btn.setText("已启用 ✓")
            self.enable_btn.setStyleSheet(
                f"QPushButton{{background:{SUCCESS};color:white;border:none;border-radius:7px;"
                f"padding:6px 18px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:#2DB84D;}}"
            )
        else:
            self.enable_btn.setText("已禁用 — 点击启用")
            self.enable_btn.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{FG2};border:1px solid {BORDER};border-radius:7px;"
                f"padding:6px 18px;font-size:12px;}}"
                f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
            )

    def _test(self):
        self.test_btn.setEnabled(False)
        self.test_result.setText("连接中...")
        self.test_result.setStyleSheet(f"color:{FG2};font-size:10px;")
        cfg = self._collect_cfg()
        try:
            from llm_client import LLMClient
            ok, msg = LLMClient(cfg).test_connection()
            self.test_result.setText(msg)
            self.test_result.setStyleSheet(f"color:{SUCCESS if ok else ERR};font-size:10px;")
        except Exception as e:
            self.test_result.setText(str(e))
            self.test_result.setStyleSheet(f"color:{ERR};font-size:10px;")
        finally:
            self.test_btn.setEnabled(True)

    def _collect_cfg(self) -> dict:
        from llm_client import PROVIDERS
        provider = self.provider_cb.currentData()
        preset   = PROVIDERS.get(provider, {})
        return {
            "provider": provider,
            "api_key":  self.key_edit.text().strip(),
            "base_url": self.url_edit.text().strip() or preset.get("base_url", ""),
            "model":    self.model_edit.text().strip() or preset.get("model", ""),
            "enabled":  self.enable_btn.isChecked(),
        }

    def _save(self):
        from llm_client import save_config
        cfg = self._collect_cfg()
        if cfg["enabled"] and not cfg["api_key"]:
            QMessageBox.warning(self, "提示", "请先填写 API Key 再启用大模型功能。")
            return
        save_config(cfg)
        self.accept()

    def get_config(self) -> dict:
        return self._collect_cfg()


# ═══════════════════════════════════════════════
# 投研 Agent Team 智能问答面板
# ═══════════════════════════════════════════════

class AgentChatPanel(QWidget):
    """一键分析主页面（自动注入中间结果，支持追问）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")
        self._llm_cfg: dict = {}
        self._history: list[dict] = []   # [{role, content}, ...]
        self._worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── 对话历史滚动区 ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._msg_w = QWidget(); self._msg_w.setStyleSheet("background:transparent;")
        self._msg_lay = QVBoxLayout(self._msg_w)
        self._msg_lay.setContentsMargins(16, 16, 16, 8); self._msg_lay.setSpacing(12)
        self._msg_lay.addStretch()
        self._scroll.setWidget(self._msg_w)
        root.addWidget(self._scroll, 1)

        # ── 欢迎提示（首次显示）──
        self._welcome = QLabel(
            "✦  一键分析\n\n"
            "先在左侧搜索股票代码，再点击「一键分析」\n"
            "系统将自动读取年报、行情、消息等中间结果\n"
            "由 AI 生成综合投研分析报告\n\n"
            "分析完成后可继续追问"
        )
        self._welcome.setFont(QFont("Arial", 12))
        self._welcome.setStyleSheet(
            f"color:{FG2};background:{CARD};border:1px solid {BORDER};"
            f"border-radius:12px;padding:20px 24px;"
        )
        self._welcome.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._welcome.setWordWrap(True)
        self._msg_lay.insertWidget(self._msg_lay.count() - 1, self._welcome)

        # ── 底部输入区 ──
        input_frame = QFrame()
        input_frame.setStyleSheet(
            f"QFrame{{background:{BG};border-top:1px solid {BORDER2};}}"
        )
        input_lay = QVBoxLayout(input_frame)
        input_lay.setContentsMargins(16, 10, 16, 14); input_lay.setSpacing(8)

        # 工具栏行（清空按钮 + 当前股票标签）
        tool_row = QHBoxLayout(); tool_row.setSpacing(8)
        self._ctx_lbl = QLabel("")
        self._ctx_lbl.setFont(QFont("Arial", 9))
        self._ctx_lbl.setStyleSheet(
            f"color:{ACCENT};background:rgba(79,142,247,0.1);"
            f"border:1px solid rgba(79,142,247,0.25);border-radius:5px;padding:2px 8px;"
        )
        self._ctx_lbl.hide()
        tool_row.addWidget(self._ctx_lbl)
        tool_row.addStretch()
        self._clear_btn = QPushButton("清空对话")
        self._clear_btn.setFixedHeight(26)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{FG2};border:1px solid {BORDER};"
            f"border-radius:6px;font-size:10px;padding:0 10px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
        )
        self._clear_btn.clicked.connect(self._clear_chat)
        tool_row.addWidget(self._clear_btn)

        # 重新分析按钮
        self._reanalyze_btn = QPushButton("重新分析")
        self._reanalyze_btn.setFixedHeight(26)
        self._reanalyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reanalyze_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACCENT};border:1px solid rgba(79,142,247,0.4);"
            f"border-radius:6px;font-size:10px;padding:0 10px;}}"
            f"QPushButton:hover{{background:rgba(79,142,247,0.1);}}"
        )
        self._reanalyze_btn.hide()
        self._reanalyze_btn.clicked.connect(self._do_reanalyze)
        tool_row.addWidget(self._reanalyze_btn)
        self._last_ctx = ""
        input_lay.addLayout(tool_row)

        # 输入框行
        inp_row = QHBoxLayout(); inp_row.setSpacing(8)
        self._inp = QTextEdit()
        self._inp.setPlaceholderText("输入投研问题，按 Ctrl+Enter 发送…")
        self._inp.setFont(QFont("Arial", 12))
        self._inp.setFixedHeight(72)
        self._inp.setStyleSheet(
            f"QTextEdit{{background:{INPUT_BG};color:{FG};border:1.5px solid {INPUT_BD};"
            f"border-radius:10px;padding:8px 12px;font-size:12px;}}"
            f"QTextEdit:focus{{border-color:{ACCENT};}}"
        )
        self._inp.installEventFilter(self)
        inp_row.addWidget(self._inp, 1)

        send_col = QVBoxLayout(); send_col.setSpacing(4)
        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedSize(64, 34)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;border-radius:8px;"
            f"font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self._send_btn.clicked.connect(self._send)
        send_col.addWidget(self._send_btn)
        send_col.addStretch()
        inp_row.addLayout(send_col)
        input_lay.addLayout(inp_row)

        root.addWidget(input_frame)

    # ── 事件过滤：Ctrl+Enter 发送 ──
    def eventFilter(self, obj, event):
        if obj is self._inp and event.type() == event.Type.KeyPress:
            if (event.key() == Qt.Key.Key_Return and
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self._send()
                return True
        return super().eventFilter(obj, event)

    def set_llm_cfg(self, cfg: dict):
        self._llm_cfg = cfg

    def set_context(self, code: str, company: str = ""):
        """设置当前股票上下文"""
        if code:
            label = f"当前股票：{code}"
            if company: label += f"  {company}"
            self._ctx_lbl.setText(label)
            self._ctx_lbl.show()
        else:
            self._ctx_lbl.hide()

    def auto_analyze(self, context: str):
        """自动注入上下文并触发分析，每次点击都重新分析"""
        self._last_ctx = context
        self._reanalyze_btn.show()
        # 清空历史，重新开始
        self._clear_chat()
        prompt = (
            "以下是该公司的当前数据，请你作为专业投研分析师，"
            "从基本面、行情表现、近期消息三个维度给出综合分析，"
            "指出主要风险点和亮点，结构清晰，语言简洁专业：\n\n"
            + context
        )
        self._trigger_analysis(prompt)

    def _do_reanalyze(self):
        """重新触发分析（使用上次的上下文）"""
        if self._last_ctx:
            self.auto_analyze(self._last_ctx)

    def _trigger_analysis(self, prompt: str):
        """内部：直接发送 prompt 触发 LLM，不显示用户气泡"""
        if not self._llm_cfg.get("enabled") or not self._llm_cfg.get("api_key"):
            self._append_bubble("system", "⚠ 请先在「设置」中配置并启用 LLM API Key")
            return
        if hasattr(self, "_welcome") and self._welcome and self._welcome.isVisible():
            self._welcome.hide()
        self._send_btn.setEnabled(False)
        # 显示「分析中」气泡
        self._append_bubble("user", "📊 正在读取数据，自动生成分析报告…")
        self._history.append({"role": "user", "content": prompt})
        self._thinking_lbl = self._append_bubble("assistant", "⏳ 分析中，请稍候…")
        self._worker = _AgentChatWorker(self._history.copy(), self._llm_cfg)
        self._worker.finished.connect(self._on_reply)
        self._worker.error.connect(self._on_err)
        self._worker.start()

    def _clear_chat(self):
        self._history.clear()
        lay = self._msg_lay
        # 保留 stretch（最后一项）
        while lay.count() > 1:
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        # 重新显示欢迎语
        self._welcome = QLabel(
            "✦  一键分析\n\n"
            "先在左侧搜索股票代码，再点击「一键分析」\n"
            "系统将自动读取年报、行情、消息等中间结果\n"
            "由 AI 生成综合投研分析报告\n\n"
            "分析完成后可继续追问"
        )
        self._welcome.setFont(QFont("Arial", 12))
        self._welcome.setStyleSheet(
            f"color:{FG2};background:{CARD};border:1px solid {BORDER};"
            f"border-radius:12px;padding:20px 24px;"
        )
        self._welcome.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._welcome.setWordWrap(True)
        self._msg_lay.insertWidget(0, self._welcome)

    def _send(self):
        text = self._inp.toPlainText().strip()
        if not text: return
        if not self._llm_cfg.get("enabled") or not self._llm_cfg.get("api_key"):
            self._append_bubble("system", "⚠ 请先在「设置」中配置并启用 LLM API Key")
            return
        # 隐藏欢迎语
        if hasattr(self, "_welcome") and self._welcome and self._welcome.isVisible():
            self._welcome.hide()
        self._inp.clear()
        self._send_btn.setEnabled(False)
        self._append_bubble("user", text)
        self._history.append({"role": "user", "content": text})
        # 显示思考中气泡
        self._thinking_lbl = self._append_bubble("assistant", "⏳ 思考中…")
        # 启动 worker
        self._worker = _AgentChatWorker(self._history.copy(), self._llm_cfg)
        self._worker.finished.connect(self._on_reply)
        self._worker.error.connect(self._on_err)
        self._worker.start()

    def _on_reply(self, reply: str):
        self._send_btn.setEnabled(True)
        # 替换思考中气泡
        if self._thinking_lbl:
            self._thinking_lbl.setText(reply)
            self._thinking_lbl.setStyleSheet(
                f"color:{FG};background:{CARD};border:1px solid {BORDER};"
                f"border-radius:10px;padding:10px 14px;"
            )
            self._thinking_lbl = None
        self._history.append({"role": "assistant", "content": reply})
        self._scroll_bottom()

    def _on_err(self, msg: str):
        self._send_btn.setEnabled(True)
        if self._thinking_lbl:
            self._thinking_lbl.setText(f"⚠ {msg}")
            self._thinking_lbl.setStyleSheet(
                f"color:{WARN};background:rgba(255,159,10,0.08);border:1px solid rgba(255,159,10,0.3);"
                f"border-radius:10px;padding:10px 14px;"
            )
            self._thinking_lbl = None

    def _append_bubble(self, role: str, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Arial", 12))
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if role == "user":
            lbl.setStyleSheet(
                f"color:{FG};background:rgba(79,142,247,0.15);border:1px solid rgba(79,142,247,0.3);"
                f"border-radius:10px;padding:10px 14px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        elif role == "assistant":
            lbl.setStyleSheet(
                f"color:{FG2};background:{CARD};border:1px solid {BORDER};"
                f"border-radius:10px;padding:10px 14px;"
            )
        else:  # system
            lbl.setStyleSheet(
                f"color:{WARN};background:rgba(255,159,10,0.08);border:1px solid rgba(255,159,10,0.3);"
                f"border-radius:8px;padding:8px 12px;"
            )
        self._msg_lay.insertWidget(self._msg_lay.count() - 1, lbl)
        self._scroll_bottom()
        return lbl

    def _scroll_bottom(self):
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))


class _AgentChatWorker(QThread):
    """后台调用 LLM 的工作线程"""
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    SYSTEM_PROMPT = (
        "你是一位专业的投资研究分析师，擅长中国大陆、中国香港、美国市场的基本面分析、"
        "行业研究、财务数据解读和投资逻辑梳理。"
        "当收到系统自动整理的公司数据时，请从基本面、行情表现、近期消息三个维度给出结构化分析，"
        "指出主要风险点和亮点，语言简洁专业，使用 Markdown 格式输出。"
        "当用户追问时，结合已有上下文继续深入分析。"
        "不要提供具体买卖建议，但可以客观分析利弊。"
    )

    def __init__(self, history: list, cfg: dict, parent=None):
        super().__init__(parent)
        self._history = history
        self._cfg = cfg

    def run(self):
        try:
            from llm_client import LLMClient
            client = LLMClient(self._cfg)
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT}] + self._history
            reply = client.chat_messages(messages)
            self.finished.emit(reply)
        except Exception as e:
            self.error.emit(_friendly_err(e, "AgentChatWorker"))


# ═══════════════════════════════════════════════
# 同行业智能搜索面板（内嵌页面）
# ═══════════════════════════════════════════════

class PeerSearchPanel(QWidget):
    """同行业智能搜索：输入公司描述，LLM 推荐同行业上市公司"""
    stock_selected = pyqtSignal(str)   # 用户点击某只股票时 emit 代码

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")
        self._llm_cfg: dict = {}
        self._worker = None
        self._last_results: list = []   # 缓存最近一次搜索结果，供一键分析使用
        self._last_query: str = ""      # 缓存最近一次搜索关键词
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── 顶部输入区 ──
        top_frame = QFrame()
        top_frame.setStyleSheet(
            f"QFrame{{background:{BG};border-bottom:1px solid {BORDER2};}}"
        )
        top_lay = QVBoxLayout(top_frame)
        top_lay.setContentsMargins(20, 16, 20, 14); top_lay.setSpacing(10)

        desc_lbl = QLabel("输入公司名称或行业描述，AI 先调研业务再推荐同行业上市公司：")
        desc_lbl.setFont(QFont("Arial", 11))
        desc_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        top_lay.addWidget(desc_lbl)

        inp_row = QHBoxLayout(); inp_row.setSpacing(10)
        self._inp = QLineEdit()
        self._inp.setPlaceholderText("例如：超维无际、做新能源汽车电池的龙头企业、美国云计算SaaS公司…")
        self._inp.setFont(QFont("Arial", 12))
        self._inp.setFixedHeight(40)
        self._inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};color:{FG};border:1.5px solid {INPUT_BD};"
            f"border-radius:10px;padding:0 12px;font-size:12px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};}}"
        )
        self._inp.returnPressed.connect(self._search)
        inp_row.addWidget(self._inp, 1)

        self._search_btn = QPushButton("智能搜索")
        self._search_btn.setFixedHeight(40)
        self._search_btn.setFixedWidth(100)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;border-radius:10px;"
            f"font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self._search_btn.clicked.connect(self._search)
        inp_row.addWidget(self._search_btn)
        top_lay.addLayout(inp_row)

        # 进度状态行
        self._progress_lbl = QLabel("")
        self._progress_lbl.setFont(QFont("Arial", 10))
        self._progress_lbl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        self._progress_lbl.hide()
        top_lay.addWidget(self._progress_lbl)

        root.addWidget(top_frame)

        # ── 结果滚动区 ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._result_w = QWidget(); self._result_w.setStyleSheet("background:transparent;")
        self._result_lay = QVBoxLayout(self._result_w)
        self._result_lay.setContentsMargins(20, 16, 20, 16); self._result_lay.setSpacing(10)

        # 初始提示
        self._hint = QLabel("请在上方输入公司名称或描述，AI 将先调研业务再推荐同行业上市公司")
        self._hint.setFont(QFont("Arial", 11))
        self._hint.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_lay.addWidget(self._hint)
        self._result_lay.addStretch()
        self._scroll.setWidget(self._result_w)
        root.addWidget(self._scroll, 1)

        # 调研摘要卡片（初始隐藏）
        self._research_card = None

    def set_llm_cfg(self, cfg: dict):
        self._llm_cfg = cfg

    def _search(self):
        query = self._inp.text().strip()
        if not query: return
        if not self._llm_cfg.get("enabled") or not self._llm_cfg.get("api_key"):
            self._show_hint("⚠ 请先在「设置」中配置并启用 LLM API Key")
            return
        self._search_btn.setEnabled(False)
        self._progress_lbl.setText("🌐 第一步：正在联网搜索目标公司信息…")
        self._progress_lbl.show()
        self._clear_results()
        self._hint.hide()
        self._worker = _PeerSearchWorker(query, self._llm_cfg)
        self._worker.progress.connect(self._on_progress)
        self._worker.research_done.connect(self._on_research_done)
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_err)
        self._worker.start()

    def _on_progress(self, msg: str):
        self._progress_lbl.setText(msg)

    def _on_research_done(self, research: str):
        """阶段一完成：在结果区顶部插入调研摘要卡片"""
        self._progress_lbl.setText("📊 第二步：正在基于调研结果匹配同行业上市公司…")
        # 移除旧的调研卡片
        if self._research_card is not None:
            self._research_card.deleteLater()
            self._research_card = None
        card = self._make_research_card(research)
        self._research_card = card
        self._result_lay.insertWidget(0, card)

    def _make_research_card(self, research: str) -> QFrame:
        """构建调研摘要折叠卡片"""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid rgba(79,142,247,0.35);"
            f"border-radius:10px;}}"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(0, 0, 0, 0); card_lay.setSpacing(0)

        # 标题行（可点击折叠）
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:rgba(79,142,247,0.10);border-radius:10px 10px 0 0;"
        )
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(14, 10, 14, 10); hdr_lay.setSpacing(8)

        icon_lbl = QLabel("🔬")
        icon_lbl.setFont(QFont("Arial", 12))
        icon_lbl.setStyleSheet("background:transparent;border:none;")
        hdr_lay.addWidget(icon_lbl)

        title_lbl = QLabel("AI 调研摘要  ·  点击展开/收起")
        title_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        hdr_lay.addWidget(title_lbl)
        hdr_lay.addStretch()

        toggle_lbl = QLabel("▼")
        toggle_lbl.setFont(QFont("Arial", 10))
        toggle_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        hdr_lay.addWidget(toggle_lbl)
        card_lay.addWidget(hdr)

        # 内容区（默认展开）
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(14, 10, 14, 12); body_lay.setSpacing(0)

        content_lbl = QLabel(research)
        content_lbl.setFont(QFont("Arial", 10))
        content_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;line-height:1.6;")
        content_lbl.setWordWrap(True)
        content_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_lay.addWidget(content_lbl)
        card_lay.addWidget(body)

        # 折叠逻辑
        def _toggle(event):
            if body.isVisible():
                body.hide()
                toggle_lbl.setText("▶")
                hdr.setStyleSheet(
                    f"background:rgba(79,142,247,0.10);border-radius:10px;"
                )
            else:
                body.show()
                toggle_lbl.setText("▼")
                hdr.setStyleSheet(
                    f"background:rgba(79,142,247,0.10);border-radius:10px 10px 0 0;"
                )
        hdr.mousePressEvent = _toggle
        return card

    def _on_results(self, results: list):
        self._last_results = results    # 缓存供一键分析读取
        self._search_btn.setEnabled(True)
        self._progress_lbl.hide()
        if not results:
            self._show_hint("未找到相关上市公司，请尝试更换描述")
            return
        # 在调研卡片之后插入结果标题和列表
        insert_pos = 1 if self._research_card is not None else 0
        hdr = QLabel(f"找到 {len(results)} 家相关上市公司  ·  点击可跳转查询")
        hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        self._result_lay.insertWidget(insert_pos, hdr)
        for i, item in enumerate(results):
            card = self._make_card(i + 1, item)
            self._result_lay.insertWidget(insert_pos + 1 + i, card)

    def _on_err(self, msg: str):
        self._search_btn.setEnabled(True)
        self._progress_lbl.hide()
        self._show_hint(f"⚠ 搜索失败：{msg}")

    @staticmethod
    def _clean_code(raw_code: str) -> tuple[str, str, bool]:
        """
        清洗 LLM 返回的股票代码，返回 (clean_code, market, supported)。
        - clean_code : 剥离后缀后的纯净代码（可直接传给 QueryWorker）
        - market     : 'US' / 'HK' / 'CN' / 'TW' / ...
        - supported  : 是否在本应用支持范围内（US/HK/CN）
        """
        from fetcher import detect_market, normalize_code, _SUFFIX_MARKET, _SUFFIX_RE
        code = raw_code.strip().upper()
        # 先判断后缀是否属于不支持的市场（台股/韩股等）
        m = _SUFFIX_RE.search(code)
        if m:
            suffix = m.group(1).upper()
            mkt_val = _SUFFIX_MARKET.get(suffix)
            if mkt_val is None:
                # 不支持的市场，剥掉后缀后原样返回，标记 unsupported
                clean = _SUFFIX_RE.sub('', code)
                return clean, suffix, False
        market = detect_market(code)
        clean  = normalize_code(code, market)
        return clean, market, True

    def _make_card(self, rank: int, item: dict) -> QFrame:
        raw_code = item.get("code", "")
        clean_code, market, supported = self._clean_code(raw_code) if raw_code else ("", "", False)

        card = QFrame()
        if supported and clean_code:
            card.setStyleSheet(
                f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:8px;}}"
                f"QFrame:hover{{border-color:{ACCENT};background:{CARD2};}}"
            )
            card.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            # 不支持的市场：灰色卡片，不可点击
            card.setStyleSheet(
                f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:8px;opacity:0.6;}}"
            )

        lay = QHBoxLayout(card); lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(12)

        rank_lbl = QLabel(f"#{rank}")
        rank_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        rank_lbl.setFixedWidth(32)
        rank_lbl.setStyleSheet(f"color:{ACCENT if rank <= 3 else FG2};background:transparent;border:none;")
        lay.addWidget(rank_lbl)

        info = QVBoxLayout(); info.setSpacing(2)
        name_lbl = QLabel(item.get("name", "—"))
        name_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{FG if supported else FG2};background:transparent;border:none;")
        info.addWidget(name_lbl)

        # 显示清洗后的代码 + 市场标签
        if clean_code:
            mkt_label = {"US": "美国", "HK": "中国香港", "CN": "中国大陆"}.get(market, market)
            display_code = f"{clean_code}  ·  {mkt_label}"
            if not supported:
                display_code += "  （暂不支持）"
        else:
            display_code = item.get("market", "")
        code_lbl = QLabel(display_code)
        code_lbl.setFont(QFont("Arial", 9))
        code_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        info.addWidget(code_lbl)
        lay.addLayout(info)
        lay.addStretch()

        reason = item.get("reason", "")
        if reason:
            r_lbl = QLabel(reason)
            r_lbl.setFont(QFont("Arial", 10))
            r_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            r_lbl.setWordWrap(True)
            r_lbl.setMaximumWidth(400)
            lay.addWidget(r_lbl)

        # 只有支持的市场才绑定点击事件，emit 清洗后的代码
        if supported and clean_code:
            card.mousePressEvent = lambda e, c=clean_code: self.stock_selected.emit(c)
        return card

    def _show_hint(self, text: str):
        self._clear_results()
        self._hint.setText(text)
        self._hint.show()

    def _clear_results(self):
        self._research_card = None
        lay = self._result_lay
        while lay.count() > 1:   # 保留 stretch
            it = lay.takeAt(0)
            if it.widget() and it.widget() is not self._hint:
                it.widget().deleteLater()
        self._hint.show()
        # 确保 stretch 在末尾
        if lay.count() == 0 or lay.itemAt(lay.count()-1).spacerItem() is None:
            lay.addStretch()


class _PeerSearchWorker(QThread):
    """
    两阶段同行业搜索：
      阶段一：调研目标公司/描述的业务、行业、核心特征
      阶段二：基于调研结果推荐真正相似的上市公司
    """
    progress      = pyqtSignal(str)         # 进度文字，供 UI 实时显示
    research_done = pyqtSignal(str)         # 阶段一完成，emit 调研摘要文本
    finished      = pyqtSignal(list)        # 阶段二完成，emit 推荐列表
    error         = pyqtSignal(str)

    # ── 阶段一：调研 prompt ──────────────────────────────────────
    _RESEARCH_SYSTEM = (
        "你是一位专业的行业研究员。用户会输入一家公司名称或一段描述，"
        "你需要：\n"
        "1. 如果是公司名称，先识别这是哪家公司（包括其正式名称、所在国家/地区、上市状态）\n"
        "2. 详细描述该公司/该类公司的核心业务、所属细分行业、主要产品或服务、商业模式\n"
        "3. 总结其最关键的 3-5 个行业特征标签（用于后续寻找同行业公司）\n\n"
        "请用中文回答，格式：\n"
        "【公司/描述识别】...\n"
        "【核心业务】...\n"
        "【细分行业】...\n"
        "【行业特征标签】标签1、标签2、标签3..."
    )

    # ── 阶段二：推荐 prompt ──────────────────────────────────────
    _RECOMMEND_SYSTEM = (
        "你是一位专业的股票研究员。你将收到一份行业调研摘要，"
        "请基于该摘要推荐 5-8 家与之最相似的全球上市公司（中国大陆/中国香港/美国市场均可）。\n\n"
        "推荐要求：\n"
        "- 必须是真实存在的上市公司，代码准确\n"
        "- 优先选择业务高度重叠、商业模式相似的公司\n"
        "- 覆盖不同市场（如有）\n\n"
        "严格按以下 JSON 数组格式返回，不要有任何其他文字：\n"
        '[{"name":"公司名","code":"股票代码（不带后缀，如AAPL/00700/600519）",'
        '"market":"美国/中国香港/中国大陆","reason":"相似点（20字内）"}]'
    )

    def __init__(self, query: str, cfg: dict, parent=None):
        super().__init__(parent)
        self._query = query
        self._cfg = cfg

    def run(self):
        try:
            from llm_client import LLMClient
            from web_search import search_for_llm
            client = LLMClient(self._cfg)

            # ── 阶段一：联网搜索 ──
            self.progress.emit("🌐 第一步：正在联网搜索目标公司信息…")
            web_context = search_for_llm(self._query)

            # ── 阶段二：LLM 调研分析 ──
            self.progress.emit("🔍 第二步：AI 正在分析业务与行业特征…")
            if web_context:
                research_user = (
                    f"请分析「{self._query}」这家公司（或这类公司）的业务和行业特征。\n\n"
                    f"以下是从互联网搜索到的相关资料，请基于这些真实信息进行分析：\n\n"
                    f"{web_context}\n\n"
                    "请按格式输出分析结果。"
                )
            else:
                # 搜索失败，退回纯 LLM 知识
                research_user = (
                    f"请分析「{self._query}」这家公司（或这类公司）的业务和行业特征。\n"
                    "（注：未能获取到网络搜索结果，请基于你已有的知识进行分析）"
                )

            research = client.chat_messages([
                {"role": "system", "content": self._RESEARCH_SYSTEM},
                {"role": "user",   "content": research_user},
            ], max_tokens=800)
            self.research_done.emit(research)

            # ── 阶段三：推荐同行业上市公司 ──
            self.progress.emit("📊 第三步：正在匹配同行业上市公司…")
            from llm_client import PEER_LIST_SCHEMA, _supports_schema
            using_schema = _supports_schema(client.provider, client.model)
            recommend_prompt = (
                f"以下是对「{self._query}」的行业调研摘要：\n\n"
                f"{research}\n\n"
                "请基于以上调研，推荐最相似的上市公司列表。"
                + (
                    # 使用 Structured Outputs 时，模型必须返回 {"companies":[...]} 包装
                    "返回格式：{\"companies\":[{\"name\":...,\"code\":...,\"market\":...,\"reason\":...}]}"
                    if using_schema else
                    "只返回 JSON 数组，不要任何其他文字或 markdown 代码块。"
                )
            )
            # 第一次：尝试最强约束（Structured Outputs > json_object）
            raw = client.chat_messages([
                {"role": "system", "content": self._RECOMMEND_SYSTEM},
                {"role": "user",   "content": recommend_prompt},
            ], max_tokens=1200,
               schema=PEER_LIST_SCHEMA if using_schema else None,
               json_mode=True,
               temperature=0.1)
            results = self._parse(raw)
            # 降级：去掉 schema/json_mode，纯 prompt 约束再试一次
            if not results:
                raw2 = client.chat_messages([
                    {"role": "system", "content": self._RECOMMEND_SYSTEM},
                    {"role": "user",   "content": recommend_prompt},
                ], max_tokens=1200, json_mode=False, temperature=0.1)
                results = self._parse(raw2)
            self.finished.emit(results)

        except Exception as e:
            self.error.emit(_friendly_err(e, "RecommendWorker"))

    def _parse(self, raw: str) -> list:
        import json, re
        from llm_client import _repair_json
        if not raw:
            return []
        # 先用 _repair_json 去掉 markdown 代码块、补全截断
        cleaned = _repair_json(raw.strip())
        # 1. 直接解析（可能是数组或包含数组的对象）
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and (d.get("name") or d.get("code"))]
            # 有些模型返回 {"companies": [...]}
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        return [d for d in v if d.get("name") or d.get("code")]
        except Exception:
            pass
        # 2. 提取最外层 [...] 块（贪婪，支持嵌套）
        m = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict) and (d.get("name") or d.get("code"))]
            except Exception:
                pass
        # 3. 逐对象提取（兜底，支持简单嵌套）
        results = []
        depth = 0; start = -1
        for i, ch in enumerate(cleaned):
            if ch == '{':
                if depth == 0: start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        obj = json.loads(cleaned[start:i+1])
                        if isinstance(obj, dict) and (obj.get("name") or obj.get("code")):
                            results.append(obj)
                    except Exception:
                        pass
                    start = -1
        return results


# ═══════════════════════════════════════════════
# 区间选择按钮组
# ═══════════════════════════════════════════════

class PeriodBar(QWidget):
    period_changed = pyqtSignal(str)
    PERIODS = ["7天","30天","90天","180天","360天"]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)
        self._grp = QButtonGroup(self); self._grp.setExclusive(True)
        for p in self.PERIODS:
            btn = QPushButton(p); btn.setCheckable(True)
            btn.setFixedHeight(26); btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("period", p); self._style(btn, False)
            self._grp.addButton(btn); lay.addWidget(btn)
        lay.addStretch()
        self._grp.buttons()[1].setChecked(True)
        self._style(self._grp.buttons()[1], True)
        # 防抖：100ms 内连续点击只触发最后一次
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(100)
        self._pending_period: str = ""
        self._debounce.timeout.connect(self._emit_period)
        self._grp.buttonClicked.connect(self._click)

    def _style(self, btn, active):
        if active:
            btn.setStyleSheet(f"QPushButton{{background:{ACCENT};color:white;border:none;border-radius:6px;font-size:11px;font-weight:600;padding:0 10px;}}")
        else:
            btn.setStyleSheet(f"QPushButton{{background:{CARD};color:{FG2};border:1px solid {BORDER};border-radius:6px;font-size:11px;padding:0 10px;}}QPushButton:hover{{color:{FG};border-color:{ACCENT};}}")

    def _click(self, btn):
        for b in self._grp.buttons(): self._style(b, b is btn)
        self._pending_period = btn.property("period")
        self._debounce.start()   # 重置计时，100ms 后才真正 emit

    def _emit_period(self):
        if self._pending_period:
            self.period_changed.emit(self._pending_period)

    def current(self):
        for b in self._grp.buttons():
            if b.isChecked(): return b.property("period")
        return "30天"


# ═══════════════════════════════════════════════
# 指标表格卡片
# ═══════════════════════════════════════════════

class MetricTable(QFrame):
    """
    rows: [(name, value, color?), ...]
    两列布局，奇偶行交替背景，指标名旁有 ? 说明按钮
    """
    def __init__(self, title, rows, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame{{background:{CARD2};border:1px solid {BORDER};border-radius:8px;}}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # 标题
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{CARD};border-radius:8px 8px 0 0;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12,7,12,7)
        t = QLabel(title); t.setFont(QFont("Arial",11,QFont.Weight.Bold))
        t.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        hl.addWidget(t); hl.addStretch()
        root.addWidget(hdr)

        # 内容网格（两列）
        body = QWidget(); body.setStyleSheet("background:transparent;")
        gl = QGridLayout(body); gl.setContentsMargins(0,0,0,0); gl.setSpacing(0)
        gl.setColumnStretch(0,1); gl.setColumnStretch(1,1)

        for i, row in enumerate(rows):
            name  = row[0]; value = str(row[1])
            color = row[2] if len(row) > 2 else FG
            tip   = TIPS.get(name, "")
            col   = i % 2; r = i // 2
            bg    = CARD2 if (r % 2 == 0) else "#1E2235"

            cell = QWidget(); cell.setStyleSheet(f"background:{bg};")
            cl = QHBoxLayout(cell); cl.setContentsMargins(10,5,10,5); cl.setSpacing(4)

            nl = QLabel(name); nl.setFont(QFont("Arial",10))
            nl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            nl.setFixedWidth(118)
            cl.addWidget(nl)

            vl = QLabel(value); vl.setFont(QFont("Arial",11,QFont.Weight.Bold))
            vl.setStyleSheet(f"color:{color};background:transparent;border:none;")
            cl.addWidget(vl); cl.addStretch()

            if tip:
                ql = QLabel("?"); ql.setFont(QFont("Arial",8))
                ql.setStyleSheet(f"color:{FG2};background:rgba(79,142,247,0.15);border-radius:6px;padding:0 4px;border:none;")
                ql.setFixedSize(14,14); ql.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ql.setToolTip(f"<div style='max-width:260px;font-size:11px;line-height:1.5'>{tip}</div>")
                cl.addWidget(ql)

            gl.addWidget(cell, r, col)

        root.addWidget(body)


# ═══════════════════════════════════════════════
# 价格走势图（紧凑，固定高度）
# ═══════════════════════════════════════════════

class StockChart(FigureCanvas):
    def __init__(self, height=220, parent=None):
        self.fig = Figure(figsize=(8, height/72), facecolor=MPL_BG)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(height)
        self._df=None; self._days=30; self._label=""

    def set_data(self, df, days, label=""):
        self._df=df; self._days=days; self._label=label; self._draw()

    def _draw(self):
        self.fig.clear()
        if self._df is None or self._df.empty:
            ax = self.fig.add_subplot(111, facecolor=MPL_BG)
            ax.text(0.5,0.5,"暂无历史数据",color=MPL_TEXT,ha="center",va="center",
                    transform=ax.transAxes,**_tk(11))
            ax.set_facecolor(MPL_BG)
            for sp in ax.spines.values(): sp.set_visible(False)
            ax.set_xticks([]); ax.set_yticks([])
            self.draw(); return

        df = self._df.tail(self._days).copy()
        if df.empty: self.draw(); return

        gs = self.fig.add_gridspec(2,1,height_ratios=[3,1],
                                   hspace=0.03,left=0.08,right=0.97,top=0.88,bottom=0.15)
        ax1 = self.fig.add_subplot(gs[0], facecolor=MPL_CARD)
        ax2 = self.fig.add_subplot(gs[1], facecolor=MPL_CARD, sharex=ax1)

        dates=df.index; close=df["Close"].values
        high=df["High"].values; low=df["Low"].values

        ax1.plot(dates,close,color=MPL_LINE,linewidth=1.6,zorder=3)
        ax1.fill_between(dates,close,close.min(),color=MPL_LINE,alpha=0.07,zorder=2)

        handles=[]
        if len(close)>=20:
            ma20=df["Close"].rolling(20).mean()
            l,=ax1.plot(dates,ma20,color=MPL_MA20,linewidth=1.0,linestyle="--",alpha=0.85)
            handles.append((l,"MA20"))
        if len(close)>=60:
            ma60=df["Close"].rolling(60).mean()
            l,=ax1.plot(dates,ma60,color=MPL_MA60,linewidth=1.0,linestyle="--",alpha=0.85)
            handles.append((l,"MA60"))

        ih=df["High"].idxmax(); il=df["Low"].idxmin()
        ax1.annotate(f" {high.max():.2f}",xy=(ih,high.max()),color=UP,va="bottom",**_tk(8))
        ax1.annotate(f" {low.min():.2f}", xy=(il,low.min()), color=DN,va="top",  **_tk(8))

        title = f"近 {self._days} 交易日  收盘价走势"
        if self._label: title = f"{self._label}  |  " + title
        ax1.set_title(title,color=FG,pad=4,**_tk(10))
        ax1.set_ylabel("价格",color=MPL_TEXT,**_tk(9))
        ax1.tick_params(colors=MPL_TEXT,labelsize=8)
        ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
        ax1.grid(color=MPL_GRID,linewidth=0.4,alpha=0.6)
        for sp in ax1.spines.values(): sp.set_edgecolor(MPL_GRID)
        plt.setp(ax1.get_xticklabels(),visible=False)
        if handles:
            ax1.legend([h for h,_ in handles],[n for _,n in handles],
                       loc="upper left",fontsize=8,facecolor=MPL_CARD,
                       edgecolor=MPL_GRID,labelcolor=MPL_TEXT,framealpha=0.8)

        if "Volume" in df.columns:
            vol=df["Volume"].values
            colors=[UP if i==0 or close[i]>=close[i-1] else DN for i in range(len(close))]
            ax2.bar(dates,vol,color=colors,alpha=0.7,width=0.8)
            ax2.set_ylabel("量",color=MPL_TEXT,**_tk(8))
            ax2.yaxis.set_major_formatter(mticker.FuncFormatter(
                lambda x,_: f"{x/1e8:.1f}亿" if x>=1e8 else (f"{x/1e4:.0f}万" if x>=1e4 else str(int(x)))))
        else:
            ax2.set_visible(False)

        ax2.tick_params(colors=MPL_TEXT,labelsize=7)
        ax2.grid(color=MPL_GRID,linewidth=0.3,alpha=0.5,axis="y")
        for sp in ax2.spines.values(): sp.set_edgecolor(MPL_GRID)

        if self._days<=30:   ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        elif self._days<=90: ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d")); ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        else:                ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y/%m")); ax2.xaxis.set_major_locator(mdates.MonthLocator())

        self.fig.autofmt_xdate(rotation=25,ha="right")
        for lbl in ax2.get_xticklabels(): lbl.set_color(MPL_TEXT)
        self.draw()


# ═══════════════════════════════════════════════
# 归一化比对图
# ═══════════════════════════════════════════════

class CompareChart(FigureCanvas):
    COLORS = ["#4F8EF7","#FF9F0A","#34C759","#FF453A","#BF5AF2","#64D2FF"]

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8,3.0), facecolor=MPL_BG)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(210)

    def plot(self, series: dict, days: int):
        self.fig.clear()
        ax = self.fig.add_subplot(111, facecolor=MPL_CARD)
        self.fig.subplots_adjust(left=0.08,right=0.97,top=0.88,bottom=0.15)
        has = False
        for i,(label,df) in enumerate(series.items()):
            if df is None or df.empty: continue
            sub = df.tail(days)["Close"].dropna()
            if sub.empty: continue
            norm = sub / sub.iloc[0] * 100
            ax.plot(norm.index, norm.values,
                    color=self.COLORS[i%len(self.COLORS)],
                    linewidth=1.8, label=label)
            has = True
        if not has:
            ax.text(0.5,0.5,"暂无数据",color=MPL_TEXT,ha="center",va="center",
                    transform=ax.transAxes,**_tk(11))
            self.draw(); return

        ax.axhline(100,color=MPL_GRID,linewidth=0.8,linestyle="--")
        ax.set_title(f"近 {days} 日归一化走势（基准=100）",color=FG,pad=4,**_tk(10))
        ax.set_ylabel("相对涨跌 (%)",color=MPL_TEXT,**_tk(9))
        ax.tick_params(colors=MPL_TEXT,labelsize=8)
        ax.grid(color=MPL_GRID,linewidth=0.4,alpha=0.6)
        for sp in ax.spines.values(): sp.set_edgecolor(MPL_GRID)
        ax.legend(loc="upper left",fontsize=9,facecolor=MPL_CARD,
                  edgecolor=MPL_GRID,labelcolor=MPL_TEXT,prop=_fp(9))

        if days<=30:   ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        elif days<=90: ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d")); ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        else:          ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y/%m")); ax.xaxis.set_major_locator(mdates.MonthLocator())
        self.fig.autofmt_xdate(rotation=25,ha="right")
        for lbl in ax.get_xticklabels(): lbl.set_color(MPL_TEXT)
        self.draw()


# ═══════════════════════════════════════════════
# 年报卡片
# ═══════════════════════════════════════════════

class FilingCard(QFrame):
    download_requested = pyqtSignal(int)

    # 报告类型 → 标签颜色（绿=年报，橙=半年报，蓝=季报）
    _FORM_COLOR = {
        "年报":    "#34C759",
        "10-K":   "#34C759",
        "20-F":   "#34C759",
        "10-K/A": "#34C759",
        "半年报":  "#FF9F0A",
        "中期报告":"#FF9F0A",
        "季报":    "#64D2FF",
        "10-Q":   "#64D2FF",
        "10-Q/A": "#64D2FF",
    }

    def __init__(self, filing, index, parent=None):
        super().__init__(parent); self.filing=filing; self.index=index; self._build()

    def _build(self):
        self.setStyleSheet(f"FilingCard{{{cs(8)}}}")
        self.setFixedHeight(64)
        lay = QHBoxLayout(self); lay.setContentsMargins(14,0,14,0); lay.setSpacing(10)
        col = QVBoxLayout(); col.setSpacing(2)
        form_str = self.filing.get("form", "年报")
        fl = QLabel(form_str); fl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        form_color = FilingCard._FORM_COLOR.get(form_str, ACCENT)
        fl.setStyleSheet(f"color:{form_color};font-weight:bold;")
        sl = QLabel(f"{self.filing.get('date','—')}  {self.filing.get('title','')[:60]}")
        sl.setFont(QFont("Arial",10)); sl.setStyleSheet(ls(FG2,10))
        col.addWidget(fl); col.addWidget(sl)
        lay.addLayout(col); lay.addStretch()
        self.dl_btn = QPushButton("下载"); self.dl_btn.setFixedSize(68,30)
        self.dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_style(ACCENT)
        self.dl_btn.clicked.connect(lambda: self.download_requested.emit(self.index))
        lay.addWidget(self.dl_btn)

    def _btn_style(self, bg):
        self.dl_btn.setStyleSheet(
            f"QPushButton{{background:{bg};color:white;border:none;border-radius:7px;font-size:11px;font-weight:600;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:#3A3D4E;color:{FG2};}}"
        )
    def set_downloading(self): self.dl_btn.setText("下载中..."); self.dl_btn.setEnabled(False)
    def set_done(self, ok):
        if ok: self.dl_btn.setText("完成"); self._btn_style(SUCCESS)
        else:  self.dl_btn.setText("重试"); self.dl_btn.setEnabled(True)


# ═══════════════════════════════════════════════
# 行情分析面板
# ═══════════════════════════════════════════════

class AnalyticsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")
        self._data=None; self._workers=[]; self._load_time=None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,8); root.setSpacing(8)

        self.period_bar = PeriodBar()
        self.period_bar.period_changed.connect(self._on_period)
        root.addWidget(self.period_bar)

        # 图表（固定高度，不挤占指标区）
        self.chart = StockChart(height=220)
        root.addWidget(self.chart)

        # 指标滚动区（占剩余空间）
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.inner = QWidget(); self.inner.setStyleSheet("background:transparent;")
        self.inner_lay = QVBoxLayout(self.inner)
        self.inner_lay.setContentsMargins(0,0,4,0); self.inner_lay.setSpacing(8)
        self.inner_lay.addStretch()
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        self.hint = QLabel("请先在「年报查询」中搜索股票，然后切换到此标签查看行情分析")
        self.hint.setFont(QFont("Arial",11)); self.hint.setStyleSheet(ls(FG2,11))
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter); self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.src_label = QLabel("")
        self.src_label.setFont(QFont("Arial", 9))
        self.src_label.setStyleSheet(f"color:{FG3};background:transparent;padding:2px 0;")
        self.src_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.src_label.hide()
        root.addWidget(self.src_label)

    def load(self, code, market):
        self.hint.setText(f"正在加载 {code} 行情数据..."); self.hint.show()
        self._clear(); self.chart.set_data(None,30)
        w = AnalyticsWorker(code, market)
        w.finished.connect(self._on_data)
        w.error.connect(self._on_err)
        _track_worker(self._workers, w); w.start()

    def _on_data(self, data):
        self._data = data
        self._load_time = datetime.datetime.now()
        self.hint.hide()
        src = data.get("source", "eastmoney")
        src_name = "东方财富" if src == "eastmoney" else "Yahoo Finance"
        ts = self._load_time.strftime("%H:%M")
        self.src_label.setText(f"数据来源：{src_name}  ·  更新于 {ts}")
        self.src_label.show()
        self._render(self.period_bar.current())

    def _on_err(self, msg):
        self.hint.setText(f"加载失败：{msg}")
    def _on_period(self, p):
        if self._data: self._render(p)

    def _render(self, period):
        from analytics import PERIODS
        days = PERIODS.get(period, 30)
        self.chart.set_data(self._data.get("history_df"), days)
        self._clear()
        lay = self.inner_lay; lay.takeAt(lay.count()-1)

        # 区间统计
        pd_ = self._data.get("periods",{}).get(period,{})
        if pd_:
            pct = pd_.get("pct_change")
            pc  = UP if (pct or 0)>=0 else DN
            ps  = (f"+{pct:.2f}%" if pct>=0 else f"{pct:.2f}%") if pct is not None else "—"
            lay.addWidget(MetricTable(f"{period}  区间统计", [
                ("区间涨跌幅",   ps,                                    pc),
                ("期初价格",     _safe(pd_.get("start_price"),  "2f"),  FG),
                ("期末价格",     _safe(pd_.get("end_price"),    "2f"),  FG),
                ("区间最高",     _safe(pd_.get("period_high"),  "2f"),  UP),
                ("区间最低",     _safe(pd_.get("period_low"),   "2f"),  DN),
                ("日均波动率",   _safe(pd_.get("volatility"),   "pct1"),FG),
                ("上涨天数",     str(pd_.get("up_days","—")),           UP),
                ("下跌天数",     str(pd_.get("down_days","—")),         DN),
                ("日均成交量",   _safe(pd_.get("avg_volume"),   "vol"), FG),
                ("区间总成交量", _safe(pd_.get("total_volume"), "vol"), FG),
                ("单日最大成交", _safe(pd_.get("max_volume"),   "vol"), FG),
            ]))

        s = self._data.get("snapshot",{})

        # 估值
        val = []
        pe = s.get("trailing_pe") or s.get("pe_ttm")
        if pe: val.append(("市盈率 PE(TTM)", _safe(pe,"2f"), FG))
        fpe = s.get("forward_pe")
        if fpe: val.append(("市盈率 PE(预测)", _safe(fpe,"2f"), FG))
        ps2 = s.get("price_to_sales")
        if ps2: val.append(("市销率 PS", _safe(ps2,"2f"), FG))
        pb = s.get("price_to_book") or s.get("pb")
        if pb: val.append(("市净率 PB", _safe(pb,"2f"), FG))
        ev = s.get("ev_ebitda")
        if ev: val.append(("EV/EBITDA", _safe(ev,"2f"), FG))
        if val: lay.addWidget(MetricTable("估值指标", val))

        # 价格
        pri = []
        cp = s.get("current_price")
        if cp: pri.append(("当前价格", _safe(cp,"2f"), FG))
        chg = s.get("change_pct")
        if chg is not None: pri.append(("今日涨跌幅", f"{chg:+.2f}%", UP if chg>=0 else DN))
        amp = s.get("amplitude")
        if amp: pri.append(("今日振幅", _safe(amp,"pct1"), FG))
        h52 = s.get("52w_high")
        if h52: pri.append(("52周最高", _safe(h52,"2f"), UP))
        l52 = s.get("52w_low")
        if l52: pri.append(("52周最低", _safe(l52,"2f"), DN))
        if pri: lay.addWidget(MetricTable("价格参考", pri))

        # 规模
        siz = []
        mc = s.get("market_cap")
        if mc: siz.append(("总市值", _safe(mc,"big"), FG))
        fc = s.get("float_cap")
        if fc: siz.append(("流通市值", _safe(fc,"big"), FG))
        tr = s.get("total_revenue")
        if tr: siz.append(("年营业收入", _safe(tr,"big"), FG))
        if siz: lay.addWidget(MetricTable("市值 & 规模", siz))

        # 成交
        vol = []
        v = s.get("volume")
        if v: vol.append(("今日成交量", _safe(v,"vol"), FG))
        to = s.get("turnover")
        if to: vol.append(("成交额", _safe(to,"big"), FG))
        tvr = s.get("turnover_rate")
        if tvr is not None: vol.append(("换手率", _safe(tvr,"pct1"), FG))
        if vol: lay.addWidget(MetricTable("成交数据", vol))

        # 盈利
        prf = []
        eps = s.get("eps_ttm")
        if eps: prf.append(("EPS(TTM)", _safe(eps,"2f"), FG))
        roe = s.get("roe")
        if roe: prf.append(("净资产收益率 ROE", _safe(roe,"pct"), FG))
        roa = s.get("roa")
        if roa: prf.append(("总资产收益率 ROA", _safe(roa,"pct"), FG))
        pm = s.get("profit_margin")
        if pm: prf.append(("净利润率", _safe(pm,"pct"), FG))
        om = s.get("op_margin")
        if om: prf.append(("营业利润率", _safe(om,"pct"), FG))
        rg = s.get("revenue_growth")
        if rg is not None: prf.append(("营收增速(YoY)", _safe(rg,"pct"), UP if rg>=0 else DN))
        eg = s.get("earnings_growth")
        if eg is not None: prf.append(("净利增速(YoY)", _safe(eg,"pct"), UP if eg>=0 else DN))
        if prf: lay.addWidget(MetricTable("盈利能力", prf))

        # 财务
        fin = []
        de = s.get("debt_to_equity")
        if de: fin.append(("负债权益比", _safe(de,"2f"), FG))
        cr = s.get("current_ratio")
        if cr: fin.append(("流动比率", _safe(cr,"2f"), FG))
        fcf = s.get("free_cashflow")
        if fcf: fin.append(("自由现金流", _safe(fcf,"big"), FG))
        if fin: lay.addWidget(MetricTable("财务健康", fin))

        # 持仓
        hld = []
        ip = s.get("insider_pct")
        if ip: hld.append(("内部人持仓比", _safe(ip,"pct"), FG))
        inst = s.get("inst_pct")
        if inst: hld.append(("机构持仓比", _safe(inst,"pct"), FG))
        if hld: lay.addWidget(MetricTable("持仓结构", hld))

        # 股息
        div = []
        dy = s.get("dividend_yield")
        if dy: div.append(("股息率", _safe(dy,"pct"), FG))
        pr = s.get("payout_ratio")
        if pr: div.append(("派息比率", _safe(pr,"pct"), FG))
        if div: lay.addWidget(MetricTable("股息", div))

        lay.addStretch()

    def _clear(self):
        lay = self.inner_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        lay.addStretch()


# ═══════════════════════════════════════════════
# 多股比对面板
# ═══════════════════════════════════════════════

class ComparePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")
        self._results={}; self._workers=[]; self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,8); root.setSpacing(8)

        # 输入行
        row = QHBoxLayout(); row.setSpacing(8)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("输入多个代码，空格或逗号分隔，如：600584 688008 AAPL")
        self.inp.setFont(QFont("Arial",12)); self.inp.setFixedHeight(38)
        self.inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};border:1px solid {BORDER};border-radius:10px;color:{FG};padding:0 12px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};}}"
        )
        self.inp.returnPressed.connect(self._go)
        row.addWidget(self.inp)
        self.go_btn = QPushButton("比对"); self.go_btn.setFixedSize(76,38)
        self.go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.go_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;border-radius:10px;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:#3A3D4E;color:{FG2};}}"
        )
        self.go_btn.clicked.connect(self._go)
        row.addWidget(self.go_btn)
        root.addLayout(row)

        self.period_bar = PeriodBar()
        self.period_bar.period_changed.connect(self._on_period)
        root.addWidget(self.period_bar)

        self.chart = CompareChart()
        root.addWidget(self.chart)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.inner = QWidget(); self.inner.setStyleSheet("background:transparent;")
        self.inner_lay = QVBoxLayout(self.inner)
        self.inner_lay.setContentsMargins(0,0,4,0); self.inner_lay.setSpacing(0)
        self.inner_lay.addStretch()
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        self.status = QLabel("输入多个股票代码后点击比对（最多6只）")
        self.status.setFont(QFont("Arial",10)); self.status.setStyleSheet(ls(FG2,10))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status)

    def _go(self):
        raw = self.inp.text().strip()
        if not raw: return
        codes = [c.strip().upper() for c in re.split(r"[,\s，]+", raw) if c.strip()]
        if len(codes) < 2: self.status.setText("请至少输入 2 个股票代码"); return
        codes = codes[:6]
        self._results={}; self._pending=set(codes); self._clear_table()
        self.chart.plot({}, 30)
        self.go_btn.setEnabled(False); self.go_btn.setText("加载中...")
        self.status.setText(f"正在加载 {', '.join(codes)} ...")
        # 并发启动每只股票的独立线程
        for c in codes:
            mkt = _auto_market(c)
            w = _SingleCompareWorker(c, mkt)
            w.done.connect(self._one)
            _track_worker(self._workers, w)
            w.start()

    def _one(self, code, result):
        self._results[code] = result
        self._pending.discard(code)
        self.status.setText(f"已加载: {', '.join(self._results.keys())}")
        if not self._pending:
            self._done()

    def _done(self):
        self.go_btn.setEnabled(True); self.go_btn.setText("比对")
        self._render(self.period_bar.current())

    def _on_period(self, p):
        if self._results: self._render(p)

    def _render(self, period):
        from analytics import PERIODS
        days = PERIODS.get(period, 30)
        series = {c: r.get("history_df") for c,r in self._results.items()}
        self.chart.plot(series, days)
        self._clear_table()
        lay = self.inner_lay; lay.takeAt(lay.count()-1)
        codes = list(self._results.keys())
        if not codes: lay.addStretch(); return

        # 比对指标定义
        METRICS = [
            ("当前价格",     lambda s,p: _safe(s.get("current_price"),"2f"),         False),
            ("今日涨跌幅",   lambda s,p: f"{s['change_pct']:+.2f}%" if s.get("change_pct") is not None else "—", True),
            ("市盈率 PE",    lambda s,p: _safe(s.get("trailing_pe") or s.get("pe_ttm"),"2f"), False),
            ("市销率 PS",    lambda s,p: _safe(s.get("price_to_sales"),"2f"),         False),
            ("市净率 PB",    lambda s,p: _safe(s.get("price_to_book") or s.get("pb"),"2f"), False),
            ("总市值",       lambda s,p: _safe(s.get("market_cap"),"big"),            True),
            ("换手率",       lambda s,p: _safe(s.get("turnover_rate"),"pct1"),        True),
            ("52周最高",     lambda s,p: _safe(s.get("52w_high"),"2f"),               True),
            ("52周最低",     lambda s,p: _safe(s.get("52w_low"),"2f"),                False),
            ("净利润率",     lambda s,p: _safe(s.get("profit_margin"),"pct"),         True),
            ("净资产收益率", lambda s,p: _safe(s.get("roe"),"pct"),                   True),
            ("股息率",       lambda s,p: _safe(s.get("dividend_yield"),"pct"),        True),
            (f"{period} 涨跌幅", lambda s,p: (f"+{p['pct_change']:.2f}%" if p.get('pct_change',0)>=0 else f"{p['pct_change']:.2f}%") if p.get('pct_change') is not None else "—", True),
            (f"{period} 波动率", lambda s,p: _safe(p.get("volatility"),"pct1"),      False),
            (f"{period} 上涨天", lambda s,p: str(p.get("up_days","—")),              True),
            (f"{period} 下跌天", lambda s,p: str(p.get("down_days","—")),            False),
        ]

        # 表头
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{CARD};border:1px solid {BORDER};border-radius:8px 8px 0 0;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12,6,12,6); hl.setSpacing(0)
        nl = QLabel("指标"); nl.setFont(QFont("Arial",10,QFont.Weight.Bold))
        nl.setStyleSheet(f"color:{FG2};background:transparent;border:none;"); nl.setFixedWidth(148)
        hl.addWidget(nl)
        for code in codes:
            cl = QLabel(code); cl.setFont(QFont("Arial",10,QFont.Weight.Bold))
            cl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter); hl.addWidget(cl,1)
        lay.addWidget(hdr)

        for idx,(mname,getter,higher_better) in enumerate(METRICS):
            row_f = QFrame()
            bg = CARD2 if idx%2==0 else "#1E2235"
            row_f.setStyleSheet(f"background:{bg};border:none;")
            rl = QHBoxLayout(row_f); rl.setContentsMargins(12,5,12,5); rl.setSpacing(0)

            nm = QLabel(mname); nm.setFont(QFont("Arial",10))
            nm.setStyleSheet(f"color:{FG2};background:transparent;border:none;"); nm.setFixedWidth(148)
            tip = TIPS.get(mname,"")
            if tip: nm.setToolTip(f"<div style='max-width:260px;font-size:11px'>{tip}</div>")
            rl.addWidget(nm)

            vals = []
            for code in codes:
                r = self._results.get(code,{})
                try:
                    snap = r.get("snapshot",{})
                    pdata = r.get("periods",{}).get(period,{})
                    vals.append(getter(snap, pdata))
                except Exception: vals.append("—")

            # 最优值高亮
            nums = []
            for v in vals:
                try: nums.append(float(v.replace("%","").replace("+","").replace("亿","e8").replace("B","e9").replace("T","e12").replace("M","e6").replace("—","nan")))
                except: nums.append(float("nan"))
            valid = [x for x in nums if not math.isnan(x)]

            for i,(code,val) in enumerate(zip(codes,vals)):
                color = FG
                if valid and not math.isnan(nums[i]):
                    if higher_better and nums[i]==max(valid): color=UP
                    elif higher_better and nums[i]==min(valid): color=DN
                    elif not higher_better and nums[i]==min(valid): color=UP
                    elif not higher_better and nums[i]==max(valid): color=DN
                vl = QLabel(val); vl.setFont(QFont("Arial",10,QFont.Weight.Bold))
                vl.setStyleSheet(f"color:{color};background:transparent;border:none;")
                vl.setAlignment(Qt.AlignmentFlag.AlignCenter); rl.addWidget(vl,1)

            lay.addWidget(row_f)

        lay.addStretch()
        self.status.setText(f"比对完成：{', '.join(codes)}  |  {period}")

    def _clear_table(self):
        lay = self.inner_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        lay.addStretch()


# ═══════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pre-Diligence Lab")
        self.setMinimumSize(900, 660); self.resize(1100, 800)
        self._cur=None; self._cards=[]; self._workers=[]
        self._save_dir = str(Path.home()/"Downloads"/"Pre-Diligence-Lab")
        self._llm_cfg = {}
        self._build(); self._style()
        # 加载 LLM 配置并同步到各面板
        from llm_client import load_config as _llm_load
        self._llm_cfg = _llm_load()
        self.np.set_llm_cfg(self._llm_cfg)

    def _style(self):
        self.setStyleSheet(f"""
            QMainWindow,QWidget#central{{background:{BG};}}
            QScrollArea{{background:transparent;border:none;}}
            QScrollBar:vertical{{background:transparent;width:4px;border-radius:2px;margin:0;}}
            QScrollBar::handle:vertical{{background:{BORDER};border-radius:2px;min-height:24px;}}
            QScrollBar::handle:vertical:hover{{background:{FG3};}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;border:none;}}
            QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent;}}
            QScrollBar:horizontal{{height:0;}}
            QToolTip{{background:{CARD2};color:{FG};border:1px solid {BORDER};
                border-radius:8px;padding:7px 12px;font-size:11px;}}
            QLineEdit{{background:{INPUT_BG};color:{FG};border:1.5px solid {INPUT_BD};
                border-radius:8px;padding:6px 10px;font-size:13px;selection-background-color:{ACCENT};}}
            QLineEdit:focus{{border-color:{ACCENT};background:{CARD2};}}
            QLineEdit::placeholder{{color:{FG3};}}
        """)

    def _build(self):
        c = QWidget(); c.setObjectName("central"); self.setCentralWidget(c)
        root = QHBoxLayout(c); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── 左侧边栏 ──────────────────────────────────────────
        self._sidebar = QFrame()
        self._sidebar.setFixedWidth(200)
        self._sidebar.setStyleSheet(
            f"QFrame{{background:{SIDEBAR};border-right:1px solid {BORDER2};}}"
        )
        sb_lay = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0); sb_lay.setSpacing(0)

        # Logo 区
        logo_w = QWidget()
        logo_w.setFixedHeight(72)
        logo_w.setStyleSheet(f"background:transparent;border-bottom:1px solid {BORDER2};")
        logo_lay = QVBoxLayout(logo_w); logo_lay.setContentsMargins(20, 14, 20, 14); logo_lay.setSpacing(2)
        logo_title = QLabel("Pre-Diligence Lab")
        logo_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        logo_title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        logo_sub = QLabel("投研数据工作台")
        logo_sub.setFont(QFont("Arial", 9))
        logo_sub.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        logo_lay.addWidget(logo_title); logo_lay.addWidget(logo_sub)
        sb_lay.addWidget(logo_w)

        # 搜索区
        search_w = QWidget()
        search_w.setStyleSheet("background:transparent;")
        search_lay = QVBoxLayout(search_w); search_lay.setContentsMargins(12, 14, 12, 8); search_lay.setSpacing(6)

        sf = QFrame()
        sf.setStyleSheet(
            f"QFrame{{background:{INPUT_BG};border:1.5px solid {INPUT_BD};border-radius:10px;}}"
            f"QFrame:focus-within{{border-color:{ACCENT};}}"
        )
        sf.setFixedHeight(40)
        sl2 = QHBoxLayout(sf); sl2.setContentsMargins(10, 0, 6, 0); sl2.setSpacing(6)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("代码  AAPL / 600519 / 00700")
        self.inp.setFont(QFont("Arial", 12))
        self.inp.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;color:{FG};padding:0;}}"
        )
        self.inp.returnPressed.connect(self._search)
        sl2.addWidget(self.inp)
        self.sbtn = QPushButton("查")
        self.sbtn.setFixedSize(28, 28)
        self.sbtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sbtn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;border-radius:7px;"
            f"font-size:11px;font-weight:700;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self.sbtn.clicked.connect(self._search)
        sl2.addWidget(self.sbtn)
        search_lay.addWidget(sf)

        hint_lbl = QLabel("美国 / 中国香港 / 中国大陆")
        hint_lbl.setFont(QFont("Arial", 9))
        hint_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;padding:0 2px;")
        search_lay.addWidget(hint_lbl)

        # 一键分析快捷入口
        self.agent_chat_btn = QPushButton("✦ 一键分析")
        self.agent_chat_btn.setFixedHeight(30)
        self.agent_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.agent_chat_btn.setToolTip("根据当前查询结果自动生成投研分析报告")
        self.agent_chat_btn.setStyleSheet(
            f"QPushButton{{background:rgba(79,142,247,0.12);color:{ACCENT};"
            f"border:1px solid rgba(79,142,247,0.3);border-radius:8px;"
            f"font-size:11px;font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:rgba(79,142,247,0.22);border-color:{ACCENT};}}"
        )
        self.agent_chat_btn.clicked.connect(self._open_agent_chat_window)
        self._agent_chat_win = None  # 懒加载独立窗口
        search_lay.addWidget(self.agent_chat_btn)
        sb_lay.addWidget(search_w)

        # 导航菜单
        nav_sep = QFrame()
        nav_sep.setFixedHeight(1)
        nav_sep.setStyleSheet(f"background:{BORDER2};border:none;")
        sb_lay.addWidget(nav_sep)

        nav_label = QLabel("功能导航")
        nav_label.setFont(QFont("Arial", 9))
        nav_label.setStyleSheet(f"color:{FG3};background:transparent;border:none;padding:10px 20px 4px 20px;")
        sb_lay.addWidget(nav_label)

        NAV_ITEMS = [
            ("年报查询",     "查询公司年报文件及财报截止日期"),
            ("行情分析",     "K线图、技术指标、区间统计"),
            ("多股比对",     "多只股票横向指标对比"),
            ("消息引擎",     "行业资讯、利好利空分类"),
            ("同行业搜索",   "描述公司特征，AI 推荐同行业上市公司"),
            ("公开信息披露", "美国（SEC EDGAR）/ 中国香港（港交所）公开信息查询"),
            ("私募基金",     "中基协 AMAC 私募基金备案查询 · 管理人穿透"),
            ("工商信息尽调", "企业工商注册、失信记录、裁判文书、专利信息查询"),
            ("财务计算器",   "输入财务数据，计算指标并与同行业上市公司比对"),
            ("财务风险因子识别",   "填写业务信息，结合财务指标与同行数据，挖掘潜在财务风险因子"),
        ]
        self._nav_btns = []
        self._nav_group = QButtonGroup(self); self._nav_group.setExclusive(True)
        # 暂时下线的功能（隐藏导航按钮，代码保留）
        _HIDDEN_NAV = {"多股比对", "行情分析"}

        for i, (name, tip) in enumerate(NAV_ITEMS):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setProperty("nav_idx", i)
            self._nav_style(btn, False)
            self._nav_group.addButton(btn)
            self._nav_btns.append(btn)
            sb_lay.addWidget(btn)
            if name in _HIDDEN_NAV:
                btn.hide()
        self._nav_btns[0].setChecked(True)
        self._nav_style(self._nav_btns[0], True)
        self._nav_group.buttonClicked.connect(self._nav_click)

        sb_lay.addSpacing(8)

        # 收藏分割线
        fav_sep = QFrame()
        fav_sep.setFixedHeight(1)
        fav_sep.setStyleSheet(f"background:{BORDER2};border:none;")
        sb_lay.addWidget(fav_sep)

        fav_label = QLabel("收藏")
        fav_label.setFont(QFont("Arial", 9))
        fav_label.setStyleSheet(f"color:{FG3};background:transparent;border:none;padding:10px 20px 4px 20px;")
        sb_lay.addWidget(fav_label)

        # 收藏列表滚动区
        self._fav_scroll = QScrollArea()
        self._fav_scroll.setWidgetResizable(True)
        self._fav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fav_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._fav_inner = QWidget(); self._fav_inner.setStyleSheet("background:transparent;")
        self._fav_lay = QVBoxLayout(self._fav_inner)
        self._fav_lay.setContentsMargins(8, 0, 8, 4); self._fav_lay.setSpacing(2)
        self._fav_lay.addStretch()
        self._fav_scroll.setWidget(self._fav_inner)
        sb_lay.addWidget(self._fav_scroll, 1)

        # 底部按钮区
        bottom_sep = QFrame()
        bottom_sep.setFixedHeight(1)
        bottom_sep.setStyleSheet(f"background:{BORDER2};border:none;")
        sb_lay.addWidget(bottom_sep)

        bottom_w = QWidget()
        bottom_w.setStyleSheet("background:transparent;")
        bottom_lay = QHBoxLayout(bottom_w); bottom_lay.setContentsMargins(10, 8, 10, 10); bottom_lay.setSpacing(6)

        def _mk_icon_btn(text, tip):
            b = QPushButton(text); b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{FG2};border:1px solid {BORDER};"
                f"border-radius:7px;font-size:11px;padding:0 8px;}}"
                f"QPushButton:hover{{color:{FG};border-color:{ACCENT};background:{CARD2};}}"
            )
            return b

        self.settings_btn = _mk_icon_btn("设置", "配置 LLM API Key 及保存目录")
        self.settings_btn.clicked.connect(self._open_settings)
        self.dir_btn = _mk_icon_btn("目录", "选择年报保存目录")
        self.dir_btn.clicked.connect(self._choose_dir)
        bottom_lay.addWidget(self.settings_btn, 1)
        bottom_lay.addWidget(self.dir_btn, 1)
        sb_lay.addWidget(bottom_w)

        root.addWidget(self._sidebar)

        # ── 右侧主内容区 ──────────────────────────────────────
        right_w = QWidget(); right_w.setStyleSheet(f"background:{BG2};")
        right_lay = QVBoxLayout(right_w); right_lay.setContentsMargins(0,0,0,0); right_lay.setSpacing(0)

        # 顶部标题栏
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"QFrame{{background:{BG};border-bottom:1px solid {BORDER2};}}"
        )
        hdr_lay = QHBoxLayout(header); hdr_lay.setContentsMargins(24, 0, 20, 0); hdr_lay.setSpacing(12)

        self._page_title = QLabel("年报查询")
        self._page_title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        self._page_title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        hdr_lay.addWidget(self._page_title)

        self._page_sub = QLabel("查询公司年报文件及财报截止日期")
        self._page_sub.setFont(QFont("Arial", 10))
        self._page_sub.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        hdr_lay.addWidget(self._page_sub)
        hdr_lay.addStretch()

        # 收藏按钮（在标题栏右侧）
        self.fav_btn = QPushButton("收藏")
        self.fav_btn.setFixedHeight(30)
        self.fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_btn.setVisible(False)
        self._update_fav_btn(False)
        self.fav_btn.clicked.connect(self._toggle_fav)
        hdr_lay.addWidget(self.fav_btn)

        # 状态标签
        self.stl = QLabel("就绪")
        self.stl.setFont(QFont("Arial", 10))
        self.stl.setStyleSheet(ls(FG3, 10))
        self.stl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.stl.setMinimumWidth(280)
        hdr_lay.addWidget(self.stl)

        right_lay.addWidget(header)

        # 页面堆叠
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{BG2};")

        # Page 0 年报
        p0 = QWidget(); p0.setStyleSheet(f"background:{BG2};")
        p0l = QVBoxLayout(p0); p0l.setContentsMargins(20, 16, 20, 12); p0l.setSpacing(0)
        self.rscroll = QScrollArea(); self.rscroll.setWidgetResizable(True)
        self.rscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rw = QWidget(); self.rw.setStyleSheet("background:transparent;")
        self.rl = QVBoxLayout(self.rw); self.rl.setContentsMargins(0,0,4,0)
        self.rl.setSpacing(10); self.rl.addStretch()
        self.rscroll.setWidget(self.rw); p0l.addWidget(self.rscroll)

        # Page 1 行情
        p1 = QWidget(); p1.setStyleSheet(f"background:{BG2};")
        p1l = QVBoxLayout(p1); p1l.setContentsMargins(20, 16, 20, 12)
        asc = QScrollArea(); asc.setWidgetResizable(True)
        asc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ap = AnalyticsPanel(); asc.setWidget(self.ap); p1l.addWidget(asc)

        # Page 2 比对
        p2 = QWidget(); p2.setStyleSheet(f"background:{BG2};")
        p2l = QVBoxLayout(p2); p2l.setContentsMargins(20, 16, 20, 12)
        csc = QScrollArea(); csc.setWidgetResizable(True)
        csc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cp = ComparePanel(); csc.setWidget(self.cp); p2l.addWidget(csc)

        # Page 3 消息引擎（NewsPanel 内部已有 QScrollArea，不需要外层再套）
        p3 = QWidget(); p3.setStyleSheet(f"background:{BG2};")
        p3l = QVBoxLayout(p3); p3l.setContentsMargins(20, 16, 20, 12)
        self.np = NewsPanel(); p3l.addWidget(self.np)

        # Page 4 同行业智能搜索
        from llm_client import load_config as _llm_load
        p4 = QWidget(); p4.setStyleSheet(f"background:{BG2};")
        p4l = QVBoxLayout(p4); p4l.setContentsMargins(0, 0, 0, 0)
        self.peer_search = PeerSearchPanel()
        self.peer_search.set_llm_cfg(_llm_load())
        self.peer_search.stock_selected.connect(self._search_code)
        p4l.addWidget(self.peer_search)

        # Page 5 公开信息披露
        from due_diligence_panel import DueDiligencePanel
        p5 = QWidget(); p5.setStyleSheet(f"background:{BG2};")
        p5l = QVBoxLayout(p5); p5l.setContentsMargins(0, 0, 0, 0)
        self.dd_panel = DueDiligencePanel()
        p5l.addWidget(self.dd_panel)

        # Page 6 私募基金（AMAC 中基协）
        from amac_panel import AmacPanel
        p6 = QWidget(); p6.setStyleSheet(f"background:{BG2};")
        p6l = QVBoxLayout(p6); p6l.setContentsMargins(0, 0, 0, 0)
        self.amac_panel = AmacPanel()
        p6l.addWidget(self.amac_panel)

        # Page 7 工商信息尽调（开发中）
        p7 = QWidget(); p7.setStyleSheet(f"background:{BG2};")
        p7l = QVBoxLayout(p7); p7l.setContentsMargins(0, 0, 0, 0)
        p7l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _wip_icon = QLabel("🚧")
        _wip_icon.setFont(QFont("Arial", 48))
        _wip_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _wip_icon.setStyleSheet("background:transparent;border:none;")
        _wip_title = QLabel("功能开发中")
        _wip_title.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        _wip_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _wip_title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        _wip_sub = QLabel("工商信息尽调功能正在重构，敬请期待")
        _wip_sub.setFont(QFont("Arial", 13))
        _wip_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _wip_sub.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        p7l.addStretch(2)
        p7l.addWidget(_wip_icon)
        p7l.addSpacing(12)
        p7l.addWidget(_wip_title)
        p7l.addSpacing(8)
        p7l.addWidget(_wip_sub)
        p7l.addStretch(3)

        # Page 8 财务计算器
        from fin_calc_panel import FinCalcPanel
        p8 = QWidget(); p8.setStyleSheet(f"background:{BG2};")
        p8l = QVBoxLayout(p8); p8l.setContentsMargins(0, 0, 0, 0)
        self.fin_calc_panel = FinCalcPanel()
        p8l.addWidget(self.fin_calc_panel)

        # Page 9 财务风险因子识别
        from dd_form_panel import DueDiligenceFormPanel
        p9 = QWidget(); p9.setStyleSheet(f"background:{BG2};")
        p9l = QVBoxLayout(p9); p9l.setContentsMargins(0, 0, 0, 0)
        self.dd_form_panel = DueDiligenceFormPanel()
        p9l.addWidget(self.dd_form_panel)

        # 连接：财务计算器计算完成后自动同步到尽调填空题
        self.fin_calc_panel.calc_finished.connect(self.dd_form_panel.set_fin_calc_data)

        for p in [p0, p1, p2, p3, p4, p5, p6, p7, p8, p9]:
            self._stack.addWidget(p)

        right_lay.addWidget(self._stack, 1)
        root.addWidget(right_w, 1)

        # 初始化收藏列表
        self._refresh_fav_list()

        # 页面元数据
        self._PAGE_META = [
            ("年报查询",     "查询公司年报文件及财报截止日期"),
            ("行情分析",     "K线图、技术指标、区间统计"),
            ("多股比对",     "多只股票横向指标对比"),
            ("消息引擎",     "行业资讯、利好利空分类"),
            ("同行业搜索",   "描述公司特征，AI 推荐同行业上市公司"),
            ("公开信息披露", "美国（SEC EDGAR）/ 中国香港（港交所）公开信息查询"),
            ("私募基金",     "中基协 AMAC 私募基金备案查询 · 管理人穿透"),
            ("工商信息尽调", "企业工商注册、失信记录、裁判文书、专利信息查询"),
            ("财务计算器",   "输入财务数据，计算指标并与同行业上市公司比对"),
            ("财务风险因子识别",   "填写业务信息，结合财务指标与同行数据，挖掘潜在财务风险因子"),
        ]

    def _nav_style(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"QPushButton{{background:{CARD2};color:{FG};border:none;border-left:3px solid {ACCENT};"
                f"border-radius:0;font-size:13px;font-weight:600;padding:0 0 0 17px;text-align:left;}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{FG2};border:none;border-left:3px solid transparent;"
                f"border-radius:0;font-size:13px;font-weight:400;padding:0 0 0 17px;text-align:left;}}"
                f"QPushButton:hover{{background:{CARD};color:{FG};border-left-color:{BORDER};}}"
            )

    def _nav_click(self, btn):
        idx = btn.property("nav_idx")
        for b in self._nav_btns:
            self._nav_style(b, b is btn)
        self._stack.setCurrentIndex(idx)
        title, sub = self._PAGE_META[idx]
        self._page_title.setText(title)
        self._page_sub.setText(sub)
        # 触发数据加载
        if not self._cur: return
        mkt = _detect_market(self._cur.get("market",""))
        ticker = self._cur.get("ticker","")
        company = self._cur.get("company","")
        if idx == 1:
            self.ap.load(ticker, mkt)
        elif idx == 3:
            self.np.load(ticker, mkt, company)
        elif idx == 4:
            pass  # 同行业搜索，无需额外加载

    def _update_fav_btn(self, starred: bool):
        if starred:
            self.fav_btn.setText("已收藏")
            self.fav_btn.setStyleSheet(
                f"QPushButton{{background:rgba(255,214,10,0.15);color:{STAR};"
                f"border:1px solid rgba(255,214,10,0.4);border-radius:7px;"
                f"font-size:11px;font-weight:600;padding:0 12px;}}"
                f"QPushButton:hover{{background:rgba(255,214,10,0.25);}}"
            )
        else:
            self.fav_btn.setText("收藏")
            self.fav_btn.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{FG2};border:1px solid {BORDER};"
                f"border-radius:7px;font-size:11px;padding:0 12px;}}"
                f"QPushButton:hover{{color:{STAR};border-color:rgba(255,214,10,0.5);"
                f"background:rgba(255,214,10,0.08);}}"
            )

    def _toggle_fav(self):
        if not self._cur: return
        mkt = _detect_market(self._cur.get("market",""))
        ticker = self._cur.get("ticker","")
        name = self._cur.get("company","")
        try:
            starred = toggle_favorite(ticker, mkt, name)
        except ValueError as e:
            self._st(str(e), "#FF453A")
            return
        self._update_fav_btn(starred)
        self._refresh_fav_list()
        self._st(f"{'已收藏' if starred else '已取消收藏'}  {ticker}", STAR if starred else FG2)

    def _refresh_fav_list(self):
        """刷新侧边栏收藏列表"""
        lay = self._fav_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        favs = load_favorites()
        if not favs:
            empty = QLabel("暂无收藏")
            empty.setFont(QFont("Arial", 9))
            empty.setStyleSheet(f"color:{FG3};background:transparent;border:none;padding:4px 12px;")
            lay.addWidget(empty)
        else:
            for fav in favs:
                fb = QPushButton(f"{fav['code']}  {fav.get('name','')[:6]}")
                fb.setFixedHeight(34)
                fb.setCursor(Qt.CursorShape.PointingHandCursor)
                fb.setToolTip(f"{fav.get('name','')}  ({fav['market']})")
                fb.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{FG2};border:none;"
                    f"border-radius:6px;font-size:11px;padding:0 8px;text-align:left;}}"
                    f"QPushButton:hover{{background:{CARD};color:{FG};}}"
                )
                code, mkt = fav["code"], fav["market"]
                fb.clicked.connect(lambda _, c=code: self._search_code(c))
                lay.addWidget(fb)
        lay.addStretch()

    def _search_code(self, code: str):
        """从收藏列表快速查询"""
        self.inp.setText(code)
        self._search()

    def _open_settings(self):
        dlg = LLMSettingsDialog(self)
        if dlg.exec() == LLMSettingsDialog.DialogCode.Accepted:
            cfg = dlg.get_config()
            self.np.set_llm_cfg(cfg)          # 消息引擎
            self.peer_search.set_llm_cfg(cfg) # 同行业搜索
            if self._agent_chat_win is not None:
                self._agent_chat_win.set_llm_cfg(cfg)  # 投研问答独立窗口
            self._llm_cfg = cfg
            from llm_client import PROVIDERS
            if cfg.get("enabled") and cfg.get("api_key"):
                provider_name = PROVIDERS.get(cfg.get("provider","openai"), {}).get("name","LLM")
                self._st(f"LLM 已启用：{provider_name}", SUCCESS)
            else:
                self._st("LLM 已禁用", FG2)

    def _open_agent_chat_window(self):
        """以独立窗口弹出一键分析，自动注入当前中间结果"""
        from llm_client import load_config as _llm_load
        if self._agent_chat_win is None:
            self._agent_chat_win = AgentChatPanel()
            self._agent_chat_win.setWindowTitle("✦ 一键分析")
            self._agent_chat_win.setWindowFlags(Qt.WindowType.Window)
            self._agent_chat_win.resize(860, 680)
            self._agent_chat_win.set_llm_cfg(_llm_load())
        if self._cur:
            self._agent_chat_win.set_context(
                self._cur.get("ticker", ""),
                self._cur.get("company", "")
            )
            # 组装中间结果上下文，自动触发分析
            ctx = self._build_analysis_context()
            if ctx:
                self._agent_chat_win.auto_analyze(ctx)
        self._agent_chat_win.show()
        self._agent_chat_win.raise_()
        self._agent_chat_win.activateWindow()

    def _build_analysis_context(self) -> str:
        """把当前所有面板中间结果组装成 LLM 分析上下文字符串"""
        if not self._cur:
            return ""
        parts = []
        r = self._cur
        ticker  = r.get("ticker", "")
        company = r.get("company", "") or ticker
        market  = r.get("market", "")

        # ── 1. 公司基本信息 ──────────────────────────────────
        parts.append("## 公司基本信息")
        parts.append(f"- 股票代码：{ticker}")
        parts.append(f"- 公司名称：{company}")
        parts.append(f"- 上市市场：{market}")
        ne = r.get("next_earnings")
        if ne:
            parts.append(f"- 下次财报日期：{ne}  ({r.get('next_earnings_source','')})")
        if r.get("error"):
            parts.append(f"- 数据备注：{r['error']}")

        # ── 2. 年报文件列表 ──────────────────────────────────
        filings = r.get("filings", [])
        if filings:
            parts.append(f"\n## 最新报告文件（共 {len(filings)} 份）")
            for f in filings[:5]:
                name = f.get("name") or f.get("form") or ""
                date = f.get("date") or f.get("filed") or ""
                parts.append(f"- {name}  {date}")

        # ── 3. 行情分析数据 ──────────────────────────────────
        ap_data = getattr(self.ap, "_data", None)
        if ap_data:
            parts.append("\n## 行情分析数据")
            price = ap_data.get("price") or ap_data.get("current_price")
            if price:
                parts.append(f"- 当前价格：{price}")
            for period in ["1mo", "3mo", "6mo", "1y"]:
                stats = ap_data.get(f"stats_{period}") or ap_data.get(period)
                if stats and isinstance(stats, dict):
                    ret = stats.get("return") or stats.get("total_return")
                    if ret is not None:
                        parts.append(f"- {period} 区间涨跌：{ret:.2f}%")
            fin = ap_data.get("financials") or ap_data.get("fin")
            if fin and isinstance(fin, dict):
                parts.append("- 财务指标：" + "；".join(
                    f"{k}={v}" for k, v in list(fin.items())[:8]
                ))
            val = ap_data.get("valuation") or ap_data.get("val")
            if val and isinstance(val, dict):
                parts.append("- 估值指标：" + "；".join(
                    f"{k}={v}" for k, v in list(val.items())[:6]
                ))

        # ── 4. 消息引擎数据（NewsPanel._last_data）──────────
        np_panel = getattr(self, "np", None)
        if np_panel:
            news_data = getattr(np_panel, "_last_data", None)
            # _last_data 是 dict，其中 items/news/articles 字段存放列表
            if isinstance(news_data, dict):
                news_items = (
                    news_data.get("items")
                    or news_data.get("news")
                    or news_data.get("articles")
                    or []
                )
            elif isinstance(news_data, list):
                news_items = news_data
            else:
                news_items = []
            if news_items:
                parts.append(f"\n## 近期相关消息（共 {len(news_items)} 条，摘录前 10 条）")
                for item in news_items[:10]:
                    if isinstance(item, dict):
                        title   = item.get("title") or item.get("headline") or ""
                        date    = item.get("date") or item.get("time") or ""
                        summary = item.get("summary") or item.get("content") or ""
                        tag     = item.get("tag") or item.get("sentiment") or ""
                        line = f"- [{date}] {title}"
                        if tag:
                            line += f"  【{tag}】"
                        if summary:
                            line += f"\n  {summary[:120]}"
                        parts.append(line)

        # ── 5. 同行业搜索结果（PeerSearchPanel._last_results）──
        peer_panel = getattr(self, "peer_search", None)
        if peer_panel:
            peer_results = getattr(peer_panel, "_last_results", None)
            peer_query   = getattr(peer_panel, "_last_query", "")
            if peer_results and isinstance(peer_results, list):
                header = f"\n## 同行业搜索结果"
                if peer_query:
                    header += f"（查询：{peer_query}，共 {len(peer_results)} 家）"
                parts.append(header)
                for comp in peer_results[:10]:
                    if isinstance(comp, dict):
                        name    = comp.get("name") or comp.get("company") or ""
                        sym     = comp.get("ticker") or comp.get("symbol") or ""
                        desc    = comp.get("description") or comp.get("summary") or ""
                        line = f"- {name}"
                        if sym:
                            line += f"（{sym}）"
                        if desc:
                            line += f"：{desc[:100]}"
                        parts.append(line)

        # ── 6. 公开信息披露 / 尽调（DueDiligencePanel._last_result）──
        dd_panel = getattr(self, "dd_panel", None)
        if dd_panel:
            dd_data = getattr(dd_panel, "_last_result", None)
            if dd_data and isinstance(dd_data, dict):
                parts.append("\n## 公开信息披露（SEC 尽调）")
                info = dd_data.get("info", {})
                if info:
                    parts.append(f"- 公司名称：{info.get('name','—')}")
                    parts.append(f"- CIK：{info.get('cik','—')}")
                    parts.append(f"- Ticker：{', '.join(info.get('tickers',[]))}")
                    parts.append(f"- 交易所：{', '.join(info.get('exchanges',[]))}")
                    parts.append(f"- SIC 行业：{info.get('sic','—')} {info.get('sic_desc','')}")
                    parts.append(f"- 员工人数：{info.get('employees','—')}")
                    parts.append(f"- 注册地：{info.get('state_of_inc','—')}")
                filings_dd = dd_data.get("filings", [])
                if filings_dd:
                    parts.append(f"- 最新 SEC 文件（前 5 份）：")
                    for f in filings_dd[:5]:
                        form = f.get("form","")
                        date = f.get("filed","") or f.get("date","")
                        desc = f.get("description","") or f.get("primaryDocument","")
                        parts.append(f"  · {form}  {date}  {desc}")

        # ── 7. 同行业公司行情对比（ComparisonPanel._results）──
        cp_panel = getattr(self, "cp", None)
        if cp_panel:
            cp_results = getattr(cp_panel, "_results", None)
            if cp_results and isinstance(cp_results, list):
                parts.append(f"\n## 同行业行情对比（共 {len(cp_results)} 家）")
                for item in cp_results[:8]:
                    if isinstance(item, dict):
                        sym   = item.get("ticker") or item.get("symbol") or ""
                        name  = item.get("name") or item.get("company") or sym
                        price = item.get("price") or item.get("current_price") or ""
                        chg   = item.get("change") or item.get("change_pct") or ""
                        pe    = item.get("pe") or item.get("pe_ratio") or ""
                        line  = f"- {name}（{sym}）"
                        if price:
                            line += f"  价格：{price}"
                        if chg:
                            line += f"  涨跌：{chg}"
                        if pe:
                            line += f"  PE：{pe}"
                        parts.append(line)

        # ── 8. AMAC / 基金公开信息（amac_panel._last_result）──
        amac_panel = getattr(self, "amac_panel", None)
        if amac_panel:
            amac_data = getattr(amac_panel, "_last_result", None)
            if amac_data and isinstance(amac_data, dict):
                parts.append("\n## AMAC 公开信息")
                for k, v in list(amac_data.items())[:12]:
                    if v and not isinstance(v, (dict, list)):
                        parts.append(f"- {k}：{v}")

        if len(parts) <= 3:
            return ""
        return "\n".join(parts)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self,"选择年报保存目录",self._save_dir)
        if d: self._save_dir=d; self._st(f"保存目录：{d}")

    def _search(self):
        code = self.inp.text().strip()
        if not code: self._st("请输入股票代码",WARN); return
        self._clear_r(); self.sbtn.setEnabled(False); self.sbtn.setText("...")
        self._st(f"正在查询 {code.upper()} ...",ACCENT)
        self._stack.setCurrentIndex(0)
        self._nav_btns[0].setChecked(True)
        self._nav_style(self._nav_btns[0], True)
        for b in self._nav_btns[1:]: self._nav_style(b, False)
        w = QueryWorker(code); w.finished.connect(self._q_done); w.error.connect(self._q_err)
        _track_worker(self._workers, w); w.start()

    def _q_done(self, r):
        self.sbtn.setEnabled(True); self.sbtn.setText("查"); self._cur=r
        if r.get("error") and not r.get("filings"):
            self._st(r["error"],ERR); self._err_card(r["error"]); return
        self._st("查询完成，切换左侧导航查看行情 / 消息引擎 / 同行业",SUCCESS)
        # 更新收藏按钮
        mkt = _detect_market(r.get("market",""))
        ticker = r.get("ticker","")
        self.fav_btn.setVisible(True)
        self._update_fav_btn(is_favorite(ticker, mkt))
        # 切换到年报页
        self._nav_btns[0].setChecked(True)
        self._nav_style(self._nav_btns[0], True)
        for b in self._nav_btns[1:]: self._nav_style(b, False)
        self._stack.setCurrentIndex(0)
        self._page_title.setText("年报查询")
        self._page_sub.setText("查询公司年报文件及财报截止日期")
        self._render_r(r)

    def _q_err(self, msg):
        self.sbtn.setEnabled(True); self.sbtn.setText("查")
        self._st(f"错误：{msg}",ERR); self._err_card(msg)

    def _render_r(self, r):
        lay = self.rl; lay.takeAt(lay.count()-1)

        # 公司信息卡
        ic = QFrame(); ic.setStyleSheet(f"QFrame{{{cs(10)}}}")
        il = QVBoxLayout(ic); il.setContentsMargins(16,12,16,12); il.setSpacing(5)
        top = QHBoxLayout()
        co = QLabel(r.get("company") or r.get("ticker","—"))
        co.setFont(QFont("Arial",15,QFont.Weight.Bold)); co.setStyleSheet(ls(FG,15,True))
        top.addWidget(co)
        _mkt_raw = r.get("market","")
        _mkt_code = _detect_market(_mkt_raw)
        _mkt_display = {"US": "美国", "HK": "中国香港", "CN": "中国大陆"}.get(_mkt_code, _mkt_raw)
        mt = QLabel(_mkt_display)
        mt.setFont(QFont("Arial",10,QFont.Weight.Bold))
        mt.setStyleSheet(f"color:{ACCENT};background:rgba(79,142,247,0.15);border-radius:5px;padding:2px 8px;")
        top.addWidget(mt); top.addStretch(); il.addLayout(top)
        il.addWidget(self._lbl(f"代码：{r.get('ticker','—')}"))
        ne = r.get("next_earnings")
        if ne:
            src   = r.get("next_earnings_source", "")
            rtype = r.get("next_earnings_type", "")
            rtype_str = f"【{rtype}】" if rtype else ""
            is_deadline = "截止" in src or "规定" in src
            color = WARN if is_deadline else SUCCESS
            il.addWidget(self._lbl(
                f"下次财报 {rtype_str}：{ne}   ({src})", color, 11, True
            ))
        else:
            il.addWidget(self._lbl("下次财报日期：暂无数据"))
        if r.get("error"):
            il.addWidget(self._lbl(f"注意：{r['error']}",WARN,wrap=True))
        lay.addWidget(ic)

        if r.get("filings"):
            sl = QLabel("最新报告文件"); sl.setFont(QFont("Arial",12,QFont.Weight.Bold))
            sl.setStyleSheet(ls(FG,12,True)+"margin-top:2px;"); lay.addWidget(sl)
            self._cards=[]
            for i,f in enumerate(r["filings"]):
                card = FilingCard(f,i); card.download_requested.connect(self._dl)
                lay.addWidget(card); self._cards.append(card)

        if r.get("filings") and len(r["filings"])>1:
            ab = QPushButton("全部下载"); ab.setFixedHeight(36)
            ab.setCursor(Qt.CursorShape.PointingHandCursor)
            ab.setStyleSheet(
                f"QPushButton{{background:transparent;color:{ACCENT};border:1.5px solid {ACCENT};border-radius:8px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:rgba(79,142,247,0.1);}}"
            )
            ab.clicked.connect(self._dl_all); lay.addWidget(ab)

        tip = QLabel("点击左侧导航栏切换：行情分析 / 消息引擎 / 同行业扫描")
        tip.setFont(QFont("Arial",10)); tip.setStyleSheet(f"color:{FG3};padding:2px 0;")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(tip)
        lay.addStretch()

    def _lbl(self, text, color=FG2, size=10, bold=False, wrap=False):
        l = QLabel(text); l.setFont(QFont("Arial",size)); l.setStyleSheet(ls(color,size,bold))
        if wrap: l.setWordWrap(True)
        return l

    def _err_card(self, msg):
        lay = self.rl; lay.takeAt(lay.count()-1)
        c = QFrame()
        c.setStyleSheet("QFrame{background:rgba(255,69,58,0.1);border:1px solid rgba(255,69,58,0.4);border-radius:10px;}")
        cl = QVBoxLayout(c); cl.setContentsMargins(16,12,16,12)
        l = QLabel(f"错误：{msg}"); l.setFont(QFont("Arial",11)); l.setStyleSheet(ls(ERR,11))
        l.setWordWrap(True); cl.addWidget(l); lay.addWidget(c); lay.addStretch()

    def _dl(self, idx):
        if not self._cur: return
        filings = self._cur.get("filings",[])
        if idx>=len(filings): return
        mkt = _detect_market(self._cur.get("market",""))
        self._cards[idx].set_downloading()
        self._st(f"正在下载 {filings[idx].get('form','年报')} {filings[idx].get('date','')} ...",ACCENT)
        w = DownloadWorker(filings[idx],mkt,self._save_dir,idx)
        w.finished.connect(self._dl_done); _track_worker(self._workers, w); w.start()

    def _dl_all(self):
        if not self._cur: return
        for i in range(len(self._cur.get("filings",[]))): self._dl(i)

    def _dl_done(self, ok, path, idx):
        if idx<len(self._cards): self._cards[idx].set_done(ok)
        if ok:
            self._st(f"已保存：{path}",SUCCESS)
            folder = str(Path(path).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else: self._st(f"下载失败：{path}",ERR)

    def _clear_r(self):
        self._cards=[]
        lay = self.rl
        while lay.count():
            it = lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        lay.addStretch()

    def _st(self, msg, color=FG3):
        self.stl.setText(msg); self.stl.setStyleSheet(ls(color,10))


# ═══════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Pre-Diligence Lab")
    app.setApplicationVersion("1.4.0")
    win = MainWindow(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
