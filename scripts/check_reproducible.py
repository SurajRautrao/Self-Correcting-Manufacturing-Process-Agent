"""Check that a fresh clone reproduces every committed result without an LLM or a GPU.

    python scripts/check_reproducible.py            # all checks (a few minutes)
    python scripts/check_reproducible.py --quick    # skip the replay of deterministic systems

Checks, each against the files committed in the repository:

1. **Benchmarks:** benchmark v1 and v2 regenerate byte for byte from their documented commands.
2. **Tables:** every experiment's summary.md/.csv/.json and violations_by_rule.csv rebuild exactly from its
   results.jsonl, and every optimization.md rebuilds from its optimization.jsonl.
3. **Deterministic systems:** for every experiment produced under the current rule set, B0, B1 and R are
   replayed from the cached initial plans (no planner calls) and must give the same rows as committed.
   LLM repair (B2) cannot be re-run without the model; its stored run records are re-validated instead:
   each final plan must get the same validity and hard-violation count from today's validator.
4. **Examples:** docs/examples.md regenerates exactly from the stored run records.

Exit code 0 if everything matches. Replayed rows must match in every field; latency, which includes the
rule-based repair time measured live, must match within 0.05 s.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scmpa.evaluation import optimize_results  # noqa: E402
from scmpa.evaluation.report import build_report  # noqa: E402
from scmpa.evaluation.run_experiments import ExperimentConfig, run_experiment  # noqa: E402
from scmpa.evaluation.synthetic import generate_benchmark  # noqa: E402
from scmpa.io import load_catalogue, load_component  # noqa: E402
from scmpa.validation import validate_plan  # noqa: E402
from scmpa.validation.rules import RULE_SET_VERSION  # noqa: E402
from scmpa.workflow import load_run  # noqa: E402

EXP = ROOT / "reports" / "experiments"
BENCHMARKS = {  # folder -> generator arguments (see DATA_CARD.md)
    "benchmark_v1": dict(n_components=24, seed=2026, infeasible_fraction=0.2, profile="v1"),
    "benchmark_v2": dict(n_components=24, seed=2027, infeasible_fraction=0.2, profile="v2"),
}
TABLES = ("summary.md", "summary.csv", "summary.json", "violations_by_rule.csv")
DETERMINISTIC = ("B0", "B1", "R")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passed = 0

    def check(self, ok: bool, what: str) -> None:
        if ok:
            self.passed += 1
        else:
            self.failures.append(what)
            print(f"  MISMATCH {what}", flush=True)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def check_benchmarks(rep: Report, tmp: Path) -> None:
    print("1. Benchmarks", flush=True)
    catalogue = load_catalogue()
    for name, kwargs in BENCHMARKS.items():
        committed = ROOT / "data" / "synthetic" / name
        out = tmp / name
        generate_benchmark(out, catalogue, **kwargs)
        files = sorted(p.relative_to(committed) for p in committed.rglob("*") if p.is_file())
        fresh = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
        rep.check(files == fresh, f"{name}: file list differs")
        for f in files:
            if (out / f).exists():
                rep.check(_read(committed / f) == _read(out / f), f"{name}/{f}")
        print(f"   {name}: {len(files)} files compared", flush=True)


def experiments() -> list[Path]:
    return sorted(p for p in EXP.glob("*") if (p / "results.jsonl").exists() and (p / "config.json").exists())


def check_tables(rep: Report, tmp: Path) -> None:
    print("2. Tables rebuilt from stored results", flush=True)
    for exp in experiments():
        work = tmp / "tables" / exp.name
        work.mkdir(parents=True)
        for f in ("results.jsonl", "config.json", "environment.json"):
            if (exp / f).exists():
                shutil.copy(exp / f, work / f)
        build_report(work)
        n = 0
        for f in TABLES:
            if (exp / f).exists():
                rep.check(_read(exp / f) == _read(work / f), f"{exp.name}/{f}")
                n += 1
        if (exp / "optimization.jsonl").exists():
            rows = [json.loads(line) for line in (exp / "optimization.jsonl").open(encoding="utf-8")]
            fresh = optimize_results.render(exp.name, rows, optimize_results.summarize(rows))
            rep.check(_read(exp / "optimization.md") == fresh.replace("\r\n", "\n"), f"{exp.name}/optimization.md")
            n += 1
        print(f"   {exp.name}: {n} tables", flush=True)


def _rows(path: Path) -> dict[tuple, dict]:
    return {(r["track"], r["system"], r["component_id"], r["seed"]): r
            for r in map(json.loads, path.open(encoding="utf-8"))}


def _same_row(a: dict, b: dict | None) -> bool:
    """Equal in every field; latency only within 0.05 s, because R's repair time is measured live."""
    if b is None or set(a) != set(b):
        return False
    return all(abs((a[f] or 0) - (b[f] or 0)) <= 0.05 if f == "latency_s" else a[f] == b[f] for f in a)


