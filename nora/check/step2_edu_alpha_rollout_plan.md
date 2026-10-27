# EDU Alpha Rollout Plan — Complete, Executable, and Teachable

## Goal

Bring every in-scope EDU strategy artifact to a complete, compiler-valid, clearly
explained source/configuration package. Students should be able to understand the
market/data assumptions, indicator math, entry/exit rules, position and risk
settings, costs, and limitations, then reproduce a run using the actual EDU
compiler and backtest request.

This work improves correctness, explainability, and reproducibility. It does not
promise profitability, prove an edge, grant trading approval, or establish
TradingView parity.

## Latest execution status — 2026-10-27

- Fixed and linked new active versions for 23 reviewed, non-Vinh user alphas.
  Their `*_pct` code comments now explain percentage-point semantics, and each
  active `config.position.exit_unit` is `pct`, matching the compiler's code
  override. Signal ASTs and `program_hash` values are unchanged.
- Previous active metrics/results were retained in prior versions; the new
  active versions have empty metrics/results and
  `metrics_status=NOT_RUN_AFTER_UNIT_FIX`. No backtest was run.
- The version action names in the previous normalization report did not match
  the old regression filter; the filter now checks the actual
  `version_vN_created` actions and exact version files.
- **Not all 57 user alphas are accepted:** 27 remain
  `BLOCKED_UNKNOWN_INTENT` pending owner clarification. The 7 Vinh alpha records
  were deliberately left byte-for-byte unchanged. No users or alpha records
  were deleted.
- The user store currently contains 36 accounts: 27 with only blocked alpha,
  6 with at least one valid-as-is alpha, and 3 without alpha. These are account
  counts, not a claim that the 27 blocked strategies are ready to use.
- Local verification is recorded in
  `edu_alpha_unit_fix_report.json`. Python source syntax and migration
  verification passed. The full compiler-backed EDU suite was not run because
  the configured environment is Python 3.10 without required runtime packages;
  no profitability or backtest correctness claim is made.

## Baseline to refresh before implementation

The local EDU data snapshot checked on 2026-10-27 contains:

| Source | Current count | Treatment |
|---|---:|---|
| Active user alpha records in `data/alpha/user/*.json` | 57 | All must receive an assessment and a disposition; normalize by version/fork, never silently overwrite user source |
| Education samples in `data/alpha/education/samples.json` | 50 | All must be reviewed and made compiler-valid, complete, and teachable |
| Frontend onboarding examples in `EduStudioOnboarding.jsx` | 3 | All must be reviewed and kept in sync with compiler-valid examples |
| System strategy files in `data/alpha/strategies/` | 3 | Review all; distinguish system/runtime contracts from student custom DSL |
| Active alpha versions in `data/alpha/user/_versions/` | 11 | Preserve provenance; include in source/version mapping |
| Unattributed versions | 2 | Preserve and mark `UNKNOWN/BLOCKED`; do not rewrite or delete without ownership evidence |
| Unlinked archive | 42 alpha records and 4 version files | Out of active rollout; leave untouched |
| Saved education result artifacts | 110 | Historical run outputs, not strategy source; do not rewrite as alpha |

These are inventory counts, not necessarily unique strategies. Freeze a new
read-only manifest with file paths, IDs, owner IDs where present, status, source,
code/config/version hashes, parse/compile result, and duplicate-content groups
before changing anything. Retain every source record in the manifest even when
multiple records share the same strategy logic.

## Non-negotiable implementation rules

1. Use the actual EDU custom DSL/compiler for user examples. Do not write ordinary
   Python APIs such as `self.indicators`, `self.crossover`, arbitrary `self.*`
   state, `.rolling()`, or `.ewm()` unless the EDU compiler explicitly supports
   them and a compiler regression proves it.
2. Keep strategy source separate from backtest request fields. `symbol`, date
   range, initial capital, and run frame are not executable class settings unless
   the request/engine path explicitly consumes them. Show the effective run
   request beside the code; never imply an ignored class attribute controls it.
3. Use the engine's exact units. EDU `stop_loss_rate` and `take_profit_rate` are
   percentage points (`2.0` means 2%, not `0.02`). Set `exit_unit="pct"` for
   percentage exits. Risk sizing requires `sizing="risk"`; a risk percentage
   field alone does not activate it. Set `max_open_trades=1` when the example
   intends one open trade/no pyramiding.
4. EDU fees are applied from the effective run configuration. Slippage defaults
   to zero and must be disclosed; do not label it as realistic or TradingView
   parity.
5. Do not infer missing strategy intent. Preserve original code and config.
   Semantic changes (signal, side, timeframe, SL/TP, sizing, DCA, or costs) need
   an explicit rationale and owner/reviewer disposition. Unknown semantics remain
   blocked, not guessed.
6. Every alpha, including seed/sample code, gets a ledger row and final status.
   A duplicate implementation can share a reviewed canonical explanation/test,
   but each record keeps its identity, owner, hash, and mapping to that canonical
   implementation.
7. Keep EDU separate from COIN. Do not copy user data into COIN or change
   COIN quarantine/promotion state as part of this rollout.

## Work packages and dependency gates

### EDU-0 — Freeze post-cleanup inventory

- Recompute the source counts above and record timestamp, roots, hashes, compiler
  version, invalid JSON, missing fields, and duplicate groups.
- Include all 57 active alpha records, all 50 education samples, all 3 onboarding
  examples, all 3 system strategy files, and the 13 version files in the manifest.
- Keep archived/unattributed artifacts enumerated but outside the rewrite scope.
- **Gate:** manifest reconciles exactly to filesystem counts; no source files
  changed.

### EDU-1 — Lock the executable authoring and run contract

