# -*- mode: python ; coding: utf-8 -*-
# PreDiligenceLab.spec — PyInstaller 构建配置
# 最后更新：2026-06-15

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # ── Qt configuration (must be at Resources root for macOS .app bundle) ──
        ('qt.conf', '.'),
        ('main.py',              '.'),
        ('theme.py',             '.'),
        ('logger.py',            '.'),
        ('fetcher.py',           '.'),
        ('analytics.py',         '.'),
        ('market_utils.py',      '.'),
        ('web_search.py',        '.'),
        ('llm_client.py',        '.'),
        # ── 面板 / UI ─────────────────────────────────────
        ('fin_calc_panel.py',    '.'),
        ('fin_calc.py',          '.'),
        ('dd_form_panel.py',     '.'),
        ('due_diligence_panel.py', '.'),
        ('biz_info_panel.py',    '.'),
        ('biz_lookup.py',        '.'),
        ('amac_panel.py',        '.'),
        ('amac_fund.py',         '.'),
        ('peer_scanner.py',      '.'),
        ('news_fetcher.py',      '.'),
        ('sec_edgar.py',         '.'),
        ('hkex.py',              '.'),
        ('industry_benchmarks.py', '.'),
        # ── 资源文件 ──────────────────────────────────────
        ('fin_calc_template.md', '.'),
        # ── 风险分析 Skill ────────────────────────────────
        ('hardtech-risk-analysis/SKILL.md',    'hardtech-risk-analysis'),
        ('hardtech-risk-analysis/examples.md', 'hardtech-risk-analysis'),
    ],
    hiddenimports=[
        # PyQt6
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtPrintSupport',
        'PyQt6.sip',
        # 数据 / 财务
        'yfinance',
        'akshare',
        'pandas',
        'pandas.core.arrays.masked',
        'pandas.core.arrays.integer',
        'pandas.core.arrays.floating',
        'numpy',
        # 网络
        'requests',
        'requests.adapters',
        'requests.packages',
        'urllib3',
        'bs4',
        'beautifulsoup4',
        # 图表
        'matplotlib',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_agg',
        'matplotlib.figure',
        'matplotlib.pyplot',
        'matplotlib.dates',
        'matplotlib.ticker',
        'matplotlib.font_manager',
        # 系统
        'keyring',
        'keyring.backends',
        'keyring.backends.macOS',
        # 其他
        'json',
        'logging',
        'threading',
        'subprocess',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hook-qt6-path.py'],
    excludes=[
        'tkinter',
        'test',
        'unittest',
        'email',
        'xmlrpc',
        'ftplib',
        'imaplib',
        'poplib',
        'smtplib',
        'telnetlib',
        'nntplib',
        'sndhdr',
        'sunau',
        'aifc',
        'wave',
        'chunk',
        'colorsys',
        'imghdr',
        'turtle',
        'curses',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PreDiligenceLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PreDiligenceLab',
)

app = BUNDLE(
    coll,
    name='PreDiligenceLab.app',
    icon=None,
    bundle_identifier='com.prediligencethelab.app',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '20260615',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
