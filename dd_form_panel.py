"""
dd_form_panel.py — 尽调信息填空题面板
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
独立的 Tab 页，布局分三部分：
  1. 顶部「分析上下文预览」—— 实时显示当前会发送给 OpenClaw 的完整 prompt
  2. 中部表格区 — 19 个尽调填空题（纯文本输入，可为空）
  3. 底部按钮区 ——「获取同行数据」「清空全部」「开始分析」

数据流：
  用户填尽调信息 → 点击「获取同行数据」→ 
  (1) 用细分赛道/主营业务作为关键词调用同行业搜索，获取5-8家对标上市公司
  (2) 用对标公司代码调用 fin_calc.fetch_industry_benchmarks 获取财务指标
  (3) 将尽调+同行数据拼接成自然语言上下文，实时显示在预览区
  (4) 用户确认后点「开始分析」→ 发送完整 prompt 给 OpenClaw
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import logging
import os
import shutil
import subprocess
import textwrap

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea,
    QDialog, QTextEdit, QDialogButtonBox, QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from theme import (
    BG2, CARD, CARD2,
    ACCENT, ACCENT_H,
    FG, FG2, FG3,
    BORDER,
    INPUT_BG, INPUT_BD,
)

OPENCLAW_BIN = shutil.which("openclaw") or "openclaw"

# ═══════════════════════════════════════════════════════════════
# 尽调填空题字段定义（全部 text/填空，无下拉，可为空）
# ═══════════════════════════════════════════════════════════════

DD_FIELDS = [
    # ── 公司基本面 ──────────────────────────────────────────
    {
        "section": "公司基本面",
        "key": "dd_company_name",
        "label": "公司名称（可匿名）",
        "placeholder": "如：A公司 / 匿名，不影响分析准确性",
    },
    {
        "key": "dd_biz_desc",
        "label": "主营业务（一句话）",
        "placeholder": "如：车规级MCU芯片设计",
    },
    {
        "key": "dd_biz_model",
        "label": "业务模式",
        "placeholder": "如：Fabless设计、IDM制造、封测、纯软件/SaaS、硬件销售、系统集成",
    },
    {
        "key": "dd_stage",
        "label": "当前阶段",
        "placeholder": "如：研发期（无收入）、送样/试用、小批量出货、规模量产、成熟稳定",
    },
    {
        "key": "dd_sub_sector",
        "label": "细分赛道",
        "placeholder": "越精确越好，如 SiC衬底 而非 半导体",
    },
    {
        "key": "dd_founded_year",
        "label": "成立年份",
        "placeholder": "如 2018",
    },
    {
        "key": "dd_headcount",
        "label": "员工人数",
        "placeholder": "约多少人",
    },
    # ── 客户与供应链 ────────────────────────────────────────
    {
        "section": "客户与供应链",
        "key": "dd_top5_customer_pct",
        "label": "前五大客户占营收比重",
        "placeholder": "如 60%，未知填「未知」",
    },
    {
        "key": "dd_single_customer_40",
        "label": "单一客户依赖（第一大>40%）",
        "placeholder": "如：是、否、未知",
    },
    {
        "key": "dd_top5_supplier_pct",
        "label": "前五大供应商占采购比重",
        "placeholder": "如 55%，未知填「未知」",
    },
    # ── 融资与治理 ──────────────────────────────────────────
    {
        "section": "融资与治理",
        "key": "dd_latest_round",
        "label": "最新融资轮次",
        "placeholder": "如：天使、A、B、C及以后、Pre-IPO、未知",
    },
    {
        "key": "dd_latest_valuation",
        "label": "最新投后估值（万元）",
        "placeholder": "未知填「未披露」",
    },
    {
        "key": "dd_special_terms",
        "label": "特殊条款",
        "placeholder": "如：对赌、回购权、优先清算权、一票否决、无、未知（可多填）",
    },
    {
        "key": "dd_audit_opinion",
        "label": "审计意见",
        "placeholder": "如：标准无保留、带强调事项段、保留意见、无法表示意见、未经审计",
    },
    # ── 已暴露问题 ──────────────────────────────────────────
    {
        "section": "已暴露问题",
        "key": "dd_related_party",
        "label": "大额关联交易/资金占用",
        "placeholder": "如：是（金额xxx万）、否、未知",
    },
    {
        "key": "dd_litigation",
        "label": "未决诉讼或重大担保",
        "placeholder": "如：是、否、未知",
    },
    {
        "key": "dd_other_receivable",
        "label": "大额其他应收款（>总资产5%）",
        "placeholder": "如：是、否、未知",
    },
    {
        "key": "dd_key_person_left",
        "label": "近一年核心管理层/技术负责人离职",
        "placeholder": "如：是（几人）、否、未知",
    },
    # ── 补充备注 ────────────────────────────────────────────
    {
        "section": "补充备注",
        "key": "dd_notes",
        "label": "其他重要信息",
        "placeholder": "自由填写，如竞品替代风险、下游景气度、补贴退坡等",
    },
]


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _openclaw_available() -> bool:
    """检测本地是否安装了 openclaw 且 gateway 在运行。"""
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


def _find_skill_text(skill_name: str) -> str:
    """
    在多个候选路径中自动搜索 <skill_name>/SKILL.md，
    找到第一个可读的就返回完整内容，找不到返回空字符串。
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
            logging.getLogger("stockreporter.dd_form_panel").info(
                "%s SKILL 已从 %s 加载", skill_name, base)
            return "\n\n---\n\n".join(parts)
    logging.getLogger("stockreporter.dd_form_panel").warning(
        "%s SKILL 未找到，将跳过框架注入", skill_name)
    return ""


# ═══════════════════════════════════════════════════════════════
# OpenClaw 后台工作线程
# ═══════════════════════════════════════════════════════════════

