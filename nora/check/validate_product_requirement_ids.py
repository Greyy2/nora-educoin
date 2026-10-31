#!/usr/bin/env python3
"""Validate requirement IDs and inventory ranges across the product plan documents."""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


ID_PATTERN = r"(?:EDU|CROSS|COIN-(?:HOME|ALPHA|PROMPT|BT|LIVE))-\d{2}"
INVENTORY_ROW = re.compile(r"^### (?P<id>" + ID_PATTERN + r") —", re.MULTILINE)
MATRIX_ROW = re.compile(r"^\| (?P<id>" + ID_PATTERN + r") \|", re.MULTILINE)
TOC_RANGE = re.compile(
    r"\((?P<start>" + ID_PATTERN + r")\s*[–-]\s*(?P<end>" + ID_PATTERN + r")\)"
)
EXPECTED_RANGES = {
    "EDU": (1, 16),
    "COIN-HOME": (1, 6),
    "COIN-ALPHA": (1, 6),
    "COIN-PROMPT": (1, 9),
    "COIN-BT": (1, 6),
    "COIN-LIVE": (0, 13),
    "CROSS": (1, 6),
}


def expected_ids(
    ranges: Dict[str, Tuple[int, int]] = EXPECTED_RANGES,
) -> Set[str]:
    return {
        "{}-{:02d}".format(group, number)
        for group, (start, end) in ranges.items()
        for number in range(start, end + 1)
    }


def _extract_ids(pattern: re.Pattern, text: str) -> List[str]:
    return [match.group("id") for match in pattern.finditer(text)]


def _grouped_ids(ids: Iterable[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for requirement_id in ids:
        group, _ = requirement_id.rsplit("-", 1)
        grouped.setdefault(group, []).append(requirement_id)
    return grouped


def validate_documents(
    inventory_text: str,
    matrix_text: str,
    required_ids: Optional[Set[str]] = None,
) -> List[str]:
    required_ids = expected_ids() if required_ids is None else required_ids
    inventory_ids = _extract_ids(INVENTORY_ROW, inventory_text)
    matrix_ids = _extract_ids(MATRIX_ROW, matrix_text)
    errors: List[str] = []

    for document_name, ids in (
        ("inventory", inventory_ids),
        ("matrix", matrix_ids),
    ):
        duplicates = sorted(
            requirement_id
            for requirement_id, count in Counter(ids).items()
            if count > 1
        )
        if duplicates:
            errors.append(
                "{} has duplicate requirement IDs: {}".format(
                    document_name, ", ".join(duplicates)
                )
            )
        missing = sorted(required_ids - set(ids))
        extra = sorted(set(ids) - required_ids)
        if missing:
            errors.append(
                "{} is missing requirement IDs: {}".format(
                    document_name, ", ".join(missing)
                )
            )
        if extra:
            errors.append(
                "{} has unexpected requirement IDs: {}".format(
                    document_name, ", ".join(extra)
                )
            )

    inventory_set = set(inventory_ids)
    matrix_set = set(matrix_ids)
    if inventory_set != matrix_set:
        errors.append(
            "inventory/matrix ID sets differ: inventory-only [{}], matrix-only [{}]".format(
                ", ".join(sorted(inventory_set - matrix_set)),
                ", ".join(sorted(matrix_set - inventory_set)),
            )
        )

    inventory_groups = _grouped_ids(inventory_ids)
    toc_start = inventory_text.find("## Mục lục")
    if toc_start < 0:
        toc_start = 0
    toc_end = inventory_text.find("\n---", toc_start)
    toc = inventory_text[toc_start:toc_end] if toc_end >= 0 else inventory_text[toc_start:]
    range_claims = list(TOC_RANGE.finditer(toc))
    claimed_groups = set()
    for claim in range_claims:
        start = claim.group("start")
        end = claim.group("end")
        start_group, start_number = start.rsplit("-", 1)
        end_group, end_number = end.rsplit("-", 1)
        claimed_groups.add(start_group)
        group_ids = inventory_groups.get(start_group, [])
        if start_group != end_group or not group_ids:
            errors.append("invalid inventory TOC range: {}".format(claim.group(0)))
            continue
        actual_numbers = sorted(
            int(requirement_id.rsplit("-", 1)[1]) for requirement_id in group_ids
        )
        if int(start_number) != actual_numbers[0] or int(end_number) != actual_numbers[-1]:
            errors.append(
                "inventory TOC range for {} is {}–{} but rows span {}–{}".format(
                    start_group,
                    start_number,
                    end_number,
                    "{:02d}".format(actual_numbers[0]),
                    "{:02d}".format(actual_numbers[-1]),
                )
            )

    missing_toc_groups = sorted(set(_grouped_ids(required_ids)) - claimed_groups)
    if missing_toc_groups:
        errors.append(
            "inventory TOC is missing group ranges: {}".format(
                ", ".join(missing_toc_groups)
            )
        )
    return errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=repo_root / "nora/check/product_surface_inventory.md",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=repo_root / "nora/check/product_ux_acceptance_matrix.md",
    )
    args = parser.parse_args(argv)
    inventory_text = args.inventory.read_text(encoding="utf-8")
    matrix_text = args.matrix.read_text(encoding="utf-8")
    errors = validate_documents(inventory_text, matrix_text)
    counts = _grouped_ids(_extract_ids(INVENTORY_ROW, inventory_text))
    print(
        "Requirement IDs: {} total ({})".format(
            sum(len(ids) for ids in counts.values()),
            ", ".join(
                "{}={}".format(group, len(counts.get(group, [])))
                for group in EXPECTED_RANGES
            ),
        )
    )
    if errors:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
        return 1
    print("PASS: matrix and inventory IDs, counts, uniqueness, and TOC ranges match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
