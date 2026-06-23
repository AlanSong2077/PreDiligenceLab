"""
due_diligence_panel.py — 尽调分析主面板
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
两地区切换：美国（SEC EDGAR）/ 中国香港（港交所披露易）
中国大陆 AMAC 私募基金已独立为「私募基金」功能项
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import webbrowser

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QButtonGroup, QGridLayout,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtCore import QUrl

# ── 颜色常量（与 main.py 保持一致）──────────────────────────────
BG       = "#0B0D14"
BG2      = "#0F1117"
CARD     = "#161923"
CARD2    = "#1C2035"
ACCENT   = "#4F8EF7"
ACCENT_H = "#6BA3FF"
ACCENT_D = "#3A72D8"
ACCENT_G = "rgba(79,142,247,0.12)"
SUCCESS  = "#30D158"
WARN     = "#FF9F0A"
ERR      = "#FF453A"
FG       = "#F0F2F8"
FG2      = "#7A7F94"
FG3      = "#4A4F64"
BORDER   = "#232740"
BORDER2  = "#1A1E30"
INPUT_BG = "#13162A"
INPUT_BD = "#2A2F4A"

REGIONS = [
    ("美国", "US", "SEC EDGAR 公开申报数据"),
    # ("中国香港", "HK", "港交所披露易公告数据"),  # 暂未开放，待下次迭代
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 后台查询线程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class DDWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, keyword: str, region: str,
                 precise: bool = False, drill: bool = False):
        super().__init__()
        self.keyword = keyword.strip()
        self.region  = region
        self.precise = precise
        self.drill   = drill

    def run(self):
        try:
            result = {"region": self.region}
            if self.region == "US":
                result.update(self._query_us())
            self.finished.emit(result)
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()}")

    def _query_us(self) -> dict:
        import sec_edgar
        kw = self.keyword

        if self.precise:
            info = sec_edgar.get_company_info(kw)
            if "error" in info:
                return {"info": info}
            filings = sec_edgar.get_filings(
                info["cik"],
                form_types=["10-K", "10-Q", "8-K", "DEF 14A",
                            "13F-HR", "SC 13G", "SC 13D", "20-F", "6-K", "S-1"],
                limit=40,
            )
            series = sec_edgar.get_fund_series(info["cik"])
            return {"info": info, "filings": filings, "series": series}

        results = sec_edgar.search_company(kw)
        if not results:
            return {"info": {"error": f"未找到：{kw}"}, "filings": [], "series": []}

        if len(results) == 1 or results[0].get("match_type") == "ticker_exact":
            cik = results[0]["cik"]
            info = sec_edgar.get_company_info(cik)
            filings = sec_edgar.get_filings(
                cik,
                form_types=["10-K", "10-Q", "8-K", "DEF 14A",
                            "13F-HR", "SC 13G", "SC 13D", "20-F", "6-K", "S-1"],
                limit=40,
            )
            series = sec_edgar.get_fund_series(cik)
            return {"info": info, "filings": filings, "series": series}

        return {"search_results": results}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主面板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class DueDiligencePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._last_result: dict | None = None   # 缓存最近一次尽调结果，供一键分析使用
        self._setup_ui()

    # ─────────────────────────────────────────────
    # UI 构建
    # ─────────────────────────────────────────────
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部搜索栏 ──────────────────────────────────────────
        top_frame = QFrame()
        top_frame.setStyleSheet(
            f"QFrame{{background:{BG};border-bottom:1px solid {BORDER2};}}"
        )
        top_frame.setFixedHeight(64)
        top_lay = QHBoxLayout(top_frame)
        top_lay.setContentsMargins(20, 0, 20, 0)
        top_lay.setSpacing(10)

        # 地区切换按钮组
        self._region_btns = []
        self._region_group = QButtonGroup(self)
        self._region_group.setExclusive(True)
        for label, code, tip in REGIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.setFixedWidth(90)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setProperty("region_code", code)
            self._region_group.addButton(btn)
            self._region_btns.append(btn)
            top_lay.addWidget(btn)

        self._region_btns[0].setChecked(True)
        self._update_region_styles()
        self._region_group.buttonClicked.connect(
            lambda _: self._update_region_styles()
        )

        top_lay.addSpacing(12)

        # 搜索框
        self._inp = QLineEdit()
        self._inp.setPlaceholderText(
            "输入公司名称 / Ticker / 股票代码 / 基金名称…"
        )
        self._inp.setFixedHeight(36)
        self._inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};color:{FG};border:1px solid {INPUT_BD};"
            f"border-radius:8px;font-size:13px;padding:0 12px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};}}"
        )
        self._inp.returnPressed.connect(self._do_search)
        top_lay.addWidget(self._inp, 1)

        # 搜索按钮
        self._search_btn = QPushButton("查询")
        self._search_btn.setFixedSize(72, 36)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#fff;border:none;"
            f"border-radius:8px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{ACCENT_H};}}"
            f"QPushButton:pressed{{background:{ACCENT_D};}}"
            f"QPushButton:disabled{{background:{BORDER};color:{FG3};}}"
        )
        self._search_btn.clicked.connect(self._do_search)
        top_lay.addWidget(self._search_btn)

        root.addWidget(top_frame)

        # ── 状态栏 ──────────────────────────────────────────────
        self._status_lbl = QLabel("选择地区，输入关键词开始尽调查询")
        self._status_lbl.setFixedHeight(28)
        self._status_lbl.setStyleSheet(
            f"color:{FG3};font-size:11px;background:{BG2};"
            f"border-bottom:1px solid {BORDER2};padding:0 20px;"
        )
        root.addWidget(self._status_lbl)

        # ── 内容滚动区 ──────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{BG2};border:none;}}"
            f"QScrollBar:vertical{{background:{BG};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;}}"
        )

        self._content_w = QWidget()
        self._content_w.setStyleSheet(f"background:{BG2};")
        self._content_lay = QVBoxLayout(self._content_w)
        self._content_lay.setContentsMargins(20, 16, 20, 20)
        self._content_lay.setSpacing(0)

        self._scroll.setWidget(self._content_w)
        root.addWidget(self._scroll, 1)

        # 默认欢迎页
        self._show_welcome()

    # ─────────────────────────────────────────────
    # 地区按钮样式
    # ─────────────────────────────────────────────
    def _update_region_styles(self):
        checked = self._region_group.checkedButton()
        for btn in self._region_btns:
            active = btn is checked
            if active:
                btn.setStyleSheet(
                    f"QPushButton{{background:{ACCENT};color:#fff;border:none;"
                    f"border-radius:7px;font-size:12px;font-weight:600;padding:0 16px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{CARD};color:{FG2};"
                    f"border:1px solid {BORDER};border-radius:7px;"
                    f"font-size:12px;padding:0 16px;}}"
                    f"QPushButton:hover{{color:{FG};border-color:{ACCENT};}}"
                )

    # ─────────────────────────────────────────────
    # 欢迎页
    # ─────────────────────────────────────────────
    def _show_welcome(self):
        self._clear_content()

        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 60, 0, 0)
        lay.setSpacing(16)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        icon = QLabel("🔍")
        icon.setFont(QFont("Arial", 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon.setStyleSheet("background:transparent;border:none;")
        lay.addWidget(icon)

        title = QLabel("尽调分析")
        title.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        lay.addWidget(title)

        sub = QLabel("输入公司名称或代码，选择地区后点击查询")
        sub.setFont(QFont("Arial", 13))
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        lay.addWidget(sub)

        hint_items = [
            ("🇺🇸  美国", "SEC EDGAR 官方数据\n申报文件 · 股东结构 · 子基金穿透"),
        ]
        hint_w = QWidget()
        hint_w.setStyleSheet("background:transparent;")
        hint_lay = QHBoxLayout(hint_w)
        hint_lay.setContentsMargins(0, 20, 0, 0)
        hint_lay.setSpacing(16)
        hint_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        for region_label, desc in hint_items:
            card = QFrame()
            card.setFixedWidth(200)
            card.setStyleSheet(
                f"QFrame{{background:{CARD};border:1px solid {BORDER};"
                f"border-radius:12px;}}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 16, 16, 16)
            cl.setSpacing(6)
            rl = QLabel(region_label)
            rl.setFont(QFont("Arial", 13, QFont.Weight.Bold))
            rl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
            dl = QLabel(desc)
            dl.setFont(QFont("Arial", 10))
            dl.setWordWrap(True)
            dl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            cl.addWidget(rl)
            cl.addWidget(dl)
            hint_lay.addWidget(card)

        lay.addWidget(hint_w)
        self._content_lay.addWidget(w)
        self._content_lay.addStretch()

    # ─────────────────────────────────────────────
    # 清空内容区
    # ─────────────────────────────────────────────
    def _clear_content(self):
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ─────────────────────────────────────────────
    # 查询入口
    # ─────────────────────────────────────────────
    def _do_search(self):
        keyword = self._inp.text().strip()
        if not keyword:
            return
        checked = self._region_group.checkedButton()
        region  = checked.property("region_code") if checked else "US"
        self._start_query(keyword, region)

    def _start_query(self, keyword: str, region: str,
                     precise: bool = False, drill: bool = False):
        self._clear_content()
        self._status_lbl.setText(f"⏳  正在查询「{keyword}」…")
        self._search_btn.setEnabled(False)

        loading = QLabel("⏳  正在查询，请稍候…")
        loading.setFont(QFont("Arial", 13))
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setStyleSheet(
            f"color:{FG2};background:transparent;border:none;margin-top:80px;"
        )
        self._content_lay.addWidget(loading)
        self._content_lay.addStretch()

        self._worker = DDWorker(keyword, region, precise=precise, drill=drill)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_error(self, msg: str):
        self._search_btn.setEnabled(True)
        self._status_lbl.setText("❌  查询失败")
        self._clear_content()
        err = QLabel(f"❌  查询失败：{msg.split(chr(10))[0]}")
        err.setFont(QFont("Arial", 12))
        err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err.setStyleSheet(
            f"color:{ERR};background:transparent;border:none;margin-top:80px;"
        )
        self._content_lay.addWidget(err)
        self._content_lay.addStretch()

    def _on_result(self, data: dict):
        self._search_btn.setEnabled(True)
        self._last_result = data          # 缓存供一键分析读取
        region = data.get("region", "US")
        self._clear_content()

        if region == "US":
            self._render_us(data)

        self._content_lay.addStretch()
        self._status_lbl.setText("✓  查询完成")

    # ─────────────────────────────────────────────
    # 渲染：美国 SEC EDGAR
    # ─────────────────────────────────────────────
    def _render_us(self, data: dict):
        # 多结果候选列表
        if "search_results" in data:
            self._render_candidate_list(data["search_results"], "US")
            return

        info    = data.get("info", {})
        filings = data.get("filings", [])
        series  = data.get("series", [])

        if not info or "error" in info:
            self._on_error((info or {}).get("error", "未找到公司信息"))
            return

        # 公司基本信息
        self._content_lay.addWidget(self._section_title("🏢  公司基本信息"))
        self._content_lay.addWidget(self._make_kv_card([
            ("公司名称",   info.get("name", "—")),
            ("CIK",        info.get("cik", "—")),
            ("Ticker",     ", ".join(info.get("tickers", [])) or "—"),
            ("交易所",     ", ".join(info.get("exchanges", [])) or "—"),
            ("SIC 行业",   f"{info.get('sic','—')}  {info.get('sic_desc','')}"),
            ("注册州",     info.get("state_of_inc", "—")),
            ("财年截止",   info.get("fiscal_year_end", "—")),
            ("EIN",        info.get("ein", "—")),
            ("实体类型",   info.get("entity_type", "—")),
            ("注册地址",   info.get("mailing_addr", "—")),
            ("办公地址",   info.get("business_addr", "—")),
            ("电话",       info.get("phone", "—")),
        ]))
        self._content_lay.addSpacing(12)

        # 申报文件
        if filings:
            self._content_lay.addWidget(
                self._section_title(f"📄  近期申报文件（{len(filings)} 条）"))
            self._content_lay.addWidget(self._make_filing_card(filings))
            self._content_lay.addSpacing(12)

        # 子基金
        if series:
            self._content_lay.addWidget(
                self._section_title(f"🗂  旗下子基金（{len(series)} 只）"))
            self._content_lay.addWidget(self._make_series_card(series))
            self._content_lay.addSpacing(12)

        # EDGAR 快捷链接
        cik_int = int(info.get("cik", "0") or 0)
        if cik_int:
            self._content_lay.addWidget(self._section_title("🔗  EDGAR 官方链接"))
            self._content_lay.addWidget(self._make_link_card([
                ("公司申报总览",
                 f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=&dateb=&owner=include&count=40"),
                ("年报 10-K",
                 f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=10-K&dateb=&owner=include&count=10"),
                ("季报 10-Q",
                 f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=10-Q&dateb=&owner=include&count=10"),
                ("重大事项 8-K",
                 f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=8-K&dateb=&owner=include&count=10"),
                ("大股东披露 13G/13D",
                 f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=SC+13&dateb=&owner=include&count=10"),
            ]))

    # ─────────────────────────────────────────────
    # 候选列表（多结果时让用户选择）
    # ─────────────────────────────────────────────
    def _render_candidate_list(self, results: list, region: str):
        region_name = {"US": "美国", "HK": "中国香港"}.get(region, region)
        self._content_lay.addWidget(
            self._section_title(
                f"🔎  找到 {len(results)} 条结果，请选择（{region_name}）"
            )
        )

        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 8, 0, 8)
        cl.setSpacing(0)

        for i, r in enumerate(results[:20]):
            if region == "US":
                label = f"{r.get('ticker','—')}  {r.get('name','—')}  CIK={r.get('cik','—')}"
                key   = r.get("cik", "")
            else:  # HK
                label = f"{r.get('stock_code','—')}  {r.get('name_en','—')}"
                key   = r.get("stock_code", "")

            btn = QPushButton(label)
            btn.setFixedHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{FG};border:none;"
                f"border-bottom:1px solid {BORDER2};font-size:12px;"
                f"padding:0 20px;text-align:left;}}"
                f"QPushButton:hover{{background:{CARD2};color:{ACCENT};}}"
            )
            btn.clicked.connect(
                lambda checked, k=key, reg=region: self._start_query(k, reg, precise=True)
            )
            cl.addWidget(btn)

        self._content_lay.addWidget(card)

    # ─────────────────────────────────────────────
    # UI 组件构建器
    # ─────────────────────────────────────────────
    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color:{FG};background:transparent;border:none;padding:12px 0 6px 0;"
        )
        return lbl

    def _make_kv_card(self, pairs: list) -> QFrame:
        """键值对信息卡片，两列网格布局"""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 16, 20, 16)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        for i, (k, v) in enumerate(pairs):
            row, col = divmod(i, 2)
            base_col = col * 2

            key_lbl = QLabel(k)
            key_lbl.setFont(QFont("Arial", 10))
            key_lbl.setStyleSheet(
                f"color:{FG3};background:transparent;border:none;"
            )
            key_lbl.setFixedWidth(90)

            val_lbl = QLabel(str(v) if v else "—")
            val_lbl.setFont(QFont("Arial", 11))
            val_lbl.setStyleSheet(
                f"color:{FG};background:transparent;border:none;"
            )
            val_lbl.setWordWrap(True)

            grid.addWidget(key_lbl, row, base_col)
            grid.addWidget(val_lbl, row, base_col + 1)

        return card

    def _make_filing_card(self, filings: list) -> QFrame:
        """申报文件列表卡片"""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(0)

        for i, f in enumerate(filings[:30]):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(20, 6, 20, 6)
            row_lay.setSpacing(12)

            form_lbl = QLabel(f.get("form", "—"))
            form_lbl.setFixedWidth(72)
            form_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            form_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            form_lbl.setStyleSheet(
                f"color:{ACCENT};background:{ACCENT_G};border:1px solid {ACCENT};"
                f"border-radius:4px;padding:1px 4px;"
            )

            desc_lbl = QLabel(f.get("form_desc", "") or f.get("description", ""))
            desc_lbl.setFont(QFont("Arial", 11))
            desc_lbl.setStyleSheet(
                f"color:{FG};background:transparent;border:none;"
            )

            date_lbl = QLabel(f.get("date", "—"))
            date_lbl.setFont(QFont("Arial", 10))
            date_lbl.setStyleSheet(
                f"color:{FG2};background:transparent;border:none;"
            )
            date_lbl.setFixedWidth(90)
            date_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            url = f.get("url", "") or f.get("viewer_url", "")
            if url:
                link_btn = QPushButton("查看")
                link_btn.setFixedSize(48, 24)
                link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                link_btn.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{ACCENT};"
                    f"border:1px solid {ACCENT};border-radius:4px;font-size:10px;}}"
                    f"QPushButton:hover{{background:{ACCENT_G};}}"
                )
                link_btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            else:
                link_btn = QLabel("")
                link_btn.setFixedWidth(48)

            row_lay.addWidget(form_lbl)
            row_lay.addWidget(desc_lbl, 1)
            row_lay.addWidget(date_lbl)
            row_lay.addWidget(link_btn)

            if i < len(filings) - 1:
                row_w.setStyleSheet(
                    f"background:transparent;"
                    f"border-bottom:1px solid {BORDER2};"
                )
            lay.addWidget(row_w)

        return card

    def _make_series_card(self, series: list) -> QFrame:
        """子基金列表卡片"""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(0)

        for i, s in enumerate(series[:30]):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(20, 8, 20, 8)
            row_lay.setSpacing(12)

            name_lbl = QLabel(s.get("series_name", "—"))
            name_lbl.setFont(QFont("Arial", 11))
            name_lbl.setStyleSheet(
                f"color:{FG};background:transparent;border:none;"
            )

            status = s.get("status", "")
            color  = SUCCESS if status == "Active" else FG3
            status_lbl = QLabel(status)
            status_lbl.setFont(QFont("Arial", 10))
            status_lbl.setStyleSheet(
                f"color:{color};background:transparent;border:none;"
            )
            status_lbl.setFixedWidth(60)

            cls_lbl = QLabel(f"{s.get('class_count', 0)} 个份额类别")
            cls_lbl.setFont(QFont("Arial", 10))
            cls_lbl.setStyleSheet(
                f"color:{FG2};background:transparent;border:none;"
            )
            cls_lbl.setFixedWidth(90)

            row_lay.addWidget(name_lbl, 1)
            row_lay.addWidget(status_lbl)
            row_lay.addWidget(cls_lbl)

            if i < len(series) - 1:
                row_w.setStyleSheet(
                    f"background:transparent;"
                    f"border-bottom:1px solid {BORDER2};"
                )
            lay.addWidget(row_w)

        if len(series) > 30:
            more = QLabel(f"  … 共 {len(series)} 只，仅展示前 30 条")
            more.setStyleSheet(
                f"color:{FG3};background:transparent;border:none;"
                f"font-size:11px;padding:8px 20px;"
            )
            lay.addWidget(more)

        return card

    def _make_link_card(self, links: list) -> QFrame:
        """链接列表卡片"""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(0)

        valid = [(label, url) for label, url in links if url]
        for i, (label, url) in enumerate(valid):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(20, 8, 20, 8)
            row_lay.setSpacing(12)

            lbl = QLabel(label)
            lbl.setFont(QFont("Arial", 11))
            lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")

            open_btn = QPushButton("打开 ↗")
            open_btn.setFixedSize(64, 26)
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{ACCENT};"
                f"border:1px solid {ACCENT};border-radius:5px;font-size:10px;}}"
                f"QPushButton:hover{{background:{ACCENT_G};}}"
            )
            open_btn.clicked.connect(lambda _, u=url: webbrowser.open(u))

            row_lay.addWidget(lbl, 1)
            row_lay.addWidget(open_btn)

            if i < len(valid) - 1:
                row_w.setStyleSheet(
                    f"background:transparent;"
                    f"border-bottom:1px solid {BORDER2};"
                )
            lay.addWidget(row_w)

        return card

