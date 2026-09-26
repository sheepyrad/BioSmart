#!/bin/sh
# Serve the localhost host. The process runs as the user compose sets.
set -eu

stub="${TMPDIR:-/tmp}/biosmart-libcuda"
mkdir -p "$stub"
if [ ! -e "$stub/libcuda.so" ]; then
    for cand in \
        /usr/lib/x86_64-linux-gnu/libcuda.so \
        /usr/lib/x86_64-linux-gnu/libcuda.so.1 \
        /usr/lib64/libcuda.so.1 \
        /opt/nvidia/libcuda.so \
        /opt/nvidia/libcuda.so.1
    do
        if [ -e "$cand" ]; then
            ln -sfn "$cand" "$stub/libcuda.so"
            break
        fi
    done
fi
if [ -e "$stub/libcuda.so" ]; then
    LIBRARY_PATH="$stub${LIBRARY_PATH:+:$LIBRARY_PATH}"
    export LIBRARY_PATH
fi

PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/biosmart-pyc}"
export PYTHONPYCACHEPREFIX
mkdir -p "$PYTHONPYCACHEPREFIX"

cd /opt/biosmart
exec /opt/biosmart/.pixi/envs/server/bin/python -m biosmart serve --port "${BIOSMART_PORT:-8000}"