def _clean_model_output(text: str) -> str:
    """
    修复某些模型（如 MiniMax-M2.7）输出的"每词一行"格式问题。
    检测特征：连续多行每行只有 1-3 个 token（单词/标点），
    且不含 Markdown 结构（#/- 开头）。
    若检测到此特征，则将这些行合并为正常段落。
    """
    import re
    if not text:
        return text

    lines = text.split('\n')
    if len(lines) < 10:
        return text  # 行数少，不处理

    # 检测是否为"每词一行"格式：
    # 取前 30 行，若超过 70% 的行长度 <= 15 且不以 # / - / > 开头，则认为是碎片化输出
    sample = lines[:min(30, len(lines))]
    short_lines = sum(
        1 for l in sample
        if len(l.strip()) <= 15 and not re.match(r'^[#\-\*>|]', l.strip())
    )
    if short_lines / len(sample) < 0.6:
        return text  # 不是碎片化格式，原样返回

    # 合并逻辑：
    # - 空行 → 段落分隔符
    # - Markdown 标题/列表行 → 保留换行
    # - 其他短行 → 用空格拼接
    result_parts = []
    current_chunk = []

    def flush_chunk():
        if current_chunk:
            result_parts.append(' '.join(current_chunk))
            current_chunk.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_chunk()
            result_parts.append('')
        elif re.match(r'^#{1,6}\s', stripped) or re.match(r'^[-\*]\s', stripped) or re.match(r'^\d+\.\s', stripped) or re.match(r'^[>\|]', stripped):
            # Markdown 结构行，保留
            flush_chunk()
            result_parts.append(stripped)
        else:
            current_chunk.append(stripped)

    flush_chunk()

    # 清理多余空行
    cleaned = '\n'.join(result_parts)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


