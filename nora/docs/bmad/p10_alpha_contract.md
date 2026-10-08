# P10 — Hợp đồng chiến lược (Strategy Contract) + chỉnh sửa tại chỗ + trợ lý viết code

Mục tiêu: viết chiến lược là Python **chính xác như ứng dụng code** (gợi ý, hover, kiểm lỗi đúng dòng/cột), nhưng chỉ
gợi ý đúng những gì engine hiểu (fintech thuần, tất định, KHÔNG AI). Phong cách NautilusTrader: MỘT hợp đồng cố định
(`on_start` / `on_bar` / `on_stop`), các bộ chuyển đổi (adapters) đưa mọi dạng đầu vào khác về MỘT mô hình chuẩn
(IR `core/signal.Program`, hoặc cây khuôn của sổ chiến lược) và MỘT engine vector hoá. Mã người dùng **không bao giờ exec**:
chỉ `ast.parse` rồi biên dịch theo danh sách trắng.

Mã nguồn: `backend/alpha/contract.py` (hợp đồng, `check_contract`, catalog, gợi ý/hover), `backend/alpha/adapters.py`
(registry style -> adapter), `backend/alpha/compile.py` (trình biên dịch: một định nghĩa duy nhất của IR).
Router: `backend/routes/strategies.py` (+ `alphas.py` cho phiên bản alpha người dùng).

## 1. Vòng đời & hai "loại" mã

| Loại (`kind`) | Dùng cho | Biên dịch bởi | `ir` |
|---|---|---|---|
| `alpha` | Alpha người dùng, /alpha/create, /education, backtest tạm | `compile_program` | `Program` (IR) |
| `module` | Chiến lược hệ thống `data/alpha/strategies/*.py` (có `STRATEGY = {...}`, tham số `p(...)`, nhiều khung) | `compile_strategy_module` | dict ứng viên của sổ |

Hợp đồng (cả hai loại):

```python
class MyStrategy(SimpleAlgorithm):          # lớp cơ sở cố định (alias `Strategy` được ADAPT chuẩn hoá thành SimpleAlgorithm)
    # thuộc tính lớp (hằng): alpha -> timeframe, position_open_times/ranges, position_close_ranges, khoá vị thế, hằng số
    #                        module -> id, family, description, [side], position = {...}
    timeframe = "4h"

    def on_start(self):                      # KHAI BÁO: tham số + chỉ báo (không set_positions)
        close = self.data.pv_close
        ema = self.feat.ema(close, 20)

    def on_bar(self):                        # LUẬT: vào / thoát / dừng, là biểu thức mặt nạ, engine tính vector hoá cho cả chuỗi
        self.set_positions(close < ema, position=0)         # thoát
        self.set_positions(self.op.crossed_above(close, ema), position=1)   # vào (lệnh sau ghi đè lệnh trước)

    def on_stop(self):                       # tuỳ chọn: chỉ docstring / pass (engine không có sự kiện dừng trên chuỗi vector)
        pass
```

* `on_start` + `on_bar` được biên dịch **đồng nghĩa** với `def __algorithm__(self):` có thân = thân `on_start` rồi thân
  `on_bar` (biến cục bộ dùng chung). Cú pháp cũ `__algorithm__` vẫn hợp lệ và cho **cùng IR / cùng `program_hash`**.
* `on_start` không được gọi `set_positions` / `set_dca_gate`; `on_bar` bắt buộc có ít nhất một `set_positions`;
  `on_stop` chỉ docstring/`pass`. Không trộn `__algorithm__` với `on_start/on_bar`.
* Ngữ nghĩa mỗi nến: điều kiện được đánh giá trên nến ĐÃ ĐÓNG, y hệt trong backtest và live; không nhìn tương lai
  (`.shift(k)`, `k >= 1`); mức vị thế `1` vào long, `-1` vào short, `0` thoát; giữ mức trước khi không luật nào kích hoạt.
* `side = "LONG"|"SHORT"` (loại `module`, tuỳ chọn) khai báo chiều của chân; nếu có phải khớp `set_positions`.

## 2. `check_contract(code) -> dict`

```json
{
  "verdict": "RUN" | "ADAPT" | "REJECT",
  "style": "simple_algorithm" | "lifecycle" | "strategy_module" | "function" | "json_spec" | "ai_python" | "unknown",
  "kind": "alpha" | "module" | null,
  "diagnostics": [ {"line": 5, "col": 9, "end_line": 5, "end_col": 24, "severity": "error|warning|info",
                    "code": "UNKNOWN_FEATURE", "message_vi": "...", "suggest": ["ema", "dema"], "path": null} ],
  "normalized_code": null | "<mã native tương đương, dùng được để chạy/lưu>",
  "ir": Program | null      /* chỉ trong Python; API không trả */
}
```

