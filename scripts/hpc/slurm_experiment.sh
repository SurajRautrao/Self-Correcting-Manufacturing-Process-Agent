#!/bin/bash
#SBATCH --job-name=scmpa_experiment
#SBATCH --partition=gpu-stud

#SBATCH --gres=gpu:1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=logs/scmpa_%j.out
#SBATCH --error=logs/scmpa_%j.err

# SCMPA experiment on a GPU node: Ollama (Apptainer) + generate-validate-repair evaluation.
#
# Submit from the repo root. Slurm opens the log files BEFORE this script runs, so logs/ must exist:
#     mkdir -p logs
#     sbatch scripts/hpc/slurm_experiment.sh
#
# SMOKE RUN FIRST (a few minutes; catches wrong model tags, missing image, old Python):
#     CONFIG=configs/experiments/llm_pilot_dev_gemma3-4b.json LIMIT=2 sbatch scripts/hpc/slurm_experiment.sh
#
# Main run (default config): configs/experiments/llm_test_full_gemma3-4b.json
#     16 test components x 3 seeds, generation + corruption tracks, B0/B1/B2/R.
#
# RESUMABLE: every planner/repair call is cached under reports/experiments/<experiment_id>/.
# If the job hits --time, just submit the same command again; finished cases are skipped.
# A changed config under the same experiment_id is refused. Copy the config and give it a new
# experiment_id to change the model or the seeds.
#
# Overrides (environment variables):
#     CONFIG=...        experiment config JSON (relative to repo root)
#     LIMIT=N           only the first N components of the split (smoke runs)
#     FRESH=1           delete this experiment's cached results first
#     VENV=...          virtualenv path            (default: $HOME/.venvs/scmpa)
#     PYTHON_BIN=...    interpreter used to create the venv; must be >= 3.11 (default: python3)
#     PY_MODULE=...     environment module to load first, e.g. PY_MODULE=python/3.11
#     REBUILD_VENV=1    recreate the venv
#     OLLAMA_DIR=...    model cache, persists across jobs (default: $HOME/ollama)
#     OLLAMA_SIF=...    Apptainer image             (default: $HOME/ollama.sif)

set -euo pipefail

REPO="${SLURM_SUBMIT_DIR:-$PWD}"
cd "$REPO"

CONFIG="${CONFIG:-configs/experiments/llm_test_full_gemma3-4b.json}"
OLLAMA_DIR="${OLLAMA_DIR:-$HOME/ollama}"
OLLAMA_SIF="${OLLAMA_SIF:-$HOME/ollama.sif}"
VENV="${VENV:-$HOME/.venvs/scmpa}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Per-job port. A fixed 11434 collides with any other Ollama on this node, and the readiness
# check would then pass against THAT server, silently running the experiment on whatever
# model it happens to serve.
PORT=$(( 11434 + (${SLURM_JOB_ID:-0} % 1000) ))

echo "======================================"
echo "Job ${SLURM_JOB_ID:-local} on $(hostname)  |  $(date)"
echo "repo=$REPO"
echo "config=$CONFIG  limit=${LIMIT:-none}  port=$PORT"
echo "======================================"
nvidia-smi || echo "WARNING: nvidia-smi unavailable"

[ -f "$CONFIG" ] || { echo "ERROR: config not found: $CONFIG (submit from the repo root)"; exit 1; }
mkdir -p "$OLLAMA_DIR" "$REPO/logs" "$REPO/reports/experiments"

if [ ! -f "$OLLAMA_SIF" ]; then
  echo "ERROR: Apptainer image not found at $OLLAMA_SIF"
  echo "Build it once on a login node:  apptainer pull \"$OLLAMA_SIF\" docker://ollama/ollama:latest"
  exit 1
fi

ollama_exec() {
  apptainer exec --nv \
    --env OLLAMA_HOST=127.0.0.1:$PORT \
    --bind "$OLLAMA_DIR":/root/.ollama \
    "$OLLAMA_SIF" \
    ollama "$@"
}

# -----------------------------
# PYTHON ENV (before the server, so a bad interpreter fails fast without holding the GPU)
# -----------------------------
if [ -n "${PY_MODULE:-}" ]; then
  # Batch shells are non-interactive, so `module` may not be defined yet: load the init script.
  if ! command -v module >/dev/null 2>&1; then
    for init in /etc/profile.d/lmod.sh /etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash /usr/share/Modules/init/bash; do
      # shellcheck disable=SC1090
      [ -f "$init" ] && { set +u; source "$init"; set -u; break; }
    done
  fi
  command -v module >/dev/null 2>&1 || { echo "ERROR: PY_MODULE is set but the 'module' command is unavailable on $(hostname)"; exit 1; }
  set +u; module load "$PY_MODULE"; set -u
  echo "Loaded module $PY_MODULE: $(command -v "$PYTHON_BIN") ($("$PYTHON_BIN" --version 2>&1))"
fi
if [ -n "${REBUILD_VENV:-}" ]; then rm -rf "$VENV"; fi

