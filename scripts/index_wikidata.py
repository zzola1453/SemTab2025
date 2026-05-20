"""
Index Wikidata KG dump into Elasticsearch.

Supports:
  - Wikidata N-Triples dump (.nt.bz2, .nt)
  - Wikidata JSON dump (.json.gz, .json)

Resumability:
  - Phase 1 (NT→SQLite): line-count checkpoint in .indexing_cache/
  - Phase 2 (SQLite→ES): last-QID checkpoint in .indexing_cache/
  - ES bulk: exponential backoff retry on connection errors

Usage:
    # Full run (or resume from last checkpoint automatically)
    python scripts/index_wikidata.py --dump /mnt/c/Users/User/Downloads/latest-all.nt.bz2

    # Phase 1 only (NT parsing — safe to run in background with nohup)
    nohup python scripts/index_wikidata.py --dump /mnt/c/... --phase1-only > phase1.log 2>&1 &

    # Phase 2 only (SQLite→ES — after Phase 1 completes)
    python scripts/index_wikidata.py --dump /mnt/c/... --phase2-only

    # Quick test with 100K entities
    python scripts/index_wikidata.py --dump /mnt/c/... --max-entities 100000 --recreate
"""
import argparse
import bz2
import contextlib
import datetime
import gzip
import json
import itertools
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm

ES_HOST  = os.environ.get("ES_HOST",  "http://localhost:9200")
ES_INDEX = os.environ.get("ES_INDEX", "wikidata_entities")

DENSE_MODEL = "intfloat/e5-large-v2"
DENSE_DIMS  = 1024

CACHE_DIR            = Path(".indexing_cache")
SQLITE_DB_PATH       = CACHE_DIR / "wikidata_intermediate.db"
LINE_CHECKPOINT_PATH = CACHE_DIR / "phase1_lines.txt"
QID_CHECKPOINT_PATH  = CACHE_DIR / "phase2_last_qid.txt"
STATUS_FILE          = Path("logs/status.txt")

RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
SCHEMA_DESC = "http://schema.org/description"
SKOS_ALT    = "http://www.w3.org/2004/02/skos/core#altLabel"
RELEVANT_PREDS = {RDFS_LABEL, SCHEMA_DESC, SKOS_ALT}

EN_TRIPLE_RE = re.compile(
    r'^<http://www\.wikidata\.org/entity/(Q\d+)>\s+'
    r'<([^>]+)>\s+'
    r'"((?:[^"\\]|\\.)*)"\s*@en\s+\.\s*$'
)


# ── Notification & status ─────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_status(msg: str) -> None:
    STATUS_FILE.parent.mkdir(exist_ok=True)
    STATUS_FILE.write_text(f"[{_ts()}] {msg}\n")


def notify_windows(title: str, message: str) -> None:
    """Send a Windows toast notification from WSL2 via PowerShell."""
    ps = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$n = New-Object System.Windows.Forms.NotifyIcon; "
        f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
        f"$n.Visible = $true; "
        f"$n.ShowBalloonTip(10000, '{title}', '{message}', "
        f"[System.Windows.Forms.ToolTipIcon]::None); "
        f"Start-Sleep -Seconds 1"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            timeout=15,
            capture_output=True,
        )
    except Exception:
        pass  # 알림 실패해도 인덱싱은 계속


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unescape_nt(s: str) -> str:
    return (s.replace("\\\\", "\x00")
             .replace('\\"', '"')
             .replace("\\n", "\n")
             .replace("\\t", "\t")
             .replace("\x00", "\\"))


# ── Elasticsearch index setup ─────────────────────────────────────────────────

def get_index_mapping(dense: bool = False) -> dict:
    props = {
        "qid":         {"type": "keyword"},
        "label":       {"type": "text", "analyzer": "label_analyzer",
                        "fields": {"keyword": {"type": "keyword"}}},
        "description": {"type": "text", "analyzer": "label_analyzer"},
        "aliases":     {"type": "text", "analyzer": "label_analyzer"},
    }
    if dense:
        props["embedding"] = {
            "type": "dense_vector",
            "dims": DENSE_DIMS,
            "index": True,
            "similarity": "cosine",
        }
    return {
        "settings": {
            "number_of_shards": 3,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
            "analysis": {
                "analyzer": {
                    "label_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    }
                }
            },
        },
        "mappings": {"properties": props},
    }