* **RUN**: đúng hợp đồng native (`simple_algorithm`, `lifecycle`, `strategy_module`).
* **ADAPT**: dạng khác được bộ chuyển đổi đưa về native; `normalized_code` là mã native tương đương (IR **giống hệt**),
  `diagnostics` (severity `info`) liệt kê từng phép chuẩn hoá đã làm. Không đoán gần đúng thầm lặng.
* **REJECT**: không hỗ trợ; mỗi lỗi có `line/col/end_line/end_col` (1-based) chính xác + `message_vi` + `suggest[]`.
  Với `json_spec`, `path` là đường dẫn trường (vd. `"entry"`) và `line/col` trỏ vào khoá đó trong văn bản JSON (nếu tìm được).
* Mã lỗi (`code`): `SYNTAX`, `TOO_LARGE`, `NO_STRATEGY`, `BAD_STRUCTURE`, `UNKNOWN_FEATURE`, `UNKNOWN_OP`, `UNKNOWN_NAME`,
  `UNKNOWN_ATTR`, `BAD_ARGUMENT`, `OUT_OF_RANGE`, `BAD_TYPE`, `FORBIDDEN_SYNTAX`, `BAD_PARAM`, `BAD_LIFECYCLE`, `COMPILE`;
  ADAPT/info: `NORMALIZED_BOOL_OP`, `NORMALIZED_CHAINED_COMPARE`, `NORMALIZED_NAME`, `NORMALIZED_BASE`, `NORMALIZED_FENCE`,
  `NORMALIZED_IMPORT`, `ADAPTED_FUNCTION`, `ADAPTED_JSON`.

### Bộ chuyển đổi (registry `style detector -> adapter`)

Mỗi adapter: `detect(source) -> bool`, `convert(source) -> (ast.Module, notes)`; thêm dạng mới = `register(Adapter(...))`,
không đụng trình biên dịch. Adapter chỉ biến AST/spec thành AST native rồi dùng đúng trình biên dịch hiện có (không evaluator thứ hai).

1. `json_spec` (ADAPT) — văn bản JSON (hoặc dict):
   ```json
   {"timeframe": "4h", "params": {"fast": 20},
    "indicators": {"ema": "feat.ema(close, fast)", "atr": "feat.atr(high, low, close, 14)"},
    "entry": "op.crossed_above(close, ema + 2 * atr)", "exit": "close < ema",
    "short_entry": null, "short_exit": null}
   ```
   Biểu thức là cú pháp DSL; tên trần `open high low close volume` = cột dữ liệu, `feat.`/`op.` = `self.feat/self.op`,
   `params` thay bằng hằng số, `indicators` là biến cục bộ theo thứ tự khai báo. Thứ tự lệnh sinh ra: `exit` (0),
   `short_exit` (0), `entry` (1), `short_entry` (-1).
2. `function` (ADAPT) — `def strategy(data):` trả về `entry`/`exit` (dict hoặc tuple `(entry, exit)`):
   ```python
   timeframe = "4h"
   FAST = 20
   def strategy(data):
       close = data.close              # hoặc data["close"], data.pv_close
       ema = feat.ema(close, FAST)
       return {"entry": op.crossed_above(close, ema), "exit": close < ema}
   ```
   Khoá trả về: `entry`, `exit`, `short_entry`, `short_exit` (hoặc `long_entry`, `long_exit`). Hằng số cấp module (số) được thế
   thẳng; `timeframe` / `position_*` thành thuộc tính lớp.