# Guard on "the package imports", not on "the directory exists": a half-built or foreign
# venv at $VENV would otherwise skip the install and die later with ModuleNotFoundError.
if ! "$VENV/bin/python" -c "import scmpa, pydantic, matplotlib" 2>/dev/null; then
  "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "ERROR: $PYTHON_BIN is $("$PYTHON_BIN" --version 2>&1); SCMPA needs Python >= 3.11."
    echo "Set PY_MODULE=<python module> or PYTHON_BIN=/path/to/python3.11"
    exit 1
  }
  echo "Creating venv at $VENV with $("$PYTHON_BIN" --version)..."
  rm -rf "$VENV"
  "$PYTHON_BIN" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  # Editable install of this repo (+ matplotlib for the report chart). Small: no torch/CUDA wheels.
  "$VENV/bin/pip" install --quiet -e "$REPO[eval]"
fi
PYTHON="$VENV/bin/python"
echo "Python: $($PYTHON --version) at $PYTHON"
"$PYTHON" -c "import scmpa; print('scmpa', scmpa.__version__)"

# Validate the config before the GPU work starts (bad JSON / unknown fields fail here).
"$PYTHON" -c "from scmpa.evaluation.run_experiments import ExperimentConfig; from scmpa.io import read_json; \
c = ExperimentConfig.model_validate(read_json('$CONFIG')); print('experiment_id:', c.experiment_id, '| split:', c.split, '| seeds:', c.seeds, '| systems:', c.systems)"

# -----------------------------
# OLLAMA SERVER
# -----------------------------
echo "Starting Ollama server on 127.0.0.1:$PORT ..."
ollama_exec serve &
OLLAMA_PID=$!

# A trap, not a trailing kill: on a crash a --time=06:00:00 reservation would otherwise hold
# the GPU with a live server for the full allocation.
cleanup() {
  echo "Stopping Ollama (pid $OLLAMA_PID)..."
  kill "$OLLAMA_PID" 2>/dev/null || true
  wait "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "Waiting for Ollama on port $PORT..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/api/tags" > /dev/null; then
    echo "Ollama is ready."
    break
  fi
  if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
    echo "ERROR: Ollama server exited during startup (port $PORT already in use?)"
    exit 1
  fi
  sleep 2
done
curl -sf "http://127.0.0.1:$PORT/api/tags" > /dev/null || {
  echo "ERROR: Ollama did not become ready within 120s"
  exit 1
}

# -----------------------------
# PULL EVERY MODEL THE CONFIG NAMES (planner + repair)
# -----------------------------
# Up front, not lazily: a missing tag discovered hours in wastes the whole run.
MODELS=$("$PYTHON" - "$CONFIG" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
models = []
for key in ("planner", "llm_repair"):
    section = cfg.get(key) or {}
    if section.get("provider") == "ollama":
        models.append(section.get("model") or "qwen3.5:9b")  # adapter default if unset
print("\n".join(dict.fromkeys(models)))
PY
)
if [ -z "$MODELS" ]; then
  echo "No Ollama models in $CONFIG (mock-only config); skipping pulls."
else
  echo "Models from $CONFIG:"; echo "$MODELS" | sed 's|^|  |'
fi

while IFS= read -r MODEL; do
  [ -z "$MODEL" ] && continue
  echo "Ensuring $MODEL is available..."
  ollama_exec pull "$MODEL"
  # `ollama pull` can report progress and still fail (e.g. full quota); every call would then 404.
  curl -sf "http://127.0.0.1:$PORT/api/tags" | grep -qF "\"$MODEL\"" || {
    echo "ERROR: $MODEL not present after pull"
    exit 1
  }
  # Warm-up call: loads the model and lets us confirm it is on the GPU, not silently on CPU.
  curl -sf "http://127.0.0.1:$PORT/api/generate" \
    -d "{\"model\": \"$MODEL\", \"prompt\": \"ok\", \"stream\": false, \"options\": {\"num_predict\": 1}}" > /dev/null \
    || echo "WARNING: warm-up call for $MODEL failed"
  ollama_exec ps || true
done <<< "$MODELS"

# -----------------------------
# RUN THE EXPERIMENT
# -----------------------------
export OLLAMA_BASE_URL="http://127.0.0.1:$PORT"   # read by scmpa.llm.OllamaConfig.from_env
export PYTHONUNBUFFERED=1                           # progress lines appear in the .out log immediately

ARGS=(--config "$CONFIG")
[ -n "${LIMIT:-}" ] && ARGS+=(--limit "$LIMIT")
[ -n "${FRESH:-}" ] && ARGS+=(--fresh)

echo "======================================"
echo "Running: python -m scmpa.evaluation.run_experiments ${ARGS[*]}"
echo "======================================"
START=$(date +%s)
"$PYTHON" -m scmpa.evaluation.run_experiments "${ARGS[@]}"
echo "Experiment finished in $(( $(date +%s) - START ))s."

EXP_ID=$("$PYTHON" -c "import json; print(json.load(open('$CONFIG', encoding='utf-8'))['experiment_id'])")
OUT="$REPO/reports/experiments/$EXP_ID"
echo "======================================"
echo "Finished at $(date). Results in $OUT:"
ls -1 "$OUT" | sed 's|^|  |'
echo "--------------------------------------"
sed -n '1,60p' "$OUT/summary.md" || true
echo "======================================"
