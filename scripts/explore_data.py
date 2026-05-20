"""
Data exploration: understand table structure, target distribution,
and estimate which column types are entity columns.
"""
import csv
import os
import sys
import collections
import re

TABLES_DIR = os.environ.get("TABLES_DIR", ".data/mammotab_semtab_2025/tables")
TARGET_FILE = os.environ.get("TARGET_FILE", ".data/mammotab_semtab_2025/target_mammotab_2025.csv")


def load_targets() -> dict[str, list[tuple[int, int]]]:
    targets: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    with open(TARGET_FILE) as f:
        for row in csv.reader(f):
            if len(row) >= 3:
                targets[row[0]].append((int(row[1]), int(row[2])))
    return targets


def col_id_distribution(targets):
    col_counter = collections.Counter()
    for tgts in targets.values():
        for _, col_id in tgts:
            col_counter[col_id] += 1
    return col_counter


def sample_cell_values(targets, n_tables=10):
    items = list(targets.items())[:n_tables]
    samples = []
    for table_id, tgts in items:
        path = os.path.join(TABLES_DIR, f"{table_id}.csv")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            rows = list(csv.reader(f))
        for row_id, col_id in tgts[:3]:
            data_row = rows[row_id] if row_id < len(rows) else []
            value = data_row[col_id] if col_id < len(data_row) else ""
            samples.append({
                "table": table_id,
                "row": row_id,
                "col": col_id,
                "value": value,
                "row_context": " | ".join(data_row),
            })
    return samples


def count_numeric_cells(targets, n_tables=50) -> dict:
    numeric_pattern = re.compile(r"^-?\d+[\d,\.]*$")
    numeric, text = 0, 0
    items = list(targets.items())[:n_tables]
    for table_id, tgts in items:
        path = os.path.join(TABLES_DIR, f"{table_id}.csv")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            rows = list(csv.reader(f))
        for row_id, col_id in tgts:
            data_row = rows[row_id] if row_id < len(rows) else []
            value = (data_row[col_id] if col_id < len(data_row) else "").strip()
            if numeric_pattern.match(value.replace(",", "")):
                numeric += 1
            else:
                text += 1
    return {"numeric": numeric, "text": text, "pct_numeric": round(numeric / (numeric + text + 1e-9) * 100, 1)}


def main():
    targets = load_targets()
    total_cells = sum(len(v) for v in targets.values())

    print("=" * 60)
    print("MAMMOTAB CEA DATASET OVERVIEW")
    print("=" * 60)
    print(f"Total tables (with targets): {len(targets)}")
    print(f"Total target cells:          {total_cells}")
    targets_per_table = [len(v) for v in targets.values()]
    print(f"Targets per table — min: {min(targets_per_table)}, max: {max(targets_per_table)}, avg: {sum(targets_per_table)/len(targets_per_table):.1f}")

    print("\n--- Column ID Distribution (top 10) ---")
    col_dist = col_id_distribution(targets)
    for col_id, count in sorted(col_dist.items(), key=lambda x: -x[1])[:10]:
        pct = count / total_cells * 100
        print(f"  col{col_id}: {count:6d} cells ({pct:.1f}%)")

    print("\n--- Numeric vs Text cell types (sample 50 tables) ---")
    num_info = count_numeric_cells(targets, n_tables=50)
    print(f"  Numeric: {num_info['numeric']:5d} ({num_info['pct_numeric']:.1f}%)")
    print(f"  Text:    {num_info['text']:5d}")

    print("\n--- Sample cell values (first 10 tables, 3 cells each) ---")
    samples = sample_cell_values(targets, n_tables=10)
    for s in samples:
        print(f"  [{s['table']} r{s['row']} c{s['col']}] \"{s['value']}\"  — row: {s['row_context'][:80]}")

    # Table size distribution
    sizes = []
    for table_id in list(targets.keys())[:100]:
        path = os.path.join(TABLES_DIR, f"{table_id}.csv")
        if os.path.exists(path):
            with open(path) as f:
                sizes.append(sum(1 for _ in f))
    if sizes:
        print(f"\n--- Table size (rows incl. header, sample 100 tables) ---")
        print(f"  min: {min(sizes)}, max: {max(sizes)}, avg: {sum(sizes)/len(sizes):.1f}")


if __name__ == "__main__":
    main()