3. `ai_python` (ADAPT hoặc REJECT) — mã class "kiểu AI sinh": chuẩn hoá tất định các biến thể thường gặp:
   hàng rào ```` ```python ````, `import` trong whitelist (`nora`, `typing`, `__future__`), lớp cơ sở `Strategy/Algorithm` ->
   `SimpleAlgorithm`, `self.data.close|Close|["close"]` -> `self.data.pv_close`,
   `self.feat.EMA` -> `ema`, `and/or/not` -> `& | ~`, so sánh nối chuỗi `a<b<c` -> `(a<b)&(b<c)`. Tên hook lạ (`initialize`, `next`, `on_data`…) và `np./pd./talib.` KHÔNG đoán: REJECT kèm gợi ý.
   Mã chuẩn hoá nằm ở `normalized_code`. **Biên dịch native `compile_code` vẫn nghiêm ngặt** với class (không tự chuẩn hoá);
   hãy gửi `normalized_code` đi chạy/lưu. Riêng `function` và `json_spec` được `compile_code` nhận trực tiếp.

## 3. Danh mục (catalog) — một định nghĩa duy nhất

Sinh từ `core/indicator.FEATURES/OPS` (spec) + thuộc tính hợp đồng; vừa kiểm lỗi vừa gợi ý.

`GET /api/studio/strategies/assist/catalog`
```json
{
  "version": "9f2c1a7e03b4",
  "dsl_version": "…",
  "styles": [{"style": "simple_algorithm", "verdict": "RUN", "label_vi": "…", "example": "…"}, …],
  "lifecycle": [{"name": "on_start", "required": false, "doc_vi": "…", "insert": "def on_start(self):\n    ${1:pass}"}, …],
  "features": [{
      "name": "ema", "kind": "feature", "category": "trend", "label_vi": "Đường trung bình động hàm mũ",
      "signature": "self.feat.ema(real, timeperiod=30)",
      "args": [{"name": "real", "type": "series_num", "required": true, "default": null, "lo": null, "hi": null},
               {"name": "timeperiod", "type": "int", "required": false, "default": 30, "lo": 1, "hi": 5000}],
      "returns": "num", "outputs": 1, "warmup": 90,
      "doc_vi": "…", "formula": "…", "read_vi": "…",
      "example": "self.feat.ema(close, timeperiod=30)",
      "insert": "self.feat.ema(${1:close}, ${2:30})",
      "modes": ["alpha", "module"]}],
  "ops": [ …cùng dạng, "kind": "op", "signature": "self.op.crossed_above(a, b)" … ],
  "methods": [{"name": "shift", "op": "shift", "signature": "<chuỗi>.shift(periods=1)", "doc_vi": "…", "insert": ".shift(${1:1})"}],
  "data": [{"name": "pv_close", "column": "close", "signature": "self.data.pv_close", "doc_vi": "Giá đóng cửa"}],
  "class_attrs": {"alpha": [{"name": "timeframe", "type": "str", "choices": ["1m", …], "doc_vi": "…", "insert": "timeframe = \"${1:4h}\""}],
                  "module": [ … id, family, description, side, position … ]},
  "position_keys": [{"name": "stop_loss_rate", "label_vi": "…", "lo": 0.5, "hi": 10, "unit": "ATR", "doc_vi": "…"}],
  "frames": ["1m", "5m", "15m", "1h", "4h", "24h"],
  "p_kwargs": [{"name": "lo", "doc_vi": "…"}, …],
  "snippets": [{"label": "Chiến lược EMA", "insert": "class …", "doc_vi": "…"}]
}
```

## 4. Trợ lý viết code (tất định, không AI)

Toạ độ `line`/`col` đều **1-based**; `col` là vị trí con trỏ (trước ký tự thứ `col`).

`POST /api/studio/strategies/assist/check` — body `{"code": "…"}` → `check_contract` bỏ `ir` (luôn HTTP 200):
```json
{"verdict": "REJECT", "style": "simple_algorithm", "kind": "alpha", "normalized_code": null,
 "diagnostics": [{"line": 9, "col": 20, "end_line": 9, "end_col": 31, "severity": "error", "code": "UNKNOWN_FEATURE",
                  "message_vi": "self.feat.emaa chưa được hỗ trợ.", "suggest": ["ema"], "path": null}],
 "meta": null}
```
`meta` (khi không REJECT) = `{timeframe, features, ops, legs, position_levels, warmup_bars}` (alpha) hoặc `{strategy_id, legs}` (module).

`POST /api/studio/strategies/assist/complete` — body `{"code": "…", "line": 9, "col": 24}`:
```json
{"items": [{"label": "ema", "kind": "feature", "detail": "self.feat.ema(real, timeperiod=30)",
            "insert": "ema(${1:close}, ${2:30})", "is_snippet": true, "doc_md": "**ema** — …"}],
 "range": {"line": 9, "col": 22, "end_line": 9, "end_col": 24}}
