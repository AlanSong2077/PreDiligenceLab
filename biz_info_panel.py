"""
biz_info_panel.py — 工商信息尽调面板
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  - 企业名称搜索 → 工商基本信息
  - 失信被执行人查询
  - 裁判文书列表
  - 专利统计
  - 自动风险标记
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QScrollArea, QGridLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtCore import QUrl

from theme import (
    BG2, CARD, CARD2, CARD3,
    ACCENT, ACCENT_H, ACCENT_D,
    SUCCESS, WARN, ERR,
    FG, FG2, FG3,
    BORDER, BORDER2,
    INPUT_BG, INPUT_BD,
)


# ─────────────────────────────────────────────────────────────
# 颜色常量
# ─────────────────────────────────────────────────────────────
_GREEN  = SUCCESS
_ORANGE = WARN
_RED    = ERR


# ─────────────────────────────────────────────────────────────
# 后台查询 Worker
# ─────────────────────────────────────────────────────────────

class _BizWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, company_name: str):
        super().__init__()
        self._name = company_name

    def run(self):
        try:
            from biz_lookup import full_due_diligence
            result = full_due_diligence(self._name, timeout=25)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────
# 小工具：信息行 / 区块标题 / 风险徽章
# ─────────────────────────────────────────────────────────────

def _section_header(title: str, color: str = ACCENT) -> QWidget:
    w = QWidget()
    w.setStyleSheet(f"background:{CARD2};border-radius:6px;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(12, 6, 12, 6)
    dot = QLabel("◆")
    dot.setFont(QFont("Arial", 9))
    dot.setStyleSheet(f"color:{color};background:transparent;border:none;")
    lay.addWidget(dot)
    lbl = QLabel(title)
    lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color:{color};background:transparent;border:none;")
    lay.addWidget(lbl)
    lay.addStretch()
    return w


def _kv_row(key: str, value: str, value_color: str = FG) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(4, 2, 4, 2)
    lay.setSpacing(8)
    k = QLabel(key)
    k.setFixedWidth(90)
    k.setFont(QFont("Arial", 10))
    k.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
    k.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    v = QLabel(value or "—")
    v.setFont(QFont("Arial", 10))
    v.setStyleSheet(f"color:{value_color};background:transparent;border:none;")
    v.setWordWrap(True)
    lay.addWidget(k)
    lay.addWidget(v, 1)
    return w


def _risk_badge(text: str, level: str = "warn") -> QLabel:
    color = {"warn": _ORANGE, "error": _RED, "ok": _GREEN}.get(level, _ORANGE)
    lbl = QLabel(text)
    lbl.setFont(QFont("Arial", 9, QFont.Weight.Bold))
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color:{color};"
        f"background:rgba(0,0,0,0.25);"
        f"border:1px solid {color};"
        f"border-radius:5px;padding:3px 8px;"
    )
    return lbl


def _card_frame() -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:{CARD};border:1px solid {BORDER};"
        f"border-radius:10px;}}"
    )
    return f


# ─────────────────────────────────────────────────────────────
# 主面板
# ─────────────────────────────────────────────────────────────

class BizInfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    # ── 构建 UI ──────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部搜索栏
        root.addWidget(self._build_search_bar())

        # 内容滚动区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            f"QScrollBar:vertical{{background:{CARD2};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;min-height:24px;}}"
            f"QScrollBar::handle:vertical:hover{{background:{ACCENT};}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
        )
        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 12, 0, 24)
        self._content_lay.setSpacing(12)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

        # 初始空状态
        self._show_empty_state()

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background:{CARD2};border-bottom:1px solid {BORDER};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        title = QLabel("工商信息尽调")
        title.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        lay.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{BORDER};background:{BORDER};")
        sep.setFixedWidth(1)
        lay.addWidget(sep)

        self._inp = QLineEdit()
        self._inp.setPlaceholderText("输入企业全称或关键词，如：北京寒武纪科技股份有限公司")
        self._inp.setFixedHeight(34)
        self._inp.setFont(QFont("Arial", 11))
        self._inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};border:1.5px solid {INPUT_BD};"
            f"border-radius:8px;color:{FG};padding:0 12px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};}}"
        )
        self._inp.returnPressed.connect(self._do_search)
        lay.addWidget(self._inp, 1)

        self._btn = QPushButton("尽调查询")
        self._btn.setFixedSize(88, 34)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {ACCENT},stop:1 {ACCENT_H});"
            f"color:white;border:none;border-radius:8px;"
            f"font-size:11px;font-weight:600;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:disabled{{background:{CARD2};color:{FG3};}}"
        )
        self._btn.clicked.connect(self._do_search)
        lay.addWidget(self._btn)

        return bar

    # ── 空状态 ───────────────────────────────────────────────

    def _show_empty_state(self):
        self._clear_content()
        hint = QLabel("输入企业名称，查询工商注册、失信记录、裁判文书、专利信息")
        hint.setFont(QFont("Arial", 11))
        hint.setStyleSheet(f"color:{FG3};background:transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        self._content_lay.addWidget(hint)
        self._content_lay.addStretch()

    def _show_loading(self, name: str):
        self._clear_content()
        lbl = QLabel(f"正在查询「{name}」，请稍候...")
        lbl.setFont(QFont("Arial", 11))
        lbl.setStyleSheet(
            f"color:{ACCENT};background:rgba(79,142,247,0.08);"
            f"border:1px solid rgba(79,142,247,0.2);border-radius:8px;padding:12px 20px;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_lay.addWidget(lbl)
        self._content_lay.addStretch()

    # ── 搜索逻辑 ─────────────────────────────────────────────

    def _do_search(self):
        name = self._inp.text().strip()
        if not name:
            return
        self._btn.setEnabled(False)
        self._btn.setText("查询中...")
        self._show_loading(name)

        self._worker = _BizWorker(name)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_result(self, data: dict):
        self._btn.setEnabled(True)
        self._btn.setText("尽调查询")
        self._render(data)

    def _on_error(self, msg: str):
        self._btn.setEnabled(True)
        self._btn.setText("尽调查询")
        self._clear_content()
        err = QLabel(f"查询失败：{msg}")
        err.setFont(QFont("Arial", 10))
        err.setStyleSheet(f"color:{ERR};padding:12px;")
        err.setWordWrap(True)
        self._content_lay.addWidget(err)
        self._content_lay.addStretch()

    # ── 渲染结果 ─────────────────────────────────────────────

    def _render(self, data: dict):
        self._clear_content()
        lay = self._content_lay

        # ── 风险标记区 ────────────────────────────────────────
        flags = data.get("risk_flags", [])
        if flags:
            risk_card = _card_frame()
            risk_lay = QVBoxLayout(risk_card)
            risk_lay.setContentsMargins(14, 12, 14, 12)
            risk_lay.setSpacing(8)
            risk_lay.addWidget(_section_header("风险标记", _RED))
            for flag in flags:
                risk_lay.addWidget(_risk_badge(flag, "error"))
            lay.addWidget(risk_card)
        else:
            ok_card = _card_frame()
            ok_lay = QVBoxLayout(ok_card)
            ok_lay.setContentsMargins(14, 10, 14, 10)
            ok_lbl = QLabel("未发现明显风险标记")
            ok_lbl.setFont(QFont("Arial", 10))
            ok_lbl.setStyleSheet(
                f"color:{_GREEN};background:rgba(48,209,88,0.08);"
                f"border:1px solid rgba(48,209,88,0.25);border-radius:6px;padding:6px 12px;"
            )
            ok_lay.addWidget(ok_lbl)
            lay.addWidget(ok_card)

        # ── 工商基本信息 ──────────────────────────────────────
        basic = data.get("basic", {})
        basic_card = _card_frame()
        basic_lay = QVBoxLayout(basic_card)
        basic_lay.setContentsMargins(14, 12, 14, 14)
        basic_lay.setSpacing(6)
        basic_lay.addWidget(_section_header("工商基本信息", ACCENT))

        status = basic.get("status", "")
        _ok_statuses = ("存续", "正常", "开业", "在营", "上市公司", "上市公司（港股）", "上市公司（美股）")
        status_color = _GREEN if any(s in status for s in _ok_statuses) else _RED if status else FG2

        fields = [
            ("企业名称",   basic.get("name", ""),                    FG),
            ("统一信用代码", basic.get("credit_code", ""),           FG2),
            ("股票代码",   basic.get("stock_code", ""),              FG2),
            ("上市市场",   basic.get("listing_market", ""),          FG2),
            ("上市日期",   basic.get("listing_date", ""),            FG2),
            ("法定代表人", basic.get("legal_person", ""),            FG),
            ("注册资本",   basic.get("reg_capital", ""),             FG),
            ("成立日期",   basic.get("est_date", ""),                FG2),
            ("登记状态",   status,                                    status_color),
            ("登记机关",   basic.get("reg_org", ""),                 FG2),
            ("注册地址",   basic.get("reg_address", ""),             FG2),
            ("所属行业",   basic.get("industry", ""),                FG2),
            ("员工人数",   str(basic.get("employees", "")) if basic.get("employees") else "", FG2),
            ("公司电话",   basic.get("phone", ""),                   FG3),
            ("电子邮箱",   basic.get("email", ""),                   FG3),
        ]
        for key, val, color in fields:
            if val:
                basic_lay.addWidget(_kv_row(key, val, color))

        scope = basic.get("biz_scope", "")
        if scope:
            basic_lay.addWidget(_kv_row("经营范围", scope[:200] + ("..." if len(scope) > 200 else ""), FG2))

        if not any(v for _, v, _ in fields):
            no_data = QLabel("工商信息查询失败，请检查企业名称是否准确")
            no_data.setFont(QFont("Arial", 10))
            no_data.setStyleSheet(f"color:{FG3};padding:8px;")
            basic_lay.addWidget(no_data)

        lay.addWidget(basic_card)

        # ── 失信被执行人 ──────────────────────────────────────
        dishonest = data.get("dishonest", [])
        dis_card = _card_frame()
        dis_lay = QVBoxLayout(dis_card)
        dis_lay.setContentsMargins(14, 12, 14, 14)
        dis_lay.setSpacing(6)
        count_color = _RED if dishonest else _GREEN
        dis_lay.addWidget(_section_header(
            f"失信被执行人  ({len(dishonest)} 条)", count_color))

        if dishonest:
            for item in dishonest[:10]:
                row_w = QWidget()
                row_w.setStyleSheet(
                    f"background:{CARD2};border-radius:6px;"
                )
                row_lay = QVBoxLayout(row_w)
                row_lay.setContentsMargins(10, 8, 10, 8)
                row_lay.setSpacing(3)
                name_lbl = QLabel(item.get("name", ""))
                name_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                name_lbl.setStyleSheet(f"color:{_RED};background:transparent;border:none;")
                row_lay.addWidget(name_lbl)
                for k, v in [
                    ("案号", item.get("case_code", "")),
                    ("执行法院", item.get("court", "")),
                    ("发布日期", item.get("publish_date", "")),
                    ("履行情况", item.get("reason", "")),
                ]:
                    if v:
                        row_lay.addWidget(_kv_row(k, v))
                dis_lay.addWidget(row_w)
        else:
            ok = QLabel("未查到失信被执行人记录")
            ok.setFont(QFont("Arial", 10))
            ok.setStyleSheet(f"color:{_GREEN};padding:4px 8px;")
            dis_lay.addWidget(ok)

        lay.addWidget(dis_card)

        # ── 裁判文书 ──────────────────────────────────────────
        cases = data.get("cases", [])
        case_card = _card_frame()
        case_lay = QVBoxLayout(case_card)
        case_lay.setContentsMargins(14, 12, 14, 14)
        case_lay.setSpacing(6)
        case_color = (_RED if len(cases) >= 5 else
                      _ORANGE if cases else _GREEN)
        case_lay.addWidget(_section_header(
            f"裁判文书  ({len(cases)} 条)", case_color))

        if cases:
            for item in cases[:10]:
                row_w = QWidget()
                row_w.setStyleSheet(
                    f"background:{CARD2};border-radius:6px;"
                )
                row_w.setCursor(Qt.CursorShape.PointingHandCursor)
                row_lay = QVBoxLayout(row_w)
                row_lay.setContentsMargins(10, 8, 10, 8)
                row_lay.setSpacing(3)

                title_lbl = QLabel(item.get("title", ""))
                title_lbl.setFont(QFont("Arial", 10))
                title_lbl.setStyleSheet(
                    f"color:{ACCENT};background:transparent;border:none;"
                    f"text-decoration:underline;"
                )
                title_lbl.setWordWrap(True)
                title_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                url = item.get("url", "")
                if url:
                    title_lbl.mousePressEvent = (
                        lambda e, u=url: QDesktopServices.openUrl(QUrl(u))
                    )
                row_lay.addWidget(title_lbl)

                meta = "  |  ".join(filter(None, [
                    item.get("case_no", ""),
                    item.get("court", ""),
                    item.get("date", ""),
                    item.get("doc_type", ""),
                ]))
                if meta:
                    meta_lbl = QLabel(meta)
                    meta_lbl.setFont(QFont("Arial", 9))
                    meta_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
                    row_lay.addWidget(meta_lbl)

                case_lay.addWidget(row_w)
        else:
            ok = QLabel("未查到裁判文书记录")
            ok.setFont(QFont("Arial", 10))
            ok.setStyleSheet(f"color:{_GREEN};padding:4px 8px;")
            case_lay.addWidget(ok)

        lay.addWidget(case_card)

        # ── 专利信息 ──────────────────────────────────────────
        patents = data.get("patents", {})
        pat_card = _card_frame()
        pat_lay = QVBoxLayout(pat_card)
        pat_lay.setContentsMargins(14, 12, 14, 14)
        pat_lay.setSpacing(6)
        pat_lay.addWidget(_section_header(
            f"专利信息  (共 {patents.get('total', 0)} 件)", ACCENT))

        # 统计行
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)
        for label, val in [
            ("发明专利", patents.get("invention", 0)),
            ("实用新型", patents.get("utility", 0)),
            ("外观设计", patents.get("design", 0)),
        ]:
            stat_w = QWidget()
            stat_w.setStyleSheet(
                f"background:{CARD2};border-radius:6px;"
            )
            stat_inner = QVBoxLayout(stat_w)
            stat_inner.setContentsMargins(12, 8, 12, 8)
            stat_inner.setSpacing(2)
            num_lbl = QLabel(str(val))
            num_lbl.setFont(QFont("Arial", 16, QFont.Weight.Bold))
            num_lbl.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
            num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            type_lbl = QLabel(label)
            type_lbl.setFont(QFont("Arial", 9))
            type_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            type_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_inner.addWidget(num_lbl)
            stat_inner.addWidget(type_lbl)
            stat_row.addWidget(stat_w)
        stat_row.addStretch()
        pat_lay.addLayout(stat_row)

        # 近期专利列表
        for item in patents.get("items", [])[:5]:
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(4, 2, 4, 2)
            row_lay.setSpacing(8)
            type_tag = QLabel(item.get("type", ""))
            type_tag.setFont(QFont("Arial", 8))
            type_tag.setFixedWidth(56)
            type_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
            type_tag.setStyleSheet(
                f"color:{FG2};background:{CARD2};"
                f"border:1px solid {BORDER};border-radius:3px;padding:1px 4px;"
            )
            title_lbl = QLabel(item.get("title", ""))
            title_lbl.setFont(QFont("Arial", 10))
            title_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
            date_lbl = QLabel(item.get("date", ""))
            date_lbl.setFont(QFont("Arial", 9))
            date_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
            row_lay.addWidget(type_tag)
            row_lay.addWidget(title_lbl, 1)
            row_lay.addWidget(date_lbl)
            pat_lay.addWidget(row_w)

        if not patents.get("total"):
            no_pat = QLabel("未查到专利记录，或查询超时")
            no_pat.setFont(QFont("Arial", 10))
            no_pat.setStyleSheet(f"color:{FG3};padding:4px 8px;")
            pat_lay.addWidget(no_pat)

        lay.addWidget(pat_card)
        lay.addStretch()

    # ── 工具方法 ─────────────────────────────────────────────

    def _clear_content(self):
        while self._content_lay.count():
            it = self._content_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
