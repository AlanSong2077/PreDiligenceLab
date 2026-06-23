"""
amac_panel.py — 中国大陆私募基金查询面板（AMAC 中基协）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  • 基金搜索 → 自动显示目标基金详情 + 管理人信息 + 旗下所有子基金（含详情）
  • 管理人搜索 → 穿透子基金
  • 下载：导出当前查询结果为 CSV / JSON
数据源：中国证券投资基金业协会（AMAC）私募基金备案公示系统
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import csv
import json
import os
import webbrowser
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QFileDialog, QMessageBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 后台查询线程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class AmacWorker(QThread):
    """
    三种查询模式：
      mode="fund"    → 基金名称搜索，自动穿透管理人 + 子基金详情
      mode="manager" → 管理人名称搜索（仅列表，不穿透）
      mode="drill"   → 管理人穿透子基金（含详情）
    """
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    progress = pyqtSignal(str)   # 进度文字

    def __init__(self, keyword: str, mode: str = "fund"):
        super().__init__()
        self.keyword = keyword.strip()
        self.mode    = mode

    def run(self):
        try:
            import amac_fund

            if self.mode == "fund":
                # 搜索基金 → 穿透管理人 → 子基金（含详情）
                self.progress.emit("正在搜索基金…")
                result = amac_fund.get_fund_with_sub_funds(
                    self.keyword,
                    with_detail=True,
                    progress_cb=lambda done, total, label:
                        self.progress.emit(f"正在获取{label}（{done}/{total}）…"),
                )
                if "error" in result:
                    raise RuntimeError(result["error"])
                self.finished.emit({"mode": "fund", "data": result})

            elif self.mode == "manager":
                self.progress.emit("正在搜索管理人…")
                managers = amac_fund.search_manager(self.keyword, limit=20)
                self.finished.emit({"mode": "manager", "data": managers})

            elif self.mode == "drill":
                self.progress.emit("正在穿透子基金…")
                result = amac_fund.get_manager_funds(
                    self.keyword,
                    with_detail=True,
                    progress_cb=lambda done, total, label:
                        self.progress.emit(f"正在获取{label}（{done}/{total}）…"),
                )
                if "error" in result:
                    raise RuntimeError(result["error"])
                self.finished.emit({"mode": "drill", "data": result})

        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主面板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class AmacPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker      = None
        self._last_result = None   # 保存最近一次查询结果，用于下载
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

        title_lbl = QLabel("🇨🇳  中基协 AMAC")
        title_lbl.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        top_lay.addWidget(title_lbl)

        top_lay.addSpacing(16)

        self._inp = QLineEdit()
        self._inp.setPlaceholderText("输入基金名称 / 管理人名称…")
        self._inp.setFixedHeight(36)
        self._inp.setStyleSheet(
            f"QLineEdit{{background:{INPUT_BG};color:{FG};border:1px solid {INPUT_BD};"
            f"border-radius:8px;font-size:13px;padding:0 12px;}}"
            f"QLineEdit:focus{{border-color:{ACCENT};}}"
        )
        self._inp.returnPressed.connect(self._do_search_fund)
        top_lay.addWidget(self._inp, 1)

        # 查询基金按钮
        self._search_btn = QPushButton("查询基金")
        self._search_btn.setFixedSize(84, 36)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.setStyleSheet(self._btn_style(ACCENT))
        self._search_btn.clicked.connect(self._do_search_fund)
        top_lay.addWidget(self._search_btn)

        # 查询管理人按钮
        self._mgr_btn = QPushButton("查管理人")
        self._mgr_btn.setFixedSize(84, 36)
        self._mgr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mgr_btn.setStyleSheet(self._btn_style(CARD2, border=ACCENT, color=ACCENT))
        self._mgr_btn.clicked.connect(self._do_search_manager)
        top_lay.addWidget(self._mgr_btn)

        root.addWidget(top_frame)

        # ── 状态栏 ──────────────────────────────────────────────
        self._status_lbl = QLabel("输入基金名称或管理人名称开始查询")
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

        self._show_welcome()

    def _btn_style(self, bg: str, border: str = "", color: str = "#fff") -> str:
        bd = border or bg
        return (
            f"QPushButton{{background:{bg};color:{color};border:1px solid {bd};"
            f"border-radius:8px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{opacity:0.85;}}"
            f"QPushButton:disabled{{background:{BORDER};color:{FG3};border-color:{BORDER};}}"
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

        icon = QLabel("🏦")
        icon.setFont(QFont("Arial", 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon.setStyleSheet("background:transparent;border:none;")
        lay.addWidget(icon)

        title = QLabel("私募基金查询")
        title.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        lay.addWidget(title)

        sub = QLabel("数据来源：中国证券投资基金业协会（AMAC）私募基金备案公示系统")
        sub.setFont(QFont("Arial", 13))
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        lay.addWidget(sub)

        hint_items = [
            ("📦  基金搜索",   "按基金名称搜索\n自动显示详情 + 管理人 + 旗下所有子基金"),
            ("🏦  管理人搜索", "按管理人名称搜索\n返回法人、注册地、旗下基金数"),
            ("🔍  管理人穿透", "点击「穿透子基金」\n列出该管理人旗下所有备案基金（含详情）"),
            ("💾  数据下载",   "查询完成后\n可导出 CSV / JSON 到本地"),
        ]
        hint_w = QWidget()
        hint_w.setStyleSheet("background:transparent;")
        hint_lay = QHBoxLayout(hint_w)
        hint_lay.setContentsMargins(0, 20, 0, 0)
        hint_lay.setSpacing(12)
        hint_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        for feat_label, desc in hint_items:
            card = QFrame()
            card.setFixedWidth(190)
            card.setStyleSheet(
                f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 14, 14, 14)
            cl.setSpacing(6)
            rl = QLabel(feat_label)
            rl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            rl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
            dl = QLabel(desc)
            dl.setFont(QFont("Arial", 10))
            dl.setWordWrap(True)
            dl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            cl.addWidget(rl)
            cl.addWidget(dl)
            hint_lay.addWidget(card)

        lay.addWidget(hint_w)

        link_w = QWidget()
        link_w.setStyleSheet("background:transparent;")
        link_lay = QHBoxLayout(link_w)
        link_lay.setContentsMargins(0, 24, 0, 0)
        link_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        link_lay.setSpacing(12)

        for label, url in [
            ("私募基金公示系统 ↗",
             "https://gs.amac.org.cn/amac-infodisc/res/pof/fund/index.html"),
            ("管理人公示 ↗",
             "https://gs.amac.org.cn/amac-infodisc/res/pof/manager/managerList.html"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{ACCENT};"
                f"border:1px solid {ACCENT};border-radius:6px;"
                f"font-size:11px;padding:0 14px;}}"
                f"QPushButton:hover{{background:{ACCENT_G};}}"
            )
            btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            link_lay.addWidget(btn)

        lay.addWidget(link_w)
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
    def _do_search_fund(self):
        keyword = self._inp.text().strip()
        if not keyword:
            return
        self._start_query(keyword, mode="fund")

    def _do_search_manager(self):
        keyword = self._inp.text().strip()
        if not keyword:
            return
        self._start_query(keyword, mode="manager")

    def _start_query(self, keyword: str, mode: str = "fund"):
        self._clear_content()
        self._last_result = None
        self._status_lbl.setText(f"⏳  正在查询「{keyword}」…")
        self._set_btns_enabled(False)

        loading = QLabel("⏳  正在查询，请稍候…")
        loading.setFont(QFont("Arial", 13))
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setStyleSheet(
            f"color:{FG2};background:transparent;border:none;margin-top:80px;"
        )
        self._content_lay.addWidget(loading)
        self._content_lay.addStretch()

        self._worker = AmacWorker(keyword, mode=mode)
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(
            lambda msg: self._status_lbl.setText(f"⏳  {msg}")
        )
        self._worker.start()

    def _set_btns_enabled(self, enabled: bool):
        self._search_btn.setEnabled(enabled)
        self._mgr_btn.setEnabled(enabled)

    def _on_error(self, msg: str):
        self._set_btns_enabled(True)
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

    def _on_result(self, payload: dict):
        self._set_btns_enabled(True)
        self._clear_content()
        self._last_result = payload

        mode = payload.get("mode", "")
        data = payload.get("data", {})

        if mode == "fund":
            self._render_fund_result(data)
        elif mode == "manager":
            self._render_manager_list(data)
        elif mode == "drill":
            self._render_drill(data)

        # 下载工具栏（有结果才显示）
        if self._last_result:
            self._content_lay.addSpacing(16)
            self._content_lay.addWidget(self._make_download_bar())

        self._content_lay.addStretch()
        self._status_lbl.setText("✓  查询完成")

    # ─────────────────────────────────────────────
    # 渲染：基金搜索结果（目标基金 + 管理人 + 子基金）
    # ─────────────────────────────────────────────
    def _render_fund_result(self, data: dict):
        target = data.get("target_fund", {})
        manager = data.get("manager", {})
        sub_funds = data.get("sub_funds", [])
        total = data.get("total_sub_funds", len(sub_funds))

        # ── 目标基金详情 ──
        self._content_lay.addWidget(
            self._section_title("📦  目标基金详情"))
        self._content_lay.addWidget(self._make_fund_detail_card(target))
        self._content_lay.addSpacing(12)

        # ── 管理人信息 ──
        if manager:
            self._content_lay.addWidget(
                self._section_title("🏦  基金管理人"))
            self._content_lay.addWidget(self._make_manager_detail_card(manager))
            self._content_lay.addSpacing(12)

        # ── 子基金列表 ──
        if sub_funds:
            self._content_lay.addWidget(
                self._section_title(
                    f"🔍  管理人旗下子基金（共 {total} 只，展示 {min(len(sub_funds), 100)} 只）"
                )
            )
            self._content_lay.addWidget(self._make_fund_table(sub_funds[:100]))
            if total > 100:
                more = QLabel(f"  … 共 {total} 只，仅展示前 100 条，可下载完整数据")
                more.setStyleSheet(
                    f"color:{FG3};background:transparent;border:none;font-size:11px;padding:4px 0;"
                )
                self._content_lay.addWidget(more)
            self._content_lay.addSpacing(12)
        else:
            empty = QLabel("该管理人旗下暂无子基金记录。")
            empty.setStyleSheet(
                f"color:{FG3};background:transparent;border:none;font-size:12px;padding:8px 0;"
            )
            self._content_lay.addWidget(empty)

    # ─────────────────────────────────────────────
    # 渲染：管理人列表
    # ─────────────────────────────────────────────
    def _render_manager_list(self, managers: list):
        if not managers:
            empty = QLabel("未找到相关管理人信息。")
            empty.setFont(QFont("Arial", 13))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color:{FG3};background:transparent;border:none;margin-top:80px;"
            )
            self._content_lay.addWidget(empty)
            return

        self._content_lay.addWidget(
            self._section_title(f"🏦  管理人搜索结果（{len(managers)} 条）"))
        self._content_lay.addWidget(self._make_manager_card(managers))
        self._content_lay.addSpacing(12)

    # ─────────────────────────────────────────────
    # 渲染：管理人穿透子基金
    # ─────────────────────────────────────────────
    def _render_drill(self, data: dict):
        manager   = data.get("manager", {})
        sub_funds = data.get("funds", [])
        total     = len(sub_funds)

        if manager:
            self._content_lay.addWidget(
                self._section_title("🏦  管理人信息"))
            self._content_lay.addWidget(self._make_manager_detail_card(manager))
            self._content_lay.addSpacing(12)

        self._content_lay.addWidget(
            self._section_title(
                f"🔍  旗下子基金（共 {total} 只，展示 {min(total, 100)} 只）"
            )
        )
        self._content_lay.addWidget(self._make_fund_table(sub_funds[:100]))
        if total > 100:
            more = QLabel(f"  … 共 {total} 只，仅展示前 100 条，可下载完整数据")
            more.setStyleSheet(
                f"color:{FG3};background:transparent;border:none;font-size:11px;padding:4px 0;"
            )
            self._content_lay.addWidget(more)

    # ─────────────────────────────────────────────
    # 下载工具栏
    # ─────────────────────────────────────────────
    def _make_download_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:10px;}}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        icon_lbl = QLabel("💾  导出当前查询结果：")
        icon_lbl.setFont(QFont("Arial", 12))
        icon_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
        lay.addWidget(icon_lbl)
        lay.addStretch()

        for label, fmt in [("下载 CSV", "csv"), ("下载 JSON", "json")]:
            btn = QPushButton(label)
            btn.setFixedSize(90, 30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:{ACCENT};color:#fff;border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:{ACCENT_H};}}"
                f"QPushButton:pressed{{background:{ACCENT_D};}}"
            )
            btn.clicked.connect(lambda _, f=fmt: self._download(f))
            lay.addWidget(btn)

        return bar

    def _download(self, fmt: str):
        if not self._last_result:
            return

        # 收集所有基金数据
        payload = self._last_result
        mode    = payload.get("mode", "")
        data    = payload.get("data", {})

        rows = []
        if mode == "fund":
            target = data.get("target_fund", {})
            if target:
                rows.append(target)
            rows.extend(data.get("sub_funds", []))
        elif mode == "manager":
            rows = data  # list of managers
        elif mode == "drill":
            rows = data.get("funds", [])

        if not rows:
            QMessageBox.information(self, "提示", "暂无可下载的数据。")
            return

        # 去掉 _raw 字段（原始 dict，不适合导出）
        clean_rows = []
        for r in rows:
            clean = {k: v for k, v in r.items() if k != "_raw"}
            clean_rows.append(clean)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"amac_{mode}_{ts}.{fmt}"

        path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            f"{'CSV 文件 (*.csv)' if fmt == 'csv' else 'JSON 文件 (*.json)'}"
        )
        if not path:
            return

        try:
            if fmt == "csv":
                keys = list(clean_rows[0].keys())
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(clean_rows)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(clean_rows, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self, "下载成功",
                f"已保存 {len(clean_rows)} 条记录到：\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ─────────────────────────────────────────────
    # UI 组件：目标基金详情卡片
    # ─────────────────────────────────────────────
    def _make_fund_detail_card(self, fund: dict) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        # 基金名称 + 状态
        header = QHBoxLayout()
        name_lbl = QLabel(fund.get("fund_name", "—"))
        name_lbl.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        name_lbl.setWordWrap(True)
        header.addWidget(name_lbl, 1)

        state = fund.get("working_state", "")
        color = SUCCESS if "运作" in state else (WARN if "清算" in state else FG3)
        state_lbl = QLabel(state)
        state_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        state_lbl.setStyleSheet(
            f"color:{color};background:transparent;border:none;padding:2px 8px;"
        )
        header.addWidget(state_lbl)
        lay.addLayout(header)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER2};background:{BORDER2};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        # 基本信息网格
        basic_fields = [
            ("基金代码",   fund.get("fund_code", "—")),
            ("基金类型",   fund.get("fund_type", "—")),
            ("管理人",     fund.get("manager_name", "—")),
            ("托管人",     fund.get("custodian_name", "—") or "—"),
            ("成立日期",   fund.get("establish_date", "—") or "—"),
            ("备案日期",   fund.get("record_date", "—") or "—"),
            ("注册省份",   fund.get("province", "—") or "—"),
        ]
        # 详情字段（如果已抓取）
        detail_fields = [
            ("币种",         fund.get("detail_currency", "")),
            ("备案阶段",     fund.get("detail_record_stage", "")),
            ("管理类型",     fund.get("detail_manage_type", "")),
            ("最后更新",     fund.get("detail_last_update", "")),
            ("月报",         fund.get("detail_month_report", "")),
            ("季报",         fund.get("detail_quarter_report", "")),
            ("半年报",       fund.get("detail_half_report", "")),
            ("年报",         fund.get("detail_year_report", "")),
            ("投资者账号开立率", fund.get("detail_investor_rate", "")),
        ]

        all_fields = basic_fields + [(k, v) for k, v in detail_fields if v]

        grid_w = QWidget()
        grid_w.setStyleSheet("background:transparent;")
        grid_lay = QHBoxLayout(grid_w)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        grid_lay.setSpacing(24)

        col1 = QVBoxLayout()
        col1.setSpacing(6)
        col2 = QVBoxLayout()
        col2.setSpacing(6)

        for idx, (label, value) in enumerate(all_fields):
            row = QHBoxLayout()
            row.setSpacing(6)
            k_lbl = QLabel(f"{label}：")
            k_lbl.setFont(QFont("Arial", 10))
            k_lbl.setFixedWidth(110)
            k_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
            v_lbl = QLabel(str(value) if value else "—")
            v_lbl.setFont(QFont("Arial", 10))
            v_lbl.setWordWrap(True)
            v_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
            row.addWidget(k_lbl)
            row.addWidget(v_lbl, 1)
            if idx % 2 == 0:
                col1.addLayout(row)
            else:
                col2.addLayout(row)

        grid_lay.addLayout(col1, 1)
        grid_lay.addLayout(col2, 1)
        lay.addWidget(grid_w)

        # 诚信 / 机构提示
        for tip_key, tip_label, tip_color in [
            ("detail_credit_info", "机构诚信信息", WARN),
            ("detail_org_tip",     "机构提示信息", WARN),
            ("detail_special_tip", "协会特别提示", ERR),
        ]:
            tip_val = fund.get(tip_key, "")
            if tip_val and tip_val != "无":
                tip_lbl = QLabel(f"⚠️  {tip_label}：{tip_val}")
                tip_lbl.setFont(QFont("Arial", 10))
                tip_lbl.setWordWrap(True)
                tip_lbl.setStyleSheet(
                    f"color:{tip_color};background:transparent;border:none;"
                )
                lay.addWidget(tip_lbl)

        # 详情链接
        url = fund.get("detail_url", "")
        if url:
            link_btn = QPushButton("在中基协官网查看详情 ↗")
            link_btn.setFixedHeight(28)
            link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            link_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{ACCENT};"
                f"border:1px solid {ACCENT};border-radius:5px;font-size:11px;padding:0 12px;}}"
                f"QPushButton:hover{{background:{ACCENT_G};}}"
            )
            link_btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            btn_row = QHBoxLayout()
            btn_row.addWidget(link_btn)
            btn_row.addStretch()
            lay.addLayout(btn_row)

        return card

    # ─────────────────────────────────────────────
    # UI 组件：管理人详情卡片（单个）
    # ─────────────────────────────────────────────
    def _make_manager_detail_card(self, m: dict) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        # 名称行
        header = QHBoxLayout()
        name_lbl = QLabel(m.get("manager_name", "—"))
        name_lbl.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
        header.addWidget(name_lbl, 1)

        fund_cnt = QLabel(f"旗下基金：{m.get('fund_count', 0)} 只")
        fund_cnt.setFont(QFont("Arial", 11))
        fund_cnt.setStyleSheet(f"color:{ACCENT};background:transparent;border:none;")
        header.addWidget(fund_cnt)
        lay.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER2};background:{BORDER2};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        fields = [
            ("登记编号",   m.get("register_no", "—")),
            ("法定代表人", m.get("legal_person", "—") or "—"),
            ("主要投资类型", m.get("primary_type", "—") or "—"),
            ("机构类型",   m.get("org_form", "—") or "—"),
            ("成立日期",   m.get("establish_date", "—") or "—"),
            ("登记日期",   m.get("register_date", "—") or "—"),
            ("注册地",     f"{m.get('register_province','')}{m.get('register_city','')}".strip() or "—"),
            ("办公地",     f"{m.get('office_province','')}{m.get('office_city','')}".strip() or "—"),
        ]

        grid_w = QWidget()
        grid_w.setStyleSheet("background:transparent;")
        grid_lay = QHBoxLayout(grid_w)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        grid_lay.setSpacing(24)
        col1 = QVBoxLayout(); col1.setSpacing(6)
        col2 = QVBoxLayout(); col2.setSpacing(6)

        for idx, (label, value) in enumerate(fields):
            row = QHBoxLayout(); row.setSpacing(6)
            k_lbl = QLabel(f"{label}：")
            k_lbl.setFont(QFont("Arial", 10))
            k_lbl.setFixedWidth(90)
            k_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
            v_lbl = QLabel(str(value))
            v_lbl.setFont(QFont("Arial", 10))
            v_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
            row.addWidget(k_lbl)
            row.addWidget(v_lbl, 1)
            if idx % 2 == 0:
                col1.addLayout(row)
            else:
                col2.addLayout(row)

        grid_lay.addLayout(col1, 1)
        grid_lay.addLayout(col2, 1)
        lay.addWidget(grid_w)

        # 诚信 / 特别提示标记
        tips = []
        if m.get("has_credit_tips"):
            tips.append("⚠️  该管理人存在诚信提示")
        if m.get("has_special_tips"):
            tips.append("🚨  该管理人存在协会特别提示")
        for tip in tips:
            t = QLabel(tip)
            t.setFont(QFont("Arial", 10))
            t.setStyleSheet(f"color:{WARN};background:transparent;border:none;")
            lay.addWidget(t)

        return card

    # ─────────────────────────────────────────────
    # UI 组件：管理人列表卡片（含穿透按钮）
    # ─────────────────────────────────────────────
    def _make_manager_card(self, managers: list) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(0)

        for i, m in enumerate(managers):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(20, 10, 20, 10)
            row_lay.setSpacing(12)

            name_lbl = QLabel(m.get("manager_name", "—"))
            name_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            name_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")

            info_lbl = QLabel(
                f"法人: {m.get('legal_person', '—')}  "
                f"注册地: {m.get('register_province', '—')}{m.get('register_city', '')}  "
                f"基金数: {m.get('fund_count', 0)}"
            )
            info_lbl.setFont(QFont("Arial", 10))
            info_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")

            drill_btn = QPushButton("穿透子基金")
            drill_btn.setFixedSize(84, 26)
            drill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            drill_btn.setStyleSheet(
                f"QPushButton{{background:{ACCENT};color:#fff;border:none;"
                f"border-radius:5px;font-size:10px;}}"
                f"QPushButton:hover{{background:{ACCENT_H};}}"
            )
            mgr_name = m.get("manager_name", "")
            drill_btn.clicked.connect(
                lambda _, mn=mgr_name: self._start_query(mn, mode="drill")
            )

            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(name_lbl)
            col.addWidget(info_lbl)

            row_lay.addLayout(col, 1)
            row_lay.addWidget(drill_btn)

            if i < len(managers) - 1:
                row_w.setStyleSheet(
                    f"background:transparent;border-bottom:1px solid {BORDER2};"
                )
            lay.addWidget(row_w)

        return card

    # ─────────────────────────────────────────────
    # UI 组件：基金列表表格（子基金）
    # ─────────────────────────────────────────────
    def _make_fund_table(self, funds: list) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 表头
        header_w = QWidget()
        header_w.setStyleSheet(
            f"background:{CARD2};border-radius:12px 12px 0 0;"
        )
        header_lay = QHBoxLayout(header_w)
        header_lay.setContentsMargins(20, 8, 20, 8)
        header_lay.setSpacing(12)

        for col_text, width in [
            ("基金名称", 0),
            ("基金类型", 130),
            ("运作状态", 80),
            ("成立日期", 90),
            ("备案日期", 90),
            ("操作",     60),
        ]:
            lbl = QLabel(col_text)
            lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
            if width:
                lbl.setFixedWidth(width)
            else:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            header_lay.addWidget(lbl)

        lay.addWidget(header_w)

        # 数据行
        for i, f in enumerate(funds):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(20, 7, 20, 7)
            row_lay.setSpacing(12)

            name_lbl = QLabel(f.get("fund_name", "—"))
            name_lbl.setFont(QFont("Arial", 11))
            name_lbl.setStyleSheet(f"color:{FG};background:transparent;border:none;")
            name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            type_lbl = QLabel(f.get("fund_type", "—"))
            type_lbl.setFont(QFont("Arial", 10))
            type_lbl.setStyleSheet(f"color:{FG2};background:transparent;border:none;")
            type_lbl.setFixedWidth(130)

            state = f.get("working_state", "")
            color = SUCCESS if "运作" in state else (WARN if "清算" in state else FG3)
            state_lbl = QLabel(state)
            state_lbl.setFont(QFont("Arial", 10))
            state_lbl.setStyleSheet(f"color:{color};background:transparent;border:none;")
            state_lbl.setFixedWidth(80)

            est_lbl = QLabel(f.get("establish_date", "") or "—")
            est_lbl.setFont(QFont("Arial", 10))
            est_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
            est_lbl.setFixedWidth(90)

            rec_lbl = QLabel(f.get("record_date", "") or "—")
            rec_lbl.setFont(QFont("Arial", 10))
            rec_lbl.setStyleSheet(f"color:{FG3};background:transparent;border:none;")
            rec_lbl.setFixedWidth(90)

            row_lay.addWidget(name_lbl)
            row_lay.addWidget(type_lbl)
            row_lay.addWidget(state_lbl)
            row_lay.addWidget(est_lbl)
            row_lay.addWidget(rec_lbl)

            url = f.get("detail_url", "")
            if url:
                link_btn = QPushButton("详情")
                link_btn.setFixedSize(44, 22)
                link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                link_btn.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{ACCENT};"
                    f"border:1px solid {ACCENT};border-radius:4px;font-size:10px;}}"
                    f"QPushButton:hover{{background:{ACCENT_G};}}"
                )
                link_btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
                row_lay.addWidget(link_btn)
            else:
                row_lay.addSpacing(44)

            if i < len(funds) - 1:
                row_w.setStyleSheet(
                    f"background:transparent;border-bottom:1px solid {BORDER2};"
                )
            lay.addWidget(row_w)

        return card

    # ─────────────────────────────────────────────
    # 工具
    # ─────────────────────────────────────────────
    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color:{FG};background:transparent;border:none;padding:12px 0 6px 0;"
        )
        return lbl
