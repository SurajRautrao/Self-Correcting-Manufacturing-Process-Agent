"""SCMPA demo UI.

    streamlit run src/scmpa/app/streamlit_app.py

Three views: run the generate → validate → repair workflow on a component, inspect a saved run
record (including slow LLM runs), and browse experiment results.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import streamlit as st

from scmpa.app.view_models import (
    DISCLAIMER,
    diff_rows,
    feature_rows,
    iteration_timeline,
    list_component_sources,
    list_experiments,
    list_saved_runs,
    machine_rows,
    outcome_summary,
    plan_rows,
    precedence_rows,
    rule_catalogue_rows,
    tool_rows,
    violation_rows,
)
from scmpa.io import REPO_ROOT, InputValidationError, load_catalogue, read_json, validate_component
from scmpa.planning import FAULT_KINDS, FaultNotApplicable, MockPlanner, make_planner
from scmpa.repair import make_repair_agent
from scmpa.schemas import Component
from scmpa.workflow import RunRecord, load_run, solve

st.set_page_config(page_title="SCMPA – Self-Correcting Process Planning", page_icon="🛠️", layout="wide")


@st.cache_resource
def catalogue():
    return load_catalogue()


def table(rows: list[dict], **kwargs) -> None:
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch", **kwargs)
    else:
        st.caption("None.")


# --------------------------------------------------------------------------- rendering blocks


def render_component(component: Component) -> None:
    st.subheader(f"{component.component_id}: {component.description or 'component'}")
    prov = component.provenance
    st.caption(f"Material: {component.material} · Data source: **{prov.source_type}** ({prov.source})")
    st.markdown("**Features to produce**")
    table(feature_rows(component))
    left, right = st.columns(2)
    with left:
        st.markdown("**Available machines**")
        table(machine_rows(component))
    with right:
        st.markdown("**Available tools**")
        table(tool_rows(component))
    st.markdown("**Declared ordering assumptions** (specific to this component, not universal rules)")
    table(precedence_rows(component))
    if component.assumptions:
        st.markdown("**Stated assumptions**")
        for a in component.assumptions:
            st.markdown(f"- {a}")


def render_outcome(record: RunRecord) -> None:
    summary = outcome_summary(record)
    if summary["kind"] == "success":
        st.success(f"✅ **{summary['headline']}**. {summary['explanation']}")
    else:
        st.warning(f"⚠️ **{summary['headline']}** (`{record.stop_reason}`). {summary['explanation']}")
    cols = st.columns(4)
    cols[0].metric("Final status", record.final_status.replace("_", " ").title())
    cols[1].metric("Repairs used", f"{record.repairs_used} / {record.max_repairs}")
    first_hard = len(record.iterations[0].validation.hard_constraint_violations) if record.iterations else "–"
    last_hard = len(record.final_validation.hard_constraint_violations) if record.final_validation else "–"
    cols[2].metric("Hard violations (first → last)", f"{first_hard} → {last_hard}")
    cols[3].metric("Run time", f"{record.duration_s:.1f} s")


def render_trace(record: RunRecord) -> None:
    render_outcome(record)
    st.caption(
        f"Planner: **{record.planner}**{f' ({record.planner_model})' if record.planner_model else ''} · "
        f"repair agent: **{record.repair_agent or 'none'}** · rule set {record.versions.get('rule_set_version')} · run `{record.run_id}`"
    )
    if record.planner_result.injected_faults:
        st.info("**Deliberately injected faults** (to demonstrate detection and repair):\n" + "\n".join(
            f"- `{f['kind']}` on {', '.join(f['operations'])}: {f['detail']} → expected rule `{f['expected_rule']}`"
            for f in record.planner_result.injected_faults
        ))
    if record.stop_reason == "planner_output_invalid":
        st.error("The planner produced no usable plan. Raw model outputs are shown below.")
        for a in record.planner_result.attempts:
            with st.expander(f"Planner attempt {a.attempt}: {len(a.issues)} issue(s)"):
                st.write(a.issues)
                st.code(a.raw_output or "(no output)", language="json")
        return

    st.markdown("#### Iterations")
    table(iteration_timeline(record))
    last = len(record.iterations) - 1
    for it in record.iterations:
        v = it.validation
        status = "✅ valid" if v.valid else f"❌ {len(v.hard_constraint_violations)} hard violation(s)"
        label = f"Iteration {it.index}: {'initial plan from the planner' if it.source == 'planner' else 'repaired plan'} · {status}"
        with st.expander(label, expanded=it.index in (0, last)):
            if it.repair:
                st.markdown(f"**What the repair agent changed** ({it.repair.agent}, {it.repair.latency_s:.1f} s)")
                for change in it.repair.changes or ["(no change description given)"]:
                    st.markdown(f"- {change}")
                st.markdown("**Operation-level difference from the previous plan**")
                table(diff_rows(it.repair.diff))
            st.markdown("**Plan** (rows are in execution order)")
            table(plan_rows(it.plan, v))
            if it.plan.precedence:
                st.caption("Declared precedence: " + ", ".join(f"{a} → {b}" for a, b in it.plan.precedence))
            st.markdown("**Validator findings**")
            if v.hard_constraint_violations or v.warnings:
                table(violation_rows(v))
            else:
                st.caption("No violations or warnings.")
    if record.terminal_repair:
        t = record.terminal_repair
        with st.expander(f"Final repair call ({t.agent}): {t.status}", expanded=True):
            if t.missing_information:
                st.markdown("**Missing information reported:**")
                for m in t.missing_information:
                    st.markdown(f"- {m}")
            if t.error:
                st.error(t.error)


def render_final(record: RunRecord) -> None:
    if record.final_plan is None:
        st.info("No plan was produced.")
        return
    plan = record.final_plan
    accepted = record.final_status == "ACCEPTED"
    st.markdown(f"#### Final plan `{plan.plan_id}`: {'accepted under the declared rule set' if accepted else 'NOT accepted (needs human review)'}")
    table(plan_rows(plan, record.final_validation))
    st.markdown(f"**Explanation (from the planner, not verified):** {plan.explanation}")
    if plan.assumptions:
        st.markdown("**Planner assumptions:** " + "; ".join(plan.assumptions))
    if plan.uncertainties:
        st.markdown("**Planner uncertainties:** " + "; ".join(plan.uncertainties))
    st.caption(DISCLAIMER)
    c1, c2 = st.columns(2)
    c1.download_button(
        "Download final plan (JSON)", plan.model_dump_json(indent=2), file_name=f"{plan.plan_id}.json", mime="application/json"
    )
    c2.download_button(
        "Download full run log (JSON)", record.model_dump_json(indent=2),
        file_name=f"{record.component_id}_{record.run_id}.json", mime="application/json",
    )


def find_component(component_id: str) -> Component | None:
    for src in list_component_sources():
        if src.path.stem == component_id:
            return validate_component(read_json(src.path), catalogue(), component_id)
    return None


def render_record_tabs(record: RunRecord, component: Component | None) -> None:
    tabs = st.tabs(["1 · Input component", "2 · Workflow trace", "3 · Final plan & downloads", "Rule catalogue"])
    with tabs[0]:
        if component:
            render_component(component)
        else:
            st.info(f"Component `{record.component_id}` was not found among the bundled data.")
    with tabs[1]:
        render_trace(record)
    with tabs[2]:
        render_final(record)
    with tabs[3]:
        render_rules()


def render_rules() -> None:
    st.markdown("The validator is deterministic Python. It is the only component that decides whether a plan is valid. "
                "An LLM's claim that a plan is correct is never trusted: every plan is re-checked.")
    table(rule_catalogue_rows())
    st.caption("Full semantics: docs/constraint_catalogue.md. Assumptions and limits: docs/assumptions_and_limits.md.")


# --------------------------------------------------------------------------- views


def view_run() -> None:
    sb = st.sidebar
    sb.header("1. Component")
    source = sb.radio("Source", ["Examples", "Synthetic benchmark", "Upload JSON"], horizontal=False)
    component: Component | None = None
    if source == "Upload JSON":
        upload = sb.file_uploader("Component JSON", type="json")
        if upload is not None:
            try:
                component = validate_component(json.loads(upload.getvalue()), catalogue(), upload.name)
            except (InputValidationError, json.JSONDecodeError) as exc:
                st.error("The uploaded component was rejected:")
                st.code(str(exc))
                return
    else:
        options = [s for s in list_component_sources() if s.group == source]
        choice = sb.selectbox("Component", options, format_func=lambda s: s.label)
        if choice:
            component = validate_component(read_json(choice.path), catalogue(), choice.path.stem)
    if component is None:
        st.info("Choose or upload a component in the sidebar.")
        return

    sb.header("2. Planner")
    planner_kind = sb.radio("Planner", ["Mock (deterministic, instant)", "Ollama LLM (minutes per call on CPU)"])
    use_llm_planner = planner_kind.startswith("Ollama")
    faults: list[str] = []
    if not use_llm_planner:
        faults = sb.multiselect(
            "Inject faults", sorted(FAULT_KINDS), format_func=lambda k: f"{k} → {FAULT_KINDS[k].split('_')[0]}",
            help="Corrupt the mock plan in known ways to see how they are detected and repaired.",
        )
    seed = int(sb.number_input("Seed", min_value=0, value=0, step=1))

    sb.header("3. Repair")
    repair_kind = sb.selectbox("Repair agent", ["rule_based", "ollama", "none"], format_func={
        "rule_based": "Rule-based (deterministic reference)", "ollama": "Ollama LLM", "none": "None (validate only)",
    }.get)
    max_repairs = sb.slider("Max repair iterations", 0, 5, 3)
    model = None
    if use_llm_planner or repair_kind == "ollama":
        model = sb.text_input("Ollama model", value="gemma3:4b")
        sb.caption("Each LLM call can take several minutes on a CPU-only machine.")

    run_clicked = sb.button("Run workflow", type="primary", width="stretch")
    key = (component.component_id, planner_kind, tuple(faults), seed, repair_kind, max_repairs, model)
    if run_clicked:
        options = {"seed": seed, **({"model": model} if model else {})}
        planner = make_planner("ollama", **options) if use_llm_planner else MockPlanner(faults=faults, seed=seed)
        agent = make_repair_agent(repair_kind, **(options if repair_kind == "ollama" else {}))
        with st.spinner("Running generate → validate → repair …"):
            try:
                record = solve(component, catalogue(), planner, agent, max_repairs=max_repairs)
            except FaultNotApplicable as exc:
                st.error(f"{exc}. Faults go to distinct operations; choose fewer faults or another seed.")
                return
        st.session_state["run"] = {"key": key, "record": record}

    stored = st.session_state.get("run")
    if stored and stored["key"] == key:
        render_record_tabs(stored["record"], component)
    else:
        tabs = st.tabs(["1 · Input component", "Rule catalogue"])
        with tabs[0]:
            render_component(component)
            st.info("Set the planner and repair options in the sidebar, then press **Run workflow**.")
        with tabs[1]:
            render_rules()


def view_saved_run() -> None:
    runs = list_saved_runs()
    if not runs:
        st.info("No saved run records yet. Use `python scripts/run_demo.py` or an experiment to create some.")
        return
    choice = st.sidebar.selectbox("Saved run", runs, format_func=lambda p: p.relative_to(REPO_ROOT / "reports").as_posix())
    record = load_run(choice)
    render_record_tabs(record, find_component(record.component_id))


def view_experiments() -> None:
    experiments = list_experiments()
    if not experiments:
        st.info("No experiment results yet. Run `python -m scmpa.evaluation.run_experiments --config configs/experiments/pilot_mock.json`.")
        return
    exp: Path = st.sidebar.selectbox("Experiment", experiments, format_func=lambda p: p.name)
    tabs = st.tabs(["Summary", "Per-case results"])
    with tabs[0]:
        chart = exp / "hard_violation_rate.png"
        if chart.exists():
            st.image(str(chart))
        st.markdown((exp / "summary.md").read_text(encoding="utf-8"))
    with tabs[1]:
        with (exp / "results.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        c1, c2 = st.columns(2)
        tracks = sorted({r["track"] for r in rows})
        systems = sorted({r["system"] for r in rows})
        track = c1.multiselect("Track", tracks, default=tracks)
        system = c2.multiselect("System", systems, default=systems)
        cols = ["track", "system", "component_id", "seed", "expected_outcome", "initial_valid", "final_valid", "final_status",
                "stop_reason", "repairs_used", "final_hard_violations", "injected_faults", "latency_s"]
        table([{k: r[k] for k in cols} for r in rows if r["track"] in track and r["system"] in system])
        st.caption("Every row links to a full run record in the experiment's runs/ folder. Open it in the 'Inspect a saved run' view.")


def main() -> None:
    st.title("Self-Correcting Manufacturing Process Agent")
    st.markdown("**generate → validate → diagnose → repair → revalidate**: an LLM or mock planner proposes a CNC operation "
                "sequence, deterministic rules check it, a repair agent fixes reported violations, and the loop stops when the "
                "plan passes or a human is needed.")
    st.caption(DISCLAIMER)
    view = st.sidebar.radio("View", ["Run the workflow", "Inspect a saved run", "Experiment results"])
    st.sidebar.divider()
    if view == "Run the workflow":
        view_run()
    elif view == "Inspect a saved run":
        view_saved_run()
    else:
        view_experiments()


main()
