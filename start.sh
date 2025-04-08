#!/bin/bash

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting Telegram bot..."
python3 main.py