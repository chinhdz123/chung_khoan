#!/bin/bash
# Script de chay server tu dong tren Linux

ENV_NAME="kyluat-dautu"
PORT=8000

# Lay thu muc chua file run.sh
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
BACKEND_DIR="$PROJECT_DIR/backend"

if [ ! -d "$BACKEND_DIR" ]; then
    echo "Khong tim thay thu muc backend tai: $BACKEND_DIR"
    exit 1
fi

cd "$BACKEND_DIR"

# Kiem tra/.env
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "Da tao file .env tu .env.example"
fi

export PYTHONIOENCODING="utf-8"
export PYTHONUTF8="1"

# Kiem tra conda hoac dung venv
if command -v conda &> /dev/null; then
    echo "Da phat hien Conda, tien hanh chay bang Conda env: $ENV_NAME"
    if ! conda env list | grep -q "$ENV_NAME"; then
        echo "Dang tao moi conda env..."
        conda create -y -n $ENV_NAME python=3.12
    fi
    conda run -n $ENV_NAME --no-capture-output python -m pip install -r requirements.txt
    echo "Dang khoi dong server..."
    # Xoa bo cờ --reload cho moi truong production (nen khuyen khich cho service ngan)
    conda run -n $ENV_NAME --no-capture-output python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
else
    echo "Khong co Conda, su dung Python Venv"
    VENV_DIR="$BACKEND_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo "Dang tao venv moi..."
        python3 -m venv "$VENV_DIR"
    fi
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt
    echo "Dang khoi dong server..."
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
fi