def ensure_index(es: Elasticsearch, recreate: bool = False, dense: bool = False) -> None:
    if es.indices.exists(index=ES_INDEX):
        if recreate:
            print(f"Deleting existing index '{ES_INDEX}'...")
            es.indices.delete(index=ES_INDEX)
        else:
            count = es.count(index=ES_INDEX)["count"]
            print(f"Index '{ES_INDEX}' already exists with {count:,} docs.")
            return
    print(f"Creating index '{ES_INDEX}' (dense={dense})...")
    es.indices.create(index=ES_INDEX, body=get_index_mapping(dense=dense))
    print("Index created.")


# ── SQLite intermediate storage ───────────────────────────────────────────────

def open_sqlite() -> sqlite3.Connection:
    CACHE_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-131072")  # 128 MB page cache
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            qid TEXT PRIMARY KEY,
            label TEXT DEFAULT '',
            description TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            qid   TEXT NOT NULL,
            alias TEXT NOT NULL,
            PRIMARY KEY (qid, alias)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aliases_qid ON aliases(qid)")
    return conn


def save_line_checkpoint(n: int) -> None:
    LINE_CHECKPOINT_PATH.write_text(str(n))


def load_line_checkpoint() -> int:
    try:
        return int(LINE_CHECKPOINT_PATH.read_text().strip())
    except Exception:
        return 0


def save_qid_checkpoint(qid: str) -> None:
    QID_CHECKPOINT_PATH.write_text(qid)


def load_qid_checkpoint() -> str:
    try:
        return QID_CHECKPOINT_PATH.read_text().strip()
    except Exception:
        return ""


# ── Phase 1: NT → SQLite ─────────────────────────────────────────────────────