```
`kind` ∈ `feature | op | attr | method | param | keyword | snippet`. Ngữ cảnh:
sau `self.feat.` -> chỉ báo; `self.op.` -> operator; `self.data.` -> `pv_*`; `self.` -> `feat/op/data/set_positions/<hằng>`;
`.` sau biểu thức -> `.shift/.fillna/.abs`; trong `p(` -> `lo/hi/step/choices/unit/label/help/grid/group`; đối số tên của
feature/op (`timeperiod=`) -> tham số kế tiếp; trong chuỗi khung (`timeframe = "`, `self.frame("`) -> `1m…24h`;
trong thân class -> `on_start/on_bar/on_stop`, thuộc tính lớp; đầu dòng trong thân method -> biến đã gán, `self`, `p(`.

`POST /api/studio/strategies/assist/hover` — body `{"code": "…", "line": 9, "col": 24}` →
```json
{"md": "```python\nself.feat.ema(real, timeperiod=30)\n```\n…", "range": {"line": 9, "col": 14, "end_line": 9, "end_col": 25}}
```
`md` = `null` khi không có gì. Hover vào `p('ema_n', 30, lo=5, hi=200, step=1)` hiện khoảng đã khai báo: `**ema_n** int, mặc định 30, [5, 200] bước 1`.
Hover vào số đối số của feature hiện khoảng hợp lệ của tham số đó.

## 5. Sửa chiến lược hệ thống tại chỗ

Chiến lược hệ thống = file `data/alpha/strategies/<file>.py` (thư mục có thể đổi bằng `NORA_STRATEGIES_DIR`).

`GET /api/studio/strategies/source/{id}` — `id` là id chiến lược (`kema`) hoặc id chân (`kema_long`):
```json
{"id": "kema", "file": "kema.py", "code": "…", "sha256": "ab12…", "legs": ["kema_long", "kema_short"]}
```
404 nếu không có.

`PUT /api/studio/strategies/source/{id}` — body `{"code": "…", "sha256": "<sha256 đang sửa>"}` (khoá lạc quan):
```json
{"ok": true, "sha256": "new…", "legs": ["kema_long", "kema_short"], "normalized": false,
 "diagnostics": [], "backup": "data/cache/process/_strategy_backup/kema.20261008T101500Z.py", "reloaded": true}
```
Quy trình: `sha256` khớp file hiện tại (khác -> **409** `SHA_CONFLICT`) -> `check_contract` phải ra `module` và RUN/ADAPT (REJECT -> **422**
`CONTRACT_REJECTED` kèm `diagnostics`) -> không trùng id với file khác -> không đổi tên/bỏ id chân đang dùng khi có bot live đang chạy
(**409** `LIVE_BOT_RUNNING`) -> sao lưu bản cũ vào `data/cache/process/_strategy_backup/<file>.<UTC ts>.py` (giữ tối đa 20 bản mỗi file)
-> ghi nguyên tử -> nạp lại sổ (cache mtime vô hiệu, `build.CANDIDATES/STRATEGIES/SOURCES` làm mới tại chỗ) ->
các lượt backtest / book / funnel SAU ĐÓ dùng mã mới. Lỗi: `{"detail": {"code": "...", "message": "...", "diagnostics": [...], "current_sha256": "..."}}`.
Nếu ADAPT, file được ghi là `normalized_code`.

## 6. Alpha người dùng: viết tạm -> chạy -> Lưu = phiên bản mới

Viết chiến lược chỉ là TẠM THỜI: người dùng chạy backtest (`custom_backtest`, job tạm); nếu ổn bấm **Lưu** thì alpha được lưu KÈM kết quả.
Không có `PUT …/code` và không có `result_stale`. Sửa alpha đã lưu = mở lại, sửa trong trình soạn tạm, chạy lại, lưu thành **phiên bản mới**.

* `GET /api/studio/alphas/user/{id}/code` → `{"id", "code", "version", "program_hash", "sha256", "name", "note"}` (nạp vào trình soạn).
* `POST /api/studio/alphas/user` (hiện có) nhận thêm `alpha_id` (tuỳ chọn):
  ```json
  {"job_id": "…", "code": "…", "name": "…", "note": "", "source": "alpha-create", "alpha_id": "a1b2c3d4e5f6"}
  ```
  Không có `alpha_id`: hành vi cũ (id = sha1(program_hash + cấu hình)). Có `alpha_id`: giữ nguyên id, bản ghi hiện tại được lưu vào
  `data/alpha/user/_versions/<id>.v<n>.json` (nguyên bản ghi cũ), bản ghi chính nhận `code`, `result`, `evidence`, `metrics`… MỚI,
  `version = n+1`, `versions = [{version, saved_at, program_hash, job_id, name}]`, `status`/`created_at` giữ nguyên. Phản hồi
  `action: "versioned"`, thêm `version`. `alpha_id` không tồn tại -> 404; job không hợp lệ -> 409 như cũ.
* `GET /api/studio/alphas/user/{id}/versions` → `[{version, saved_at, program_hash, job_id, name}]` (gồm bản hiện tại);
  `GET /api/studio/alphas/user/{id}/versions/{n}` → bản ghi đầy đủ của phiên bản n (so sánh kết quả).
* Danh sách `GET /user` không liệt kê `_versions`.
