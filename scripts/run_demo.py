"""Run the generate–validate–repair workflow on one component and print a readable trace.

Examples::

    python scripts/run_demo.py                                    # mock planner, rule-based repair
    python scripts/run_demo.py --faults incompatible_tool swap_precedence --component demo_plate_002
    python scripts/run_demo.py --planner ollama --repair ollama   # local LLM for both steps
    python scripts/run_demo.py --planner mock --faults missing_operation --repair ollama --model gemma3:4b

The full run record (every plan, validation result and repair call) is saved
as JSON under ``reports/runs/`` unless ``--no-save`` is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scmpa.io import EXAMPLE_COMPONENTS_DIR, REPO_ROOT, load_catalogue, load_component
from scmpa.planning import FAULT_KINDS, FaultNotApplicable, MockPlanner, make_planner
from scmpa.repair import make_repair_agent
from scmpa.workflow import RunRecord, save_run, solve


def print_trace(record: RunRecord) -> None:
    print(f"\nRun {record.run_id}  component={record.component_id}  planner={record.planner}"
          f"{f' ({record.planner_model})' if record.planner_model else ''}  repair={record.repair_agent}  "
          f"max_repairs={record.max_repairs}")
    for fault in record.planner_result.injected_faults:
        print(f"  injected fault: {fault['kind']} on {fault['operation_id']} ({fault['detail']}) -> expect {fault['expected_rule']}")
    for it in record.iterations:
        if it.repair:
            print(f"\n  repair ({it.repair.agent}, {it.repair.latency_s:.1f}s):")
            for change in it.repair.changes:
                print(f"    * {change}")
        v = it.validation
        print(f"\n  [iteration {it.index} | {it.source}] valid={v.valid}  coverage={v.coverage.covered_features}/{v.coverage.required_features}")
        for op in it.plan.operations:
            print(f"    {op.operation_id:<5} {op.type:<15} {','.join(op.target_features):<8} {op.machine_id:<4} {op.tool_id:<4} {op.duration_min:>5.1f} min")
        if it.plan.precedence:
            print(f"    precedence: {', '.join(f'{a}->{b}' for a, b in it.plan.precedence)}")
        for x in v.hard_constraint_violations:
            print(f"    HARD  {x.rule_id}: {x.message}")
        for x in v.warnings:
            print(f"    WARN  {x.rule_id}: {x.message}")
    if record.terminal_repair:
        print(f"\n  repair ({record.terminal_repair.agent}) ended the run: {record.terminal_repair.status}")
    print(f"\n  => {record.final_status} ({record.stop_reason}) {record.stop_detail}")
    print(f"     repairs used: {record.repairs_used}, total time {record.duration_s:.1f}s")
    print("  NOTE: decision-support output under simplified assumptions; not a production-ready or executable plan.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--component", default="demo_bracket_001", help="example name or path to a component JSON file")
    parser.add_argument("--planner", choices=["mock", "ollama"], default="mock")
    parser.add_argument("--repair", choices=["rule_based", "ollama", "none"], default="rule_based")
    parser.add_argument("--faults", nargs="*", default=[], choices=sorted(FAULT_KINDS), help="faults to inject (mock planner only)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", help="Ollama model (default: $SCMPA_LLM_MODEL or qwen3.5:9b)")
    parser.add_argument("--max-repairs", type=int, default=None, help="default: $SCMPA_MAX_REPAIRS or 3")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.component)
    if not path.exists():
        path = EXAMPLE_COMPONENTS_DIR / f"{args.component}.json"
    catalogue = load_catalogue()
    component = load_component(path, catalogue)

    llm_options = {"model": args.model, "seed": args.seed} if args.model else {"seed": args.seed}
    if args.planner == "mock":
        planner = MockPlanner(faults=args.faults, seed=args.seed)
    else:
        if args.faults:
            parser.error("--faults requires --planner mock")
        planner = make_planner("ollama", **llm_options)
    repair_agent = make_repair_agent(args.repair, **(llm_options if args.repair == "ollama" else {}))

    try:
        record = solve(component, catalogue, planner, repair_agent, max_repairs=args.max_repairs)
    except FaultNotApplicable as exc:
        print(f"error: {exc} (faults are injected into distinct operations; try fewer faults or another seed)", file=sys.stderr)
        return 2
    print_trace(record)
    if not args.no_save:
        print(f"\n  run record: {save_run(record, REPO_ROOT / 'reports' / 'runs')}")
    return 0 if record.final_status == "ACCEPTED" else 1


if __name__ == "__main__":
    sys.exit(main())
