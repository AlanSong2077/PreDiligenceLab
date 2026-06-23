"""
fin_calc_panel.py — 财务计算器面板
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
布局：
  左侧：原始数据输入表单（9 个必填 + 5 个可选）+ 行业/对标公司选择
  右侧：逐指标分析卡片（数值 + 行业中位数 + 百分位条 + 判断标签）
         + 底部 CSV 下载按钮

单位约定：全部使用「万元」，在表单顶部明确标注。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import csv
import io
import json
import math
import os
import shutil
import subprocess
import textwrap

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QScrollArea, QSizePolicy, QComboBox,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QTextEdit, QDialogButtonBox,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QColor, QBrush

from theme import (
    BG2, CARD, CARD2,
    ACCENT, ACCENT_H,
    SUCCESS, WARN, ERR,
    FG, FG2, FG3,
    BORDER,
    INPUT_BG, INPUT_BD,
)
from fin_calc import METRIC_META, METRIC_GROUPS, INDUSTRY_PEERS, run_analysis

_GREEN  = SUCCESS
_ORANGE = WARN
_RED    = ERR


# ─────────────────────────────────────────────────────────────
# CSV 导出工具
# ─────────────────────────────────────────────────────────────

def _build_csv(inputs: dict, metrics: dict, analysis: dict,
               benchmarks: dict, peer_codes: list, industry: str) -> str:
    """
    将计算结果序列化为 CSV 字符串。

    包含三个 section：
      [输入数据]   用户填写的原始财报科目
      [计算指标]   calculate_metrics() 的输出
      [对标数据]   每个指标的同行中位数 / 百分位（若有）
    """
    buf = io.StringIO()
    w = csv.writer(buf)

    # ── Section 1：输入数据 ───────────────────────────────────
    w.writerow(["# 输入数据（单位：万元）"])
    w.writerow(["字段", "显示名", "值"])
    for key, label, _, _ in INPUT_FIELDS:
        val = inputs.get(key, "")
        w.writerow([key, label, val if val != "" else "（未填）"])
    w.writerow([])

    # ── Section 2：计算指标 ───────────────────────────────────
    w.writerow(["# 计算指标"])
    w.writerow(["指标键", "指标名", "单位", "计算值", "判断", "行业中位数", "百分位"])
    for key, info in analysis.items():
        meta = METRIC_META.get(key)
        unit = meta[1] if meta else ""
        val  = info.get("value")
        jdg  = info.get("judgment", "")
        med  = info.get("median", "")
        pct  = info.get("percentile", "")
        w.writerow([
            key,
            info.get("display_name", key),
            unit,
            "" if val is None else round(val, 4),
            jdg,
            "" if med  == "" or med  is None else round(med, 4),
            "" if pct  == "" or pct  is None else round(pct, 1),
        ])
    w.writerow([])

    # ── Section 3：对标原始数据 ───────────────────────────────
    if benchmarks and any(v for v in benchmarks.values()):
        src = f"对标公司：{', '.join(peer_codes)}" if peer_codes else f"行业：{industry}"
        w.writerow([f"# 对标数据（{src}）"])
        w.writerow(["指标键", "指标名", "同行数据（逗号分隔）", "中位数", "均值"])
        import statistics
        for key, vals in benchmarks.items():
            if not vals:
                continue
            meta = METRIC_META.get(key)
            name = meta[0] if meta else key
            med  = round(statistics.median(vals), 4)
            avg  = round(sum(vals) / len(vals), 4)
            w.writerow([key, name, "|".join(str(round(v, 4)) for v in vals), med, avg])

    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 后台 Worker
# ─────────────────────────────────────────────────────────────

class _CalcWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, inputs: dict, industry: str, peer_codes: list):
        super().__init__()
        self._inputs     = inputs
        self._industry   = industry
        self._peer_codes = peer_codes

    def run(self):
        try:
            result = run_analysis(
                self._inputs,
                industry_name=self._industry,
                peer_codes=self._peer_codes if self._peer_codes else None,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────
# OpenClaw 深度分析 Worker
# ─────────────────────────────────────────────────────────────

OPENCLAW_BIN = shutil.which("openclaw") or "/opt/homebrew/bin/openclaw"


def _openclaw_available() -> bool:
    """检测本地是否安装了 openclaw 且 gateway 在运行。
    openclaw health 返回 0 即表示 gateway 正常，无需检查 stdout 内容。
    """
    if not os.path.isfile(OPENCLAW_BIN):
        return False
    try:
        r = subprocess.run(
            [OPENCLAW_BIN, "health"],
            capture_output=True, text=True, timeout=8
        )
        return r.returncode == 0
    except Exception:
        return False


class _OpenClawWorker(QThread):
    """后台调用 openclaw agent，流式返回进度，最终返回完整结果"""
    progress = pyqtSignal(str)   # 进度文字
    finished = pyqtSignal(str)   # 最终分析文本
    error    = pyqtSignal(str)

    def __init__(self, prompt: str, thinking: str = "high"):
        super().__init__()
        self._prompt   = prompt
        self._thinking = thinking

    def run(self):
        try:
            self.progress.emit("🔗 正在连接 OpenClaw Gateway…")
            cmd = [
                OPENCLAW_BIN, "agent",
                "--agent", "main",
                "--message", self._prompt,
                "--thinking", self._thinking,
                "--json",
                "--timeout", "300",
            ]
            self.progress.emit("🧠 OpenClaw 正在深度分析财务风险，请稍候（最长 5 分钟）…")
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=320
            )
            if result.returncode != 0:
                self.error.emit(f"OpenClaw 返回错误：{result.stderr[:400]}")
                return

            # 解析 JSON 输出
            raw = result.stdout.strip()
            # openclaw 可能在 JSON 前输出 emoji 行，找到第一个 '{'
            brace = raw.find('{')
            if brace > 0:
                raw = raw[brace:]
            data = json.loads(raw)

            # 提取 payloads 文本
            payloads = (
                data.get("result", {}).get("payloads", [])
                or data.get("payloads", [])
            )
            texts = []
            for p in payloads:
                if isinstance(p, dict) and p.get("text"):
                    texts.append(p["text"])
                elif isinstance(p, str):
                    texts.append(p)

            if not texts:
                # fallback：直接用 summary
                texts = [data.get("summary", "") or raw[:2000]]

            self.finished.emit("\n\n".join(texts))

        except subprocess.TimeoutExpired:
            self.error.emit("OpenClaw 分析超时（>5 分钟），请稍后重试")
        except json.JSONDecodeError as e:
            # JSON 解析失败时直接返回原始文本
            self.finished.emit(result.stdout[:8000] if 'result' in dir() else str(e))
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────
# OpenClaw 结果展示对话框
# ─────────────────────────────────────────────────────────────

class _OpenClawResultDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🦞 OpenClaw 深度财务风险分析")
        self.resize(820, 640)
        self.setStyleSheet(
            f"QDialog{{background:#1a1d23;color:#e2e8f0;}}"
            f"QTextEdit{{background:#0f1117;color:#e2e8f0;"
            f"border:1px solid #2d3748;border-radius:8px;"
            f"font-family:'Menlo','Monaco','Courier New',monospace;"
            f"font-size:12px;padding:12px;line-height:1.6;}}"
            f"QPushButton{{background:#2d3748;color:#e2e8f0;"
            f"border:1px solid #4a5568;border-radius:6px;"
            f"padding:6px 18px;font-size:11px;}}"
            f"QPushButton:hover{{background:#4a5568;}}"
            f"QProgressBar{{background:#2d3748;border:none;"
            f"border-radius:4px;height:6px;text-align:center;}}"
            f"QProgressBar::chunk{{background:#4f8ef7;border-radius:4px;}}"
            f"QLabel{{color:#a0aec0;font-size:11px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)

        # 标题行
        hdr = QHBoxLayout()
        title = QLabel("🦞  OpenClaw 深度财务风险分析报告")
        title.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#4f8ef7;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._copy_btn = QPushButton("复制全文")
        self._copy_btn.clicked.connect(self._copy_all)
        hdr.addWidget(self._copy_btn)
        lay.addLayout(hdr)

        # 进度条（分析中显示）
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # 不确定进度
        self._progress.setFixedHeight(6)
        lay.addWidget(self._progress)

        # 状态标签
        self._status = QLabel("正在连接 OpenClaw…")
        lay.addWidget(self._status)

        # 结果文本框
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlaceholderText("分析结果将在此显示…")
        lay.addWidget(self._text, 1)

        # 关闭按钮
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            "QDialogButtonBox QPushButton{min-width:80px;}"
        )
        lay.addWidget(btns)

    def set_status(self, msg: str):
        self._status.setText(msg)

    def set_result(self, text: str):
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._status.setText("✅ OpenClaw 执行完成")
        self._text.setPlainText(text)

    def set_error(self, msg: str):
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._status.setText(f"❌ {msg}")
        self._text.setPlainText(f"错误：{msg}")

    def _copy_all(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._text.toPlainText())


# ─────────────────────────────────────────────────────────────
# 输入字段定义
# ─────────────────────────────────────────────────────────────
# (key, 显示名, 财报来源说明, 必填?)

INPUT_FIELDS = [
    # ── 必填：利润表 ──────────────────────────────────────────
    ("revenue",          "营业收入",   "利润表第一行",                True),
    ("cogs",             "营业成本",   "利润表，营业收入下方",        True),
    ("operating_profit", "营业利润",   "利润表，利润总额上方",        True),
    ("net_profit",       "净利润",     "利润表，归属母公司股东净利润", True),
    # ── 必填：资产负债表 ──────────────────────────────────────
    ("total_assets",     "资产总计",   "资产负债表右下角合计",        True),
    ("current_assets",   "流动资产合计", "资产负债表流动资产小计",    True),
    ("current_liab",     "流动负债合计", "资产负债表流动负债小计",    True),
    ("total_liab",       "负债合计",   "资产负债表负债合计",          True),
    ("equity",           "归母股东权益", "资产负债表归属母公司股东权益合计", True),
    # ── 可选：补充科目 ────────────────────────────────────────
    ("inventory",        "存货",       "资产负债表（无则填 0）",      False),
    ("ar",               "应收账款",   "资产负债表（无则填 0）",      False),
    ("interest_exp",     "利息支出",   "利润表财务费用附注（无则留空）", False),
    ("da",               "折旧与摊销", "现金流量表附注（无则留空）",  False),
    ("cfo",              "经营现金流净额", "现金流量表经营活动净额（无则留空）", False),
    ("market_cap",       "总市值",     "可选，用于 PE/PB/PS",         False),
]

INDUSTRY_LIST = ["（不选行业，仅计算指标）"] + list(INDUSTRY_PEERS.keys())


# ─────────────────────────────────────────────────────────────
# 小工具
# ─────────────────────────────────────────────────────────────

def _section_hdr(title: str, color: str = ACCENT) -> QWidget:
    w = QWidget()
    w.setStyleSheet(f"background:{CARD2};border-radius:6px;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(10, 5, 10, 5)
    dot = QLabel("◆")
    dot.setFont(QFont("Arial", 8))
    dot.setStyleSheet(f"color:{color};background:transparent;border:none;")
    lay.addWidget(dot)
    lbl = QLabel(title)
    lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color:{color};background:transparent;border:none;")
    lay.addWidget(lbl)
    lay.addStretch()
    return w


def _judgment_color(judgment: str) -> str:
    if "极高" in judgment or "极低" in judgment or "需关注" in judgment:
        return _RED
    if "偏高" in judgment or "偏低" in judgment:
        return _ORANGE
    return _GREEN


# ─────────────────────────────────────────────────────────────
# 对比表格构建
# ─────────────────────────────────────────────────────────────

# 表格中展示的指标列（按分组顺序，排除估值）
_TABLE_COLS = [
    # 规模
    "revenue", "gross_profit", "net_profit_abs",
    # 盈利
    "gross_margin", "operating_margin", "net_margin", "roe", "roa", "ebitda_margin",
    # 偿债
    "current_ratio", "quick_ratio", "debt_ratio", "interest_cover",
    # 运营
    "ar_days", "inv_days", "asset_turnover",
    # 现金流
    "cfo_to_revenue", "cfo_to_netprofit",
    # 估值
    "pe", "pb", "ps",
]

# 分组分隔线位置（在第几列前插入分组标题）
_COL_GROUPS = {
    0:  "规模",
    3:  "盈利能力",
    9:  "偿债能力",
    13: "运营效率",
    16: "现金流",
    18: "估值",
}


def _fmt_val(val, unit: str) -> str:
    if val is None:
        return "—"
    if unit == "%":
        return f"{val:.1f}%"
    if unit == "x":
        return f"{val:.2f}x"
    if unit == "天":
        return f"{val:.0f}天"
    if unit == "万元":
        # 超过 1 亿万元（即 1 万亿）用亿显示
        if abs(val) >= 10000:
            return f"{val/10000:.1f}亿"
        return f"{val:.0f}万"
    return str(val)


def _cell_bg(val, key: str, analysis_row: dict) -> str:
    """根据判断结果返回单元格背景色（半透明）"""
    if val is None or key not in analysis_row:
        return "transparent"
    jdg = analysis_row[key].get("judgment", "")
    if "需关注" in jdg or "极" in jdg:
        return "rgba(239,68,68,0.15)"
    if "偏高" in jdg or "偏低" in jdg:
        return "rgba(245,158,11,0.15)"
    if "优秀" in jdg or "正常" in jdg:
        return "rgba(34,197,94,0.10)"
    return "transparent"


def _build_comparison_table(my_metrics: dict, analysis: dict,
                             peer_rows: list) -> QTableWidget:
    """
    构建对比表格。
    行：本公司（高亮）+ 每家同行公司
    列：各财务指标
    """
    cols = _TABLE_COLS
    n_cols = len(cols)
    n_rows = 1 + len(peer_rows)   # 本公司 + 同行

    tbl = QTableWidget(n_rows, n_cols)
    tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tbl.setAlternatingRowColors(False)
    tbl.verticalHeader().setVisible(False)
    tbl.setShowGrid(True)
    tbl.setStyleSheet(
        f"QTableWidget{{background:{CARD};border:none;"
        f"gridline-color:{BORDER};color:{FG};font-size:12px;}}"
        f"QTableWidget::item{{padding:4px 8px;border:none;}}"
        f"QTableWidget::item:selected{{background:rgba(79,142,247,0.25);color:{FG};}}"
        f"QHeaderView::section{{background:{CARD2};color:{FG2};"
        f"border:none;border-bottom:1px solid {BORDER};"
        f"border-right:1px solid {BORDER};padding:4px 6px;"
        f"font-size:11px;font-weight:bold;}}"
        f"QScrollBar:horizontal{{background:{CARD2};height:6px;border-radius:3px;}}"
        f"QScrollBar::handle:horizontal{{background:{BORDER};border-radius:3px;}}"
        f"QScrollBar::handle:horizontal:hover{{background:{ACCENT};}}"
        f"QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0px;}}"
        f"QScrollBar:vertical{{background:{CARD2};width:6px;border-radius:3px;}}"
        f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{ACCENT};}}"
        f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
    )

    # ── 列标题 ────────────────────────────────────────────────
    for ci, key in enumerate(cols):
        meta = METRIC_META.get(key, (key, "", True))
        header_text = f"{meta[0]}\n({meta[1]})" if meta[1] else meta[0]
        tbl.setHorizontalHeaderItem(ci, QTableWidgetItem(header_text))

    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    tbl.horizontalHeader().setMinimumSectionSize(72)

    # ── 本公司行（row 0，蓝色高亮） ──────────────────────────
    for ci, key in enumerate(cols):
        meta = METRIC_META.get(key, (key, "", True))
        unit = meta[1]
        val  = my_metrics.get(key)
        text = _fmt_val(val, unit)
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        # 本公司行底色 + 判断着色
        bg = _cell_bg(val, key, analysis)
        if bg == "transparent":
            bg = f"rgba(79,142,247,0.12)"
        item.setBackground(QColor(bg))
        item.setForeground(QColor(ACCENT))
        tbl.setItem(0, ci, item)

    # ── 同行公司行 ────────────────────────────────────────────
    for ri, peer in enumerate(peer_rows, start=1):
        for ci, key in enumerate(cols):
            meta = METRIC_META.get(key, (key, "", True))
            unit = meta[1]
            val  = peer.get(key)
            text = _fmt_val(val, unit)
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFont(QFont("Arial", 11))
            item.setForeground(QColor(FG2))
            tbl.setItem(ri, ci, item)

    # ── 行标题（公司名）用垂直表头 ───────────────────────────
    tbl.setVerticalHeaderItem(0, QTableWidgetItem("▶ 本公司"))
    tbl.verticalHeader().setVisible(True)
    tbl.verticalHeader().setDefaultSectionSize(32)
    tbl.verticalHeader().setStyleSheet(
        f"QHeaderView::section{{background:{CARD2};color:{FG2};"
        f"border:none;border-bottom:1px solid {BORDER};"
        f"border-right:1px solid {BORDER};padding:2px 8px;"
        f"font-size:11px;min-width:90px;}}"
    )
    for ri, peer in enumerate(peer_rows, start=1):
        name = peer.get("_name", peer.get("_code", f"同行{ri}"))
        tbl.setVerticalHeaderItem(ri, QTableWidgetItem(name))

    tbl.resizeRowsToContents()
    return tbl


# ─────────────────────────────────────────────────────────────
# 主面板
# ─────────────────────────────────────────────────────────────

class FinCalcPanel(QWidget):

    calc_finished = pyqtSignal(dict)  # 计算完成时发出，携带 _last_data

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker         = None
        self._oc_worker      = None   # OpenClaw worker
        self._last_data      = None   # 最近一次计算结果，供 CSV 下载 / OpenClaw 使用
        self._oc_notice      = None   # OpenClaw 未就绪提示卡片
        self._setup_ui()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 左侧输入面板 ──────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(300)
        left.setStyleSheet(
            f"background:{CARD2};border-right:1px solid {BORDER};"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        # 标题栏
        title_bar = QWidget()
        title_bar.setStyleSheet(
            f"background:{CARD2};border-bottom:1px solid {BORDER};"
        )
        tb_lay = QHBoxLayout(title_bar)
        tb_lay.setContentsMargins(14, 10, 14, 10)
        title_lbl = QLabel("财务计算器")
        title_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(
            f"color:{FG};background:transparent;border:none;"
        )
        tb_lay.addWidget(title_lbl)
        left_lay.addWidget(title_bar)

        # ── 固定区：单位说明 + 行业/对标公司（不随表单滚动）──
        fixed_top = QWidget()
        fixed_top.setStyleSheet(
            f"background:{CARD2};border-bottom:1px solid {BORDER};"
        )
        fixed_top_lay = QVBoxLayout(fixed_top)
        fixed_top_lay.setContentsMargins(12, 8, 12, 8)
        fixed_top_lay.setSpacing(6)

        # 单位说明（紧凑单行）
        unit_box = QFrame()
        unit_box.setStyleSheet(
            f"QFrame{{background:rgba(79,142,247,0.10);"
            f"border:1px solid rgba(79,142,247,0.28);border-radius:5px;}}"
        )
        unit_lay = QHBoxLayout(unit_box)
        unit_lay.setContentsMargins(8, 5, 8, 5)
        unit_lay.setSpacing(6)
        unit_icon = QLabel("📌")
        unit_icon.setFont(QFont("Arial", 9))
        unit_icon.setStyleSheet("background:transparent;border:none;")
        unit_lay.addWidget(unit_icon)
        unit_desc = QLabel("所有金额统一填「万元」  例：5亿 → 50000")
        unit_desc.setFont(QFont("Arial", 8))
        unit_desc.setStyleSheet(
            f"color:{FG2};background:transparent;border:none;"
        )
        unit_lay.addWidget(unit_desc, 1)
        fixed_top_lay.addWidget(unit_box)

        # 行业下拉
        ind_lbl = QLabel("行业基准（东方财富板块）")
        ind_lbl.setFont(QFont("Arial", 8))
        ind_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        fixed_top_lay.addWidget(ind_lbl)
        self._industry_combo = QComboBox()
        self._industry_combo.addItems(INDUSTRY_LIST)
        self._industry_combo.setFixedHeight(28)
        self._industry_combo.setStyleSheet(
            f"QComboBox{{background:{INPUT_BG};border:1px solid {INPUT_BD};"
            f"border-radius:6px;color:{FG};padding:0 8px;font-size:10px;}}"
            "QComboBox::drop-down{border:none;}"
            f"QComboBox QAbstractItemView{{background:{CARD};color:{FG};"
            f"border:1px solid {BORDER};selection-background-color:{ACCENT};}}"
        )
        fixed_top_lay.addWidget(self._industry_combo)

        # 对标公司代码
        peer_lbl = QLabel("或指定对标公司代码（优先级更高）")
        peer_lbl.setFont(QFont("Arial", 8))
        peer_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        fixed_top_lay.addWidget(peer_lbl)
        self._peer_input = QLineEdit()
        self._peer_input.setPlaceholderText(
            "如：600519,000858,002304"
        )
        self._peer_input.setFixedHeight(28)
        self._peer_input.setFont(QFont("Arial", 9))
        self._peer_input.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};border:1px solid {INPUT_BD};"
            f"border-radius:6px;color:{FG};padding:0 8px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};}}"
        )
        fixed_top_lay.addWidget(self._peer_input)
        left_lay.addWidget(fixed_top)

        # ── 滚动区：仅财报数据字段 ────────────────────────────
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        form_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            f"QScrollBar:vertical{{background:{CARD2};width:4px;border-radius:2px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:2px;}}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}"
        )
        form_w = QWidget()
        form_w.setStyleSheet("background:transparent;")
        form_lay = QVBoxLayout(form_w)
        form_lay.setContentsMargins(12, 10, 12, 10)
        form_lay.setSpacing(7)

        # ── 财报数据输入 ──────────────────────────────────────
        form_lay.addWidget(_section_hdr("财报原始数据（万元）", ACCENT))

        # 必填 / 可选分组标签
        req_lbl = QLabel("▸ 必填（利润表 + 资产负债表）")
        req_lbl.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        req_lbl.setStyleSheet(
            f"color:{FG2};background:transparent;border:none;"
        )
        form_lay.addWidget(req_lbl)

        self._field_inputs: dict[str, QLineEdit] = {}
        optional_started = False

        for key, label, placeholder, required in INPUT_FIELDS:
            # 在第一个可选字段前插入分隔标签
            if not required and not optional_started:
                optional_started = True
                opt_lbl = QLabel("▸ 可选（填了更准，不填系统估算）")
                opt_lbl.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                opt_lbl.setStyleSheet(
                    f"color:{FG3};background:transparent;border:none;"
                )
                form_lay.addWidget(opt_lbl)

            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_lay = QVBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(2)

            lbl_row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFont(QFont("Arial", 9))
            lbl.setStyleSheet(
                f"color:{FG if required else FG3};"
                "background:transparent;border:none;"
            )
            lbl_row.addWidget(lbl)
            if required:
                req_mark = QLabel("*")
                req_mark.setFont(QFont("Arial", 9))
                req_mark.setStyleSheet(
                    f"color:{_RED};background:transparent;border:none;"
                )
                lbl_row.addWidget(req_mark)
            lbl_row.addStretch()
            # 来源提示
            src_lbl = QLabel(placeholder)
            src_lbl.setFont(QFont("Arial", 7))
            src_lbl.setStyleSheet(
                f"color:{FG3};background:transparent;border:none;"
            )
            lbl_row.addWidget(src_lbl)
            row_lay.addLayout(lbl_row)

            inp = QLineEdit()
            inp.setPlaceholderText("万元")
            inp.setFixedHeight(28)
            inp.setFont(QFont("Arial", 10))
            inp.setStyleSheet(
                f"QLineEdit{{background:{INPUT_BG};border:1px solid {INPUT_BD};"
                f"border-radius:6px;color:{FG};padding:0 8px;}}"
                f"QLineEdit:focus{{border-color:{ACCENT};}}"
            )
            row_lay.addWidget(inp)
            self._field_inputs[key] = inp
            form_lay.addWidget(row)

        form_lay.addStretch()
        form_scroll.setWidget(form_w)
        left_lay.addWidget(form_scroll, 1)

        # 底部按钮栏
        btn_bar = QWidget()
        btn_bar.setStyleSheet(
            f"background:{CARD2};border-top:1px solid {BORDER};"
        )
        btn_lay = QHBoxLayout(btn_bar)
        btn_lay.setContentsMargins(12, 10, 12, 10)
        btn_lay.setSpacing(8)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedHeight(32)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{FG2};"
            f"border:1px solid {BORDER};border-radius:8px;font-size:10px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
        )
        self._clear_btn.clicked.connect(self._clear_inputs)
        btn_lay.addWidget(self._clear_btn)

        self._calc_btn = QPushButton("计算并比对")
        self._calc_btn.setFixedHeight(32)
        self._calc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._calc_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {ACCENT},stop:1 {ACCENT_H});"
            "color:white;border:none;border-radius:8px;"
            "font-size:11px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self._calc_btn.clicked.connect(self._do_calc)
        btn_lay.addWidget(self._calc_btn, 1)
        left_lay.addWidget(btn_bar)

        root.addWidget(left)

        # ── 右侧结果面板 ──────────────────────────────────────
        right = QWidget()
        right.setStyleSheet("background:transparent;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # 指标卡片滚动区
        cards_w = QWidget()
        cards_w.setStyleSheet(f"background:{BG2};")
        cards_outer = QVBoxLayout(cards_w)
        cards_outer.setContentsMargins(0, 0, 0, 0)
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._cards_scroll.setStyleSheet(
            f"QScrollArea{{background:{BG2};border:none;}}"
            f"QScrollBar:vertical{{background:{CARD2};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;min-height:24px;}}"
            f"QScrollBar::handle:vertical:hover{{background:{ACCENT};}}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}"
        )
        self._cards_inner = QWidget()
        self._cards_inner.setStyleSheet("background:transparent;")
        self._cards_lay = QVBoxLayout(self._cards_inner)
        self._cards_lay.setContentsMargins(16, 12, 16, 24)
        self._cards_lay.setSpacing(10)
        self._cards_scroll.setWidget(self._cards_inner)
        cards_outer.addWidget(self._cards_scroll)
        right_lay.addWidget(cards_w, 1)

        # 底部 CSV 下载栏
        csv_bar = QWidget()
        csv_bar.setStyleSheet(
            f"background:{CARD2};border-top:1px solid {BORDER};"
        )
        csv_bar_lay = QHBoxLayout(csv_bar)
        csv_bar_lay.setContentsMargins(12, 8, 12, 8)
        csv_bar_lay.addStretch()
        self._csv_btn = QPushButton("⬇  下载源数据 CSV")
        self._csv_btn.setFixedHeight(32)
        self._csv_btn.setEnabled(False)
        self._csv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._csv_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{FG2};"
            f"border:1px solid {BORDER};border-radius:8px;font-size:10px;padding:0 14px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};border-color:{BORDER};}}"
        )
        self._csv_btn.clicked.connect(self._download_csv)
        csv_bar_lay.addWidget(self._csv_btn)

        # OpenClaw 深度分析按钮
        self._oc_btn = QPushButton("🦞  OpenClaw 深度风险分析")
        self._oc_btn.setFixedHeight(32)
        self._oc_btn.setEnabled(False)
        self._oc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._oc_btn.setToolTip(
            "调用本地 OpenClaw AI，对当前财务数据进行深度潜在风险研究"
        )
        self._oc_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #7c3aed,stop:1 #a855f7);"
            "color:white;border:none;border-radius:8px;"
            "font-size:11px;font-weight:bold;padding:0 14px;}}"
            "QPushButton:hover{background:#a855f7;}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};border:1px solid {BORDER};}}"
        )
        self._oc_btn.clicked.connect(self._do_openclaw)
        csv_bar_lay.addWidget(self._oc_btn)
        right_lay.addWidget(csv_bar)

        root.addWidget(right, 1)

        self._show_empty()

    # ── 状态显示 ─────────────────────────────────────────────

    def _show_empty(self):
        self._clear_cards()
        hint = QLabel(
            "在左侧输入财报数据，点击「计算并比对」\n"
            "系统将自动计算财务指标并与同行业上市公司比对\n\n"
            "所有金额字段单位统一为「万元」"
        )
        hint.setFont(QFont("Arial", 11))
        hint.setStyleSheet(f"color:{FG3};background:transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        self._cards_lay.addWidget(hint)
        self._cards_lay.addStretch()

    def _show_loading(self):
        self._clear_cards()
        lbl = QLabel("正在计算指标并拉取行业基准数据，请稍候...")
        lbl.setFont(QFont("Arial", 11))
        lbl.setStyleSheet(
            f"color:{ACCENT};background:rgba(79,142,247,0.08);"
            f"border:1px solid rgba(79,142,247,0.2);border-radius:8px;padding:12px 20px;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cards_lay.addWidget(lbl)
        self._cards_lay.addStretch()

    def _show_error(self, msg: str):
        self._clear_cards()
        lbl = QLabel(msg)
        lbl.setFont(QFont("Arial", 10))
        lbl.setStyleSheet(f"color:{ERR};padding:12px;")
        lbl.setWordWrap(True)
        self._cards_lay.addWidget(lbl)
        self._cards_lay.addStretch()

    # ── 计算逻辑 ─────────────────────────────────────────────

    def _do_calc(self):
        inputs = {}
        for key, inp in self._field_inputs.items():
            text = inp.text().strip().replace(",", "").replace("，", "")
            if text:
                try:
                    inputs[key] = float(text)
                except ValueError:
                    pass

        # 必填字段校验
        required_keys = [k for k, _, _, req in INPUT_FIELDS if req]
        missing = [
            label
            for k, label, _, req in INPUT_FIELDS
            if req and k not in inputs
        ]
        if missing:
            self._show_error(
                f"以下必填字段未填写：{', '.join(missing)}\n"
                "请填写完整后重新计算。"
            )
            return

        # 解析对标公司代码
        peer_text = self._peer_input.text().strip()
        peer_codes = []
        if peer_text:
            peer_codes = [
                c.strip() for c in peer_text.replace("，", ",").split(",")
                if c.strip()
            ]

        # 行业
        industry = self._industry_combo.currentText()
        if industry.startswith("（"):
            industry = ""

        self._calc_btn.setEnabled(False)
        self._calc_btn.setText("计算中...")
        self._show_loading()

        self._worker = _CalcWorker(inputs, industry, peer_codes)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_result(self, data: dict):
        self._calc_btn.setEnabled(True)
        self._calc_btn.setText("计算并比对")
        self._render(data)

    def _on_error(self, msg: str):
        self._calc_btn.setEnabled(True)
        self._calc_btn.setText("计算并比对")
        self._show_error(f"计算失败：{msg}")

    def _clear_inputs(self):
        for inp in self._field_inputs.values():
            inp.clear()
        self._peer_input.clear()
        self._last_data = None
        self._csv_btn.setEnabled(False)
        self._show_empty()

    # ── 渲染结果 ─────────────────────────────────────────────

    def _render(self, data: dict):
        self._clear_cards()
        metrics    = data.get("metrics", {})
        analysis   = data.get("analysis", {})
        benchmarks = data.get("benchmarks", {})
        industry   = data.get("industry", "")
        peer_codes = data.get("peer_codes", [])
        peer_rows  = benchmarks.get("_peer_rows", [])

        if not analysis:
            self._show_error("未能计算出任何指标，请检查输入数据")
            return

        # 保存本次结果供 CSV 下载 / OpenClaw 使用
        self._last_data = data
        self.calc_finished.emit(data)
        self._csv_btn.setEnabled(True)
        # 检测 OpenClaw 并更新按钮 + 提示卡片
        self._refresh_openclaw_status()

        # ── 来源标签 ──────────────────────────────────────────
        if peer_codes:
            src_text = f"对标公司：{', '.join(peer_codes)}  （{len(peer_rows)} 家数据已加载）"
        elif industry:
            src_text = f"行业基准：{industry}  （{len(peer_rows)} 家代表公司）"
        else:
            src_text = "未选择行业/对标公司，仅显示本公司指标（无同行比对）"

        src_lbl = QLabel(src_text)
        src_lbl.setFont(QFont("Arial", 10))
        src_lbl.setStyleSheet(
            f"color:{ACCENT};background:rgba(79,142,247,0.08);"
            f"border:1px solid rgba(79,142,247,0.2);"
            "border-radius:5px;padding:4px 12px;"
        )
        src_lbl.setWordWrap(True)
        self._cards_lay.addWidget(src_lbl)

        # ── 对比表格 ──────────────────────────────────────────
        tbl = _build_comparison_table(metrics, analysis, peer_rows)
        self._cards_lay.addWidget(tbl, 1)

    # ── OpenClaw 状态检测 & 提示 ─────────────────────────────

    def _refresh_openclaw_status(self):
        """检测 OpenClaw，更新按钮状态，并在结果区底部渲染提示卡片"""
        # 移除旧的 OpenClaw 提示卡（如果有）
        if hasattr(self, "_oc_notice") and self._oc_notice is not None:
            self._oc_notice.deleteLater()
            self._oc_notice = None

        available = _openclaw_available()
        if available:
            self._oc_btn.setEnabled(True)
            self._oc_btn.setToolTip("调用本地 OpenClaw AI，对当前财务数据进行深度潜在风险研究")
            # 已就绪，不需要提示卡
            return

        # ── 未检测到 OpenClaw：渲染提示卡片 ──────────────────
        self._oc_btn.setEnabled(False)
        self._oc_btn.setToolTip("未检测到本地 OpenClaw 或 Gateway 未运行，点击查看安装说明")

        card = QFrame()
        card.setStyleSheet(
            "QFrame{"
            "background:rgba(124,58,237,0.10);"
            "border:1px solid rgba(168,85,247,0.40);"
            "border-radius:10px;"
            "}"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 12, 16, 12)
        card_lay.setSpacing(8)

        # 标题行
        hdr = QHBoxLayout()
        icon_lbl = QLabel("🦞")
        icon_lbl.setFont(QFont("Arial", 18))
        icon_lbl.setStyleSheet("background:transparent;border:none;")
        hdr.addWidget(icon_lbl)
        title_lbl = QLabel("OpenClaw 深度风险分析 — 未就绪")
        title_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(
            "color:#a855f7;background:transparent;border:none;"
        )
        hdr.addWidget(title_lbl)
        hdr.addStretch()
        card_lay.addLayout(hdr)

        # 说明文字
        desc = QLabel(
            "未检测到本地 OpenClaw 或其 Gateway 服务未运行。\n"
            "安装并启动后，可对当前财务数据进行 AI 深度潜在风险研究，\n"
            "识别盈利质量、偿债压力、现金流陷阱、同行异常偏差等风险。"
        )
        desc.setFont(QFont("Arial", 10))
        desc.setStyleSheet(
            f"color:{FG2};background:transparent;border:none;"
        )
        desc.setWordWrap(True)
        card_lay.addWidget(desc)

        # 安装命令行
        cmd_frame = QFrame()
        cmd_frame.setStyleSheet(
            f"QFrame{{background:#0f1117;border:1px solid #2d3748;"
            f"border-radius:6px;}}"
        )
        cmd_lay = QHBoxLayout(cmd_frame)
        cmd_lay.setContentsMargins(10, 6, 10, 6)
        cmd_lbl = QLabel("npm install -g openclaw   &&   openclaw gateway start")
        cmd_lbl.setFont(QFont("Menlo, Monaco, Courier New", 10))
        cmd_lbl.setStyleSheet(
            "color:#a855f7;background:transparent;border:none;"
        )
        cmd_lay.addWidget(cmd_lbl, 1)
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(48, 24)
        copy_btn.setStyleSheet(
            "QPushButton{background:#2d3748;color:#e2e8f0;"
            "border:1px solid #4a5568;border-radius:4px;font-size:10px;}"
            "QPushButton:hover{background:#4a5568;}"
        )
        copy_btn.clicked.connect(
            lambda: __import__("PyQt6.QtWidgets", fromlist=["QApplication"])
            .QApplication.clipboard()
            .setText("npm install -g openclaw && openclaw gateway start")
        )
        cmd_lay.addWidget(copy_btn)
        card_lay.addWidget(cmd_frame)

        # 文档链接 + 重新检测按钮
        btn_row = QHBoxLayout()
        doc_btn = QPushButton("📖  查看文档  docs.openclaw.ai")
        doc_btn.setFixedHeight(28)
        doc_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#a855f7;"
            "border:1px solid rgba(168,85,247,0.4);border-radius:6px;"
            "font-size:10px;padding:0 10px;}"
            "QPushButton:hover{background:rgba(168,85,247,0.12);}"
        )
        doc_btn.clicked.connect(
            lambda: __import__("PyQt6.QtGui", fromlist=["QDesktopServices"])
            .QDesktopServices.openUrl(
                __import__("PyQt6.QtCore", fromlist=["QUrl"])
                .QUrl("https://docs.openclaw.ai")
            )
        )
        btn_row.addWidget(doc_btn)

        retry_btn = QPushButton("🔄  重新检测")
        retry_btn.setFixedHeight(28)
        retry_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{FG2};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"font-size:10px;padding:0 10px;}}"
            f"QPushButton:hover{{color:{FG};border-color:#a855f7;}}"
        )
        retry_btn.clicked.connect(self._refresh_openclaw_status)
        btn_row.addWidget(retry_btn)
        btn_row.addStretch()
        card_lay.addLayout(btn_row)

        self._oc_notice = card
        self._cards_lay.addWidget(card)

    # ── OpenClaw 深度分析 ────────────────────────────────────

    def _do_openclaw(self):
        if not self._last_data:
            return
        if not _openclaw_available():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "OpenClaw 未就绪",
                "未检测到本地 OpenClaw 或 Gateway 未运行。\n"
                "请先启动 OpenClaw Gateway：openclaw gateway start"
            )
            return

        prompt = self._build_openclaw_prompt()
        dlg = _OpenClawResultDialog(self)
        dlg.show()

        self._oc_worker = _OpenClawWorker(prompt, thinking="high")
        self._oc_worker.progress.connect(dlg.set_status)
        self._oc_worker.finished.connect(dlg.set_result)
        self._oc_worker.error.connect(dlg.set_error)
        self._oc_worker.start()

    @staticmethod
    def _find_skill_text(skill_name: str) -> str:
        """
        在多个候选路径中自动搜索 <skill_name>/SKILL.md（+ examples.md），
        找到第一个可读的就返回完整内容，找不到返回空字符串。
        搜索顺序：
          1. 本文件同级目录（项目内随代码打包）
          2. ~/.openclaw/workspace/skills/
          3. 桌面（Desktop）
        """
        home = os.path.expanduser("~")
        this_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(this_dir, skill_name),
            os.path.join(home, ".openclaw", "workspace", "skills", skill_name),
            os.path.join(home, "Desktop", skill_name),
        ]
        for base in candidates:
            skill_md = os.path.join(base, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            parts = []
            for fname in ["SKILL.md", "examples.md"]:
                fpath = os.path.join(base, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        parts.append(f.read().strip())
                except Exception:
                    pass
            if parts:
                import logging
                logging.getLogger("stockreporter.fin_calc_panel").info(
                    "hardtech-risk-analysis SKILL 已从 %s 加载", base)
                return "\n\n---\n\n".join(parts)
        import logging
        logging.getLogger("stockreporter.fin_calc_panel").warning(
            "hardtech-risk-analysis SKILL 未找到，将跳过框架注入")
        return ""

    def _build_openclaw_prompt(self) -> str:
        """把当前计算结果组装成发给 OpenClaw 的深度分析 Prompt"""
        data       = self._last_data
        inputs     = data.get("inputs", {})
        metrics    = data.get("metrics", {})
        analysis   = data.get("analysis", {})
        benchmarks = data.get("benchmarks", {})
        industry   = data.get("industry", "未指定")
        peer_codes = data.get("peer_codes", [])
        peer_rows  = benchmarks.get("_peer_rows", [])

        import statistics

        lines = []

        # ── 0. 自动找到并注入 hardtech-risk-analysis SKILL ──────
        skill_text = self._find_skill_text("hardtech-risk-analysis")
        if skill_text:
            lines.append("# 分析框架（必须严格遵循）")
            lines.append("")
            lines.append(skill_text)
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.append("# 财务深度风险分析任务")
        lines.append("")
        lines.append(
            "你是一位资深财务分析师和风险研究专家。"
            + ("请严格按照上方【分析框架】的九步方法论，" if skill_text else "")
            + "对以下目标公司进行深度财务风险分析。"
            "行业基准取对标公司所在行业（即下方同行数据），"
            "重点诊断目标公司整体财务风险，识别与行业的异常偏差，"
            "并按框架要求输出结构化报告。"
        )
        lines.append("")

        # ── 1. 原始财报输入 ──────────────────────────────────
        lines.append("## 一、原始财报数据（万元）")
        field_map = {k: lbl for k, lbl, _, _ in INPUT_FIELDS}
        for k, v in inputs.items():
            lbl = field_map.get(k, k)
            lines.append(f"- {lbl}：{v:,.0f} 万元")
        lines.append("")

        # ── 3. 计算指标 + 判断 ───────────────────────────────
        lines.append("## 二、计算财务指标及系统判断")
        for key, info in analysis.items():
            val  = info.get("value")
            jdg  = info.get("judgment", "")
            name = info.get("display_name", key)
            meta = METRIC_META.get(key)
            unit = meta[1] if meta else ""
            if val is None:
                continue
            val_str = _fmt_val(val, unit)
            med = info.get("median")
            pct = info.get("percentile")
            line = f"- {name}：{val_str}"
            if jdg:
                line += f"  【{jdg}】"
            if med is not None:
                line += f"  行业中位数={_fmt_val(med, unit)}"
            if pct is not None:
                line += f"  百分位={pct:.0f}%"
            lines.append(line)
        lines.append("")

        # ── 3. 同行对比 ──────────────────────────────────────
        if peer_rows:
            src = f"对标公司：{', '.join(peer_codes)}" if peer_codes else f"行业：{industry}"
            lines.append(f"## 三、同行对比数据（{src}，共 {len(peer_rows)} 家）")
            for peer in peer_rows:
                name = peer.get("_name") or peer.get("_code", "同行")
                row_parts = []
                for key in ["gross_margin", "net_margin", "roe", "roa",
                             "current_ratio", "debt_ratio", "cfo_to_revenue",
                             "ar_days", "inv_days", "pe", "pb"]:
                    v = peer.get(key)
                    if v is None:
                        continue
                    meta = METRIC_META.get(key)
                    unit = meta[1] if meta else ""
                    row_parts.append(f"{METRIC_META.get(key,(key,''))[0]}={_fmt_val(v, unit)}")
                lines.append(f"- {name}：" + "；".join(row_parts))
            lines.append("")

            # 行业统计摘要
            lines.append("## 四、行业统计摘要")
            for key in ["gross_margin", "net_margin", "roe", "current_ratio",
                         "debt_ratio", "cfo_to_revenue"]:
                vals = [p[key] for p in peer_rows if p.get(key) is not None]
                if len(vals) < 2:
                    continue
                meta = METRIC_META.get(key)
                name = meta[0] if meta else key
                unit = meta[1] if meta else ""
                med  = statistics.median(vals)
                avg  = sum(vals) / len(vals)
                mn, mx = min(vals), max(vals)
                lines.append(
                    f"- {name}：中位数={_fmt_val(med,unit)}"
                    f"  均值={_fmt_val(avg,unit)}"
                    f"  区间=[{_fmt_val(mn,unit)}, {_fmt_val(mx,unit)}]"
                )
            lines.append("")
        else:
            lines.append(f"## 三、行业/对标信息")
            lines.append(f"- 行业：{industry or '未指定'}")
            lines.append(f"- 对标公司：{', '.join(peer_codes) or '未指定'}")
            lines.append("")

        # ── 4. 风险分析要求 ──────────────────────────────────
        lines.append("## 五、分析要求")
        lines.append(textwrap.dedent("""\
            请按以下结构输出报告：

            ### 1. 核心财务风险识别（高/中/低 分级）
            逐一列出发现的风险点，说明数据依据和风险逻辑。

            ### 2. 盈利质量分析
            分析净利润含金量、应收账款/存货异常、利润操纵信号。

            ### 3. 偿债与流动性风险
            短期偿债压力、债务结构、利息覆盖能力。

            ### 4. 现金流健康度
            经营现金流与净利润的背离、自由现金流状况。

            ### 5. 与同行的异常偏差
            指出本公司与行业中位数偏差超过 20% 的指标，分析原因。

            ### 6. 综合风险评级
            给出 A/B/C/D 四档综合评级，并说明理由。

            ### 7. 改善建议
            针对高风险项给出 3-5 条具体可操作建议。
        """))

        return "\n".join(lines)

    # ── CSV 下载 ──────────────────────────────────────────────

    def _download_csv(self):
        if not self._last_data:
            return
        data       = self._last_data
        inputs     = data.get("inputs", {})
        metrics    = data.get("metrics", {})
        analysis   = data.get("analysis", {})
        benchmarks = data.get("benchmarks", {})
        peer_codes = data.get("peer_codes", [])
        industry   = data.get("industry", "")

        csv_text = _build_csv(inputs, metrics, analysis, benchmarks,
                              peer_codes, industry)

        path, _ = QFileDialog.getSaveFileName(
            self, "保存 CSV", "财务分析数据.csv",
            "CSV 文件 (*.csv);;所有文件 (*)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(csv_text)

    # ── 工具 ─────────────────────────────────────────────────

    def _clear_cards(self):
        while self._cards_lay.count():
            it = self._cards_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