def phase1_nt_to_sqlite(dump_path: str, max_entities: int | None = None) -> None:
    """Parse N-Triples dump and persist to SQLite. Fully resumable via line checkpoint."""

    resume_at = load_line_checkpoint()
    conn = open_sqlite()

    if resume_at > 0:
        n_existing = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        print(f"Phase 1 — Resuming from line {resume_at:,}  ({n_existing:,} entities already in SQLite)")
    else:
        print("Phase 1 — Parsing N-Triples → SQLite (fresh start)")

    SQLITE_BATCH    = 5_000
    CHECKPOINT_EVERY = 500_000  # save line checkpoint every 500K lines

    label_batch = []       # (qid, label)
    desc_batch  = []       # (qid, desc)
    alias_batch = []       # (qid, alias)

    def flush(force: bool = False) -> None:
        total = len(label_batch) + len(desc_batch) + len(alias_batch)
        if not force and total < SQLITE_BATCH:
            return
        with conn:
            if label_batch:
                conn.executemany(
                    "INSERT INTO entities(qid,label) VALUES(?,?) "
                    "ON CONFLICT(qid) DO UPDATE SET label=excluded.label",
                    label_batch,
                )
                label_batch.clear()
            if desc_batch:
                conn.executemany(
                    "INSERT INTO entities(qid,description) VALUES(?,?) "
                    "ON CONFLICT(qid) DO UPDATE SET description=excluded.description",
                    desc_batch,
                )
                desc_batch.clear()
            if alias_batch:
                conn.executemany(
                    "INSERT OR IGNORE INTO aliases(qid,alias) VALUES(?,?)",
                    alias_batch,
                )
                alias_batch.clear()

    line_count = 0

    # bzcat handles multi-stream bz2 (Python's bz2.open stops at first stream boundary)
    if dump_path.endswith(".bz2"):
        proc = subprocess.Popen(
            ["bzcat", dump_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1 << 20,
        )
        raw_stream = proc.stdout
    elif dump_path.endswith(".gz"):
        import gzip as _gzip
        proc = None
        raw_stream = _gzip.open(dump_path, "rb")
    else:
        proc = None
        raw_stream = open(dump_path, "rb")

    # Fast-forward: count newlines in 4MB binary chunks (avoids decode overhead)
    if resume_at > 0:
        print(f"Fast-forward: skipping {resume_at:,} lines (binary chunk scan)...")
        CHUNK = 4 * 1024 * 1024
        with tqdm(desc="Fast-forward", unit=" lines", unit_scale=True, total=resume_at) as ff_pbar:
            while line_count < resume_at:
                chunk = raw_stream.read(CHUNK)
                if not chunk:
                    break
                n = chunk.count(b"\n")
                line_count += n
                ff_pbar.update(n)
        print(f"Fast-forward done at line ~{line_count:,}")

    with tqdm(desc="Parsing NT", unit=" lines", unit_scale=True, mininterval=10) as pbar:
        for raw_bytes in raw_stream:
            line_count += 1
            line = raw_bytes.decode("utf-8", errors="replace")

            pbar.update(1)

            # Fast pre-filter (avoids regex on >95% of lines)
            if '"@en ' not in line and '"@en\t' not in line and '"@en.' not in line:
                continue
            if "/entity/Q" not in line:
                continue

            m = EN_TRIPLE_RE.match(line.rstrip("\n\r"))
            if not m:
                continue

            qid, pred, raw = m.group(1), m.group(2), m.group(3)
            if pred not in RELEVANT_PREDS:
                continue

            value = _unescape_nt(raw)

            if pred == RDFS_LABEL:
                label_batch.append((qid, value))
            elif pred == SCHEMA_DESC:
                desc_batch.append((qid, value))
            elif pred == SKOS_ALT:
                alias_batch.append((qid, value))

            flush()

            if line_count % CHECKPOINT_EVERY == 0:
                flush(force=True)
                save_line_checkpoint(line_count)
                n = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
                pbar.set_postfix(entities=f"{n:,}", checkpoint=f"L{line_count//1_000_000}M")
                write_status(f"Phase 1 진행중 — {line_count//1_000_000}M 라인 처리, 엔티티 {n:,}개 저장")

            if max_entities:
                n = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
                if n >= max_entities:
                    print(f"\nEarly stop: {n:,} entities reached max_entities={max_entities}")
                    break

    flush(force=True)
    save_line_checkpoint(line_count)

    n_entities = conn.execute("SELECT COUNT(*) FROM entities WHERE label != ''").fetchone()[0]
    n_aliases  = conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
    conn.close()

    print(f"Phase 1 done — {n_entities:,} entities with English label, {n_aliases:,} aliases")
    print(f"SQLite DB: {SQLITE_DB_PATH}  ({SQLITE_DB_PATH.stat().st_size / 1e9:.1f} GB)")
    write_status(f"Phase 1 완료 — 엔티티 {n_entities:,}개, 별칭 {n_aliases:,}개 SQLite 저장 완료")


# ── Phase 2: SQLite → ES ─────────────────────────────────────────────────────

def _bulk_with_retry(es: Elasticsearch, batch: list, max_retries: int = 8) -> tuple[int, int]:
    """Bulk index with exponential backoff. Returns (ok, errors)."""
    for attempt in range(max_retries):
        try:
            ok, errs = helpers.bulk(es, batch, raise_on_error=False, stats_only=True)
            return ok, errs
        except Exception as exc:
            if attempt == max_retries - 1:
                print(f"\nFATAL: ES bulk failed after {max_retries} retries: {exc}")
                raise
            wait = min(2 ** attempt, 60)
            print(f"\nES error (attempt {attempt+1}/{max_retries}): {exc}. Retry in {wait}s...")
            time.sleep(wait)
            try:
                es = Elasticsearch(hosts=[ES_HOST], request_timeout=60)
            except Exception:
                pass
    return 0, 0


def phase2_sqlite_to_es(
    es: Elasticsearch,
    batch_size: int = 2000,
    encoder=None,
) -> None:
    """Stream entities from SQLite → Elasticsearch with QID-based checkpointing."""

    resume_qid = load_qid_checkpoint()
    conn = open_sqlite()

    total     = conn.execute("SELECT COUNT(*) FROM entities WHERE label != ''").fetchone()[0]
    remaining = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE label != '' AND qid > ?", (resume_qid,)
    ).fetchone()[0] if resume_qid else total

    print(f"Phase 2 — SQLite → Elasticsearch")
    print(f"  Total entities with label : {total:,}")
    print(f"  To index (after checkpoint): {remaining:,}")
    if resume_qid:
        print(f"  Resuming after QID: {resume_qid}")

    query = """
        SELECT e.qid, e.label, e.description,
               GROUP_CONCAT(a.alias, '|||') AS aliases
        FROM entities e
        LEFT JOIN aliases a ON e.qid = a.qid
        WHERE e.label != ''
          AND e.qid > ?
        GROUP BY e.qid
        ORDER BY e.qid
    """

    indexed, errors = 0, 0
    batch: list = []
    last_qid = resume_qid

    with tqdm(desc="Indexing to ES", unit=" entities", total=remaining) as pbar:
        for row in conn.execute(query, (resume_qid,)):
            qid, label, description, aliases_raw = row
            aliases = aliases_raw.split("|||") if aliases_raw else []

            source: dict = {
                "qid": qid,
                "label": label,
                "description": description or "",
                "aliases": aliases,
            }

            if encoder is not None:
                passage = f"passage: {label}" if "e5" in DENSE_MODEL.lower() else label
                source["embedding"] = encoder.encode(passage, normalize_embeddings=True).tolist()

            batch.append({"_index": ES_INDEX, "_id": qid, "_source": source})
            last_qid = qid

            if len(batch) >= batch_size:
                ok, errs = _bulk_with_retry(es, batch)
                indexed += ok
                errors  += errs
                pbar.update(ok)
                batch.clear()
                save_qid_checkpoint(last_qid)

        if batch:
            ok, errs = _bulk_with_retry(es, batch)
            indexed += ok
            errors  += errs
            pbar.update(ok)
            save_qid_checkpoint(last_qid)

    conn.close()
    print(f"\nPhase 2 done — Indexed: {indexed:,} | Errors: {errors:,}")
    write_status(f"Phase 2 완료 — ES 인덱싱 {indexed:,}개, 오류 {errors:,}개")


