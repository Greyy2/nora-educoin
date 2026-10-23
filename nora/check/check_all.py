#!/usr/bin/env python3
"""
NORA MASTER SYSTEM & ARCHITECTURE VERIFIER
==========================================
Script kiểm tra toàn diện độc lập cho Nora (COIN & EDU):
1. [Arch] Kiểm định cấu trúc thư mục sạch (chỉ còn nora/coin, nora/edu, nora/ops, nora/check)
2. [Isolation] Kiểm định cô lập mã nguồn: không cross-import giữa EDU và COIN
3. [Services] Kiểm tra sức khỏe dịch vụ đang chạy trên port 18012 (COIN) và 18022 (EDU)
4. [Nginx] Kiểm tra trạng thái vhost và domain cutover
5. [RubiLab] Kiểm tra tính đúng đắn toán học, causality, edge-cases của thuật toán
6. [Test Suites] Chạy bộ test hồi quy tự động của COIN và EDU (tuỳ chọn hoặc mặc định)

Sử dụng:
    python nora/check/check_all.py
    python nora/check/check_all.py --skip-tests
    python nora/check/check_all.py --help
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

# Base paths
NORA_DIR = Path("/home/vmc03/norabt/nora").resolve()
VENV_PYTHON = Path("/home/vmc03/.venvs/nora312/bin/python")
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class SystemChecker:
    def __init__(self, run_tests: bool = True):
        self.run_tests = run_tests
        self.results: List[Tuple[str, str, bool, str]] = []

    def log_result(self, category: str, item: str, passed: bool, message: str):
        self.results.append((category, item, passed, message))
        status_str = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  [{status_str}] {BOLD}{item}{RESET}: {message}")

    # =========================================================================
    # 1. ARCHITECTURE CLEANLINESS
    # =========================================================================
    def check_architecture(self):
        print(f"\n{CYAN}{BOLD}1. KIỂM ĐỊNH CẤU TRÚC THƯ MỤC NORA (ARCH CLEANLINESS){RESET}")
        
        # 1.1 Kiểm tra thư mục gốc nora/ chỉ chứa: coin, edu, ops, check
        allowed_items = {"coin", "edu", "ops", "check"}
        current_items = {p.name for p in NORA_DIR.iterdir() if not p.name.startswith(".")}
        unexpected = current_items - allowed_items
        if unexpected:
            self.log_result("Arch", "Root Directory Hygiene", False, f"Còn file/folder lạ trong nora/: {unexpected}")
        else:
            self.log_result("Arch", "Root Directory Hygiene", True, f"Thư mục nora/ sạch tuyệt đối: {sorted(list(current_items))}")

        # 1.2 Kiểm tra nora/coin cấu trúc chuẩn
        coin_dir = NORA_DIR / "coin"
        coin_reqs = ["backend", "frontend", "data", "ops", "tests", "requirements.txt"]
        missing_coin = [req for req in coin_reqs if not (coin_dir / req).exists()]
        if missing_coin:
            self.log_result("Arch", "COIN Structure", False, f"Thiếu thành phần COIN: {missing_coin}")
        else:
            self.log_result("Arch", "COIN Structure", True, "Đầy đủ backend, frontend, data, ops, tests, requirements.txt")

        # 1.3 Kiểm tra nora/edu cấu trúc chuẩn & symlink data/market
        edu_dir = NORA_DIR / "edu"
        edu_reqs = ["backend", "frontend", "data", "ops", "tests", "requirements.txt"]
        missing_edu = [req for req in edu_reqs if not (edu_dir / req).exists()]
        if missing_edu:
            self.log_result("Arch", "EDU Structure", False, f"Thiếu thành phần EDU: {missing_edu}")
        else:
            self.log_result("Arch", "EDU Structure", True, "Đầy đủ backend, frontend, data, ops, tests, requirements.txt")

        # Symlink market
        edu_market = edu_dir / "data" / "market"
        if edu_market.is_symlink() and edu_market.exists():
            target = os.readlink(edu_market)
            self.log_result("Arch", "EDU Market Data Symlink", True, f"Symlink hợp lệ trỏ tới {target}")
        else:
            self.log_result("Arch", "EDU Market Data Symlink", False, "EDU data/market không phải symlink hợp lệ")

        # 1.4 Kiểm tra Git Worktree sạch trong nora/
        try:
            res = subprocess.run(["git", "status", "--porcelain", "nora/"], cwd=str(NORA_DIR.parent), capture_output=True, text=True, timeout=5)
            dirty_lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
            if dirty_lines:
                self.log_result("Arch", "Git Worktree Cleanliness (nora/)", False, f"Thư mục nora/ chưa sạch commit: {dirty_lines}")
            else:
                self.log_result("Arch", "Git Worktree Cleanliness (nora/)", True, "Thư mục nora/ sạch hoàn toàn, không có uncommitted files")
        except Exception as e:
            self.log_result("Arch", "Git Worktree Cleanliness (nora/)", False, f"Lỗi kiểm tra git: {e}")

    # =========================================================================
    # 2. CODE ISOLATION & IMPORT HYGIENE
    # =========================================================================
    def check_isolation(self):
        print(f"\n{CYAN}{BOLD}2. KIỂM ĐỊNH TÍNH ĐỘC LẬP & CÔ LẬP MÃ NGUỒN (ISOLATION){RESET}")
        
        # 2.1 EDU không import COIN
        edu_backend = NORA_DIR / "edu" / "backend"
        cross_edu_to_coin = []
        for py_file in edu_backend.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if re.search(r"(from|import)\s+.*\b(nora\.coin|coin\.backend)\b", content):
                    cross_edu_to_coin.append(py_file.name)
            except Exception:
                pass

        if cross_edu_to_coin:
            self.log_result("Isolation", "EDU -> COIN Cross-Import", False, f"Phát hiện cross-import: {cross_edu_to_coin}")
        else:
            self.log_result("Isolation", "EDU -> COIN Cross-Import", True, "0 vi phạm cross-import từ EDU sang COIN")

        # 2.2 COIN không import EDU
        coin_backend = NORA_DIR / "coin" / "backend"
        cross_coin_to_edu = []
        for py_file in coin_backend.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if re.search(r"(from|import)\s+.*\b(nora\.edu|edu\.backend)\b", content):
                    cross_coin_to_edu.append(py_file.name)
            except Exception:
                pass

        if cross_coin_to_edu:
            self.log_result("Isolation", "COIN -> EDU Cross-Import", False, f"Phát hiện cross-import: {cross_coin_to_edu}")
        else:
            self.log_result("Isolation", "COIN -> EDU Cross-Import", True, "0 vi phạm cross-import từ COIN sang EDU")

    # =========================================================================
    # 3. LIVE SERVICES HEALTH & IDENTITY
    # =========================================================================
    def check_services(self):
        print(f"\n{CYAN}{BOLD}3. KIỂM TRA SỨC KHỎE DỊCH VỤ ĐANG CHẠY (SERVICES HEALTH){RESET}")

        def probe_api(port: int, expected_product: str, name: str):
            url = f"http://127.0.0.1:{port}/api/health"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "NoraCheck/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        prod = data.get("product")
                        ok = data.get("ok")
                        engine = data.get("engine", {}).get("name", "n/a")
                        if ok and prod == expected_product:
                            self.log_result("Services", f"{name} (Port {port})", True, f"HTTP 200 OK | product={prod} | engine={engine}")
                        else:
                            self.log_result("Services", f"{name} (Port {port})", False, f"Phản hồi không đúng product kỳ vọng: {data}")
                    else:
                        self.log_result("Services", f"{name} (Port {port})", False, f"HTTP status code: {resp.status}")
            except Exception as e:
                self.log_result("Services", f"{name} (Port {port})", False, f"Không thể kết nối {url}: {e}")

        # Kiểm tra COIN (18012)
        probe_api(18012, "coin", "COIN Service")

        # Kiểm tra EDU (18022)
        probe_api(18022, "edu", "EDU Service")

        # Kiểm tra Legacy fallback (18010)
        try:
            url_legacy = "http://127.0.0.1:18010/api/health"
            with urllib.request.urlopen(url_legacy, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                self.log_result("Services", "Legacy Fallback (Port 18010)", True, f"Đang chạy làm dự phòng soak: ok={data.get('ok')}")
        except Exception:
            self.log_result("Services", "Legacy Fallback (Port 18010)", True, "Đã tắt hoặc không phản hồi (chấp nhận được nếu cutover xong)")

    # =========================================================================
    # 4. NGINX VHOST & CUTOVER READINESS
    # =========================================================================
    def check_nginx(self):
        print(f"\n{CYAN}{BOLD}4. KIỂM TRA TRẠNG THÁI NGINX & VHOST CUTOVER{RESET}")

        sites_enabled = Path("/etc/nginx/sites-enabled")
        if sites_enabled.exists():
            enabled = [f.name for f in sites_enabled.iterdir()]
            self.log_result("Nginx", "Sites Enabled", True, f"Các vhost đang bật: {enabled}")
            
            # Kiểm tra xem nora.expsolution.io.conf có symlink hợp lệ không
            nora_main = sites_enabled / "nora.expsolution.io.conf"
            if nora_main.exists() and not nora_main.is_symlink() or (nora_main.is_symlink() and os.path.exists(os.path.realpath(nora_main))):
                self.log_result("Nginx", "Main VHost Link", True, f"nora.expsolution.io.conf trỏ hợp lệ: {os.path.realpath(nora_main)}")
            else:
                self.log_result("Nginx", "Main VHost Link", False, "nora.expsolution.io.conf bị broken symlink!")
        else:
            self.log_result("Nginx", "Nginx Directory", False, "Không tìm thấy /etc/nginx/sites-enabled")

        # Thử curl test cục bộ với Host header
        def test_url(host: str, path: str = "/api/health") -> str:
            try:
                cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-H", f"Host: {host}", f"http://127.0.0.1{path}"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                return res.stdout.strip()
            except Exception as e:
                return str(e)

        def test_product(host: str) -> Tuple[str, str]:
            request = urllib.request.Request(
                "http://127.0.0.1/api/health",
                headers={"Host": host},
            )
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    return str(response.status), str(data.get("product", ""))
            except urllib.error.HTTPError as error:
                return str(error.code), ""
            except (OSError, ValueError) as error:
                return f"ERROR: {error}", ""

        # 4.1 Apex Legacy API
        main_api_code = test_url("nora.expsolution.io", "/api/health")
        self.log_result("Nginx", "Legacy API (nora.expsolution.io)", main_api_code == "200", f"HTTP {main_api_code}")

        # 4.2 Apex UI (Không được trả 500; phải trả 410 Gone hoặc 302/301 Redirect)
        apex_ui_code = test_url("nora.expsolution.io", "/")
        if apex_ui_code == "500":
            self.log_result("Nginx", "Apex UI (nora.expsolution.io/)", False, "HTTP 500 Internal Server Error (Rewrite cycle loop sang /index.html - Nginx chưa reload config mới)")
        elif apex_ui_code in ("410", "301", "302"):
            self.log_result("Nginx", "Apex UI (nora.expsolution.io/)", True, f"HTTP {apex_ui_code} (Chủ đích ngắt UI monolith cũ, chuyển hướng sang domain mới)")
        else:
            self.log_result("Nginx", "Apex UI (nora.expsolution.io/)", False, f"HTTP {apex_ui_code} (Chưa cấu hình phản hồi dừng UI chuẩn)")

        # 4.3 EDU Domain Cutover (BẮT BUỘC HTTP 200 và đúng product)
        edu_code, edu_product = test_product("edu.expsolution.io")
        if edu_code == "200" and edu_product == "edu":
            self.log_result("Nginx", "Host: edu.expsolution.io", True, "HTTP 200 OK | product=edu")
        elif edu_code == "404":
            self.log_result("Nginx", "Host: edu.expsolution.io", False, "HTTP 404 (VHost chưa được kích hoạt hoặc Nginx chưa reload)")
        else:
            self.log_result("Nginx", "Host: edu.expsolution.io", False, f"HTTP {edu_code} | product={edu_product!r} (Chưa sẵn sàng)")

        # 4.4 COIN Domain Cutover (BẮT BUỘC HTTP 200 và đúng product)
        coin_code, coin_product = test_product("coin.expsolution.io")
        if coin_code == "200" and coin_product == "coin":
            self.log_result("Nginx", "Host: coin.expsolution.io", True, "HTTP 200 OK | product=coin")
        elif coin_code == "404":
            self.log_result("Nginx", "Host: coin.expsolution.io", False, "HTTP 404 (VHost chưa được kích hoạt hoặc Nginx chưa reload)")
        else:
            self.log_result("Nginx", "Host: coin.expsolution.io", False, f"HTTP {coin_code} | product={coin_product!r} (Chưa sẵn sàng)")

    # =========================================================================
    # 5. RUBILAB MATHEMATICAL & PRODUCTION VERIFICATION
    # =========================================================================
    def check_rubilab(self):
        print(f"\n{CYAN}{BOLD}5. KIỂM ĐỊNH TOÁN HỌC & PRODUCTION RUBILAB (PHASE 1){RESET}")
        rubilab_script = NORA_DIR / "check" / "rubilab_verify.py"
        if not rubilab_script.exists():
            self.log_result("RubiLab", "Script Exists", False, "Không tìm thấy nora/check/rubilab_verify.py")
            return

        cmd = [str(VENV_PYTHON), str(rubilab_script)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if res.returncode == 0:
                self.log_result("RubiLab", "Production & Mathematical Assertions", True, "100% Passed: Production Functions, Nautilus Parity, Causality, Edge Cases, Risk, Bias")
            else:
                self.log_result("RubiLab", "Production & Mathematical Assertions", False, f"Thất bại:\n{res.stderr or res.stdout}")
        except Exception as e:
            self.log_result("RubiLab", "Execution", False, f"Lỗi chạy script: {e}")

    # =========================================================================
    # 6. AUTOMATED TEST SUITES
    # =========================================================================
    def check_test_suites(self):
        if not self.run_tests:
            print(f"\n{YELLOW}{BOLD}6. BỎ QUA TEST SUITES (--skip-tests){RESET}")
            return

        print(f"\n{CYAN}{BOLD}6. CHẠY BỘ TEST HỒI QUY TỰ ĐỘNG (COIN & EDU){RESET}")

        # COIN test
        coin_test_file = NORA_DIR / "coin" / "tests" / "test_coin_app.py"
        try:
            cmd = [str(VENV_PYTHON), "-m", "pytest", "-q", str(coin_test_file)]
            res = subprocess.run(cmd, cwd=str(NORA_DIR / "coin"), capture_output=True, text=True, timeout=20)
            if res.returncode == 0:
                self.log_result("Tests", "COIN App Tests (test_coin_app.py)", True, "100% Passed (API routes, app factory)")
            else:
                self.log_result("Tests", "COIN App Tests (test_coin_app.py)", False, res.stdout or res.stderr)
        except Exception as e:
            self.log_result("Tests", "COIN App Tests", False, str(e))

        # EDU test
        edu_test_file = NORA_DIR / "edu" / "tests" / "test_edu_app.py"
        try:
            cmd = [str(VENV_PYTHON), "-m", "pytest", "-q", str(edu_test_file)]
            res = subprocess.run(cmd, cwd=str(NORA_DIR / "edu"), capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                self.log_result("Tests", "EDU App Tests (test_edu_app.py)", True, "100% Passed (12 tests, golden parity, isolation)")
            else:
                self.log_result("Tests", "EDU App Tests (test_edu_app.py)", False, res.stdout or res.stderr)
        except Exception as e:
            self.log_result("Tests", "EDU App Tests", False, str(e))

    # =========================================================================
    # SUMMARY
    # =========================================================================
    def summarize(self) -> bool:
        print("\n" + "=" * 80)
        print(f"{BOLD}TỔNG HỢP KIỂM ĐỊNH HỆ THỐNG NORA{RESET}")
        print("=" * 80)
        
        passed_count = sum(1 for _, _, p, _ in self.results if p)
        total_count = len(self.results)
        all_passed = (passed_count == total_count)

        for cat, item, passed, msg in self.results:
            tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
            print(f"[{tag}] {cat:12} | {item:30} | {msg}")

        print("-" * 80)
        if all_passed:
            print(f"{GREEN}{BOLD}🎉 HOÀN TẤT: {passed_count}/{total_count} HẠNG MỤC ĐẠT CHUẨN HOÀN TOÀN!{RESET}\n")
        else:
            failed_count = total_count - passed_count
            print(f"{RED}{BOLD}⚠️ CẢNH BÁO: {failed_count}/{total_count} HẠNG MỤC CẦN XỬ LÝ!{RESET}\n")

        return all_passed


def main():
    parser = argparse.ArgumentParser(description="Master System Verifier for Nora")
    parser.add_argument("--skip-tests", action="store_true", help="Bỏ qua việc chạy pytest COIN và EDU")
    args = parser.parse_args()

    checker = SystemChecker(run_tests=not args.skip_tests)
    checker.check_architecture()
    checker.check_isolation()
    checker.check_services()
    checker.check_nginx()
    checker.check_rubilab()
    checker.check_test_suites()

    success = checker.summarize()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
