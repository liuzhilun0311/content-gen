"""Read allowlisted local runtime paths without changing process environment."""

import os
from pathlib import Path
import re


CONFIG = Path(__file__).resolve().parent.parent / "config" / ".env"
RUNTIME_KEYS = frozenset(("SANBAO_NODE", "SANBAO_MARKED", "SANBAO_PLAYWRIGHT", "SANBAO_BROWSER"))


def read_runtime_config(path=None):
    source = Path(path) if path is not None else CONFIG
    if not source.exists():
        return {}
    values = {}
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*", line)
        if not match or match[1] not in RUNTIME_KEYS:
            continue
        value = match[2]
        quoted = re.fullmatch(r"""(["'])(.*?)\1\s*(?:#.*)?""", value)
        values[match[1]] = quoted[2] if quoted else re.sub(r"\s+#.*$", "", value).strip()
    return values


def runtime_value(name, default=None):
    if name not in RUNTIME_KEYS:
        raise ValueError("Unsupported local runtime setting")
    value = os.environ[name] if name in os.environ else read_runtime_config().get(name)
    return value or default
