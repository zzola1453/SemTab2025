"""
Run CEA baseline on a sample of tables and write submission CSV.

Usage:
    python scripts/run_baseline.py [--tables N] [--no-debate] [--exp-name NAME]

Examples:
    # Quick test (5 tables, no debate):
    python scripts/run_baseline.py --tables 5 --no-debate

    # Full ES run with cross-encoder reranking:
    python scripts/run_baseline.py --backend elasticsearch --tables 826 --no-debate --rerank

    # Named experiment:
    python scripts/run_baseline.py --backend elasticsearch --tables 826 --no-debate --exp-name bm25_full
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.cea.pipeline import CeaPipeline

EXPERIMENTS_LOG = "output/experiments.csv"


def build_exp_name(args, use_debate: bool) -> str:
    parts = [args.backend.replace("_", "")]
    if getattr(args, "agent", False):
        parts.append("agent")
    elif use_debate:
        parts.append("debate")
    elif args.rerank and args.dense_rerank:
        parts.append("ensemble")
    elif args.dense_rerank:
        parts.append("dense")
    elif args.rerank:
        parts.append("rerank")
    else:
        parts.append("bm25")
    if args.verification:
        parts.append("verify")
    if args.collective:
        parts.append("collective")
    parts.append(f"{args.tables}t")
    parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
    return "_".join(parts)


def save_metadata(exp_name: str, config: dict, stats: dict, output_csv: str) -> None:
    meta = {
        "exp_name": exp_name,
        "timestamp": datetime.now().isoformat(),
        "config": config,
        "stats": stats,
        "output_csv": output_csv,
    }
    meta_path = output_csv.replace(".csv", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {meta_path}")


def append_experiment_log(exp_name: str, config: dict, stats: dict, output_csv: str) -> None:
    os.makedirs(os.path.dirname(EXPERIMENTS_LOG), exist_ok=True)
    write_header = not os.path.exists(EXPERIMENTS_LOG)
    with open(EXPERIMENTS_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "exp_name", "timestamp", "backend", "tables", "debate", "rerank",
                "dense_rerank", "verification", "collective", "total", "submitted",
                "skipped", "submission_rate", "official_f1", "output_csv",
            ])
        writer.writerow([
            exp_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            config["backend"],
            config["tables"],
            config["debate"],
            config["rerank"],
            config["dense_rerank"],
            config["verification"],
            config["collective"],
            stats["total"],
            stats["submitted"],
            stats["skipped"],
            f"{stats['submitted'] / stats['total'] * 100:.1f}%",
            "",  # official_f1 — fill in manually after submission
            output_csv,
        ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", type=int, default=10, help="Number of tables to process")
    parser.add_argument("--no-debate", action="store_true", help="Skip LLM debate (top-1 retrieval only)")
    parser.add_argument("--verification", action="store_true", help="Enable LLM verification step")
    parser.add_argument("--query-rewriting", action="store_true", help="Enable LLM query rewriting fallback")
    parser.add_argument("--collective", action="store_true", help="Enable collective inference")
    parser.add_argument("--rerank", action="store_true", help="Enable local cross-encoder reranking (no API key needed)")
    parser.add_argument("--reranker-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2", help="Cross-encoder model name")
    parser.add_argument("--dense-rerank", action="store_true", help="Enable bi-encoder dense reranking (E5/BGE)")
    parser.add_argument("--dense-model", default="intfloat/e5-large-v2", help="Bi-encoder model name")
    parser.add_argument("--bm25-weight", type=float, default=0.3, help="BM25 score weight in dense hybrid (0-1)")
    parser.add_argument("--ensemble-weight", type=float, default=0.6, help="Cross-encoder weight when using ensemble (0-1)")
    parser.add_argument("--nil-threshold", type=float, default=None, help="Score threshold below which top-1 is treated as NIL")
    parser.add_argument("--backend", default="wikidata_api", choices=["wikidata_api", "elasticsearch", "hybrid"])
    parser.add_argument("--llm-backend", default="ollama", choices=["ollama", "groq", "anthropic"], help="LLM 백엔드 선택")
    parser.add_argument("--llm-model", default="qwen2.5:14b", help="LLM 모델명")
    parser.add_argument("--agent", action="store_true", help="Enable ReAct Agentic mode (tool calling)")
    parser.add_argument("--agent-model", default="llama3.1:8b", help="Model for the ReAct agent")
    parser.add_argument("--agent-max-steps", type=int, default=5, help="Max tool-calling steps per cell")
    parser.add_argument("--exp-name", default=None, help="Experiment name (auto-generated if omitted)")
    parser.add_argument("--output", default=None, help="Output CSV path (auto-generated from exp-name if omitted)")
    args = parser.parse_args()

    tables_dir = os.environ.get("TABLES_DIR", ".data/mammotab_semtab_2025/tables")
    target_file = os.environ.get("TARGET_FILE", ".data/mammotab_semtab_2025/target_mammotab_2025.csv")

    if not os.path.exists(tables_dir):
        print(f"ERROR: Tables directory not found: {tables_dir}")
        sys.exit(1)
    if not os.path.exists(target_file):
        print(f"ERROR: Target file not found: {target_file}")
        sys.exit(1)

    use_debate = not args.no_debate

    exp_name = args.exp_name or build_exp_name(args, use_debate)
    output_file = args.output or f"output/experiments/{exp_name}.csv"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    config = {
        "backend": args.backend,
        "tables": args.tables,
        "debate": use_debate,
        "rerank": args.rerank,
        "reranker_model": args.reranker_model if args.rerank else None,
        "dense_rerank": args.dense_rerank,
        "dense_model": args.dense_model if args.dense_rerank else None,
        "bm25_weight": args.bm25_weight if args.dense_rerank else None,
        "ensemble_weight": args.ensemble_weight if (args.rerank and args.dense_rerank) else None,
        "nil_threshold": args.nil_threshold,
        "verification": args.verification,
        "query_rewriting": args.query_rewriting,
        "collective": args.collective,
        "llm_backend": args.llm_backend,
        "llm_model": args.llm_model,
        "agent": args.agent,
        "agent_model": args.agent_model if args.agent else None,
        "agent_max_steps": args.agent_max_steps if args.agent else None,
    }

    print(f"Experiment: {exp_name}")
    print(f"Config: {config}")

    pipeline = CeaPipeline(
        tables_dir=tables_dir,
        retrieval_backend=args.backend,
        max_candidates=10,
        use_debate=use_debate,
        use_verification=args.verification,
        use_query_rewriting=args.query_rewriting,
        use_collective=args.collective,
        use_reranker=args.rerank,
        reranker_model=args.reranker_model,
        use_dense_reranker=args.dense_rerank,
        dense_model=args.dense_model,
        bm25_weight=args.bm25_weight,
        ensemble_weight=args.ensemble_weight,
        nil_threshold=args.nil_threshold,
        llm_backend=args.llm_backend,
        llm_model=args.llm_model,
        use_agent=args.agent,
        agent_model=args.agent_model,
        agent_max_steps=args.agent_max_steps,
    )

    start = time.time()
    results = pipeline.run_on_target_file(
        target_file=target_file,
        output_file=output_file,
        max_tables=args.tables,
    )
    elapsed = time.time() - start

    total = len(results)
    submitted = sum(1 for r in results if not r.skipped and r.entity_id != "NIL")
    skipped = total - submitted

    stats = {
        "total": total,
        "submitted": submitted,
        "skipped": skipped,
        "elapsed_sec": round(elapsed, 1),
    }

    print(f"\nSummary: total={total}, submitted={submitted}, skipped/NIL={skipped}")
    print(f"Submission rate: {submitted/total*100:.1f}%  |  Elapsed: {elapsed:.0f}s")
    print(f"Output: {output_file}")

    save_metadata(exp_name, config, stats, output_file)
    append_experiment_log(exp_name, config, stats, output_file)
    print(f"Logged to: {EXPERIMENTS_LOG}")


if __name__ == "__main__":
    main()
