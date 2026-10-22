"""Backend của Nora: API FastAPI, core NautilusTrader, analys (alpha, signal, param, position, metrics, validation, result), adapter."""
import sys
import importlib
import importlib.abc
import importlib.util


# ─── BỘ CHUYỂN HƯỚNG TƯƠNG THÍCH NGƯỢC (Zero clutter, không duplicate file) ───
class _LegacyAliasLoader(importlib.abc.Loader):
    def __init__(self, target_module):
        self._target_module = target_module

    def create_module(self, spec):
        return self._target_module

    def exec_module(self, module):
        pass


class _LegacyAliasFinder(importlib.abc.MetaPathFinder):
    """Tự động ánh xạ các module cũ vào các module chuẩn mới mà không cần giữ file rác trên đĩa."""
    _ALIASES = {
        "backend.nautilus": "backend.core",
        "backend.signal": "backend.analys.signal",
        "backend.indicator": "backend.analys.indicator",
        "backend.metrics": "backend.analys.metrics",
        "backend.alpha": "backend.analys.alpha",
        "backend.strategies": "backend.analys.alpha.strategies",
        "backend.carlo": "backend.analys.validation.carlo",
        "backend.wfa": "backend.analys.validation.wfa",
        "backend.models.params": "backend.analys.param.params",
        "backend.models.position_size": "backend.analys.position.position_size",
        "backend.signal.indicator": "backend.analys.indicator.indicator",
        "backend.jobs.workers": "backend.jobs.worker",
        "backend.routes.alpha": "backend.routes.studio",
        "backend.routes.book": "backend.routes.studio",
        "backend.routes.users": "backend.routes.system",
    }


    def find_spec(self, fullname, path, target=None):
        for prefix, target_prefix in self._ALIASES.items():
            if fullname == prefix:
                try:
                    mod = importlib.import_module(target_prefix)
                    return importlib.util.spec_from_loader(fullname, _LegacyAliasLoader(mod))
                except Exception:
                    return None
            elif fullname.startswith(prefix + "."):
                sub = fullname[len(prefix) + 1:]
                if prefix == "backend.nautilus" and sub in ("live", "live_ledger"):
                    target_fullname = "backend.adapter.exchange"
                elif prefix == "backend.carlo" and sub == "carlo":
                    target_fullname = "backend.analys.validation.carlo.carlo"
                elif prefix == "backend.wfa" and sub == "wfa":
                    target_fullname = "backend.analys.validation.wfa.wfa"
                elif prefix == "backend.nautilus" and sub == "stats":
                    target_fullname = "backend.analys.metrics.stats"
                elif prefix == "backend.nautilus" and sub == "results":
                    target_fullname = "backend.analys.result.format"
                elif prefix == "backend.nautilus" and sub == "signals":
                    target_fullname = "backend.analys.signal.signal"
                elif prefix == "backend.nautilus" and sub == "version":
                    target_fullname = "backend.core"
                elif prefix == "backend.alpha" and sub in ("compile", "contract", "plan", "route"):
                    target_fullname = f"backend.analys.alpha.code.{sub}"
                elif prefix == "backend.alpha" and sub in ("llm", "research"):
                    target_fullname = f"backend.analys.alpha.prompt.{sub}"
                elif prefix == "backend.alpha" and sub in ("store", "strategies"):
                    target_fullname = "backend.analys.alpha.strategies"
                elif prefix == "backend.signal" and sub in ("nodes", "signals"):
                    target_fullname = "backend.analys.signal.signal"
                elif prefix == "backend.signal" and sub == "indicator":
                    target_fullname = "backend.analys.indicator.indicator"
                else:
                    target_fullname = target_prefix + "." + sub
                try:
                    mod = importlib.import_module(target_fullname)
                    return importlib.util.spec_from_loader(fullname, _LegacyAliasLoader(mod))
                except Exception:
                    return None
        return None


if not any(isinstance(finder, _LegacyAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _LegacyAliasFinder())


from backend.models.models import set_default_data_factory as _set_factory


def _engine_data_factory():
    from backend.data.data import make_engine_data
    return make_engine_data()


_set_factory(_engine_data_factory)
