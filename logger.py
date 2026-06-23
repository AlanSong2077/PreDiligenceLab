"""
logger.py — 全局日志配置
日志文件：~/.stockreporter/app.log（按大小轮转，最多 3 个备份，每个 2MB）
用法：
    from logger import get_logger
    log = get_logger(__name__)
    log.info("...")
    log.error("...", exc_info=True)   # 自动附带堆栈
"""

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR  = Path.home() / ".stockreporter"
_LOG_FILE = _LOG_DIR / "app.log"
_INITIALIZED = False


def _init():
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("stockreporter")
    root.setLevel(logging.DEBUG)

    # ── 文件 Handler（轮转，2MB × 3）────────────────────────────
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)

    # ── 控制台 Handler（仅 WARNING 以上）────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s  %(name)s  %(message)s"))
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """获取以 'stockreporter.<name>' 为命名空间的 logger"""
    _init()
    # 去掉文件路径前缀，只保留模块名
    short = name.split(".")[-1] if "." in name else name
    return logging.getLogger(f"stockreporter.{short}")
