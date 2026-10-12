# ARCHIVED (P17-T1 B4): script của kho pkl / backend.crawl cũ (catalog nay cập nhật bằng job data_update -> backend.data.crawl).
#!/usr/bin/env python
"""P9.3c — chuyển nora/data/ sang cây dữ liệu CUỐI của ADR-P9 §4 (docs/bmad/adr-p9-backend-layout.md; log: docs/bmad/p9_review_log.md "P9.3c plan").

    ops/run_limited.sh --no-lock -- test/scripts/migrate_data_tree.py --dry-run --allow-live            # từ thư mục nora/
    ... migrate_data_tree.py --apply --allow-live [--allow-jobs] [--remove-stale-registry] [--full-hash] [--git-stage] [--write-gitignore]

Cây đích: market/<sàn>/{cex,dex}, market/binance/cex_ref, market/_meta · alpha/{strategies,education,research,user,funnel,book,explore,testnet,*.json}
· backtest/<id> + backtest/education · wfa/<id> · carlo/<id> · live/<venue_mode> · cache/{process/<id>, process/_mem, process/_staging, shared/, shared/quality_gate}.
cache CHỈ có process/ và shared/ (người dùng chốt 2026-10-07).

Thứ tự (mỗi bước độc lập, idempotent): market -> alpha (cấu hình) -> registry_fix (bỏ mục cũ, CÓ sao lưu; cần --remove-stale-registry)
-> thư mục kết quả (backtest, wfa, funnel, book) -> live -> cache/shared -> persist_finished_jobs(apply=True) của api/jobs/batch.py (GỌI, không viết lại:
chép kết quả job đã xong sang backtest|wfa|alpha, dọn thư mục process) -> cache/process (+ _mem, _staging) -> kiểm bot live còn ghi.
Mục "Đã xoá 2026-10-07" (ADR §4) không còn trong kế hoạch; nếu xuất hiện lại sẽ báo ở "CHƯA ÁNH XẠ".

Nguyên tắc
- Chỉ DI CHUYỂN (rename trong cùng ổ đĩa, nguyên tử, giữ inode); khác ổ đĩa mới sao chép + kiểm + xoá nguồn. Không viết lại nội dung.
- Mỗi đường cũ để lại SYMLINK TƯƠNG ĐỐI trỏ vào chỗ mới (code cũ, đường dẫn tuyệt đối ghi trong job/state/registry vẫn đọc được).
  Thứ tự: tạo symlink tạm cạnh nguồn -> rename nguồn -> rename symlink tạm thành đường cũ (cửa sổ hở chỉ vài micro giây, cả với thư mục live).
- Kiểm: đếm file + sha256 từng file (file > 100 MB: size + mtime_ns, trừ khi --full-hash). Kiểm TRƯỚC khi chuyển (manifest nguồn), SAU khi chuyển (manifest đích).
  Chuyển bằng rename: cùng inode = cùng file; file đang được tiến trình khác ghi thêm (live bot, out.log) chỉ ghi nhận "mutated_live", không tính là lỗi.
- Idempotent: chạy lại sau khi xong hoặc bị ngắt giữa chừng đều an toàn (trạng thái từng mục: todo | done | needs_link | merge_todo | conflict | foreign_link | src_missing).
- Từ chối --apply khi có bot live_bot đang chạy (job.json state=running + pid sống) trừ khi --allow-live; job nặng khác đang chạy: trừ khi --allow-jobs.
- Báo cáo: data/_migration/p9_3c_<UTC>/report.json (+ registry.json.bak) khi --apply; --dry-run chỉ ghi khi có --report.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
NORA = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.dirname(NORA)
BIG_BYTES = 100 * 1024 * 1024
LNK_SUFFIX = ".p93lnk"
STALE_ALPHA_ID = "trend_long_perp__SOL"      # mục registry.json mồ côi (run nguồn _cache/optimize/20261001_1440 đã xoá); người dùng chốt bỏ 2026-10-07
if NORA not in sys.path:
    sys.path.insert(0, NORA)


@dataclass
class Move:
    key: str
    kind: str                 # dir | file | merge (gộp từng file vào thư mục đích đã có) | persist | registry (bước đặc biệt, không có nguồn/đích)
    src: str                  # tương đối so với gốc nguồn (data/ hoặc nora/ khi base="nora")
    dst: str                  # tương đối so với data/
    group: str
    note: str = ""
    live: bool = False        # thư mục có tiến trình đang ghi: cấm sao chép khác ổ đĩa
    base: str = "data"        # data | nora
    newest_wins: bool = False  # merge: trùng tên khác nội dung -> giữ bản mtime mới hơn (chỉ cho cache thuần)


def MOVES() -> List[Move]:
    m: List[Move] = []
    # ── market ───────────────────────────────────────────────────────────────────────────────────────
    m += [Move("okx_cex", "dir", "okx/cex", "market/okx/cex", "market"),
          Move("okx_dex", "dir", "okx/dex", "market/okx/dex", "market"),
          Move("binance_cex", "dir", "binance/cex", "market/binance/cex", "market"),
          ]
    # data/binance_hist KHÔNG chuyển: phiên logic gộp nó vào binance/cex (một chuỗi liền) TRƯỚC khi migrate; --apply từ chối nếu nó còn
    # data/_meta (danh sách target crawl cũ, không code nào đọc) KHÔNG chuyển: người dùng chốt 2026-10-08 bỏ hẳn, chỉ còn market/<sàn>/{cex,dex}
    # ── alpha: cấu hình / định nghĩa (git-tracked) ───────────────────────────────────────────────────
    for f in ("book.json", "registry.json", "presets.json"):
        m.append(Move(f"alpha_{f.split('.')[0]}", "file", f"alphas/{f}", f"alpha/{f}", "alpha", "git-tracked"))
    m += [Move("alpha_explore", "dir", "alphas/explore", "alpha/explore", "alpha", "git-tracked"),
          Move("alpha_testnet", "dir", "alphas/testnet", "alpha/testnet", "alpha", "git-tracked"),
          Move("alpha_user", "dir", "alphas/user", "alpha/user", "alpha", "không commit; hiện rỗng"),
          Move("alpha_strategies", "dir", "alphas/strategies", "alpha/strategies", "alpha",
               "P9.9: chiến lược hệ thống = file Python DSL (kema/sideway/dca.py); optimize/book/build.strategies_dir() ưu tiên alpha/strategies, rơi về alphas/strategies; đang git-tracked"),
          Move("alpha_research", "dir", "alphas/research", "alpha/research", "alpha",
               "okx_top10_agents.json (core/analytics/top_agents.py đọc; đang git-tracked)"),
          Move("edu_samples", "file", "education/samples.json", "alpha/education/samples.json", "alpha", "tracked theo ADR §4.7 (hiện .gitignore chặn)"),
          Move("registry_fix", "registry", "", "", "alpha",
               f"BƯỚC RIÊNG: bỏ mục alpha_id={STALE_ALPHA_ID} khỏi alpha/registry.json (sao lưu vào thư mục báo cáo); cần --remove-stale-registry")]
    # ── kết quả lâu dài ──────────────────────────────────────────────────────────────────────────────
    m += [Move("backtest_runs", "dir", "_cache/backtest", "backtest", "backtest",
               "kết quả backtest/<id> do bộ ghi kết quả của phiên alpha đã tạo (run_dir fallback _cache/backtest); phải đi TRƯỚC edu_results"),
          Move("edu_results", "dir", "education/results", "backtest/education", "backtest", "sinh lại được (edu_precompute)"),
          Move("wfa", "dir", "_cache/book_wfa", "wfa", "wfa"),
          Move("funnel", "dir", "_cache/funnel", "alpha/funnel", "alpha", "không commit; chứa results.sqlite(+wal/shm)"),
          Move("book_runs", "dir", "_cache/book", "alpha/book", "alpha", "không commit")]
    # ── live: lâu dài, bot đang ghi (rename nguyên tử + symlink tương đối ở đường cũ) ────────────────────
    m.append(Move("live", "dir", "_cache/live", "live", "live", "bot paper/demo đang ghi vào đây: cần --allow-live", live=True))
    # ── cache/shared: mmap dùng chung + cache quality gate (cache CHỈ có process/ và shared/) ───────────
    m += [Move("shared_mmap", "merge", "_cache/shared", "cache/shared", "cache", "mmap chỉ báo dùng chung; hiện KHÔNG tồn tại (mỗi run dùng <run_dir>/_shared) -> bỏ qua"),
          Move("qg_root", "dir", "_cache/quality_gate", "cache/shared/quality_gate", "cache"),
          Move("qg_okx", "merge", "okx/_cache/quality_gate", "cache/shared/quality_gate", "cache", "tên file = sha1 khoá: gộp, trùng nội dung thì bỏ bản sao; trùng tên khác nội dung giữ bản mới hơn", newest_wins=True),
          Move("qg_binance", "merge", "binance/_cache/quality_gate", "cache/shared/quality_gate", "cache", newest_wins=True)]
    # ── vòng đời kết quả: persist_finished_jobs TRƯỚC khi chuyển phần job còn lại sang cache/process ────
    m.append(Move("persist_finished", "persist", "", "", "process",
                  "api/jobs/batch.persist_finished_jobs(apply=True): kết quả job đã xong -> backtest|wfa|alpha/{book,funnel}; dọn thư mục process (live_bot/custom_backtest bỏ qua)"))
    m += [Move("process", "dir", "_cache/api_jobs", "cache/process", "cache", "job còn lại: đang chạy (kể cả live_bot), lỗi/huỷ (log 7 ngày), live_bot đã dừng, custom_backtest", live=True),
          Move("mem_csv", "dir", "_cache/runs", "cache/process/_mem", "cache",
               "log RAM *_mem.csv của run_limited.sh (không theo job: tên '_mem' không khớp _JOB_ID_RE nên prune/persist không đụng); dọn sau 7 ngày = việc của P9.6"),
          Move("staging", "dir", "data_staging", "cache/process/_staging", "cache", "nora/data_staging (vùng đệm crawl->promote); hiện không tồn tại -> bỏ qua", base="nora"),
          Move("migration_archive", "merge", "_migration", "cache/process/_migration", "cache",
               "bản lưu của migrate_pkl_meta (manifest gốc + sao lưu binance) do phiên logic ghi tạm ở data/_migration")]
    return m


# ── tiện ích ─────────────────────────────────────────────────────────────────────────────────────────
def repo_of(data: str) -> str:
    """Gốc repo = cha của cha data/ (nora/data -> <repo>)."""
    return os.path.dirname(os.path.dirname(data))


def src_abs(m: Move, data: str) -> str:
    return os.path.join(os.path.dirname(data) if m.base == "nora" else data, m.src)


def dst_abs(m: Move, data: str) -> str:
    return os.path.join(data, m.dst)


def walk_files(path: str):
    """(đường tương đối, đường tuyệt đối) mọi file thường + symlink (không theo symlink) dưới path."""
    if os.path.isfile(path) and not os.path.islink(path):
        yield "", path
        return
    for root, dirs, files in os.walk(path, followlinks=False):
        for n in files:
            p = os.path.join(root, n)
            yield os.path.relpath(p, path), p
        for n in dirs:
            p = os.path.join(root, n)
            if os.path.islink(p):
                yield os.path.relpath(p, path), p


def stats(path: str) -> Tuple[int, int]:
    n = b = 0
    for _, p in walk_files(path):
        try:
            st = os.lstat(p)
        except OSError:
            continue
        n += 1
        b += 0 if os.path.islink(p) else st.st_size
    return n, b


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            blk = fh.read(4 * 1024 * 1024)
            if not blk:
                break
            h.update(blk)
    return h.hexdigest()


def manifest(path: str, full: bool, workers: int) -> Dict[str, dict]:
    """rel -> {size, mtime_ns, ino, sha (None nếu file lớn và không --full-hash), link (nếu symlink)}."""
    out: Dict[str, dict] = {}
    todo = []
    for rel, p in walk_files(path):
        st = os.lstat(p)
        if os.path.islink(p):
            out[rel] = {"link": os.readlink(p), "size": 0, "mtime_ns": st.st_mtime_ns, "ino": st.st_ino, "sha": None}
            continue
        out[rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "ino": st.st_ino, "sha": None}
        if full or st.st_size <= BIG_BYTES:
            todo.append((rel, p))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for (rel, _), h in zip(todo, ex.map(lambda t: sha256_file(t[1]), todo)):
            out[rel]["sha"] = h
    return out


def compare(pre: Dict[str, dict], post: Dict[str, dict]) -> dict:
    """Số file khớp, thiếu, thừa, khác; 'mutated_live' = cùng inode nhưng nội dung đổi (tiến trình khác đang ghi)."""
    res = {"pre_files": len(pre), "post_files": len(post), "missing": [], "extra": [], "differ": [], "mutated_live": [], "hashed": 0}
    for rel, a in pre.items():
        b = post.get(rel)
        if b is None:
            res["missing"].append(rel)
            continue
        if a.get("link") != b.get("link"):
            res["differ"].append(rel)
            continue
        if a["sha"] is not None:
            res["hashed"] += 1
        same = a["size"] == b["size"] and (a["sha"] == b["sha"] if a["sha"] is not None and b["sha"] is not None else a["mtime_ns"] == b["mtime_ns"])
        if not same:
            (res["mutated_live"] if a["ino"] == b["ino"] and b["size"] >= a["size"] else res["differ"]).append(rel)
    res["extra"] = [r for r in post if r not in pre]
    res["ok"] = not (res["missing"] or res["differ"])
    res["mutated_live_n"] = len(res["mutated_live"])
    res["mutated_live"] = res["mutated_live"][:20]
    for k in ("missing", "extra", "differ"):
        res[k] = res[k][:20]
    return res


def same_device(a: str, b: str) -> bool:
    b = b
    while not os.path.exists(b):
        b = os.path.dirname(b)
    return os.stat(a).st_dev == os.stat(b).st_dev


def pid_alive(pid) -> bool:
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            return fh.read().rsplit(b")", 1)[1].split()[0] != b"Z"
    except Exception:
        return False


def running_jobs(data: str) -> List[dict]:
    """Job API đang chạy (job.json state=running + pid sống), duyệt cả đường cũ _cache/api_jobs lẫn cache/process."""
    seen, out = set(), []
    for base in (os.path.join(data, "cache", "process"), os.path.join(data, "_cache", "api_jobs")):
        if not os.path.isdir(base):
            continue
        real = os.path.realpath(base)
        if real in seen:
            continue
        seen.add(real)
        for n in os.listdir(real):
            jp = os.path.join(real, n, "job.json")
            try:
                with open(jp, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                continue
            if meta.get("state") == "running" and pid_alive(meta.get("pid")):
                out.append({"id": meta.get("id", n), "kind": meta.get("kind"), "pid": meta.get("pid"), "params": meta.get("params") or {}})
    return out


def entry_state(m: Move, data: str) -> str:
    s, d = src_abs(m, data), dst_abs(m, data)
    if os.path.islink(s):
        return "done" if os.path.realpath(s) == os.path.realpath(d) else "foreign_link"
    if os.path.lexists(s):
        if m.kind == "merge":
            return "merge_todo"
        return "conflict" if os.path.lexists(d) else "todo"
    if os.path.lexists(d):
        return "needs_link"
    return "src_missing"


def rel_link(s: str, d: str) -> str:
    return os.path.relpath(os.path.realpath(d), os.path.realpath(os.path.dirname(s)))


# ── thực hiện ────────────────────────────────────────────────────────────────────────────────────────
def link_swap(s: str, d: str, mover) -> None:
    """Tạo symlink tạm -> mover() (chuyển nguồn) -> đặt symlink tạm vào đường cũ. Mọi bước là rename nguyên tử."""
    tmp = s + LNK_SUFFIX
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(rel_link(s, d), tmp)
    try:
        mover()
        os.replace(tmp, s)
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise


def do_dir_or_file(m: Move, data: str, a) -> dict:
    s, d = src_abs(m, data), dst_abs(m, data)
    r: dict = {}
    os.makedirs(os.path.dirname(d), exist_ok=True)
    pre = manifest(s, a.full_hash, a.workers)
    r["files"], r["bytes"] = len(pre), sum(v["size"] for v in pre.values())
    same = same_device(s, d)
    r["method"] = "rename" if same else "copy"
    if not same and m.live:
        raise RuntimeError("thư mục live khác ổ đĩa: không sao chép khi tiến trình đang ghi")
    if same:
        # d chưa tồn tại (entry_state đã kiểm); thư mục cha của d đã tạo ở trên
        link_swap(s, d, lambda: os.rename(s, d))
    else:
        part = d + ".p93part"
        if os.path.lexists(part):
            shutil.rmtree(part) if os.path.isdir(part) else os.remove(part)
        (shutil.copytree(s, part, symlinks=True) if os.path.isdir(s) else shutil.copy2(s, part))
        chk = compare(pre, manifest(part, a.full_hash, a.workers))
        if not chk["ok"] or chk["mutated_live_n"]:
            raise RuntimeError(f"kiểm sau sao chép lỗi: {chk}")
        os.rename(part, d)
        old = s + ".p93old"
        link_swap(s, d, lambda: os.rename(s, old))
        shutil.rmtree(old) if os.path.isdir(old) else os.remove(old)
    post = manifest(d, a.full_hash, a.workers)
    chk = compare(pre, post)
    r["verify"] = chk
    if not chk["ok"]:
        # hoàn tác (chỉ khi rename): bỏ symlink, trả thư mục về chỗ cũ
        if same and os.path.islink(s):
            os.remove(s)
            os.rename(d, s)
            r["rolled_back"] = True
        raise RuntimeError(f"kiểm sau chuyển lỗi: {chk}")
    return r


def do_merge(m: Move, data: str, a) -> dict:
    s, d = src_abs(m, data), dst_abs(m, data)
    os.makedirs(d, exist_ok=True)
    pre = manifest(s, a.full_hash, a.workers)
    r = {"files": len(pre), "bytes": sum(v["size"] for v in pre.values()), "moved": 0, "deduped": 0, "method": "rename"}
    for rel in sorted(pre):
        sp, dp = os.path.join(s, rel), os.path.join(d, rel)
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        if not os.path.lexists(dp):
            os.rename(sp, dp)
            r["moved"] += 1
        elif pre[rel]["sha"] is not None and sha256_file(dp) == pre[rel]["sha"]:
            os.remove(sp)
            r["deduped"] += 1
        elif m.newest_wins:   # cache thuần: giữ bản mới hơn
            if os.lstat(sp).st_mtime_ns > os.lstat(dp).st_mtime_ns:
                os.replace(sp, dp)
            else:
                os.remove(sp)
            r["collisions_resolved"] = r.get("collisions_resolved", 0) + 1
        else:
            raise RuntimeError(f"va chạm tên khác nội dung: {rel}")
    for root, dirs, files in os.walk(s, topdown=False):   # chỉ còn thư mục rỗng
        for n in dirs:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.rmdir(p)
    os.rmdir(s)
    os.symlink(rel_link(s, d), s)
    post = manifest(d, a.full_hash, a.workers)
    miss = [rel for rel in pre if rel not in post or (not m.newest_wins and pre[rel]["sha"] and post[rel]["sha"] != pre[rel]["sha"])]
    done = r["moved"] + r["deduped"] + r.get("collisions_resolved", 0)
    r["verify"] = {"ok": not miss and done == len(pre), "missing_or_differ": miss[:20], "pre_files": len(pre), "accounted": done}
    if miss or done != len(pre):
        raise RuntimeError(f"kiểm gộp lỗi: {r['verify']}")
    return r


def needs_link_fix(m: Move, data: str) -> dict:
    s, d = src_abs(m, data), dst_abs(m, data)
    tmp = s + LNK_SUFFIX
    if os.path.lexists(tmp):
        os.replace(tmp, s)
    else:
        os.makedirs(os.path.dirname(s), exist_ok=True)
        os.symlink(rel_link(s, d), s)
    return {"method": "relink"}


# ── chính ────────────────────────────────────────────────────────────────────────────────────────────
def covered(rel: str, srcs: List[str]) -> Optional[bool]:
    """True nếu rel là/nằm trong nguồn đã ánh xạ; None nếu là cha của một nguồn (đi sâu hơn); False nếu chưa được ánh xạ."""
    for s in srcs:
        if rel == s or rel.startswith(s + "/"):
            return True
    for s in srcs:
        if s.startswith(rel + "/"):
            return None
    return False


def find_unmapped(data: str, moves: List[Move]) -> List[dict]:
    srcs = [m.src for m in moves if m.base == "data" and m.kind in ("dir", "file", "merge")]
    out: List[dict] = []

    def rec(rel: str):
        full = os.path.join(data, rel)
        for n in sorted(os.listdir(full)):
            r = f"{rel}/{n}" if rel else n
            p = os.path.join(data, r)
            if os.path.islink(p) or r.startswith("_migration"):
                continue
            c = covered(r, srcs)
            if c is None and os.path.isdir(p):
                rec(r)
            elif c is False:
                nf, nb = stats(p)
                out.append({"path": r, "files": nf, "bytes": nb})
    rec("")
    dest_roots = {m.dst.split("/")[0] for m in moves if m.dst}      # market, cache, alpha, backtest, wfa, live: gốc ĐÍCH, không phải dữ liệu chưa ánh xạ
    return [u for u in out if u["path"].split("/")[0] not in dest_roots]


def fmt_b(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return str(n)


# ── .gitignore (ADR §4.7): đề xuất, KHÔNG ghi trừ khi --write-gitignore ──────────────────────────────────
GITIGNORE_BLOCK = """# Ngoại lệ: nora/data/ chỉ theo dõi phần định nghĩa/cấu hình của nora/data/alpha/ (ADR-P9 §4.7). Không commit: alpha/{user,funnel,book}/, market/, backtest/,
# wfa/, carlo/, live/, cache/ và symlink tạm ở đường cũ (alphas, _cache, okx, binance, ... nằm dưới nora/data/* nên đã bị chặn)
!nora/data/
nora/data/*
!nora/data/alpha/
nora/data/alpha/*
!nora/data/alpha/strategies/
!nora/data/alpha/education/
!nora/data/alpha/universes/
!nora/data/alpha/research/
!nora/data/alpha/explore/
!nora/data/alpha/testnet/
!nora/data/alpha/presets.json
!nora/data/alpha/registry.json
!nora/data/alpha/book.json
"""
_GI_OLD = re.compile(r"# Ngoại lệ: nora/data/alpha/[^\n]*\n!nora/data/\nnora/data/\*\n!nora/data/alpha/\n")


def new_gitignore_text(old: str) -> str:
    if not _GI_OLD.search(old):
        raise RuntimeError("không thấy khối nora/data cũ trong .gitignore (đã sửa rồi?)")
    return _GI_OLD.sub(lambda _m: GITIGNORE_BLOCK, old, count=1)


def gitignore_diff() -> str:
    gp = os.path.join(REPO, ".gitignore")
    with open(gp, encoding="utf-8") as fh:
        old = fh.read()
    new = new_gitignore_text(old)
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/.gitignore", "b/.gitignore"))


# ── bước đặc biệt ────────────────────────────────────────────────────────────────────────────────────
def newpath(p: str, data: str, moves: List[Move]) -> str:
    """Ánh xạ đường CŨ -> MỚI theo bảng MOVES (để dry-run hiển thị đích mới của persist_finished_jobs)."""
    for m in moves:
        if m.kind in ("dir", "file", "merge") and m.base == "data":
            sa = os.path.join(data, m.src)
            if p == sa or p.startswith(sa + os.sep):
                return os.path.join(data, m.dst) + p[len(sa):]
    return p


def persist_step(data: str, apply: bool, moves: List[Move]) -> dict:
    os.environ["NORA_DATA_ROOT"] = data
    if os.environ.get("NORA_LOCAL_DATA_ROOT"):
        raise RuntimeError("NORA_LOCAL_DATA_ROOT đang đặt: batch.persist_finished_jobs sẽ ghi sai chỗ")
    from backend.optimize.process import process as batch
    jr = batch.jobs_root()
    rows = batch.persist_finished_jobs(apply=apply)
    by: Dict[str, Dict[str, int]] = {}
    for r in rows:
        by.setdefault(str(r["kind"]), {}).setdefault(r["action"], 0)
        by[str(r["kind"])][r["action"]] += 1
    dests: Dict[str, set] = {}
    for r in rows:
        if r.get("dest"):
            dests.setdefault(str(r["kind"]), set()).add(os.path.relpath(os.path.dirname(newpath(r["dest"], data, moves)), data))
    n_dirs = sum(1 for n in os.listdir(jr) if os.path.isdir(os.path.join(jr, n)))
    return {"jobs_root": os.path.relpath(jr, data), "process_dirs_before_or_now": n_dirs, "touched": len(rows), "by_kind": by,
            "dest_dirs": {k: sorted(v) for k, v in dests.items()}, "ids": [r["id"] for r in rows] if apply else []}


def registry_path(data: str) -> Optional[str]:
    for rel in ("alpha/registry.json", "alphas/registry.json"):
        p = os.path.join(data, rel)
        if os.path.isfile(p):
            return p
    return None


def registry_plan(data: str) -> dict:
    rp = registry_path(data)
    if not rp:
        return {"state": "src_missing"}
    with open(rp, encoding="utf-8") as fh:
        text = fh.read()
    reg = json.loads(text)
    ids = [a.get("alpha_id") for a in reg.get("alphas", [])]
    hit = [i for i in ids if i == STALE_ALPHA_ID]
    return {"path": os.path.relpath(rp, repo_of(data)), "alphas_before": ids, "remove": hit, "alphas_after": [i for i in ids if i != STALE_ALPHA_ID],
            "other_keys_untouched": sorted(k for k in reg if k != "alphas"), "state": "todo" if hit else "done",
            "source_optimization": reg.get("source_optimization"), "pairs_evaluated": reg.get("pairs_evaluated"),
            "source_exists": os.path.exists(str(reg.get("source_optimization") or "")),
            "format_preserved": json.dumps(reg, indent=2, ensure_ascii=False) == text}


def registry_apply(data: str, outdir: str) -> dict:
    plan = registry_plan(data)
    rp = registry_path(data)
    os.makedirs(outdir, exist_ok=True)
    bak = os.path.join(outdir, "registry.json.bak")
    shutil.copy2(rp, bak)
    with open(rp, encoding="utf-8") as fh:
        text = fh.read()
    reg = json.loads(text)
    if json.dumps(reg, indent=2, ensure_ascii=False) != text:
        raise RuntimeError("registry.json không còn đúng định dạng indent=2: không tự ghi lại (đã có bản sao lưu)")
    reg["alphas"] = [a for a in reg.get("alphas", []) if a.get("alpha_id") != STALE_ALPHA_ID]
    tmp = rp + ".p93tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(reg, indent=2, ensure_ascii=False))
    os.replace(tmp, rp)
    plan.update({"backup": bak, "backup_sha256": sha256_file(bak), "written": True})
    return plan


# ── tiến trình đang giữ file dưới data/ (đọc-chỉ /proc) ──────────────────────────────────────────────────
def proc_holders(data: str) -> List[dict]:
    real = os.path.realpath(data)
    pre = (data, real)
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == os.getpid():
            continue
        refs: Dict[str, List[str]] = {}
        try:
            with open(f"/proc/{p}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue

        def add(k, v):
            refs.setdefault(k, [])
            if v not in refs[k]:
                refs[k].append(v)
        try:
            for f in os.listdir(f"/proc/{p}/fd"):
                try:
                    t = os.readlink(f"/proc/{p}/fd/{f}")
                except OSError:
                    continue
                if t.startswith(pre):
                    add("fd", os.path.relpath(t, real))
        except OSError:
            pass
        try:
            t = os.readlink(f"/proc/{p}/cwd")
            if t.startswith(pre):
                add("cwd", os.path.relpath(t, real))
        except OSError:
            pass
        try:
            with open(f"/proc/{p}/maps") as fh:
                for ln in fh:
                    if real in ln:
                        add("mmap", os.path.relpath(ln.split()[-1], real))
        except OSError:
            pass
        for a in cmd.split():
            if a.startswith(pre):
                add("cmdline", os.path.relpath(a, real))
        try:
            with open(f"/proc/{p}/environ", "rb") as fh:
                for kv in fh.read().split(b"\0"):
                    k, _, v = kv.decode("utf-8", "replace").partition("=")
                    if k.startswith("NORA_") and v.startswith(pre):
                        add("env:" + k, os.path.relpath(v, real))
        except OSError:
            pass
        if refs:
            out.append({"pid": int(p), "cmd": cmd[:160], "refs": refs})
    return out


# ── bot live: kiểm còn ghi sau khi chuyển ─────────────────────────────────────────────────────────────
def state_key(params: dict) -> str:
    """Nguyên văn store.live_state_key."""
    venue, mode, book, engine = params.get("venue", "okx"), params.get("mode", "paper"), params.get("book", "main"), params.get("engine", "legacy")
    return f"{venue}_{mode}" + ("_explore" if book == "explore" else "") + ("_unified" if engine == "unified" and mode in ("demo", "live") else "")


def _first(*paths: str) -> str:
    return next((p for p in paths if os.path.exists(p)), paths[0])


def live_paths(j: dict, data: str) -> dict:
    jd = _first(os.path.join(data, "cache", "process", j["id"]), os.path.join(data, "_cache", "api_jobs", j["id"]))
    sd = _first(os.path.join(data, "live", state_key(j["params"])), os.path.join(data, "_cache", "live", state_key(j["params"])))
    return {"job_dir": jd, "state_dir": sd}


def _sig_dir(d: str) -> dict:
    out = {}
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        try:
            st = os.stat(os.path.join(d, n))
            out[n] = (st.st_ino, st.st_size, st.st_mtime_ns)
        except OSError:
            pass
    return out


def live_snapshot(live: List[dict], data: str) -> Dict[str, dict]:
    snap = {}
    for j in live:
        lp = live_paths(j, data)
        snap[j["id"]] = {"pid": j["pid"], "key": state_key(j["params"]), "job_dir_before": lp["job_dir"], "state_dir_before": lp["state_dir"],
                         "job": _sig_dir(lp["job_dir"]), "state": _sig_dir(lp["state_dir"])}
    return snap


def live_verify(snap: Dict[str, dict], data: str, wait: float) -> List[dict]:
    """Mỗi bot: còn sống; đường CŨ (symlink) và đường MỚI cùng một thư mục; out.log cùng inode; có file nào đổi mtime không (chờ tối đa `wait` giây)."""
    t_end = time.time() + wait
    while True:
        res = []
        for jid, b in snap.items():
            old_job, new_job = os.path.join(data, "_cache", "api_jobs", jid), os.path.join(data, "cache", "process", jid)
            old_state, new_state = os.path.join(data, "_cache", "live", b["key"]), os.path.join(data, "live", b["key"])
            nj, ns = _sig_dir(new_job), _sig_dir(new_state)
            grew = [f"job/{n}" for n, v in nj.items() if n not in b["job"] or b["job"][n][2] != v[2]] + \
                   [f"state/{n}" for n, v in ns.items() if n not in b["state"] or b["state"][n][2] != v[2]]
            same_log = "out.log" in b["job"] and "out.log" in nj and b["job"]["out.log"][0] == nj["out.log"][0]
            res.append({"id": jid, "pid": b["pid"], "alive": pid_alive(b["pid"]),
                        "job_old_resolves": os.path.realpath(old_job) == os.path.realpath(new_job) and os.path.isdir(new_job),
                        "state_old_resolves": os.path.realpath(old_state) == os.path.realpath(new_state) and os.path.isdir(new_state),
                        "out_log_same_inode": same_log, "files_changed_since_snapshot": grew[:6], "writing": bool(grew)})
        if all(r["writing"] for r in res) or time.time() >= t_end:
            for r in res:
                r["ok"] = bool(r["alive"] and r["job_old_resolves"] and r["state_old_resolves"] and r["out_log_same_inode"])
            return res
        time.sleep(5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="mặc định: chỉ lập kế hoạch + kiểm điều kiện, không đổi gì")
    mode.add_argument("--apply", action="store_true", help="thực hiện chuyển")
    ap.add_argument("--data-root", default=os.environ.get("NORA_DATA_ROOT") or os.path.join(NORA, "data"))
    ap.add_argument("--allow-live", action="store_true", help="cho phép khi live_bot đang chạy (thư mục live/process chuyển nguyên tử, symlink thế chỗ)")
    ap.add_argument("--allow-jobs", action="store_true", help="cho phép khi job nặng khác đang chạy")
    ap.add_argument("--remove-stale-registry", action="store_true", help=f"bước registry_fix: bỏ mục {STALE_ALPHA_ID} khỏi alpha/registry.json (có sao lưu)")
    ap.add_argument("--only", default="", help="chỉ các khoá này (phân tách bằng dấu phẩy)")
    ap.add_argument("--full-hash", action="store_true", help="băm sha256 cả file > 100 MB (mặc định size + mtime_ns)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--verify-wait", type=float, default=90.0, help="giây chờ tối đa để thấy bot live còn ghi sau khi chuyển (chỉ --apply)")
    ap.add_argument("--git-stage", action="store_true", help="sau khi chuyển: git rm --cached đường cũ đã theo dõi + git add đường mới (KHÔNG commit)")
    ap.add_argument("--write-gitignore", action="store_true", help="(chỉ --apply) ghi .gitignore mới; mặc định chỉ in diff")
    ap.add_argument("--print-gitignore", action="store_true", help="in diff .gitignore đề xuất rồi thoát")
    ap.add_argument("--drop-old-links", action="store_true",
                    help="(chỉ --apply, bot đã DỪNG) sau khi chuyển: xoá symlink tương thích ở đường cũ, thư mục cũ rỗng và data/_meta -> data/ chỉ còn cây đích")
    ap.add_argument("--report", default="")
    a = ap.parse_args(argv)
    if a.print_gitignore:
        print(gitignore_diff())
        return 0
    dry = not a.apply
    data = os.path.abspath(a.data_root)
    moves = MOVES()
    only = {x for x in a.only.split(",") if x}
    unknown = only - {m.key for m in moves}
    if unknown:
        print(f"khoá không có: {sorted(unknown)}", file=sys.stderr)
        return 2
    t0 = time.time()
    run_jobs = running_jobs(data)
    live = [j for j in run_jobs if j["kind"] == "live_bot"]
    other = [j for j in run_jobs if j["kind"] != "live_bot"]
    guard = {"live_bot_running": [{k: v for k, v in j.items() if k != "params"} for j in live], "other_jobs_running": other,
             "allow_live": a.allow_live, "allow_jobs": a.allow_jobs}
    would_refuse = (bool(live) and not a.allow_live) or (bool(other) and not a.allow_jobs)
    plan = [m for m in moves if not only or m.key in only]

    print(f"[migrate_data_tree] {'DRY-RUN' if dry else 'APPLY'}  data={data}")
    print(f"  guard: live_bot đang chạy={len(live)} {[j['id'] for j in live]}  job khác={len(other)}  -> "
          f"{'SẼ TỪ CHỐI' if would_refuse else 'cho phép'}" + ("" if not would_refuse else " (cần --allow-live / --allow-jobs)"))
    if not dry and os.path.lexists(os.path.join(data, "binance_hist")):
        print("  TỪ CHỐI: data/binance_hist còn — phiên logic phải gộp nó vào binance/cex trước (người dùng chốt 2026-10-08).", file=sys.stderr)
        return 3
    if not dry and would_refuse:
        print("  TỪ CHỐI: dừng bot/job hoặc truyền --allow-live / --allow-jobs.", file=sys.stderr)
        return 3
    holders = proc_holders(data)
    snap = live_snapshot(live, data) if not dry else {}
    report_dir = os.path.join(data, "cache", "process", "_migration", f"p9_3c_{datetime.fromtimestamp(t0, timezone.utc):%Y%m%dT%H%M%SZ}")
    # báo cáo ghi tạm ở data/_migration_tmp_*, chuyển vào report_dir SAU cùng: bước "process" (_cache/api_jobs -> cache/process) phải thấy cache/process chưa tồn tại
    work_dir = os.path.join(data, f"_migration_tmp_{os.getpid()}")

    rows: List[dict] = []
    tot_f = tot_b = 0
    conflicts = 0
    for m in plan:
        s, d = (src_abs(m, data), dst_abs(m, data)) if m.kind in ("dir", "file", "merge") else ("", "")
        row = {"key": m.key, "group": m.group, "kind": m.kind, "src": os.path.relpath(s, repo_of(data)) if s else "", "dst": os.path.relpath(d, repo_of(data)) if d else "",
               "note": m.note, "live": m.live}
        rows.append(row)
        t1 = time.time()
        if m.kind == "persist":
            row["state_before"] = "todo"
            try:
                row["persist"] = persist_step(data, apply=not dry, moves=moves)
                row["status"] = None if dry else "ok"
            except Exception as exc:   # noqa: BLE001
                row["status"], row["error"] = "LỖI", f"{type(exc).__name__}: {exc}"
                print(f"  LỖI {m.key}: {row['error']}", file=sys.stderr)
                if not dry:
                    break
            row["seconds"] = round(time.time() - t1, 2)
            continue
        if m.kind == "registry":
            row["registry"] = registry_plan(data)
            row["state_before"] = row["registry"]["state"]
            if dry or row["state_before"] != "todo":
                continue
            if not a.remove_stale_registry:
                row["status"] = "BỎ QUA(cần --remove-stale-registry)"
                continue
            try:
                row["registry"] = registry_apply(data, work_dir)
                row["status"] = "ok"
            except Exception as exc:   # noqa: BLE001
                row["status"], row["error"] = "LỖI", f"{type(exc).__name__}: {exc}"
                print(f"  LỖI {m.key}: {row['error']}", file=sys.stderr)
                break
            continue
        st = entry_state(m, data)
        row["state_before"] = st
        if st in ("todo", "merge_todo"):
            nf, nb = stats(s)
            row["files"], row["bytes"] = nf, nb
            tot_f += nf
            tot_b += nb
            row["same_device"] = same_device(s, d)
            row["link"] = rel_link(s, d)
            if m.kind == "merge" and os.path.isdir(d):
                clash = [rel for rel, _ in walk_files(s) if os.path.lexists(os.path.join(d, rel))]
                row["name_clashes"] = len(clash)
        elif st == "conflict":
            conflicts += 1
        if dry:
            continue
        if st in ("done", "src_missing", "foreign_link", "conflict"):
            row["status"] = {"done": "ok(đã xong)", "src_missing": "bỏ qua(không có nguồn)", "foreign_link": "BỎ QUA(symlink lạ)", "conflict": "XUNG ĐỘT"}[st]
            if st in ("conflict", "foreign_link"):
                break
            continue
        try:
            res = needs_link_fix(m, data) if st == "needs_link" else (do_merge(m, data, a) if st == "merge_todo" else do_dir_or_file(m, data, a))
            row.update(res)
            row["status"] = "ok"
        except Exception as exc:   # noqa: BLE001 — báo cáo và dừng ở mục lỗi (các mục sau không chạy)
            row["status"] = "LỖI"
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["seconds"] = round(time.time() - t1, 2)
            print(f"  LỖI {m.key}: {row['error']}", file=sys.stderr)
            break
        row["seconds"] = round(time.time() - t1, 2)

    unmapped = find_unmapped(data, moves)
    try:
        gi_diff = gitignore_diff()
    except RuntimeError as exc:
        gi_diff = f"(không tạo được diff: {exc})"
    rep = {"mode": "dry-run" if dry else "apply", "started_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(), "data_root": data,
           "guard": guard, "would_refuse": would_refuse, "entries": rows, "unmapped": unmapped, "proc_holders": holders,
           "totals": {"entries": len(plan), "to_move_files": tot_f, "to_move_bytes": tot_b, "conflicts": conflicts},
           "gitignore_diff": gi_diff, "seconds": round(time.time() - t0, 1)}
    failed = any(r.get("status") in ("LỖI", "XUNG ĐỘT", "BỎ QUA(symlink lạ)") for r in rows)
    if not dry and snap and not failed:
        rep["live_verify"] = live_verify(snap, data, a.verify_wait)
    if not dry and a.write_gitignore and not failed:
        gp = os.path.join(REPO, ".gitignore")
        with open(gp, encoding="utf-8") as fh:
            old = fh.read()
        with open(gp, "w", encoding="utf-8") as fh:
            fh.write(new_gitignore_text(old))
        rep["gitignore_written"] = gp
    if not dry and a.drop_old_links and not failed:
        if live:
            print("  BỎ QUA --drop-old-links: live_bot còn chạy (bot đang dùng symlink ở đường cũ)", file=sys.stderr)
        else:
            rep["dropped_old"] = drop_old_links(data, moves)
    if not dry and a.git_stage and not failed:
        rep["git"] = git_stage(rows, data)

    print(f"{'key':<20}{'state':<14}{'files':>8}{'size':>11}  {'src':<44} -> dst")
    for r in rows:
        print(f"{r['key']:<20}{(r.get('status') or r['state_before']):<14}{r.get('files', 0):>8}{fmt_b(r.get('bytes', 0)):>11}  {r['src'][-44:]:<44} -> {r['dst']}"
              + (f"  (va chạm tên={r['name_clashes']})" if r.get("name_clashes") else ""))
        if r.get("persist"):
            ps = r["persist"]
            print(f"    persist: root={ps['jobs_root']} thư mục process={ps['process_dirs_before_or_now']} chạm={ps['touched']}")
            for k, v in sorted(ps["by_kind"].items()):
                print(f"      {k:<18}{v}  -> {ps['dest_dirs'].get(k, ['(dọn, không chép)'])}")
        if r.get("registry"):
            g = r["registry"]
            print(f"    registry: {g.get('path')} alphas {g.get('alphas_before')} -> {g.get('alphas_after')}; khoá giữ nguyên={g.get('other_keys_untouched')}; "
                  f"source_optimization tồn tại={g.get('source_exists')}; giữ định dạng={g.get('format_preserved')}")
    print(f"  CHƯA ÁNH XẠ ({len(unmapped)}): " + (", ".join(f"{u['path']} ({u['files']}f, {fmt_b(u['bytes'])})" for u in unmapped) or "không"))
    print(f"  TỔNG cần chuyển: {tot_f} file, {fmt_b(tot_b)} trong {len(plan)} bước; xung đột={conflicts}; {rep['seconds']}s")
    print(f"  tiến trình giữ file dưới data/: {len(holders)}")
    for h in holders:
        print(f"    pid {h['pid']}: {h['cmd'][:90]}  " + "; ".join(f"{k}={v[:2]}" for k, v in h["refs"].items()))
    if not dry:
        bad = [r for r in rows if r.get("status") in ("LỖI", "XUNG ĐỘT")]
        mutated = sum(r.get("verify", {}).get("mutated_live_n", 0) for r in rows)
        print(f"  KẾT QUẢ: {len(rows) - len(bad)}/{len(rows)} bước ok; file live đang ghi trong lúc chuyển (cùng inode): {mutated}")
        for v in rep.get("live_verify", []):
            print(f"  live {v['id']} pid {v['pid']}: ok={v['ok']} alive={v['alive']} job_old->new={v['job_old_resolves']} state_old->new={v['state_old_resolves']} "
                  f"out.log cùng inode={v['out_log_same_inode']} đang ghi={v['writing']} {v['files_changed_since_snapshot']}")
    path = a.report or (None if dry else os.path.join(work_dir, "report.json"))
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1, default=str)
    if os.path.isdir(work_dir):   # mọi bước chuyển đã xong -> đưa báo cáo (và bản sao lưu registry) vào cache/process/_migration
        os.makedirs(os.path.dirname(report_dir), exist_ok=True)
        shutil.move(work_dir, report_dir)
        if path and os.path.abspath(path).startswith(work_dir + os.sep):
            path = os.path.join(report_dir, os.path.relpath(path, work_dir))
    if path:
        print(f"  báo cáo: {path}")
    if not dry and (failed or any(not v["ok"] for v in rep.get("live_verify", []))):
        return 1
    return 0


OLD_TOP = ("okx", "binance", "_cache", "alphas", "education")   # thư mục gốc cũ: chỉ xoá khi rỗng sau khi bỏ symlink
META_FILES = ("cex_targets.json", "dex_targets.json", "geckoterminal_dex_targets.json", "geckoterminal_dex_targets.quality.json",
              "geckoterminal_dex_targets.refill.json", "geckoterminal_dex_targets.refill.out.json")   # data/_meta: danh sách target crawl cũ, không code nào đọc


def drop_old_links(data: str, moves: List[Move]) -> dict:
    """Bỏ phần tương thích sau khi chuyển: symlink ở đường cũ (chỉ khi trỏ đúng đích), thư mục cũ rỗng, data/_meta (đúng 6 file đã biết)."""
    out = {"links_removed": [], "dirs_removed": [], "meta_removed": [], "kept": []}
    for m in moves:
        if m.kind not in ("dir", "file", "merge"):
            continue
        s, d = src_abs(m, data), dst_abs(m, data)
        if os.path.islink(s) and os.path.realpath(s) == os.path.realpath(d):
            os.remove(s)
            out["links_removed"].append(os.path.relpath(s, data))
    meta = os.path.join(data, "_meta")
    if os.path.isdir(meta):
        extra = sorted(set(os.listdir(meta)) - set(META_FILES))
        if extra:
            out["kept"].append({"_meta": extra})
        else:
            for f in os.listdir(meta):
                os.remove(os.path.join(meta, f))
                out["meta_removed"].append(f)
            os.rmdir(meta)
    for top in OLD_TOP:
        root = os.path.join(data, top)
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        for r, dirs, files in os.walk(root, topdown=False):
            if not os.listdir(r):
                os.rmdir(r)
                out["dirs_removed"].append(os.path.relpath(r, data))
        if os.path.isdir(root):
            out["kept"].append({top: sorted(os.listdir(root))[:20]})
    return out


def git_stage(rows: List[dict], data: str) -> dict:
    """Chỉ stage (không commit): bỏ đường cũ đang được theo dõi khỏi chỉ mục, thêm đường mới (-f) cho mục thuộc nhóm alpha."""
    out = {"rm_cached": [], "added": []}
    tracked = set(subprocess.run(["git", "-C", REPO, "ls-files", "nora/data"], capture_output=True, text=True).stdout.split())
    for r in rows:
        if r.get("status") not in ("ok", "ok(đã xong)") or r["group"] != "alpha" or not r["src"]:
            continue
        olds = [t for t in tracked if t == r["src"] or t.startswith(r["src"] + "/")]
        if olds or r["key"] == "edu_samples":
            subprocess.run(["git", "-C", REPO, "rm", "-r", "--cached", "-q", "--", r["src"]], check=False)
            subprocess.run(["git", "-C", REPO, "add", "-f", "--", r["dst"]], check=False)
            out["rm_cached"].append(r["src"])
            out["added"].append(r["dst"])
    return out


if __name__ == "__main__":
    sys.exit(main())