class _OpenClawWorker(QThread):
    """后台调用 openclaw agent，流式返回进度，最终返回完整结果"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
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
            self.progress.emit("🧠 OpenClaw 正在深度分析，请稍候（最长 5 分钟）…")
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=320
            )
            if result.returncode != 0:
                self.error.emit(f"OpenClaw 返回错误：{result.stderr[:400]}")
                return

            raw = result.stdout.strip()
            brace = raw.find('{')
            if brace > 0:
                raw = raw[brace:]
            data = json.loads(raw)

            payloads = (
                data.get("result", {}).get("payloads", [])
                or data.get("payloads", [])
            )
            texts = []
            for p in payloads:
                if isinstance(p, dict) and p.get("text"):
                    texts.append(_clean_model_output(p["text"]))
                elif isinstance(p, str):
                    texts.append(_clean_model_output(p))

            if not texts:
                texts = [_clean_model_output(data.get("summary", "") or raw[:2000])]

            self.finished.emit("\n\n".join(texts))

        except subprocess.TimeoutExpired:
            self.error.emit("OpenClaw 分析超时（>5 分钟），请稍后重试")
        except json.JSONDecodeError as e:
            self.finished.emit(result.stdout[:8000] if 'result' in dir() else str(e))
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════
# OpenClaw 结果展示对话框
# ═══════════════════════════════════════════════════════════════

class _OpenClawResultDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🦞 OpenClaw 财务风险因子识别")
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

        hdr = QHBoxLayout()
        title = QLabel("🦞  OpenClaw 财务风险因子识别报告")
        title.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#4f8ef7;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._copy_btn = QPushButton("复制全文")
        self._copy_btn.clicked.connect(self._copy_all)
        hdr.addWidget(self._copy_btn)
        lay.addLayout(hdr)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        lay.addWidget(self._progress)

        self._status = QLabel("正在连接 OpenClaw…")
        lay.addWidget(self._status)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlaceholderText("分析结果将在此显示…")
        lay.addWidget(self._text, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet("QDialogButtonBox QPushButton{min-width:80px;}")
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


# ═══════════════════════════════════════════════════════════════
# 工具函数：渲染 Section 标题
# ═══════════════════════════════════════════════════════════════

def _section_hdr(text: str, color: str = ACCENT) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
    lbl.setStyleSheet(
        f"color:{color};background:transparent;border:none;"
        f"padding:6px 0 2px 0;"
    )
    return lbl


# ═══════════════════════════════════════════════════════════════
# 主面板
# ═══════════════════════════════════════════════════════════════

class DueDiligenceFormPanel(QWidget):
    """尽调信息填空题 — 独立 Tab 页，含上下文预览 + 同行数据自动获取"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG2};")
        self._dd_widgets: dict[str, QLineEdit] = {}
        self._peer_data: dict | None = None     # 缓存的同行数据 {peers, benchmarks, keyword}
        self._fin_calc_data: dict | None = None # 从 FinCalcPanel 注入的财务计算结果
        self._last_prompt_text: str = ""        # 最近一次构建的完整 prompt
        self._peer_keyword: str = ""            # 本次同行搜索使用的关键词
        self._setup_ui()

    def set_fin_calc_data(self, data: dict | None):
        """从 FinCalcPanel 注入财务计算结果，自动刷新上下文预览"""
        self._fin_calc_data = data
        self._refresh_preview()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部标题栏 ──────────────────────────────────────
        header = QWidget()
        header.setStyleSheet(f"background:{CARD2};border-bottom:1px solid {BORDER};")
        hdr_lay = QVBoxLayout(header)
        hdr_lay.setContentsMargins(24, 16, 24, 12)
        hdr_lay.setSpacing(4)

        title = QLabel("财务风险因子识别")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        hdr_lay.addWidget(title)

        subtitle = QLabel("填写业务信息 → 获取同行数据 → 预览分析上下文 → 开始分析")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        subtitle.setWordWrap(True)
        hdr_lay.addWidget(subtitle)

        root.addWidget(header)

        # ── 分析上下文预览区 ────────────────────────────────
        preview_sec = QWidget()
        preview_sec.setStyleSheet(f"background:{CARD2};border-bottom:1px solid {BORDER};")
        preview_lay = QVBoxLayout(preview_sec)
        preview_lay.setContentsMargins(24, 12, 24, 10)
        preview_lay.setSpacing(6)

        preview_hdr = QHBoxLayout()
        preview_title_lbl = QLabel("📋 分析上下文预览")
        preview_title_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        preview_title_lbl.setStyleSheet(f"color:#a855f7;background:transparent;border:none;")
        preview_hdr.addWidget(preview_title_lbl)
        preview_hdr.addStretch()

        self._preview_status = QLabel("（尚未构建）")
        self._preview_status.setFont(QFont("Arial", 9))
        self._preview_status.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        preview_hdr.addWidget(self._preview_status)
        preview_lay.addLayout(preview_hdr)

        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setPlaceholderText(
            "填写业务信息并点击「获取同行数据」后，此处将显示完整的分析上下文…"
        )
        self._preview_text.setMaximumHeight(180)
        self._preview_text.setFont(QFont("Menlo", 10))
        self._preview_text.setStyleSheet(
            f"QTextEdit{{background:{BG2};color:{FG2};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"padding:8px;line-height:1.4;}}"
        )
        preview_lay.addWidget(self._preview_text)

        copy_btn_row = QHBoxLayout()
        copy_btn_row.addStretch()
        self._copy_preview_btn = QPushButton("复制上下文")
        self._copy_preview_btn.setFixedHeight(26)
        self._copy_preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_preview_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{FG2};"
            f"border:1px solid {BORDER};border-radius:6px;font-size:10px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
        )
        self._copy_preview_btn.clicked.connect(self._copy_preview)
        copy_btn_row.addWidget(self._copy_preview_btn)
        preview_lay.addLayout(copy_btn_row)

        root.addWidget(preview_sec)

        # ── 表单滚动区 ──────────────────────────────────────
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_scroll.setStyleSheet(
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QScrollBar:vertical{{background:{CARD2};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;min-height:24px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        form_w = QWidget()
        form_w.setStyleSheet("background:transparent;")
        form_lay = QVBoxLayout(form_w)
        form_lay.setContentsMargins(24, 16, 24, 16)
        form_lay.setSpacing(6)

        self._dd_widgets = {}

        current_section = None
        for f_def in DD_FIELDS:
            # Section 标题
            if "section" in f_def and f_def["section"] != current_section:
                current_section = f_def["section"]
                form_lay.addWidget(_section_hdr(current_section, "#a855f7"))

            key = f_def["key"]
            label = f_def["label"]

            lbl = QLabel(label)
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            form_lay.addWidget(lbl)

            inp = QLineEdit()
            inp.setPlaceholderText(f_def.get("placeholder", ""))
            inp.setFixedHeight(30)
            inp.setFont(QFont("Arial", 10))
            inp.setStyleSheet(
                f"QLineEdit{{background:{INPUT_BG};border:1px solid {INPUT_BD};"
                f"border-radius:6px;color:{FG};padding:0 10px;}}"
                f"QLineEdit:focus{{border-color:#a855f7;}}"
            )
            # 所有字段输入变化时刷新上下文预览
            inp.textChanged.connect(lambda k=key: self._on_any_field_changed(k))
            # 细分赛道/主营业务修改时，额外标记同行数据过期
            if key in ("dd_sub_sector", "dd_biz_desc"):
                inp.textChanged.connect(self._on_key_field_changed)
            form_lay.addWidget(inp)
            self._dd_widgets[key] = inp

        form_lay.addStretch()
        form_scroll.setWidget(form_w)
        root.addWidget(form_scroll, 1)

        # ── 底部按钮栏 ──────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background:{CARD2};border-top:1px solid {BORDER};")
        btn_lay = QHBoxLayout(btn_bar)
        btn_lay.setContentsMargins(24, 12, 24, 12)
        btn_lay.setSpacing(10)

        self._peer_btn = QPushButton("获取同行数据")
        self._peer_btn.setFixedHeight(34)
        self._peer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._peer_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:#a855f7;"
            f"border:1px solid #a855f7;border-radius:8px;font-size:11px;}}"
            f"QPushButton:hover{{background:rgba(168,85,247,0.1);}}"
        )
        self._peer_btn.clicked.connect(self._fetch_peer_data)
        btn_lay.addWidget(self._peer_btn)

        self._peer_status = QLabel("")
        self._peer_status.setFont(QFont("Arial", 9))
        self._peer_status.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
        btn_lay.addWidget(self._peer_status, 1)

        self._clear_btn = QPushButton("清空全部")
        self._clear_btn.setFixedHeight(34)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{FG2};"
            f"border:1px solid {BORDER};border-radius:8px;font-size:11px;}}"
            f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
        )
        self._clear_btn.clicked.connect(self._clear_all)
        btn_lay.addWidget(self._clear_btn)

        self._analyze_btn = QPushButton("开始分析")
        self._analyze_btn.setFixedHeight(34)
        self._analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._analyze_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #a855f7,stop:1 #7c3aed);"
            "color:white;border:none;border-radius:8px;"
            "font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:#7c3aed;}}"
        )
        self._analyze_btn.clicked.connect(self._do_analyze)
        btn_lay.addWidget(self._analyze_btn, 1)

        root.addWidget(btn_bar)

        # ── 初始化默认上下文预览 ──────────────────────────
        self._refresh_preview()

    # ── 字段变化回调 ───────────────────────────────────────

    def _on_any_field_changed(self, key: str):
        """任意字段输入变化时，实时刷新上下文预览"""
        self._refresh_preview()

    def _on_key_field_changed(self):
        """细分赛道/主营业务变化时标记同行数据过期"""
        if self._peer_data is not None:
            self._peer_data = None
            self._peer_keyword = ""
            self._peer_status.setText("")
            self._preview_status.setText("（同行数据已过期，请重新获取）")
            self._preview_status.setStyleSheet(
                f"color:#f59e0b;background:transparent;border:none;font-size:9px;"
            )
            self._refresh_preview()

    # ── 数据收集 ─────────────────────────────────────────────

    def _collect_dd_data(self) -> dict:
        """收集尽调字段值，返回 {key: value_str, ...}（仅收集非空字段）"""
        result = {}
        for f_def in DD_FIELDS:
            key = f_def["key"]
            w = self._dd_widgets.get(key)
            if w is None:
                continue
            val = w.text().strip()
            if val:
                result[key] = val
        return result

    # ── 获取同行数据 ────────────────────────────────────────

    def _get_search_keyword(self) -> str:
        """从已填字段中智能构造搜索关键词"""
        dd = self._collect_dd_data()
        parts = []
        if "dd_sub_sector" in dd:
            parts.append(dd["dd_sub_sector"])
        if "dd_biz_desc" in dd:
            parts.append(dd["dd_biz_desc"])
        if "dd_biz_model" in dd:
            parts.append(dd["dd_biz_model"])
        if not parts:
            if "dd_company_name" in dd:
                parts.append(dd["dd_company_name"])
        return " ".join(parts) if parts else ""

    def _fetch_peer_data(self):
        """触发同行数据获取——搜索 + 拉取上市公司财务指标"""
        keyword = self._get_search_keyword()
        if not keyword:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "提示",
                "请先填写「主营业务」「细分赛道」或「公司名称」中至少一项，以便搜索同行业上市公司。"
            )
            return

        self._peer_btn.setEnabled(False)
        self._peer_status.setText("⏳ 正在搜索同行业公司…")
        self._peer_status.setStyleSheet(
            f"color:{ACCENT};background:transparent;border:none;font-size:9px;"
        )

        self._peer_worker = _PeerDataWorker(keyword)
        self._peer_worker.progress.connect(lambda msg: self._peer_status.setText(msg))
        self._peer_worker.finished.connect(self._on_peer_data_ready)
        self._peer_worker.error.connect(lambda e: self._peer_status.setText(f"❌ {e}"))
        self._peer_worker.start()

    def _on_peer_data_ready(self, result: dict):
        """同行数据获取完成"""
        self._peer_btn.setEnabled(True)
        if result.get("error"):
            self._peer_status.setText(f"⚠️ {result['error']}")
            self._peer_status.setStyleSheet(
                f"color:#f59e0b;background:transparent;border:none;font-size:9px;"
            )
            self._peer_data = None
            return

        self._peer_data = result
        self._peer_keyword = result.get("keyword", "")
        peers = result.get("peers", [])
        self._peer_status.setText(f"✅ 已获取 {len(peers)} 家对标公司数据")
        self._peer_status.setStyleSheet(
            f"color:#22c55e;background:transparent;border:none;font-size:9px;"
        )
        self._refresh_preview()

    # ── 上下文预览 ───────────────────────────────────────────

    @staticmethod
    def _slot(val: str) -> str:
        """填值或占位符：有值绿色高亮，无值灰色下划线"""
        if val:
            return f'<span style="color:#22c55e;font-weight:bold">{val}</span>'
        return '<span style="color:#6b7280;text-decoration:underline">___</span>'

    def _build_context_html(self) -> str:
        """
        构建完形填空式上下文 HTML —— 用户一眼看到 prompt 的完整框架。
        已填的槽显示为绿色文字，未填的显示为灰色 ___ 下划线。
        """
        dd = self._collect_dd_data()

        s = self._slot  # 简写

        # ── 财务指标部分（来自 FinCalcPanel）───────────────
        fin_html = ""
        if self._fin_calc_data:
            metrics = self._fin_calc_data.get("metrics", {})
            analysis = self._fin_calc_data.get("analysis", {})
            inputs = self._fin_calc_data.get("inputs", {})
            if metrics:
                fin_items = []
                # 精选关键指标展示
                key_metrics = [
                    ("revenue", "营收"), ("revenue_yoy", "营收增速"),
                    ("net_profit", "净利润"), ("net_margin", "净利率"),
                    ("gross_margin", "毛利率"), ("roe", "ROE"),
                    ("total_assets", "总资产"), ("total_liabilities", "总负债"),
                    ("debt_ratio", "资产负债率"), ("current_ratio", "流动比率"),
                    ("quick_ratio", "速动比率"),
                ]
                for mk, ml in key_metrics:
                    mv = metrics.get(mk)
                    if mv is not None:
                        # 带百分号的指标
                        if mk in ("revenue_yoy", "net_margin", "gross_margin", "roe", "debt_ratio"):
                            fin_items.append(f"{ml}={mv}%")
                        elif isinstance(mv, float):
                            fin_items.append(f"{ml}={mv:.2f}")
                        else:
                            fin_items.append(f"{ml}={mv}")
                if fin_items:
                    fin_html = "，".join(fin_items)
                    fin_html = f'<span style="color:#22c55e;font-weight:bold">{fin_html}</span>'
                else:
                    fin_html = '<span style="color:#4b5563;font-size:10px">（财务计算器已有数据，但未提取到指标）</span>'
            else:
                fin_html = '<span style="color:#4b5563;font-size:10px">（财务计算器已有数据，但未提取到指标）</span>'
        else:
            fin_html = self._slot("")
            fin_html += ' <span style="color:#4b5563;font-size:10px">← 请先在「财务计算器」中填写并计算</span>'

        # ── 同行数据部分 ────────────────────────────────────
        peer_html = ""
        if self._peer_data and self._peer_data.get("peers"):
            peers = self._peer_data["peers"]
            benchmarks = self._peer_data.get("benchmarks", {})
            # 关键指标展示顺序（label: key）
            _BENCH_LABELS = [
                ("营收(亿)", "revenue"), ("营收增速", "revenue_yoy"),
                ("净利润(亿)", "net_profit"), ("净利率", "net_margin"),
                ("毛利率", "gross_margin"), ("ROE", "roe"),
                ("资产负债率", "debt_ratio"), ("流动比率", "current_ratio"),
                ("速动比率", "quick_ratio"), ("PE", "pe"),
                ("总资产(亿)", "total_assets"),
            ]
            _PCT_KEYS = {"revenue_yoy", "net_margin", "gross_margin", "roe", "debt_ratio"}
            peer_rows = []
            for p in peers:
                code = p.get("code", "")
                b = benchmarks.get(code, {})
                bp = []
                for bl, bk in _BENCH_LABELS:
                    bv = b.get(bk)
                    if bv is not None:
                        suffix = "%" if bk in _PCT_KEYS else ""
                        if isinstance(bv, float):
                            bp.append(f"{bl}={bv:.1f}{suffix}")
                        else:
                            bp.append(f"{bl}={bv}{suffix}")
                b_str = f'<span style="color:#9ca3af;font-size:10px">（{"，".join(bp)}）</span>' if bp else ""
                peer_rows.append(
                    f'<span style="color:#22c55e">{p["name"]}({code} {p.get("market","")})</span>{b_str}'
                )
            peer_html = "<br>".join(peer_rows)
        else:
            peer_html = self._slot("")
            peer_html += ' <span style="color:#4b5563;font-size:10px">← 点击「获取同行数据」自动填入</span>'

        html = (
            f'<p style="line-height:1.8;margin:0;">'
            f'我的一家'
            f'{s(dd.get("dd_stage", ""))}'
            f'公司「'
            f'{s(dd.get("dd_company_name", ""))}'
            f'」'
            f'，成立于'
            f'{s(dd.get("dd_founded_year", ""))}'
            f'年，约有'
            f'{s(dd.get("dd_headcount", ""))}'
            f'人。'
            f'行业为'
            f'{s(dd.get("dd_sub_sector", "") or dd.get("dd_biz_model", ""))}'
            f'，主要业务是'
            f'{s(dd.get("dd_biz_desc", ""))}'
            f'，业务模式为'
            f'{s(dd.get("dd_biz_model", ""))}'
            f'。</p>'
            f'<p style="line-height:1.8;margin:4px 0;">'
            f'客户供应链方面：'
            f'前五大客户占营收'
            f'{s(dd.get("dd_top5_customer_pct", ""))}'
            f'，单一客户是否超40%：'
            f'{s(dd.get("dd_single_customer_40", ""))}'
            f'，前五大供应商占采购'
            f'{s(dd.get("dd_top5_supplier_pct", ""))}'
            f'。</p>'
            f'<p style="line-height:1.8;margin:4px 0;">'
            f'融资与治理方面：'
            f'融资轮次'
            f'{s(dd.get("dd_latest_round", ""))}'
            f'，投后估值'
            f'{s(dd.get("dd_latest_valuation", ""))}'
            f'万元，特殊条款：'
            f'{s(dd.get("dd_special_terms", ""))}'
            f'，审计意见：'
            f'{s(dd.get("dd_audit_opinion", ""))}'
            f'。</p>'
            f'<p style="line-height:1.8;margin:4px 0;">'
            f'已暴露问题：'
            f'关联交易/资金占用：'
            f'{s(dd.get("dd_related_party", ""))}'
            f'，未决诉讼：'
            f'{s(dd.get("dd_litigation", ""))}'
            f'，大额其他应收款：'
            f'{s(dd.get("dd_other_receivable", ""))}'
            f'，核心人员流失：'
            f'{s(dd.get("dd_key_person_left", ""))}'
            f'。</p>'
            f'<p style="line-height:1.8;margin:4px 0;">'
            f'其他信息：'
            f'{s(dd.get("dd_notes", ""))}'
            f'。</p>'
            f'<p style="line-height:1.8;margin:8px 0;">'
            f'<span style="color:#60a5fa;">━━━ 目标公司财务指标（来自财务计算器）━━━</span><br>'
            f'{fin_html}'
            f'</p>'
            f'<p style="line-height:1.8;margin:8px 0;">'
            f'<span style="color:#a78bfa;">━━━ 同行业上市公司对标数据 ━━━</span><br>'
            f'{peer_html}'
            f'</p>'
            f'<p style="line-height:1.8;margin:8px 0;color:#fbbf24;">'
            f'【分析任务】根据以上业务信息、财务指标和同行对比数据，'
            f'深度挖掘该目标公司潜在的财务风险因子，'
            f'请逐项披露相关财务风险（如收入质量、盈利可持续性、'
            f'偿债压力、现金流异常、关联交易、估值泡沫等），'
            f'并结合同行对标数据说明风险的相对严重程度。'
            f'</p>'
        )
        return html

    def _build_context_plain(self) -> str:
        """
        构建纯文本上下文（用于发给 OpenClaw 的 prompt）。
        填了的值直接用，没填的用「[未填写]」标注。
        """
        dd = self._collect_dd_data()

        def v(key, label=""):
            val = dd.get(key, "")
            return val if val else "[未填写]"

        lines = []
        lines.append(
            f'我的一家{v("dd_stage")}公司「{v("dd_company_name")}」，'
            f'成立于{v("dd_founded_year")}年，约有{v("dd_headcount")}人。'
            f'行业为{v("dd_sub_sector") or v("dd_biz_model")}，'
            f'主要业务是{v("dd_biz_desc")}，业务模式为{v("dd_biz_model")}。'
        )
        lines.append(
            f'客户供应链方面：前五大客户占营收{v("dd_top5_customer_pct")}，'
            f'单一客户是否超40%：{v("dd_single_customer_40")}，'
            f'前五大供应商占采购{v("dd_top5_supplier_pct")}。'
        )
        lines.append(
            f'融资与治理方面：融资轮次{v("dd_latest_round")}，'
            f'投后估值{v("dd_latest_valuation")}万元，'
            f'特殊条款：{v("dd_special_terms")}，审计意见：{v("dd_audit_opinion")}。'
        )
        lines.append(
            f'已暴露问题：关联交易/资金占用：{v("dd_related_party")}，'
            f'未决诉讼：{v("dd_litigation")}，'
            f'大额其他应收款：{v("dd_other_receivable")}，'
            f'核心人员流失：{v("dd_key_person_left")}。'
        )
        lines.append(f'其他信息：{v("dd_notes")}。')

        # ── 财务指标（来自 FinCalcPanel）───────────────
        if self._fin_calc_data:
            metrics = self._fin_calc_data.get("metrics", {})
            if metrics:
                key_metrics = [
                    ("revenue", "营收"), ("revenue_yoy", "营收增速"),
                    ("net_profit", "净利润"), ("net_margin", "净利率"),
                    ("gross_margin", "毛利率"), ("roe", "ROE"),
                    ("total_assets", "总资产"), ("total_liabilities", "总负债"),
                    ("debt_ratio", "资产负债率"), ("current_ratio", "流动比率"),
                    ("quick_ratio", "速动比率"),
                ]
                fin_items = []
                for mk, ml in key_metrics:
                    mv = metrics.get(mk)
                    if mv is not None:
                        if mk in ("revenue_yoy", "net_margin", "gross_margin", "roe", "debt_ratio"):
                            fin_items.append(f"{ml}={mv}%")
                        elif isinstance(mv, float):
                            fin_items.append(f"{ml}={mv:.2f}")
                        else:
                            fin_items.append(f"{ml}={mv}")
                if fin_items:
                    lines.append(f'\n目标公司财务指标（来自财务计算器）：{"，".join(fin_items)}')
                else:
                    lines.append('\n目标公司财务指标：[财务计算器已有数据，但未提取到指标]')
            else:
                lines.append('\n目标公司财务指标：[财务计算器已有数据，但未提取到指标]')
        else:
            lines.append('\n目标公司财务指标：[未计算，请先在「财务计算器」中填写并计算]')

        if self._peer_data and self._peer_data.get("peers"):
            peers = self._peer_data["peers"]
            benchmarks = self._peer_data.get("benchmarks", {})
            _BENCH_LABELS = [
                ("营收(亿)", "revenue"), ("营收增速", "revenue_yoy"),
                ("净利润(亿)", "net_profit"), ("净利率", "net_margin"),
                ("毛利率", "gross_margin"), ("ROE", "roe"),
                ("资产负债率", "debt_ratio"), ("流动比率", "current_ratio"),
                ("速动比率", "quick_ratio"), ("PE", "pe"),
                ("总资产(亿)", "total_assets"),
            ]
            _PCT_KEYS = {"revenue_yoy", "net_margin", "gross_margin", "roe", "debt_ratio"}
            peer_items = []
            for p in peers:
                code = p.get("code", "")
                b = benchmarks.get(code, {})
                bp = []
                for bl, bk in _BENCH_LABELS:
                    bv = b.get(bk)
                    if bv is not None:
                        suffix = "%" if bk in _PCT_KEYS else ""
                        if isinstance(bv, float):
                            bp.append(f"{bl}={bv:.1f}{suffix}")
                        else:
                            bp.append(f"{bl}={bv}{suffix}")
                b_str = f"（{'，'.join(bp)}）" if bp else ""
                peer_items.append(f'{p["name"]}({code} {p.get("market","")}){b_str}')
            lines.append(
                f'\n同行业上市公司对标数据（共{len(peers)}家）：\n'
                + '\n'.join(f'  · {item}' for item in peer_items)
            )
        else:
            lines.append('\n同行业上市公司对标数据：[未获取，请点击「获取同行数据」]')

        lines.append(
            '\n【分析任务】根据以上业务信息、财务指标和同行对比数据，'
            '深度挖掘该目标公司潜在的财务风险因子，'
            '请逐项披露相关财务风险（如收入质量、盈利可持续性、偿债压力、'
            '现金流异常、关联交易、估值泡沫等），'
            '并结合同行对标数据说明风险的相对严重程度。'
        )

        return "\n".join(lines)

    def _refresh_preview(self):
        """刷新预览区文本（富文本 HTML 模式，完形填空效果）"""
        html = self._build_context_html()
        self._preview_text.setHtml(html)
        # 同步保存纯文本版本给 _build_prompt 使用
        self._last_prompt_text = self._build_context_plain()

        dd_count = len(self._collect_dd_data())
        peer_count = len(self._peer_data.get("peers", [])) if self._peer_data else 0
        status = f"（已填{dd_count}项尽调"
        if peer_count:
            status += f" + {peer_count}家同行"
        status += "）"
        self._preview_status.setText(status)
        self._preview_status.setStyleSheet(
            f"color:#22c55e;background:transparent;border:none;font-size:9px;"
            if dd_count or peer_count
            else f"color:{FG3};background:transparent;border:none;font-size:9px;"
        )

    def _copy_preview(self):
        """复制上下文到剪贴板"""
        from PyQt6.QtWidgets import QApplication
        text = self._preview_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    # ── 构建 Prompt ────────────────────────────────────────

    def _build_prompt(self) -> str:
        """将尽调信息组装成发给 OpenClaw 的 Prompt"""
        dd_data = self._collect_dd_data()

        lines = []

        # ── 注入 hardtech-risk-analysis SKILL ─────────────────
        skill_text = _find_skill_text("hardtech-risk-analysis")
        if skill_text:
            lines.append("# 分析框架（必须严格遵循）")
            lines.append("")
            lines.append(skill_text)
            lines.append("")
            lines.append("---")
            lines.append("")

        # ── 环境上下文（自然语言段落）───────────────────────
        lines.append("# 分析场景上下文")
        lines.append("")
        context = self._build_context_plain()
        lines.append(context)
        lines.append("")

        lines.append("---")
        lines.append("")

        lines.append("# 尽调风险分析任务")
        lines.append("")
        lines.append(
            "你是一位资深投资尽调专家和风险研究分析师。"
            + ("请严格按照上方【分析框架】的九步方法论，" if skill_text else "")
            + "请根据以上【分析场景上下文】中的所有信息，对该公司进行深度风险诊断。"
            "请重点关注：业务模式风险、客户与供应链集中度风险、"
            "融资条款陷阱、治理缺陷、已暴露的法律/经营问题，"
            "并结合同行业上市公司财务数据进行交叉验证。"
        )
        lines.append("")

        # ── 结构化尽调信息 ──────────────────────────────────
        if dd_data:
            lines.append("## 目标公司尽调信息（结构化数据）")
            lines.append("")
            current_section = None
            for f_def in DD_FIELDS:
                if "section" in f_def and f_def["section"] != current_section:
                    current_section = f_def["section"]
                    lines.append(f"### {current_section}")
                key = f_def["key"]
                if key in dd_data:
                    lines.append(f"- {f_def['label']}：{dd_data[key]}")
            lines.append("")
            lines.append("> 以上尽调信息可能不完整。如某字段未出现，表示用户未填写。")
            lines.append("")
        else:
            lines.append("> ⚠️ 用户未填写任何尽调信息。请直接给出提示并结束。")
            return "\n".join(lines)

        # ── 同行对标数据 ────────────────────────────────────
        if self._peer_data and self._peer_data.get("peers"):
            lines.append("## 同行业上市公司对标数据")
            lines.append("")
            peers = self._peer_data["peers"]
            benchmarks = self._peer_data.get("benchmarks", {})
            for p in peers:
                code = p.get("code", "")
                lines.append(
                    f"### {p['name']}（{code} {p.get('market','')}）"
                )
                lines.append(f"- 相似原因：{p.get('reason','')}")
                if code in benchmarks:
                    b = benchmarks[code]
                    for k, v in b.items():
                        lines.append(f"- {k}：{v}")
                lines.append("")
            lines.append("")

        # ── 分析要求 ─────────────────────────────────────────
        lines.append("## 分析要求")
        lines.append("")
        lines.append(textwrap.dedent("""\
            你是一位资深风险研究分析师，专注于挖掘财务数据中的隐性风险。
            请严格按以下结构输出报告，每个章节必须有实质性内容，不得泛泛而谈。

            ---

            ### 0. 【质变级异常识别】（最重要，必须首先完成）
            在开始分析前，先做"组合异常交叉验证"：
            将所有财务指标放在一起，寻找"单个指标看似合理、但组合在一起就不可能同时成立"的矛盾点。
            例如：
            - ROE 极高 + 净资产极薄 → 说明什么？（杠杆驱动还是净资产被消耗殆尽？）
            - 成立年限极短 + 已量产 + 高估值 → 三者能否同时成立？时间线是否合理？
            - 毛利率偏低 + 净利率更低 → 费用结构是否异常？研发/销售费用率是多少？
            - 高估值 + 低营收 → P/S 倍率是多少？与同行相比意味着什么？
            - 流动比率 = 速动比率 → 说明存货为零，这对制造业意味着什么？
            请列出所有你发现的"组合矛盾"，并说明每个矛盾背后最可能的解释和风险含义。
            这一节是整个报告的核心，必须深入、具体、有数字支撑。

            ### 1. 公司概览与业务风险评估
            根据主营业务、业务模式、当前阶段判断业务成熟度和内在风险。
            重点：成立时间与当前阶段是否匹配？团队规模与业务复杂度是否匹配？

            ### 2. 财务健康度深度分析
            逐项分析：收入质量（营收规模/增速/人均产出）、盈利质量（毛利率/净利率与行业对比）、
            资产负债结构（净资产规模/债务结构/偿债能力）、现金流风险（流动比率/速动比率含义）。
            必须给出与同行对标数据的具体偏离量，说明偏离是否在合理范围内。

            ### 3. 客户与供应链风险
            分析客户/供应商集中度，单一依赖风险，议价能力。
            结合行业特性判断集中度是否属于结构性问题。

            ### 4. 融资与估值风险
            计算 P/S、P/E 等估值倍率，与同行上市公司对比。
            分析当前估值是否可持续，下一轮融资需要达到什么营收规模才能支撑。
            特殊条款（对赌/回购/一票否决等）的潜在影响。

            ### 5. 信息缺口与治理风险
            明确列出哪些关键字段未填写（审计意见/关联交易/诉讼等），
            说明每个缺口对风险判断的影响，以及最坏情况假设。

            ### 6. 综合风险评级
            给出 A/B/C/D 四档综合风险评级，并用数据支撑理由。
            A=风险极低，B=风险可控，C=存在显著风险需谨慎，D=高危不建议投资。
            必须说明：是哪几个具体指标/组合异常导致了这个评级。

            ### 7. 优先级尽调清单
            按优先级（P0/P1/P2）列出具体尽调行动，每条必须说明：
            要查什么、为什么查、预期发现什么、如果发现异常意味着什么。
        """))

        return "\n".join(lines)

    # ── 执行分析 ─────────────────────────────────────────────

    def _do_analyze(self):
        """收集尽调数据 → 构建 prompt → 发 OpenClaw"""
        dd_data = self._collect_dd_data()
        if not dd_data:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "提示",
                "请至少填写一项尽调信息后再开始分析。"
            )
            return

        if not _openclaw_available():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "OpenClaw 未就绪",
                "未检测到本地 OpenClaw 或 Gateway 未运行。\n"
                "请先启动 OpenClaw Gateway：openclaw gateway start"
            )
            return

        prompt = self._build_prompt()
        dlg = _OpenClawResultDialog(self)
        dlg.show()

        self._oc_worker = _OpenClawWorker(prompt, thinking="high")
        self._oc_worker.progress.connect(dlg.set_status)
        self._oc_worker.finished.connect(dlg.set_result)
        self._oc_worker.error.connect(dlg.set_error)
        self._oc_worker.start()

    # ── 清空 ─────────────────────────────────────────────────

    def _clear_all(self):
        """清空所有尽调字段、同行数据和预览"""
        for w in self._dd_widgets.values():
            w.clear()
        self._peer_data = None
        self._fin_calc_data = None
        self._peer_keyword = ""
        self._last_prompt_text = ""
        self._preview_text.clear()
        self._preview_status.setText("（已清空）")
        self._preview_status.setStyleSheet(
            f"color:{FG3};background:transparent;border:none;font-size:9px;"
        )
        self._peer_status.setText("")


