#!/bin/bash

cd "$(dirname "$0")"
export PYTHONPATH=$PYTHONPATH:$(pwd)/src

exec python3 src/main.py $@
