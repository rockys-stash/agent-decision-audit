#!/usr/bin/env bash
# Re-runs every experiment reported in research/REPORT.md, then regenerates its tables and figures.
set -euo pipefail
cd "$(dirname "$0")/.."
# Single-threaded BLAS/OpenMP: experiments run seeds in parallel worker processes.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
for cfg in configs/e1_reconstruction.yaml configs/e2_audit_delay.yaml configs/e3_violations.yaml \
           configs/e4_tamper.yaml configs/e5_overhead.yaml; do
  echo "== $cfg"
  uv run agentaudit run "$cfg"
done
uv run agentaudit report
