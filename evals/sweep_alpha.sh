#!/bin/sh
# Tune the smoothing constant on seeds 1-5; report the chosen value on holdout seeds 6-10 (forecast_eval.py default).
cd "$(dirname "$0")/.." || exit 1
PY=${PY:-.venv/bin/python}
for a in 0.03 0.05 0.08 0.12 0.2; do
  echo "alpha=$a dow=on"; $PY evals/forecast_eval.py --seeds 1 2 3 4 5 --alpha $a --out sweep_alpha_${a}.json | head -1
done
echo "alpha=0.05 dow=off"; $PY evals/forecast_eval.py --seeds 1 2 3 4 5 --alpha 0.05 --no-dow --out sweep_alpha_0.05_nodow.json | head -1
