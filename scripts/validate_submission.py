"""
Validate a CEA submission CSV before final submission.

Usage:
    python scripts/validate_submission.py --submission output/submission.csv
    python scripts/validate_submission.py --submission output/submission.csv \
        --target .data/mammotab_semtab_2025/target_mammotab_2025.csv
"""
import argparse
import csv
import re
import sys
from collections import defaultdict


QID_RE = re.compile(r"^Q\d+$")


def load_csv(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.reader(f))


def validate(submission_path: str, target_path: str | None) -> bool:
    rows = load_csv(submission_path)
    ok = True
    errors: list[str] = []

    # --- Format checks ---
    seen: set[tuple[str, str, str]] = set()
    valid_rows: list[tuple[str, int, int, str]] = []

    for i, row in enumerate(rows, 1):
        if len(row) != 4:
            errors.append(f"Row {i}: expected 4 columns, got {len(row)} → {row}")
            ok = False
            continue

        table_id, row_id_s, col_id_s, qid = row

        if not table_id:
            errors.append(f"Row {i}: empty table_id")
            ok = False

        try:
            row_id = int(row_id_s)
            col_id = int(col_id_s)
        except ValueError:
            errors.append(f"Row {i}: row_id/col_id must be integers, got '{row_id_s}', '{col_id_s}'")
            ok = False
            continue

        if not QID_RE.match(qid):
            errors.append(f"Row {i}: invalid QID format '{qid}' (expected Q<digits>)")
            ok = False

        key = (table_id, row_id_s, col_id_s)
        if key in seen:
            errors.append(f"Row {i}: duplicate entry ({table_id}, {row_id_s}, {col_id_s})")
            ok = False
        seen.add(key)
        valid_rows.append((table_id, row_id, col_id, qid))

    # --- Cross-check against target file ---
    coverage_pct: float | None = None
    if target_path:
        targets = load_csv(target_path)
        target_set: set[tuple[str, str, str]] = set()
        for row in targets:
            if len(row) >= 3:
                target_set.add((row[0], row[1], row[2]))

        submitted_set = {(t, str(r), str(c)) for t, r, c, _ in valid_rows}
        extra = submitted_set - target_set
        missing = target_set - submitted_set

        if extra:
            errors.append(f"{len(extra)} submitted entries not in target file (first 5: {list(extra)[:5]})")
            ok = False

        covered = len(target_set) - len(missing)
        coverage_pct = covered / len(target_set) * 100 if target_set else 0.0

    # --- Report ---
    print(f"Submission: {submission_path}")
    print(f"Total rows  : {len(rows)}")
    print(f"Valid rows  : {len(valid_rows)}")
    print(f"Format OK   : {'YES' if ok else 'NO'}")
    if coverage_pct is not None:
        print(f"Coverage    : {coverage_pct:.1f}% of target cells")

    by_table: dict[str, int] = defaultdict(int)
    for t, _, _, _ in valid_rows:
        by_table[t] += 1
    print(f"Tables      : {len(by_table)}")
    print(f"Avg per table: {len(valid_rows)/len(by_table):.1f}" if by_table else "")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors)-20} more")

    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--target", default=None, help="Target CSV to check coverage")
    args = parser.parse_args()

    ok = validate(args.submission, args.target)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
