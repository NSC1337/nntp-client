#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
cmake -S benchmarks/download -B benchmarks/download/_build \
    -DCMAKE_BUILD_TYPE=Release -DPython_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build benchmarks/download/_build
exec .venv/bin/python benchmarks/download/run_benchmark.py "$@"
