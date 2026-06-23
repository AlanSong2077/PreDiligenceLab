# Pre-Diligence Lab

> 一级市场（私募 / Pre-IPO / 硬科技）投研与风控桌面工作台
> PyQt6 GUI | 多数据源聚合 | 内置尽调框架与 LLM 增强分析

---

## 项目定位

面向**一级市场投研人员**的本地化工作台，覆盖以下场景：

- **上市公司公开数据查询**：美股 (SEC EDGAR)、港股 (HKEXnews)、A 股 (巨潮资讯 / 东方财富)
- **行业对标分析**：跨市场同业财务指标横向对比
- **尽调框架内置**：硬科技 / 半导体 / AI 行业的财务风险深度分析框架（见 `hardtech-risk-analysis/SKILL.md`）
- **辅助分析**：可选接入 OpenAI / DeepSeek / 通义千问 等 OpenAI 兼容 LLM，用于尽调问答与文本结构化
- **本地数据存储**：用户输入、收藏、配置全部落盘本地（`~/.prediligencelab/`），不上传服务端

> 本项目不抓取非公开信息，所有数据源均为**公开可访问**的金融信息披露平台。

---

## 功能模块

| 模块 | 说明 | 入口 |
|------|------|------|
| 公司资料查询 | 工商信息、董监高、联系方式、所属行业 | `biz_info_panel.py` |
| 财报与财务计算 | TTM / 季度 / 年度数据，财务比率计算 | `fin_calc.py` + `fin_calc_panel.py` |
| 年报 / 公告下载 | 美股 10-K、港股年报、A 股年报 PDF | `fetcher.py` |
| 同行业对标 | 跨市场同业公司扫描 + 指标对比 | `peer_scanner.py` |
| 尽调框架 | 内置硬科技风险分析 Skill | `due_diligence_panel.py` + `dd_form_panel.py` |
| 私募基金查询 | 中基协 AMAC 公开数据 | `amac_panel.py` + `amac_fund.py` |
| 新闻聚合 | 多源新闻抓取（百度 / 搜狗 / 东方财富 / Google RSS / Yahoo） | `news_fetcher.py` + `web_search.py` |
| K 线 / 行情 | yfinance 数据 + Matplotlib 图表 | `analytics.py` |

---

## 系统要求

- **Python**：3.10 ~ 3.12（PyQt6 在 3.13 上可能有 wheel 缺失问题，推荐 3.11）
- **操作系统**：macOS 11+ / Windows 10+ / Ubuntu 20.04+
- **依赖**：见 <filepath>requirements.txt</filepath>

### 第三方数据源（外部依赖）

- SEC EDGAR（美股）
- HKEXnews（港股）
- 巨潮资讯 / 东方财富（A 股）
- 中基协 AMAC（私募基金）
- 百度 / 搜狗 / Bing / Google RSS（新闻）
- Yahoo Finance（行情）

> 这些数据源**非本项目运营方**，使用时请遵守各源的 ToS 与限流规则。

---

## 快速开始

### 方式 A：下载预编译可执行文件（推荐普通用户）

到 [Releases](https://github.com/AlanHermitSoong/PreDiligenceLab/releases) 下载：

- **Windows**：`PreDiligenceLab-Setup-x.y.z.exe` 一键安装版，或 `PreDiligenceLab-x.y.z-windows-x64.zip` 绿色版
- **macOS**：`PreDiligenceLab-x.y.z-macOS.zip`（解压后将 `.app` 拖入 `/Applications`）

### 方式 B：从源码运行（开发者）

```bash
git clone https://github.com/AlanHermitSoong/PreDiligenceLab.git
cd PreDiligenceLab
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 方式 C：从源码本地打包

**macOS**

```bash
chmod +x build_mac.sh
./build_mac.sh
# 产出：dist/PreDiligenceLab.app
```

**Windows**

```bat
:: 需要先安装 Inno Setup 6（https://jrsoftware.org/isdl.php）
build_win.bat
:: 产出：dist\PreDiligenceLab\PreDiligenceLab.exe
::        dist\PreDiligenceLab_Setup.exe（安装包）
```

---

## 项目结构

```
PreDiligenceLab/
├── main.py                       # GUI 入口（PyQt6 主窗口）
├── theme.py                      # 颜色 / 主题常量
├── logger.py                     # 日志（轮转落盘到 ~/.prediligencelab/）
├── fetcher.py                    # SEC / cninfo 年报下载
├── sec_edgar.py                  # 美股 EDGAR API 封装
├── hkex.py                       # 港交所披露易
├── amac_fund.py / amac_panel.py  # 中基协私募
├── fin_calc.py / fin_calc_panel.py  # 财务计算与展示
├── analytics.py                  # 行情 / 图表
├── peer_scanner.py               # 同业扫描
├── news_fetcher.py               # 新闻聚合
├── web_search.py                 # 多源搜索
├── biz_lookup.py / biz_info_panel.py  # 工商信息
├── due_diligence_panel.py / dd_form_panel.py  # 尽调表单
├── llm_client.py                 # OpenAI 兼容 LLM 客户端（可选）
├── market_utils.py               # 行情辅助
├── industry_benchmarks.py        # 行业基准数据
├── PreDiligenceLab.spec          # PyInstaller macOS 打包配置
├── build_mac.sh                  # macOS 一键打包
├── build_win.bat                 # Windows 一键打包 + Inno Setup
├── installer.iss                 # Windows 安装脚本
├── fin_calc_template.md          # 财报模板
├── hardtech-risk-analysis/       # 硬科技尽调框架（Skill）
│   ├── SKILL.md
│   └── examples.md
├── requirements.txt
├── LICENSE                       # Apache-2.0
├── README.md
├── .gitignore
└── .github/
    ├── workflows/
    │   ├── build.yml             # CI：PR / push 验证
    │   └── release.yml           # 发版：tag 触发构建
    ├── ISSUE_TEMPLATE/
    ├── PULL_REQUEST_TEMPLATE.md
    ├── CODEOWNERS
    └── SECURITY.md
```

---

## LLM 配置（可选）

应用启动后，进入 **设置 → LLM 配置**，选择 provider（OpenAI / DeepSeek / 通义千问 / 自定义 OpenAI 兼容）并填入 API Key。Key 优先存入**系统密钥环**（macOS Keychain / Windows Credential Vault），JSON 备份文件权限 600。**不会上传到任何服务端**。

不使用 LLM 也能跑（所有数据抓取、计算、图表都不依赖 LLM），只是失去尽调问答的辅助能力。

---

## 贡献

欢迎 Issue / PR。提 PR 前：

1. Fork → 新建分支 `feat/xxx` 或 `fix/xxx`
2. 跑通 `python main.py` 与 `pip install -r requirements.txt` 验证依赖完整
3. 提交信息格式：`type(scope): subject`（如 `fix(fetcher): 修复 SEC 限流时的重试`）
4. 描述里附上你验证的方式（截屏 / 命令行输出）

详见 <filepath>.github/PULL_REQUEST_TEMPLATE.md</filepath>。

---

## 许可证

本项目基于 **Apache License 2.0** 开源，详见 <filepath>LICENSE</filepath>。

第三方数据归各自运营方所有；本项目仅做**公开数据聚合**与**本地分析**，不提供任何投资建议。

---

## 免责声明

本项目为**研究 / 教学 / 内部投研辅助工具**，不构成任何投资建议。使用者应自行核实所有数据，并对投资决策负全部责任。
