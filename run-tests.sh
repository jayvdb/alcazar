#!/bin/bash

set -e

python -m unittest discover -f tests "$@" \
    && ./run-samples.sh