# ── JSON path (streaming, no SQLite needed) ───────────────────────────────────

def iter_entities_json(dump_path: str, encoder=None) -> Iterator[dict]:
    open_fn = gzip.open if dump_path.endswith(".gz") else open
    with open_fn(dump_path, "rt", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                entity = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entity.get("type") != "item":
                continue
            qid = entity.get("id", "")
            if not qid.startswith("Q"):
                continue
            label = entity.get("labels", {}).get("en", {}).get("value", "")
            if not label:
                continue
            description = entity.get("descriptions", {}).get("en", {}).get("value", "")
            alias_list  = entity.get("aliases", {}).get("en", [])
            aliases     = [a["value"] for a in alias_list if isinstance(a, dict)]
            source: dict = {"qid": qid, "label": label, "description": description, "aliases": aliases}
            if encoder is not None:
                passage = f"passage: {label}" if "e5" in DENSE_MODEL.lower() else label
                source["embedding"] = encoder.encode(passage, normalize_embeddings=True).tolist()
            yield {"_index": ES_INDEX, "_id": qid, "_source": source}


def run_indexing_json(
    es: Elasticsearch,
    dump_path: str,
    batch_size: int = 2000,
    max_entities: int | None = None,
    encoder=None,
) -> None:
    resume_qid = load_qid_checkpoint()
    skipping   = bool(resume_qid)
    if skipping:
        print(f"Resuming JSON indexing after QID '{resume_qid}'")

    indexed, errors = 0, 0
    batch: list = []
    last_qid = resume_qid

    gen = iter_entities_json(dump_path, encoder=encoder)
    if max_entities:
        gen = itertools.islice(gen, max_entities)

    with tqdm(desc="Indexing (JSON)", unit=" entities") as pbar:
        for doc in gen:
            qid = doc["_source"]["qid"]
            if skipping:
                if qid == resume_qid:
                    skipping = False
                continue

            batch.append(doc)
            last_qid = qid

            if len(batch) >= batch_size:
                ok, errs = _bulk_with_retry(es, batch)
                indexed += ok
                errors  += errs
                pbar.update(ok)
                batch.clear()
                save_qid_checkpoint(last_qid)

        if batch:
            ok, errs = _bulk_with_retry(es, batch)
            indexed += ok
            errors  += errs
            pbar.update(ok)
            save_qid_checkpoint(last_qid)

    print(f"\nDone — Indexed: {indexed:,} | Errors: {errors:,}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Index Wikidata KG dump into Elasticsearch")
    parser.add_argument("--dump",          required=True, help="Dump path (.nt.bz2 / .json.gz / etc.)")
    parser.add_argument("--batch-size",    type=int, default=2000, help="ES bulk batch size")
    parser.add_argument("--max-entities",  type=int, default=None, help="Stop after N entities (testing)")
    parser.add_argument("--recreate",      action="store_true", help="Drop and recreate the ES index")
    parser.add_argument("--dense",         action="store_true", help=f"Encode with {DENSE_MODEL}")
    parser.add_argument("--phase1-only",   action="store_true", help="NT→SQLite only (no ES)")
    parser.add_argument("--phase2-only",   action="store_true", help="SQLite→ES only (skip NT parsing)")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Clear checkpoints and start fresh")
    args = parser.parse_args()

    if not os.path.exists(args.dump):
        print(f"ERROR: Dump file not found: {args.dump}")
        sys.exit(1)

    if args.reset_checkpoint:
        for p in (LINE_CHECKPOINT_PATH, QID_CHECKPOINT_PATH):
            if p.exists():
                p.unlink()
                print(f"Cleared {p}")

    is_nt = args.dump.endswith(".nt") or args.dump.endswith(".nt.bz2")

    encoder = None
    if args.dense:
        from sentence_transformers import SentenceTransformer
        print(f"Loading dense encoder: {DENSE_MODEL} ...")
        encoder = SentenceTransformer(DENSE_MODEL)

    start = time.time()
    write_status("인덱싱 시작")

    try:
        if is_nt:
            if not args.phase2_only:
                phase1_nt_to_sqlite(args.dump, max_entities=args.max_entities)

            if not args.phase1_only:
                es = Elasticsearch(hosts=[ES_HOST], request_timeout=60)
                if not es.ping():
                    raise RuntimeError(f"Cannot connect to Elasticsearch at {ES_HOST}")
                ensure_index(es, recreate=args.recreate, dense=args.dense)
                phase2_sqlite_to_es(es, batch_size=args.batch_size, encoder=encoder)
        else:
            es = Elasticsearch(hosts=[ES_HOST], request_timeout=60)
            if not es.ping():
                raise RuntimeError(f"Cannot connect to Elasticsearch at {ES_HOST}")
            ensure_index(es, recreate=args.recreate, dense=args.dense)
            run_indexing_json(es, args.dump, batch_size=args.batch_size,
                              max_entities=args.max_entities, encoder=encoder)

        elapsed = time.time() - start
        print(f"\nTotal time: {elapsed / 60:.1f} min")

        if not args.phase1_only:
            es = Elasticsearch(hosts=[ES_HOST], request_timeout=60)
            es.indices.refresh(index=ES_INDEX)
            count = es.count(index=ES_INDEX)["count"]
            print(f"Index '{ES_INDEX}' now has {count:,} documents.")
            for p in (LINE_CHECKPOINT_PATH, QID_CHECKPOINT_PATH):
                if p.exists():
                    p.unlink()
            msg = f"인덱싱 완료! ES 문서 {count:,}개 ({elapsed/60:.0f}분 소요)"
            print("Checkpoints cleared — indexing complete!")
        else:
            msg = f"Phase 1 완료! ({elapsed/60:.0f}분 소요) — 이제 --phase2-only 실행하세요"

        write_status(msg)
        notify_windows("Wikidata 인덱싱 완료 ✅", msg)

    except Exception as exc:
        elapsed = time.time() - start
        err_msg = f"오류 발생 ({elapsed/60:.0f}분 후): {exc}"
        print(f"\nFATAL: {err_msg}", file=sys.stderr)
        write_status(f"FAILED — {err_msg}")
        notify_windows("Wikidata 인덱싱 실패 ❌", str(exc)[:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
