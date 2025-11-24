#!/bin/bash
export PYTHONPATH="$(pwd)/src"
streamlit run src/ui/streamlit_app.py --server.port ${PORT:-8501} --server.address 0.0.0.0