def check_replay(rep: Report, tmp: Path) -> None:
    print(f"3. Deterministic systems replayed under rule set {RULE_SET_VERSION}", flush=True)
    catalogue = load_catalogue()
    for exp in experiments():
        env = json.loads((exp / "environment.json").read_text(encoding="utf-8"))
        if env.get("rule_set_version") != RULE_SET_VERSION:
            print(f"   {exp.name}: rule set {env.get('rule_set_version')}, superseded; skipped (see docs/results.md)", flush=True)
            continue
        cfg = ExperimentConfig.model_validate_json((exp / "config.json").read_text(encoding="utf-8"))
        systems = [s for s in cfg.systems if s in DETERMINISTIC]
        out_root = tmp / "replay" / exp.name
        src = out_root / exp.name
        src.mkdir(parents=True)
        shutil.copy(exp / "config.json", src / "config.json")
        shutil.copytree(exp / "plans", src / "plans")
        replay = cfg.model_copy(update={"experiment_id": "replay", "systems": systems, "llm_repair": None,
                                        "initial_plans_from": exp.name, "output_dir": str(out_root)})
        out = run_experiment(replay, log=lambda *a, **k: None)
        old, new = _rows(exp / "results.jsonl"), _rows(out / "results.jsonl")
        keys = [k for k in old if k[1] in systems]
        same = sum(_same_row(old[k], new.get(k)) for k in keys)
        rep.check(same == len(keys) and len(new) == len(keys), f"{exp.name}: {len(keys) - same} of {len(keys)} replayed rows differ")
        # B2 cannot be re-run without the model: re-validate its stored final plans instead.
        b2 = [k for k in old if k[1] == "B2"]
        agree = 0
        for k in b2:
            record = load_run(exp / old[k]["run_file"])
            component = load_component(ROOT / cfg.benchmark_dir / "components" / f"{k[2]}.json", catalogue)
            result = validate_plan(record.final_plan, component, catalogue) if record.final_plan else None
            hard = len(result.hard_constraint_violations) if result else None
            agree += bool(result) and result.valid == old[k]["final_valid"] and hard == old[k]["final_hard_violations"]
        rep.check(agree == len(b2), f"{exp.name}: {len(b2) - agree} of {len(b2)} stored B2 final plans re-validate differently")
        print(f"   {exp.name}: {same}/{len(keys)} rows replayed identically ({', '.join(systems)}); "
              f"{agree}/{len(b2)} B2 final plans re-validated", flush=True)


def check_examples(rep: Report) -> None:
    print("4. docs/examples.md", flush=True)
    spec = importlib.util.spec_from_file_location("make_examples", ROOT / "scripts" / "make_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    rep.check(_read(ROOT / "docs" / "examples.md") == mod.render().replace("\r\n", "\n"), "docs/examples.md")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip the replay of deterministic systems")
    args = ap.parse_args()
    if not experiments():
        print("No experiment results in reports/experiments/: nothing to check.")
        return 1
    rep = Report()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        check_benchmarks(rep, tmp)
        check_tables(rep, tmp)
        if not args.quick:
            check_replay(rep, tmp)
        check_examples(rep)
    print(f"\n{rep.passed} checks passed, {len(rep.failures)} failed.")
    for f in rep.failures:
        print(f"  - {f}")
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
