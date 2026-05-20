import re
import csv
import os
from dataclasses import dataclass, field


@dataclass
class CellContext:
    table_id: str
    row_id: int
    col_id: int
    cell_value: str
    row_values: list[str]
    col_values: list[str]
    col_header: str
    table_sample: list[list[str]]
    # {(row_id, col_id): qid} — populated during collective inference
    confirmed_annotations: dict = field(default_factory=dict)


def normalize_cell(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^\(|\)$", "", value)
    return value


def load_table(table_id: str, tables_dir: str) -> list[list[str]]:
    path = os.path.join(tables_dir, f"{table_id}.csv")
    with open(path, encoding="utf-8") as f:
        return list(csv.reader(f))


def get_cell_context(rows: list[list[str]], row_id: int, col_id: int, table_id: str) -> CellContext:
    # rows[0] is header, rows[1..] are data; row_id is 1-based data index
    header = rows[0] if rows else []
    data_rows = rows[1:]

    data_row = data_rows[row_id - 1] if 0 < row_id <= len(data_rows) else []
    cell_value = data_row[col_id] if col_id < len(data_row) else ""
    cell_value = normalize_cell(cell_value)

    row_values = [normalize_cell(v) for v in data_row]

    col_values = []
    for dr in data_rows[:20]:  # cap at 20 for context window
        if col_id < len(dr):
            v = normalize_cell(dr[col_id])
            if v and v != cell_value:
                col_values.append(v)
    col_values = col_values[:10]

    col_header = header[col_id] if col_id < len(header) else f"col{col_id}"

    table_sample = rows[:6]

    return CellContext(
        table_id=table_id,
        row_id=row_id,
        col_id=col_id,
        cell_value=cell_value,
        row_values=row_values,
        col_values=col_values,
        col_header=col_header,
        table_sample=table_sample,
    )


def is_numeric_column(col_values: list[str]) -> bool:
    if not col_values:
        return False
    numeric = sum(1 for v in col_values if re.match(r"^-?\d+(\.\d+)?$", v.replace(",", "")))
    return numeric / len(col_values) > 0.8


def is_date_column(col_values: list[str]) -> bool:
    date_pattern = re.compile(r"\b(19|20)\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
    if not col_values:
        return False
    matches = sum(1 for v in col_values if date_pattern.search(v))
    return matches / len(col_values) > 0.8
