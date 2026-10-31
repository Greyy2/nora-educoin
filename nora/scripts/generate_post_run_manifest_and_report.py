#!/usr/bin/env python3
"""Script tái dựng manifest hậu kiểm (post_run_reconstruction) và cập nhật báo cáo kỹ thuật.

Alias chuẩn tên cho `generate_authoritative_manifest_and_report.py` nhằm phản ánh đúng
bản chất kỹ thuật là tái dựng hậu kiểm (post-run reconstruction), tránh gây hiểu nhầm
với runtime snapshot bất biến.
"""
import sys
from pathlib import Path
REPO_ROOT = Path("/home/vmc03/norabt")
sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_authoritative_manifest_and_report import main

if __name__ == "__main__":
    main()
