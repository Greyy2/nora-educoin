#!/usr/bin/env python3
"""Make the frozen 57 EDU user-alpha records explicit without running jobs."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EDU_ROOT = ROOT / "nora/edu"
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha.code.compile import compile_code  # noqa: E402
from backend.analys.indicator import FEATURES, OPS  # noqa: E402
from backend.analys.param import (  # noqa: E402
    BASE_POSITION,
    NORA_DEFAULTS,
    POSITION_KEYS,
    RISK,
    StrategyParams,
    resolve_costs,
    resolve_position_auto,
)


USER_ALPHA_DIR = EDU_ROOT / "data/alpha/user"
MANIFEST_PATH = ROOT / "nora/check/edu_alpha_57_explicit_contracts_20261028.json"
CONTRACT_VERSION = "edu-alpha-explicit-contract-v1"

LEGACY_CONTRACTS: dict[str, tuple[str, str]] = {
    "0873864b8db7": ("DEMA trend reclaim with macro filter", "Price crossing above DEMA is accepted only above a slower EMA; the DEMA recross is the structural exit."),
    "090730ae35b8": ("Standard-deviation channel breakout", "A close breakout through the moving-average plus deviation band is accepted only above the macro EMA; loss of the center average exits."),
    "0d51ba8d2012": ("OBV accumulation with RSI confirmation", "OBV above its own SMA is combined with an RSI midline cross; the RSI falling below its exit level closes the long."),
    "14e3b934b1e5": ("ROC momentum exhaustion", "Positive ROC above its entry threshold is accepted above the EMA; negative ROC or loss of the EMA invalidates the position."),
    "15567e02a806": ("Triple-EMA trend alignment", "A fast/mid EMA bullish cross is admitted only when price is above the long EMA; price crossing below the fast EMA exits."),
    "18e87aa868ad": ("Fast standard-deviation channel breakout", "A close breakout through the 18-bar deviation channel is admitted above the macro EMA; loss of the center average exits."),
    "270e6e28416f": ("Rising-EMA trend continuation", "Price must be above a rising short EMA and the macro EMA; a close below the short EMA exits."),
    "303d4b713dda": ("Macro-filtered deviation-channel breakout", "A close breakout through the deviation channel is admitted above a 105-bar EMA; loss of the center average exits."),
    "33312a2f4dfc": ("Regime-filtered deviation-channel breakout", "A close breakout through the 20-bar deviation channel is admitted above the macro EMA; loss of the center average exits."),
    "3cfcc2d296a2": ("Donchian support ratchet", "Price crossing above the EMA opens a long; closing below the rolling lower channel exits."),
    "4f28285aa44c": ("Dual-EMA crossover with ADX strength", "A bullish fast/slow EMA cross is accepted only while ADX exceeds its trend-strength threshold; a bearish EMA cross exits."),
    "541c55834f56": ("Wide bullish range expansion", "An unusually wide bullish bar above the SMA opens a long; a bearish cross below the SMA exits."),
    "5e52d3fdf71f": ("Bollinger midline entry with overextension exit", "A cross above the Bollinger middle band opens a long; the upper band is a profit-taking exit and loss of the middle band is a defensive exit."),
    "6055aa8f661e": ("Three-screen EMA/MACD/RSI confluence", "The long EMA defines the trend, positive MACD line confirms direction, and an RSI midline cross times entry; falling below the EMA exits."),
    "6afa7f774655": ("Oversold RSI with fast-SMA reclaim", "RSI must be below its oversold threshold as price crosses above a fast SMA; RSI above the recovery threshold exits."),
    "715e56a6dd33": ("Linear-regression lower-band reversion", "A reclaim of the regression estimate minus a standard-deviation envelope opens a long; crossing above the regression estimate exits."),
    "717c1890c59e": ("WMA crossover with macro trend filter", "A fast/slow WMA bullish cross is accepted above the macro EMA; price crossing below the fast WMA exits."),
    "7f3486d63ca8": ("Dual-oscillator overbought exit", "Price crossing above its SMA opens a long; simultaneous RSI and stochastic overbought conditions or loss of the SMA exits."),
    "7f67e9aed0aa": ("RSI/stochastic recovery confluence", "An RSI cross above its entry threshold requires stochastic %K above %D; RSI above its exit threshold closes."),
    "89379cc0ab52": ("Stochastic %K/%D oversold cross", "A bullish %K/%D cross below the oversold ceiling opens a long; a bearish cross above the exit level closes."),
    "8a47cdbcc942": ("RSI dip recovery with trend filters", "A recovering RSI cross is accepted only above both the short SMA and macro EMA; elevated RSI or a price cross below the SMA exits."),
    "b4b65cd3493f": ("CCI oversold snapback", "CCI crossing upward through the oversold threshold opens a long; CCI crossing above the upper exit threshold closes."),
    "b96bafe57445": ("NATR expansion with trend filter", "A NATR threshold cross is accepted above the EMA; closing below the EMA exits."),
    "bf519617d973": ("DEMA trend reclaim with macro filter", "Price crossing above DEMA is accepted only above a slower EMA; the DEMA recross is the structural exit."),
    "c33cc317bbeb": ("Cumulative-return selloff snapback", "A multi-bar return below the selloff threshold is bought only after a higher close; recovery above the return exit threshold closes."),
    "cb750cb1eb10": ("Volume-confirmed EMA golden cross", "A fast/slow EMA bullish cross requires a positive volume z-score; closing below the slow EMA exits."),
    "efb1fbe2db86": ("Volatility-expansion channel breakout", "A close breakout through a deviation channel is admitted above the macro EMA; loss of the center average exits."),
    "f261549d9efa": ("ROC acceleration with trend filter", "ROC crossing upward through its momentum threshold is accepted above the EMA; ROC crossing below zero exits."),
    "f4e211e9510d": ("Rolling multi-week high breakout", "A close above the prior rolling high opens a long; closing below the SMA exits."),
    "fa9587a97fa9": ("Trend-aligned deviation-channel breakout", "A close breakout through the deviation channel is admitted above the macro EMA; loss of the center average exits."),
}

CALL_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "stddev": {"timeperiod": "std_period", "nbdev": "std_nbdev"},
    "bbands": {
        "timeperiod": "bbands_period",
        "nbdevup": "bbands_upper_mult",
        "nbdevdn": "bbands_lower_mult",
    },
    "stoch": {
        "fastk_period": "stoch_k_period",
        "slowk_period": "stoch_k_smooth",
        "slowk_matype": "stoch_slowk_matype",
        "slowd_period": "stoch_d_period",
        "slowd_matype": "stoch_slowd_matype",
    },
    "volume_z": {"timeperiod": "vol_z_period"},
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def numeric_literal(node: ast.AST) -> int | float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = numeric_literal(node.operand)
        if value is not None:
            return -value if isinstance(node.op, ast.USub) else value
    return None


def node_source(code: str, node: ast.AST) -> str:
    return ast.get_source_segment(code, node) or ast.unparse(node)


def node_offset(lines: list[str], lineno: int, byte_col: int) -> int:
    prefix = lines[lineno - 1].encode("utf-8")[:byte_col].decode("utf-8")
    return sum(len(line) for line in lines[: lineno - 1]) + len(prefix)


def class_and_method(tree: ast.Module) -> tuple[ast.ClassDef, ast.FunctionDef]:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError(f"Expected one strategy class, found {len(classes)}")
    methods = [
        node for node in classes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == "on_bar"
    ]
    if len(methods) != 1:
        raise ValueError(f"{classes[0].name}: expected exactly one on_bar")
    return classes[0], methods[0]


def class_numeric_attrs(cls: ast.ClassDef) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for stmt in cls.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        try:
            result[stmt.targets[0].id] = ast.literal_eval(stmt.value)
        except (ValueError, TypeError):
            continue
    return result


def method_path(call: ast.Call) -> str:
    node: ast.AST = call.func
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def expression_stem(node: ast.AST) -> str:
    ignored = {"close", "open", "high", "low", "volume", "self"}
    names = [item.id for item in ast.walk(node) if isinstance(item, ast.Name) and item.id not in ignored]
    return re.sub(r"[^A-Za-z0-9_]", "_", names[0] if names else "signal").strip("_") or "signal"


def assignment_role(name: str) -> str:
    lower = name.lower()
    if "exit" in lower or "close" in lower or lower.startswith(("lx", "sx")):
        return "exit"
    if "enter" in lower or "entry" in lower or "buy" in lower or lower.startswith(("le", "se")):
        return "entry"
    return "signal"


class SignalParameterizer(ast.NodeVisitor):
    def __init__(self, code: str, cls: ast.ClassDef):
        self.code = code
        self.lines = code.splitlines(keepends=True)
        self.existing_attrs = class_numeric_attrs(cls)
        self.new_attrs: dict[str, Any] = {}
        self.generated: dict[str, dict[str, Any]] = {}
        self.edits: list[tuple[int, int, str]] = []
        self.owner = "signal"

    def _parameter_name(self, candidate: str, value: Any) -> str:
        name = re.sub(r"[^A-Za-z0-9_]", "_", candidate).strip("_").lower() or "signal_parameter"
        if name[0].isdigit():
            name = f"signal_{name}"
        if name in POSITION_KEYS:
            name = f"signal_{name}"
        if name in self.existing_attrs and self.existing_attrs[name] == value:
            return name
        if name in self.new_attrs and self.new_attrs[name] == value:
            return name
        if name in self.existing_attrs or name in self.new_attrs:
            name = f"{name}_signal"
        suffix = 2
        base = name
        while (name in self.existing_attrs and self.existing_attrs[name] != value) or (
            name in self.new_attrs and self.new_attrs[name] != value
        ):
            name = f"{base}_{suffix}"
            suffix += 1
        return name

    def _add_literal_parameter(
        self,
        node: ast.AST,
        *,
        candidate: str,
        value: int | float,
        kind: str,
        unit: str,
        expression: str,
    ) -> None:
        name = self._parameter_name(candidate, value)
        existing_value = self.existing_attrs.get(name, self.new_attrs.get(name))
        if existing_value != value:
            self.new_attrs[name] = value
            self.generated[name] = {
                "name": name,
                "value": value,
                "kind": kind,
                "unit": unit,
                "expression": expression,
            }
        start = node_offset(self.lines, node.lineno, node.col_offset)
        end = node_offset(self.lines, node.end_lineno, node.end_col_offset)
        self.edits.append((start, end, f"self.{name}"))

    def visit_Assign(self, node: ast.Assign) -> None:
        previous = self.owner
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        self.owner = assignment_role(names[0]) if names else "signal"
        self.visit(node.value)
        self.owner = previous

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        previous = self.owner
        self.owner = assignment_role(node.target.id) if isinstance(node.target, ast.Name) else "signal"
        if node.value is not None:
            self.visit(node.value)
        self.owner = previous

    def _threshold_name(self, stem: str) -> str:
        suffix = {"entry": "enter_level", "exit": "exit_level"}.get(self.owner, "signal_level")
        return f"{stem}_{suffix}"

    def visit_Call(self, node: ast.Call) -> None:
        name = method_path(node).split(".")[-1]
        spec = FEATURES.get(name) or OPS.get(name)
        params = getattr(spec, "params", ()) if spec else ()
        for index, (arg, param) in enumerate(zip(node.args, params)):
            value = numeric_literal(arg)
            if value is None:
                continue
            param_kind = getattr(param, "kind", "")
            param_name = getattr(param, "name", f"arg_{index + 1}")
            if param_kind not in {"int", "float", "matype"}:
                continue
            if param_name == "value" and name in {"crossed_above_value", "crossed_below_value"}:
                candidate = self._threshold_name(expression_stem(node.args[0]))
                unit = "native units of the crossed signal"
                kind = "entry_threshold" if self.owner == "entry" else "exit_threshold" if self.owner == "exit" else "signal_threshold"
            else:
                candidate = CALL_PARAM_ALIASES.get(name, {}).get(param_name)
                if candidate is None:
                    suffix = {
                        "timeperiod": "period",
                        "window": "period",
                        "periods": "lag_bars",
                        "matype": "matype",
                    }.get(param_name, param_name)
                    candidate = f"{name}_{suffix}"
                unit = "bars" if param_kind == "int" else "indicator multiplier" if param_name in {"nbdev", "nbdevup", "nbdevdn"} else "TA moving-average type code" if param_kind == "matype" else "same units as the production indicator parameter"
                kind = "lookback" if param_kind == "int" else "indicator_parameter"
            self._add_literal_parameter(
                arg,
                candidate=candidate,
                value=value,
                kind=kind,
                unit=unit,
                expression=node_source(self.code, node),
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        self.generic_visit(node.left)
        for comparator in node.comparators:
            value = numeric_literal(comparator)
            if value is None:
                self.visit(comparator)
                continue
            self._add_literal_parameter(
                comparator,
                candidate=self._threshold_name(expression_stem(node.left)),
                value=value,
                kind=f"{self.owner}_threshold",
                unit="native units of the compared expression",
                expression=node_source(self.code, node),
            )

    def parameterize(self, method: ast.FunctionDef) -> tuple[str, dict[str, dict[str, Any]]]:
        for stmt in method.body:
            self.visit(stmt)
        code = self.code
        for start, end, replacement in sorted(self.edits, reverse=True):
            code = code[:start] + replacement + code[end:]
        return code, self.generated


def position_default_map() -> dict[str, Any]:
    base = StrategyParams()
    defaults = {key: getattr(base, key) for key in POSITION_KEYS}
    defaults.update(BASE_POSITION)
    defaults.update(NORA_DEFAULTS)
    return defaults


def normalize_ir(value: Any, *, erase_numbers: bool = False) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "<number>" if erase_numbers else value
    if isinstance(value, (str, type(None))):
        return value
    if isinstance(value, dict):
        return {key: normalize_ir(item, erase_numbers=erase_numbers) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [normalize_ir(item, erase_numbers=erase_numbers) for item in value]
    if hasattr(value, "bound") and hasattr(value, "spec"):
        return {
            "type": type(value).__name__,
            "kind": value.kind,
            "feature": value.is_feature,
            "function": value.spec.name,
            "bound": normalize_ir(value.bound, erase_numbers=erase_numbers),
        }
    if hasattr(value, "col_name"):
        return {"type": type(value).__name__, "column": value.col_name}
    if hasattr(value, "value"):
        return {
            "type": type(value).__name__,
            "value": normalize_ir(value.value, erase_numbers=erase_numbers),
        }
    if hasattr(value, "op") and hasattr(value, "a"):
        result = {"type": type(value).__name__, "op": value.op, "a": normalize_ir(value.a, erase_numbers=erase_numbers)}
        if hasattr(value, "b"):
            result["b"] = normalize_ir(value.b, erase_numbers=erase_numbers)
        return result
    if hasattr(value, "call") and hasattr(value, "idx"):
        return {"type": type(value).__name__, "call": normalize_ir(value.call, erase_numbers=erase_numbers), "idx": value.idx}
    raise TypeError(f"Unsupported signal IR node: {type(value).__name__}")


def program_signature(program: Any, *, erase_numbers: bool = False) -> dict[str, Any]:
    return {
        "timeframe": program.timeframe,
        "calls": [
            {"mask": normalize_ir(mask, erase_numbers=erase_numbers), "position": normalize_ir(level, erase_numbers=erase_numbers)}
            for mask, level, _line in program.calls
        ],
        "open_times": program.open_times,
        "open_ranges": program.open_ranges,
        "close_ranges": program.close_ranges,
        "features": program.features,
        "ops": program.ops,
        "columns": program.columns,
    }


def action_expressions(code: str) -> list[dict[str, Any]]:
    tree = ast.parse(code)
    cls, method = class_and_method(tree)
    actions: list[dict[str, Any]] = []
    for stmt in method.body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "self":
                continue
            action = node.func.attr
            if action not in {"buy", "sell", "close", "close_position", "set_position", "set_positions"}:
                continue
            condition = node.args[0] if node.args else None
            if condition is None:
                continue
            position: float | None
            if action in {"buy", "sell", "close", "close_position"}:
                position = {"buy": 1.0, "sell": -1.0, "close": 0.0, "close_position": 0.0}[action]
            else:
                target = node.args[1] if len(node.args) > 1 else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "position"), None
                )
                position = numeric_literal(target) if target is not None else None
            actions.append({
                "action": action,
                "position": position,
                "expression": node_source(code, condition),
                "line": node.lineno,
            })
    actions.sort(key=lambda item: item["line"])
    return actions


def all_class_attrs(cls: ast.ClassDef) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            try:
                result[stmt.targets[0].id] = ast.literal_eval(stmt.value)
            except (ValueError, TypeError):
                continue
    return result


def referenced_self_attrs(method: ast.FunctionDef) -> set[str]:
    return {
        node.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
        and node.attr not in {"data", "feat", "op"}
    }


def parameter_unit(name: str, value: Any) -> str:
    lower = name.lower()
    if "matype" in lower:
        return "TA moving-average type code (0 = simple)"
    if lower.endswith(("_period", "_bars", "_lag")) or "period" in lower or "lag_bars" in lower:
        return "bars on the declared signal timeframe"
    if any(token in lower for token in ("threshold", "level")):
        return "native units of the compared expression"
    if any(token in lower for token in ("mult", "nbdev", "factor")):
        return "dimensionless multiplier"
    return "declared code-level constant; see source expression"


def position_unit_map(position: dict[str, Any]) -> dict[str, str]:
    exit_unit = position.get("exit_unit", "pct")
    exit_measure = "ATR multiple" if exit_unit == "atr" else "percent"
    return {
        "stop_loss_rate": exit_measure,
        "take_profit_rate": exit_measure,
        "trailing_stop": exit_measure,
        "trailing_activation_pct": exit_measure,
        "timeout": "minutes",
        "cooldown": "minutes",
        "risk_per_trade_pct": "percent of equity at stop",
        "max_notional_pct": "percent of equity notional cap",
        "leverage": "x",
        "atr_period": "bars",
        "atr_frame": "timeframe",
        "fee_rate": "fraction per taker side",
        "maker_fee_rate": "fraction per maker side",
        "slippage_rate": "fraction per side",
        "limit_through_pct": "percent through limit level",
        "max_open_trades": "concurrent trades",
        "dca_step_pct": "percent",
        "dca_max_layers": "additional layers",
        "dca_size_multiplier": "dimensionless multiplier",
        "maintenance_margin_rate": "fraction",
    }


def _literal_source(value: Any) -> str:
    return repr(value)


def normalize_code(
    code: str,
    position: dict[str, Any],
    cls: ast.ClassDef,
    method: ast.FunctionDef,
    generated_params: dict[str, dict[str, Any]],
) -> str:
    tree = ast.parse(code)
    cls, method = class_and_method(tree)
    position_aliases = set(POSITION_KEYS)
    from backend.analys.signal import RISK_PARAM_MAP

    position_aliases.update(RISK_PARAM_MAP)
    method_refs = referenced_self_attrs(method)
    lines = code.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        name = stmt.targets[0].id
        if name not in position_aliases or name in method_refs:
            continue
        start_line = stmt.lineno - 1
        start = sum(len(line) for line in lines[:start_line])
        end_line = stmt.end_lineno
        end = sum(len(line) for line in lines[:end_line])
        edits.append((start, end, ""))
    for line_no, line in enumerate(lines, start=1):
        if line.strip() in {
            "# Signal parameters lifted from inline numeric arguments.",
            "# Effective position/execution contract, mirrored in the saved config.",
        }:
            start = sum(len(item) for item in lines[:line_no - 1])
            edits.append((start, start + len(line), ""))

    first_method = min(
        stmt.lineno for stmt in cls.body if isinstance(stmt, ast.FunctionDef)
    )
    insert_at = sum(len(line) for line in lines[: first_method - 1])
    param_lines = [
        f"    {name} = {_literal_source(generated_params[name]['value'])}\n"
        for name in sorted(generated_params)
    ]
    block = []
    if param_lines:
        block.extend(["    # Signal parameters lifted from inline numeric arguments.\n", *param_lines, "\n"])
    block.append("    # Effective position/execution contract, mirrored in the saved config.\n")
    block.extend(
        f"    {key} = {_literal_source(position[key])}\n"
        for key in sorted(POSITION_KEYS)
        if key in position and key not in method_refs
    )
    block.append("\n")
    edits.append((insert_at, insert_at, "".join(block)))
    output = code
    for start, end, replacement in sorted(edits, reverse=True):
        output = output[:start] + replacement + output[end:]
    return output


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def legacy_contract(record: dict[str, Any], actions: list[dict[str, Any]]) -> tuple[str, str, str, str]:
    family, thesis = LEGACY_CONTRACTS[record["id"]]
    entries = [item["expression"] for item in actions if item["position"] not in (0, None)]
    exits = [item["expression"] for item in actions if item["position"] == 0]
    entry_rule = "A LONG entry is requested when " + ("; or ".join(entries) if entries else "the source entry mask is true") + "."
    exit_rule = "The long is closed when " + ("; or ".join(exits) if exits else "the source exit mask is true") + "."
    return family, thesis, entry_rule, exit_rule


def effective_position(record: dict[str, Any], program: Any, timeframe: str) -> dict[str, Any]:
    defaults = position_default_map()
    config = record.get("config") or {}
    position = {**defaults, **program.position_overrides, **(config.get("position") or {})}
    position = resolve_position_auto(position, timeframe)
    costs = resolve_costs(
        "cex",
        str(position.get("market") or "perp"),
        position.get("fee_rate"),
        position.get("slippage_rate"),
        position.get("maker_fee_rate"),
    )
    position.update({
        "fee_rate": costs[0],
        "maker_fee_rate": costs[1],
        "slippage_rate": costs[2],
    })
    return {key: position[key] for key in POSITION_KEYS}


def position_provenance(record: dict[str, Any], program: Any, position: dict[str, Any]) -> dict[str, str]:
    config_position = (record.get("config") or {}).get("position") or {}
    code_position = program.position_overrides or {}
    provenance: dict[str, str] = {}
    for key in position:
        if key in config_position:
            source = "saved_config"
        elif key in code_position:
            source = "prior_code_attribute"
        elif key in {"fee_rate", "maker_fee_rate", "slippage_rate"}:
            source = "resolved_framework_cost_default_unverified_for_account"
        elif key in NORA_DEFAULTS:
            source = "NORA_DEFAULTS"
        elif key in BASE_POSITION:
            source = "BASE_POSITION"
        else:
            source = "StrategyParams_default"
        provenance[key] = source
    return provenance


def run_contract_update(*, dry_run: bool = False, repair: bool = False) -> dict[str, Any]:
    paths = sorted(USER_ALPHA_DIR.glob("*.json"))
    records = {json.loads(path.read_text(encoding="utf-8"))["id"]: (path, json.loads(path.read_text(encoding="utf-8"))) for path in paths}
    if len(paths) != 57 or len(records) != 57:
        raise ValueError(f"Expected exactly 57 unique records; found {len(paths)} files/{len(records)} IDs")
    migrated = [record.get("strategy_contract_version") == CONTRACT_VERSION for _, record in records.values()]
    if any(migrated):
        if all(migrated) and not repair:
            raise RuntimeError("The 57-alpha contract migration is already applied; refusing to mutate it twice.")
        if not all(migrated) or not repair:
            raise RuntimeError("Partial contract migration detected; inspect records before proceeding.")

    staged: list[tuple[Path, dict[str, Any]]] = []
    manifest_rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for alpha_id, (path, record) in sorted(records.items()):
        saved_config_before = dict(record.get("config") or {})
        if repair and record.get("strategy_contract_version") == CONTRACT_VERSION:
            history = record.setdefault("contract_history", [])
            if history and "config" not in history[0]:
                archived_result = (history[0].get("result_snapshot") or {}).get("result") or {}
                archived_config = archived_result.get("config")
                if isinstance(archived_config, dict):
                    history[0]["config"] = archived_config
                    history[0]["config_snapshot_status"] = "recovered_from_superseded_result"
                else:
                    recovered_config = dict(saved_config_before)
                    for key in ("position", "risk", "program", "strategies"):
                        recovered_config.pop(key, None)
                    if record.get("disposition") == "RESEARCH_PROPOSAL":
                        recovered_config.pop("run_frame", None)
                    history[0]["config"] = recovered_config
                    history[0]["config_snapshot_status"] = "reconstructed_before_contract_materialization"
        code_before = record.get("code")
        if not isinstance(code_before, str) or not code_before.strip():
            raise ValueError(f"{alpha_id}: missing canonical code")
        tree_before = ast.parse(code_before)
        cls_before, method_before = class_and_method(tree_before)
        program_before = compile_code(code_before, register=False)
        old_signature = program_signature(program_before)
        old_source_sha = sha256_text(code_before)
        timeframe = str((record.get("config") or {}).get("timeframe") or program_before.timeframe)
        if timeframe != program_before.timeframe:
            raise ValueError(f"{alpha_id}: config timeframe {timeframe} differs from code {program_before.timeframe}")
        source_config = saved_config_before
        if repair and record.get("contract_history"):
            source_config = record["contract_history"][0].get("config") or source_config

        parameterizer = SignalParameterizer(code_before, cls_before)
        code_with_signal_params, generated = parameterizer.parameterize(method_before)
        tree_with_params = ast.parse(code_with_signal_params)
        cls_with_params, _ = class_and_method(tree_with_params)
        position = effective_position(record, program_before, timeframe)
        position_sources = position_provenance(record, program_before, position)
        if repair and record.get("contract_history"):
            original_source = record["contract_history"][0]
            original_config = original_source.get("config") or source_config
            original_code = original_source.get("code")
            if isinstance(original_code, str):
                original_program = compile_code(original_code, register=False)
                position_sources = position_provenance(
                    {"config": original_config},
                    original_program,
                    position,
                )
        code_after = normalize_code(
            code_with_signal_params,
            position,
            cls_with_params,
            class_and_method(tree_with_params)[1],
            generated,
        )
        try:
            program_after = compile_code(code_after, register=False)
        except Exception as error:
            lines_after = code_after.splitlines()
            error_line = getattr(error, "line", None)
            excerpt = "\n".join(
                f"{number}: {lines_after[number - 1]}"
                for number in range(max(1, (error_line or 1) - 2), min(len(lines_after), (error_line or 1) + 2) + 1)
            )
            raise ValueError(f"{alpha_id}: generated code did not compile:\n{excerpt}") from error
        if program_signature(program_after) != old_signature:
            raise ValueError(f"{alpha_id}: explicit position contract changed the signal IR")
        if program_after.position_overrides != position:
            missing = {key: value for key, value in position.items() if program_after.position_overrides.get(key) != value}
            extra = {key: value for key, value in program_after.position_overrides.items() if key not in position}
            raise ValueError(f"{alpha_id}: code/config position mismatch; missing={missing}, extra={extra}")

        config = dict(record.get("config") or {})
        config["timeframe"] = timeframe
        config.setdefault("run_frame", timeframe)
        config["position"] = position
        config["risk"] = {**RISK, **(config.get("risk") or {})}
        config["program"] = {
            "name": program_after.name,
            "legs": program_after.legs,
            "levels": program_after.levels,
            "features": program_after.features,
            "warmup_bars": program_after.warmup_bars,
        }
        config["strategies"] = [f"py_{program_after.code_hash}_long"] if program_after.has_long and not program_after.has_short else [
            f"py_{program_after.code_hash}_{side.lower()}" for side in program_after.legs
        ]
        record["config"] = config

        actions = action_expressions(code_after)
        if alpha_id in LEGACY_CONTRACTS:
            family, thesis, entry_rule, exit_rule = legacy_contract(record, actions)
            record.update({
                "thesis": thesis,
                "primary_signal_family": family,
                "entry_rule": entry_rule,
                "exit_rule": exit_rule,
                "novelty_status": "NOT_REAUDITED_WITHIN_THE_30_LEGACY_RECORDS",
            })
        else:
            family = record.get("primary_signal_family", "UNSPECIFIED_RESEARCH_SIGNAL_FAMILY")
            thesis = record.get("thesis", "Research hypothesis is the declared source-level signal rule; it is not a profitability claim.")
            entry_rule = record.get("entry_rule", "See the exact production-compiled entry expression in strategy_contract.actions.")
            exit_rule = record.get("exit_rule", "See the exact production-compiled exit expression in strategy_contract.actions.")

        tree_after = ast.parse(code_after)
        cls_after, method_after = class_and_method(tree_after)
        attrs = all_class_attrs(cls_after)
        refs = referenced_self_attrs(method_after)
        signal_params = []
        for name in sorted(refs - set(POSITION_KEYS) - {"timeframe"}):
            if name in attrs:
                if name in generated:
                    signal_params.append({
                        **generated[name],
                        "source": "lifted_inline_literal",
                    })
                else:
                    signal_params.append({
                        "name": name,
                        "value": attrs[name],
                        "unit": parameter_unit(name, attrs[name]),
                        "source": "existing_class_attribute",
                    })
        parent_map = {
            child: parent
            for parent in ast.walk(method_after)
            for child in ast.iter_child_nodes(parent)
        }
        remaining_constants: list[dict[str, Any]] = []
        for node in ast.walk(method_after):
            if isinstance(node, (ast.Constant, ast.UnaryOp)):
                value = numeric_literal(node)
                if value is None:
                    continue
                if isinstance(node, ast.Constant) and isinstance(parent_map.get(node), ast.UnaryOp):
                    continue
                remaining_constants.append({
                    "value": value,
                    "line": node.lineno,
                    "expression": node_source(code_after, node),
                    "classification": "fixed_formula_or_position_level",
                })

        signature = program_signature(program_after)
        family_signature = program_signature(program_after, erase_numbers=True)
        signature_json = json.dumps(signature, sort_keys=True, separators=(",", ":"))
        family_json = json.dumps(family_signature, sort_keys=True, separators=(",", ":"))
        current_source_sha = sha256_text(code_after)
        old_program_hash = record.get("program_hash")
        old_result_fields = {
            key: record.get(key)
            for key in ("metrics", "result", "data_sha", "job_id", "sample_key", "final_equity", "evidence", "explain", "checklist")
            if key in record and record.get(key) not in (None, {}, [])
        }
        has_old_result = bool(record.get("result") or record.get("metrics") or record.get("final_equity") is not None)
        has_superseded_result = has_old_result or any(
            (entry.get("result_snapshot") or {})
            for entry in record.get("contract_history", [])
        )
        prior_source = {
            "source_sha256": old_source_sha,
            "program_hash": old_program_hash or program_before.code_hash,
            "code": code_before,
            "config": saved_config_before,
            "config_snapshot_status": "captured_before_contract_materialization",
            "signal_ir_sha256": sha256_text(json.dumps(old_signature, sort_keys=True, separators=(",", ":"))),
            "result_snapshot": old_result_fields,
        }
        contract_changed = old_source_sha != current_source_sha or saved_config_before != config
        if contract_changed:
            record.setdefault("contract_history", []).append(prior_source)

        record["code"] = code_after
        record["code_sha256"] = current_source_sha
        record["program_hash"] = program_after.code_hash
        record["strategy_contract_version"] = CONTRACT_VERSION
        record["strategy_contract"] = {
            "scope": "source-level strategy and resolved position/execution configuration; no performance claim",
            "thesis": thesis,
            "primary_signal_family": family,
            "entry_rule": entry_rule,
            "exit_rule": exit_rule,
            "actions": actions,
            "action_precedence": "The DSL applies rules in source order; a later matching action takes precedence.",
            "signal_timeframe": timeframe,
            "data_scope": {
                "symbols": config.get("symbols", []),
                "data_symbols": config.get("data_symbols", []),
                "start": config.get("start"),
                "end": config.get("end"),
                "exchange": config.get("exchange"),
                "exchange_status": "SAVED_CONFIG_EXCHANGE_COST_TIER_UNVERIFIED" if config.get("exchange") else "UNSPECIFIED_NOT_INFERRED",
                "run_frame": config["run_frame"],
                "run_frame_provenance": "saved_config" if source_config.get("run_frame") else "materialized_from_signal_timeframe_for_explicitness",
            },
            "warmup_bars": program_after.warmup_bars,
            "signal_parameters": signal_params,
            "fixed_formula_constants": remaining_constants,
            "position_units": position_unit_map(position),
            "position": position,
            "position_provenance": position_sources,
            "portfolio_risk": config["risk"],
            "signal_ir_sha256": sha256_text(signature_json),
            "normalized_rule_shape_sha256": sha256_text(family_json),
            "prior_signal_ir_preserved": program_signature(program_after) == old_signature,
            "validation_scope": "production DSL compile and IR equivalence only; no backtest, WFA, job submission, profitability, fill, or accounting validation",
            "cost_status": "DEFAULT_COSTS_MATERIALIZED_BUT_ACCOUNT/VENUE_TIER_UNVERIFIED",
            "funding_status": "NOT_ASSERTED_BY_THIS_CONTRACT",
            "promotion_allowed": False,
            "falsification_criteria": "Pre-register verified data, fees/funding/slippage semantics, holdout and statistical gates before any performance evaluation; reject if the frozen hypothesis fails those gates.",
        }

        if has_old_result:
            record["metrics"] = {}
            record["result"] = None
            record["data_sha"] = None
            record["job_id"] = None
            record["sample_key"] = None
            record["final_equity"] = None
            record["evidence"] = {}
            record["explain"] = {}
            record["metrics_status"] = "STALE_SOURCE_CHANGED"
            record["backtest_status"] = "STALE_SOURCE_CHANGED"
        elif has_superseded_result:
            record["metrics"] = {}
            record["result"] = None
            record["metrics_status"] = "STALE_SOURCE_CHANGED"
            record["backtest_status"] = "STALE_SOURCE_CHANGED"
        else:
            record["metrics"] = {}
            record["result"] = None
            record["metrics_status"] = "NOT_RUN_AFTER_CONTRACT_UPDATE"
            record["backtest_status"] = "NOT_RUN_AFTER_CONTRACT_UPDATE"
        record["updated_at"] = now
        if contract_changed:
            record["version"] = int(record.get("version") or 0) + 1
        if contract_changed and isinstance(record.get("versions"), list):
            record["versions"].append({
                "version": record["version"],
                "saved_at": now,
                "program_hash": program_after.code_hash,
                "job_id": None,
                "name": record.get("name"),
                "change": "explicit signal and execution contract; no backtest",
            })

        manifest_rows.append({
            "alpha_id": alpha_id,
            "owner_id": record.get("owner_id"),
            "name": record.get("name"),
            "timeframe": timeframe,
            "data_scope": record["strategy_contract"]["data_scope"],
            "signal_parameters": signal_params,
            "position": position,
            "position_provenance": position_sources,
            "risk": config["risk"],
            "thesis": thesis,
            "primary_signal_family": family,
            "entry_rule": entry_rule,
            "exit_rule": exit_rule,
            "actions": actions,
            "warmup_bars": program_after.warmup_bars,
            "features": program_after.features,
            "ops": program_after.ops,
            "source_sha256": current_source_sha,
            "program_hash": program_after.code_hash,
            "signal_ir_sha256": sha256_text(signature_json),
            "normalized_rule_shape_sha256": sha256_text(family_json),
            "compile_status": "PASS",
            "signal_ir_preserved": True,
            "previous_results": "SUPERSEDED" if has_superseded_result else "NONE",
            "backtest_status": record["backtest_status"],
            "novelty_status": record.get("novelty_status", "RULE_SHAPE_CHECK_ONLY"),
        })
        staged.append((path, record))

    shape_groups: dict[str, list[str]] = {}
    for row in manifest_rows:
        shape_groups.setdefault(row["normalized_rule_shape_sha256"], []).append(row["alpha_id"])
    collisions = [sorted(ids) for ids in shape_groups.values() if len(ids) > 1]
    collision_by_id = {alpha_id: ids for ids in collisions for alpha_id in ids}
    for row in manifest_rows:
        row["normalized_rule_shape_collision_ids"] = collision_by_id.get(row["alpha_id"], [])
        row["novelty_status"] = (
            "STRUCTURAL_COLLISION_REVIEW_REQUIRED"
            if row["normalized_rule_shape_collision_ids"]
            else row["novelty_status"]
        )
        record = next(updated for _, updated in staged if updated["id"] == row["alpha_id"])
        record["strategy_contract"]["normalized_rule_shape_collision_ids"] = row["normalized_rule_shape_collision_ids"]
        record["novelty_status"] = row["novelty_status"]

    manifest = {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "created_at": now,
        "status": "57_EXPLICIT_SOURCE_AND_POSITION_CONTRACTS_COMPILED_NO_BACKTESTS",
        "record_count": len(manifest_rows),
        "compiled_count": sum(row["compile_status"] == "PASS" for row in manifest_rows),
        "signal_ir_equivalent_count": sum(row["signal_ir_preserved"] for row in manifest_rows),
        "backtests_run": 0,
        "jobs_submitted": 0,
        "superseded_result_count": sum(row["previous_results"] == "SUPERSEDED" for row in manifest_rows),
        "normalized_rule_shape_collision_groups": collisions,
        "novelty_limit": "Number-normalized DSL structure is a triage signal, not a complete semantic or economic-independence proof; collisions remain blocked for review.",
        "execution_limit": "Default fee assumptions are explicit but not verified for an account tier. Funding and venue-specific fill/cost parity remain unverified. Promotion is disabled.",
        "results": manifest_rows,
    }

    if not dry_run:
        for path, record in staged:
            write_atomic(path, record)
        write_atomic(MANIFEST_PATH, manifest)
    action = "Validated" if dry_run else "Updated"
    print(f"{action} {len(staged)}/57 canonical records; {len(collisions)} normalized rule-shape collision groups.")
    print(f"Superseded old result payloads: {manifest['superseded_result_count']}.")
    print("Backtests run: 0. Jobs submitted: 0. Promotion: blocked.")
    return manifest


if __name__ == "__main__":
    run_contract_update(
        dry_run="--dry-run" in sys.argv,
        repair="--repair-inline-parameters" in sys.argv,
    )
