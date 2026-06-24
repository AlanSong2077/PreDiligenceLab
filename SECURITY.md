# Security Policy

## Supported Versions


## Reporting a Vulnerability

**Please do NOT open a public GitHub Issue for security vulnerabilities.**

Report privately via one of:

- GitHub Security Advisories: <https://github.com/AlanHermitSoong/PreDiligenceLab/security/advisories/new>
- Email: <121917266+AlanHermitSoong@users.noreply.github.com>（GitHub noreply，可改在 GitHub 上直接 DM maintainer）

请在报告里包含漏洞描述与影响范围、复现步骤 / PoC、涉及版本 / commit SHA、是否有已知的修复方案，我们会在 7 个工作日内回复。

## 安全设计说明

- **密钥存储**：所有 API Key 清写入**系统密钥**（macOS Keychain / Windows Credential Vault）；JSON 备份文件权限设为 600，**禁止写入源码或日志**。
- **网络请求**：所有外部请求走 `requests` / `urllib3`，未引入额外的不安全依赖；TLS 校验默认开启。
- **本地数据**：用户配置、收藏、下载的 PDF 均存储在 `~/.prediligencelab/`，**不上传任何服务端**。