- Document supported class bases, lifecycle forms, data/frame access, indicators,
  operators, target-position semantics, supported class attributes, and supported
  position keys from the current EDU compiler.
- Map each source field to its actual consumer: compiler, plan builder, backtest
  request, engine, UI-only metadata, or unsupported.
- Add explicit effective-value/unit behavior for stop/target, fee, slippage,
  sizing, leverage, max-open-trades, date window, symbol, and initial capital.
- Fix or block the current SL/TP display-vs-runtime unit mismatch before using
  those displays as educational evidence.
- **Gate:** executable contract has compiler tests and runtime assertions; no
  illustrative field is described as effective unless the result proves it.

### EDU-2 — Build canonical teaching templates

- Create a beginner template with a single thesis, readable indicator math,
  entry/exit explanations, supported position controls, and a matching run
  request.
- Create an advanced template with explicitly derived formulas, units, inputs,
  timeframe alignment, warm-up, missing-data behavior, and test hooks.
- Every template must state whether it is educational, its assumptions, fee
  behavior, zero-slippage limitation, and that structure is not profitability
  evidence.
- Compile with the production EDU compiler and run deterministic fixtures before
  exposing the templates in the Studio.
- **Gate:** templates compile, position fields materialize as declared, and
  fixture expectations match signal bars and execution/accounting output.

### EDU-3 — Assess every source record

- Process all source records from EDU-0 in deterministic batches, preserving a
  row per record.
- Extract original code/config hashes, identity/owner/source/status, timeframe,
  data requirements, indicators/formulas, entry/exit, position/risk/cost settings,
  compiler status, stored-result provenance, and known limitations.
- Classify each record as `VALID_AS_IS`, `NEEDS_EDUCATIONAL_REWRITE`,
  `DUPLICATE_OF_CANONICAL`, `BLOCKED_UNKNOWN_INTENT`, `UNSUPPORTED`,
  `INVALID_SOURCE`, or `ARCHIVED_OUT_OF_SCOPE`.
- Stored PnL metrics do not establish correctness or profitability. No ranking
  based on stored returns.
- **Gate:** 100% of in-scope records have a row, evidence references, and a
  disposition; no record silently disappears due to deduplication or parse error.

### EDU-4 — Normalize user alpha records in protected batches

- Produce a new immutable version/fork for each of the 57 active user alpha
  records unless a reviewer records `VALID_AS_IS` with evidence.
- Preserve the original source/hash and owner attribution. Link each normalized
  version to its source record/hash and list every semantic or explanatory change.
- Rewrite only against the EDU contract from EDU-1. If intent cannot be recovered,
  retain the original and mark the normalized work `BLOCKED_UNKNOWN_INTENT`.
- Group records with identical code into canonical teaching explanations and
  shared regression fixtures while retaining per-record mappings and ownership.
- **Gate per batch:** all records in the batch have source-to-normalized mapping,
  compiler outcome, effective config, reviewer disposition, and no unapproved
  semantic change.

### EDU-5 — Normalize education samples, onboarding, and system strategies

- Review all 50 `samples.json` entries and all 3 onboarding examples; make the
  code, displayed description, default run request, and result explanation agree.
- Review all 3 `data/alpha/strategies/*.py` files separately. Do not paste system
  module syntax into student custom DSL; provide a student-facing equivalent only
  where semantics can be faithfully expressed and tested.
- Ensure that each example names the indicators and formula, explains signal
  transitions and exits, states risk/cost behavior, and shows the effective
  request needed to reproduce a run.
- **Gate:** every sample/example is compiler-valid in its intended pathway, with
  regression coverage and no unsupported API or silently ignored setting.

### EDU-6 — Correctness, risk, and UX regression

- Add a manifest-driven test that compiles every in-scope custom DSL source after
  normalization.
- Add independent deterministic oracles for representative indicator, signal,
  stop/target, fee, sizing, rounding, and final-bar behavior; test every unique
  canonical implementation and map tests back to all duplicate records.
- Assert effective configuration provenance in API results and UI: declared,
  UI override, and engine default values/units must be distinguishable.
- Test result states and disclosures: success, empty/no-trade, invalid/unsupported,
  missing data, zero slippage, blocked/unknown, and reload/reopen.
- Run EDU backend tests, browser journeys, frontend build, isolation checks, and
  `git diff --check`.
- **Gate:** all focused gates pass; no `UNKNOWN` or unsupported source is
  represented as complete; failures have owner and reason.

### EDU-7 — Reconcile and close rollout

- Reconcile the original inventory against final assessment rows and normalized
  versions: 100% coverage across all sources from EDU-0.
- Report counts for valid-as-is, rewritten, duplicate-mapped, blocked, unsupported,
  invalid, and archived; include IDs/owners/hash mapping and test evidence.
- Confirm original user alpha records remain unchanged and all new versions are
  attributable. Confirm `vinh`'s seven alpha records remain intact.
- Explicitly separate local implementation/test status from public deployment,
  TradingView parity, alpha profitability, and Demo/Live approval.
- **Gate:** no missing record; owner/reviewer signs off semantic changes and
  blocked cases; rollback snapshot and restore procedure are verified.

## Completion criteria

- 100% of current in-scope EDU source records have an assessment and disposition.
- 100% of active user alpha records have either a compiler-verified normalized
  version or an explicit blocked/valid-as-is disposition with evidence.
- All 50 education samples, 3 onboarding examples, and 3 system strategies are
  reviewed in their correct authoring pathways.
- Every effective setting is traceable to code, run request/UI, or engine default;
  units and ignored/unsupported fields are explicit.
- Original user code is unchanged; every changed strategy is versioned and
  attributable.
- Correctness tests pass. No claim of all-alpha profitability, TradingView parity,
  or production readiness follows from completing this plan.
