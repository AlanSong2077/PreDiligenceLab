"""
llm_client.py  —  统一 LLM 接口
支持：OpenAI / DeepSeek / 通义千问 / 任意 OpenAI 兼容接口
配置持久化到 ~/.stockreporter/llm_config.json

输出格式约束（从强到弱，自动降级）：
  1. Structured Outputs / json_schema  —— 字段名+类型+必填全部锁死（OpenAI gpt-4o+ 支持）
  2. json_object mode                  —— 保证合法 JSON，不约束字段（OpenAI/DeepSeek/custom）
  3. 纯 prompt 约束 + _repair_json     —— 所有模型兜底
"""

import json, os, re
from pathlib import Path

CONFIG_PATH = Path.home() / ".stockreporter" / "llm_config.json"

# ── Keyring 辅助（API Key 安全存储）────────────────────────────
_KEYRING_SERVICE = "PreDiligenceLab"
_KEYRING_USER    = "llm_api_key"

def _keyring_set(key: str):
    """将 API Key 写入系统密钥环；若 keyring 不可用则静默降级。"""
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, key)
        return True
    except Exception:
        return False

def _keyring_get() -> str:
    """从系统密钥环读取 API Key；失败返回空字符串。"""
    try:
        import keyring
        val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        return val or ""
    except Exception:
        return ""

def _keyring_available() -> bool:
    """检测 keyring 是否可用（已安装且后端正常）。"""
    try:
        import keyring
        keyring.get_password(_KEYRING_SERVICE, "__probe__")
        return True
    except Exception:
        return False

# 预设 provider 配置
PROVIDERS = {
    "openai": {
        "name":     "OpenAI (GPT-4o)",
        "base_url": "https://api.openai.com/v1",
        "model":    "gpt-4o-mini",
    },
    "deepseek": {
        "name":     "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model":    "deepseek-chat",
    },
    "qwen": {
        "name":     "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model":    "qwen-turbo",
    },
    "minimax": {
        "name":     "MiniMax (abab)",
        "base_url": "https://api.minimax.chat/v1",
        "model":    "abab6.5s-chat",
    },
    "custom": {
        "name":     "自定义 (OpenAI 兼容)",
        "base_url": "",
        "model":    "gpt-3.5-turbo",
    },
}


def load_config() -> dict:
    """加载持久化配置。
    api_key 优先从系统密钥环读取；若 keyring 不可用则回退到 JSON 文件中的明文值。
    """
    cfg = {"provider": "openai", "api_key": "", "base_url": "", "model": "", "enabled": False}
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    # 优先从 keyring 读取 api_key（覆盖 JSON 中可能残留的明文值）
    kr_key = _keyring_get()
    if kr_key:
        cfg["api_key"] = kr_key
    return cfg


def save_config(cfg: dict):
    """保存配置。
    api_key 写入系统密钥环（若可用），JSON 文件中不保存明文 key。
    若 keyring 不可用则降级写入 JSON（并在文件权限上尽力保护）。
    """
    api_key = cfg.get("api_key", "")
    # 尝试写入 keyring
    if api_key and _keyring_set(api_key):
        # keyring 成功：JSON 中存空字符串，不留明文
        cfg_to_save = {**cfg, "api_key": ""}
    else:
        # keyring 不可用：降级写入 JSON，并限制文件权限（仅 owner 可读）
        cfg_to_save = cfg

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg_to_save, ensure_ascii=False, indent=2), encoding="utf-8")
    # 限制文件权限为 600（仅 owner 读写），Windows 上此操作无效但不报错
    try:
        CONFIG_PATH.chmod(0o600)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Provider 能力表
# ─────────────────────────────────────────────────────────────

# 支持 json_object mode 的 provider
_JSON_MODE_PROVIDERS = {"openai", "deepseek", "custom"}

# 支持 Structured Outputs（json_schema）的模型前缀
# OpenAI: gpt-4o / gpt-4o-mini / o1 / o3 系列
# DeepSeek: deepseek-chat（v3 起支持，但字段约束不如 OpenAI 严格）
_SCHEMA_MODEL_PREFIXES = (
    "gpt-4o", "gpt-4-turbo", "o1", "o3",   # OpenAI
    "deepseek-chat",                          # DeepSeek v3+
)


def _supports_schema(provider: str, model: str) -> bool:
    """判断当前 provider+model 是否支持 json_schema Structured Outputs"""
    if provider not in _JSON_MODE_PROVIDERS:
        return False
    m = (model or "").lower()
    return any(m.startswith(p) for p in _SCHEMA_MODEL_PREFIXES)


# ─────────────────────────────────────────────────────────────
# 预定义 JSON Schema（同行业公司推荐）
# ─────────────────────────────────────────────────────────────

# 同行业公司列表的 Schema
PEER_LIST_SCHEMA = {
    "name": "peer_companies",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":   {"type": "string", "description": "公司中文或英文名称"},
                        "code":   {"type": "string", "description": "股票代码，不带后缀，如 AAPL / 00700 / 600519"},
                        "market": {"type": "string", "enum": ["美股", "港股", "A股"], "description": "上市市场"},
                        "reason": {"type": "string", "description": "与目标公司的相似点，20字以内"},
                    },
                    "required": ["name", "code", "market", "reason"],
                    "additionalProperties": False,
                },
                "minItems": 1,
                "maxItems": 10,
            }
        },
        "required": ["companies"],
        "additionalProperties": False,
    }
}


