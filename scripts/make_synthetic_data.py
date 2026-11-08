"""Generate the synthetic SCMPA benchmark (deterministic for a given seed).

    python scripts/make_synthetic_data.py                     # default: 24 components, seed 2026
    python scripts/make_synthetic_data.py --n 40 --seed 7 --out data/synthetic/my_bench
    python scripts/make_synthetic_data.py --profile v2 --seed 2027 --out data/synthetic/benchmark_v2
"""

from __future__ import annotations

import argparse
import shutil
from collections import Counter

from scmpa.io import DATA_DIR, load_catalogue
from scmpa.evaluation.synthetic import generate_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DATA_DIR / "synthetic" / "benchmark_v1"))
    parser.add_argument("--n", type=int, default=24)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--infeasible-fraction", type=float, default=0.2)
    parser.add_argument("--profile", choices=["v1", "v2"], default="v1",
                        help="v1: benchmark_v1; v2: specialised machines with partial overlap, more features and constraints")
    parser.add_argument("--force", action="store_true", help="delete an existing output directory first")
    args = parser.parse_args()

    from pathlib import Path

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        if not args.force:
            parser.error(f"{out} already exists; pass --force to regenerate it")
        shutil.rmtree(out)
    manifest = generate_benchmark(out, load_catalogue(), n_components=args.n, seed=args.seed, infeasible_fraction=args.infeasible_fraction, profile=args.profile)
    outcomes = Counter((c["split"], c["expected_outcome"]) for c in manifest["cases"])
    print(f"wrote {manifest['n_components']} components to {out}")
    for (split, outcome), n in sorted(outcomes.items()):
        print(f"  {split:<5} {outcome:<20} {n}")


if __name__ == "__main__":
    main()
