"""Khoá API sàn (E9-S7): nạp từ biến môi trường hoặc file ngoài repo (~/.config/nora/binance_testnet.env, quyền 600). Không bao giờ ghi
khoá / chữ ký vào log, payload hay result.json (redact)."""
import os
import re
import stat
from typing import Dict, Optional, Tuple

DEFAULT_FILE = os.path.expanduser("~/.config/nora/binance_testnet.env")
KEY_ENV, SECRET_ENV = "NORA_BINANCE_TESTNET_KEY", "NORA_BINANCE_TESTNET_SECRET"


def _parse(path: str) -> Dict[str, str]:
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_keys(path: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """(key, secret) hoặc None. File phải chỉ chủ sở hữu đọc được (600) — lỏng hơn thì từ chối."""
    key, sec = os.environ.get(KEY_ENV), os.environ.get(SECRET_ENV)
    if key and sec:
        return key, sec
    path = path or os.environ.get("NORA_BINANCE_KEYS_FILE") or DEFAULT_FILE
    if not os.path.isfile(path):
        return None
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise PermissionError(f"{path}: quyền {oct(mode)} quá lỏng — chmod 600")
    d = _parse(path)
    key, sec = d.get(KEY_ENV), d.get(SECRET_ENV)
    return (key, sec) if key and sec else None


OKX_FILE = os.path.expanduser("~/.config/nora/okx.env")
OKX_ENV = ("NORA_OKX_KEY", "NORA_OKX_SECRET", "NORA_OKX_PASSPHRASE")


def load_okx(path: Optional[str] = None) -> Optional[Tuple[Tuple[str, str, str], bool]]:
    """((key, secret, passphrase), demo) hoặc None. Biến môi trường hoặc ~/.config/nora/okx.env (quyền 600). NORA_OKX_DEMO=1 (mặc định):
    khoá Demo Trading; =0: khoá tài khoản thật."""
    vals = {k: os.environ.get(k) for k in OKX_ENV + ("NORA_OKX_DEMO",)}
    if not all(vals[k] for k in OKX_ENV):
        path = path or os.environ.get("NORA_OKX_KEYS_FILE") or OKX_FILE
        if not os.path.isfile(path):
            return None
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            raise PermissionError(f"{path}: quyền {oct(mode)} quá lỏng — chmod 600")
        vals.update({k: v for k, v in _parse(path).items() if k in vals})
    if not all(vals.get(k) for k in OKX_ENV):
        return None
    return tuple(vals[k] for k in OKX_ENV), str(vals.get("NORA_OKX_DEMO") or "1").strip() != "0"


_HEX = re.compile(r"[A-Za-z0-9]{32,}")


def redact(text: str, keys: Optional[Tuple[str, str]] = None) -> str:
    """Thay khoá / chữ ký / chuỗi dài giống khoá bằng ***."""
    s = str(text)
    for k in keys or ():
        if k:
            s = s.replace(k, "***")
    s = re.sub(r"signature=[0-9a-fA-F]+", "signature=***", s)
    return _HEX.sub("***", s)