# ─────────────────────────────────────────────────────────────
# JSON 修复工具
# ─────────────────────────────────────────────────────────────

def _repair_json(text: str) -> str:
    """
    尝试修复常见的截断/格式问题：
    1. 去掉 markdown 代码块包裹
    2. 补全末尾缺失的 ] 或 }
    """
    t = text.strip()
    # 去掉 ```json ... ``` 或 ``` ... ```
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    t = t.strip()
    # 尝试直接解析
    try:
        json.loads(t)
        return t
    except Exception:
        pass
    # 补全末尾：找最后一个完整的 } 后面加 ]
    last_brace = t.rfind("}")
    if last_brace != -1:
        candidate = t[:last_brace + 1]
        # 如果以 [ 开头，补 ]
        if t.lstrip().startswith("["):
            candidate = candidate + "]"
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    return t


# ─────────────────────────────────────────────────────────────
# 核心客户端
# ─────────────────────────────────────────────────────────────

class LLMClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        provider = cfg.get("provider", "openai")
        preset   = PROVIDERS.get(provider, PROVIDERS["openai"])
        self.provider = provider
        self.api_key  = cfg.get("api_key", "")
        self.base_url = cfg.get("base_url") or preset["base_url"]
        self.model    = cfg.get("model")    or preset["model"]

    # ── 内部：构造 response_format ────────────────────────────
    def _response_format(self, json_mode: bool = False,
                         schema: dict = None) -> dict | None:
        """
        返回要注入 payload 的 response_format 字段，或 None（不注入）。
        优先级：schema > json_object > 不注入
        """
        if schema and _supports_schema(self.provider, self.model):
            # Structured Outputs：字段级强约束
            return {"type": "json_schema", "json_schema": schema}
        if json_mode and self.provider in _JSON_MODE_PROVIDERS:
            # json_object：保证合法 JSON
            return {"type": "json_object"}
        return None

    # ── 基础对话 ──────────────────────────────────────────────
    def chat(self, prompt: str, system: str = "", max_tokens: int = 1000,
             json_mode: bool = False, schema: dict = None) -> str:
        """
        发送对话请求，返回文本内容。
        schema   : 传入 PEER_LIST_SCHEMA 等预定义 Schema，启用 Structured Outputs
        json_mode: 无 schema 时退而求其次，启用 json_object mode
        """
        import requests as req
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       self.model,
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": 0.1,
        }
        fmt = self._response_format(json_mode=json_mode, schema=schema)
        if fmt:
            payload["response_format"] = fmt

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        last_err = None
        for attempt in range(2):   # 最多重试1次
            try:
                r = req.post(endpoint, headers=headers, json=payload, timeout=45)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                last_err = e
                if attempt == 0:
                    import time as _t; _t.sleep(1)   # 等1秒再重试
        raise RuntimeError(f"LLM 请求失败: {last_err}")

    # ── 多轮对话 ──────────────────────────────────────────────
    def chat_messages(self, messages: list, max_tokens: int = 2000,
                      json_mode: bool = False, schema: dict = None,
                      temperature: float = 0.7) -> str:
        """
        多轮对话接口：直接传入 messages 列表（含 system/user/assistant 角色）。
        schema    : 传入预定义 Schema，启用 Structured Outputs（优先于 json_mode）
        json_mode : 无 schema 时退而求其次，启用 json_object mode
        temperature: 默认 0.7；JSON 输出场景建议传 0.1
        """
        import requests as req
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       self.model,
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": temperature,
        }
        fmt = self._response_format(json_mode=json_mode, schema=schema)
        if fmt:
            payload["response_format"] = fmt

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        last_err = None
        for attempt in range(2):
            try:
                r = req.post(endpoint, headers=headers, json=payload, timeout=60)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                last_err = e
                if attempt == 0:
                    import time as _t; _t.sleep(1)
        raise RuntimeError(f"LLM 请求失败: {last_err}")

    # ── JSON 专用快捷方法 ─────────────────────────────────────
    def chat_json(self, prompt: str, system: str = "", max_tokens: int = 1000,
                  schema: dict = None) -> str:
        """
        专门用于需要 JSON 输出的场景。
        自动按优先级选择：Structured Outputs > json_object > prompt约束
        返回修复后的 JSON 字符串。
        """
        raw = self.chat(prompt, system=system, max_tokens=max_tokens,
                        json_mode=True, schema=schema)
        return _repair_json(raw)

    # ── 连接测试 ──────────────────────────────────────────────
    def test_connection(self) -> tuple:
        """测试连接，返回 (ok: bool, msg: str)"""
        try:
            resp = self.chat("请回复'OK'", max_tokens=10)
            schema_support = _supports_schema(self.provider, self.model)
            extra = "（支持 Structured Outputs）" if schema_support else ""
            return True, f"连接成功，模型: {self.model}{extra}"
        except Exception as e:
            return False, str(e)