# ═══════════════════════════════════════════════════════════════
# 同行数据获取 Worker
# ═══════════════════════════════════════════════════════════════

class _PeerDataWorker(QThread):
    """后台：同行业搜索 → 获取对标公司财务指标"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)   # {peers: [...], benchmarks: {...}, keyword: str, error: str|None}
    error    = pyqtSignal(str)

    def __init__(self, keyword: str):
        super().__init__()
        self._keyword = keyword

    def run(self):
        try:
            # ── 阶段 1：同行业搜索 ─────────────────────────
            self.progress.emit("🔍 第一步：搜索同行业上市公司…")
            try:
                from llm_client import load_config, LLMClient, _repair_json
                from web_search import search_for_llm
                import re

                cfg = load_config()
                client = LLMClient(cfg)

                # 联网搜索
                web_context = search_for_llm(self._keyword)

                research_system = (
                    "你是一位专业的行业研究员。用户会输入一家公司名称或一段描述，"
                    "你需要：\n"
                    "1. 如果是公司名称，先识别这是哪家公司（包括其正式名称）\n"
                    "2. 详细描述该公司/该类公司的核心业务、细分行业\n"
                    "3. 总结其最关键的 3-5 个行业特征标签\n\n"
                    "请用中文简短回答。"
                )
                research_user = f"请分析「{self._keyword}」这家公司（或这类公司）的业务和行业特征。"
                if web_context:
                    research_user += f"\n\n参考信息：\n{web_context}"
                research = client.chat_messages([
                    {"role": "system", "content": research_system},
                    {"role": "user", "content": research_user},
                ], max_tokens=600)

                # ── 阶段 2：推荐同行业上市公司 ───────────────
                self.progress.emit("📊 第二步：匹配同行业上市公司…")
                recommend_system = (
                    "你是一位专业的股票研究员。请推荐 5-8 家最相似的全球上市公司。\n"
                    "严格按以下 JSON 数组格式返回：\n"
                    '[{"name":"公司名","code":"股票代码（不带后缀）","market":"市场","reason":"相似点"}]'
                )
                recommend_prompt = (
                    f"以下是对「{self._keyword}」的行业调研：\n\n{research}\n\n"
                    "请推荐最相似的上市公司列表。只返回 JSON 数组。"
                )

                # 解析函数
                def parse_peers(raw_text: str) -> list:
                    cleaned = _repair_json(raw_text.strip())
                    results = []
                    # 尝试直接 list
                    try:
                        data = json.loads(cleaned)
                        if isinstance(data, list):
                            results = [d for d in data if isinstance(d, dict) and d.get("code")]
                        elif isinstance(data, dict):
                            # 可能有 {"companies": [...]} 包装
                            for v in data.values():
                                if isinstance(v, list) and v and isinstance(v[0], dict):
                                    results = [d for d in v if d.get("code")]
                                    break
                    except json.JSONDecodeError:
                        pass
                    # 降级：正则提取 JSON 数组
                    if not results:
                        m = re.search(r'\[.*\]', cleaned, re.DOTALL)
                        if m:
                            try:
                                results = json.loads(m.group())
                                results = [d for d in results if isinstance(d, dict) and d.get("code")]
                            except json.JSONDecodeError:
                                pass
                    return results

                # 第一轮：json_mode 尝试
                raw = client.chat_messages([
                    {"role": "system", "content": recommend_system},
                    {"role": "user", "content": recommend_prompt},
                ], max_tokens=1200, json_mode=True, temperature=0.1)
                peers = parse_peers(raw)

                # 降级：去掉 json_mode，纯文本再试
                if not peers:
                    self.progress.emit("🔄 重新尝试（纯文本模式）…")
                    raw2 = client.chat_messages([
                        {"role": "system", "content": recommend_system},
                        {"role": "user", "content": recommend_prompt},
                    ], max_tokens=1200, json_mode=False, temperature=0.1)
                    peers = parse_peers(raw2)

                if not peers:
                    self.finished.emit({
                        "peers": [], "benchmarks": {},
                        "keyword": self._keyword,
                        "error": "未找到同行业上市公司（已尝试 2 轮，请检查搜索关键词或 LLM 配置）"
                    })
                    return

                # ── 阶段 3：拉取对标公司财务指标 ──────────────
                self.progress.emit(
                    f"📈 第三步：拉取 {len(peers)} 家对标公司财务数据…"
                )
                peer_codes = [p["code"] for p in peers]
                from fin_calc import fetch_industry_benchmarks
                benchmarks = fetch_industry_benchmarks(peer_codes=peer_codes)

                self.finished.emit({
                    "peers": peers,
                    "benchmarks": benchmarks,
                    "keyword": self._keyword,
                    "error": None,
                })

            except Exception as e:
                self.finished.emit({
                    "peers": [], "benchmarks": {},
                    "keyword": self._keyword,
                    "error": str(e)
                })

        except Exception as e:
            self.error.emit(str(e))
