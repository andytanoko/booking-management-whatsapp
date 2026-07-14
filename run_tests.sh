#!/bin/bash
# Quick Test Runner Script

echo "================================"
echo "Unit Test Suite - Quick Start"
echo "================================"
echo ""

cd /Users/andy.tanoko/ai/test

# Check if dependencies are installed
echo "Checking dependencies..."
python3 -m pip list | grep -q pytest
if [ $? -ne 0 ]; then
    echo "Installing test dependencies..."
    python3 -m pip install -q -r requirements.txt
fi

echo ""
echo "Running tests..."
echo "================================"

# Run tests with coverage
python3 -m pytest tests/ \
    --cov=app \
    --cov-report=html \
    --cov-report=term-missing \
    -v \
    --tb=short

echo ""
echo "================================"
echo "Test run complete!"
echo ""
echo "Coverage report: htmlcov/index.html"
echo "Open in browser: open htmlcov/index.html"
echo ""
echo "Quick commands:"
echo "  - Run specific file: pytest tests/test_models.py -v"
echo "  - Run pattern: pytest tests/ -k 'booking' -v"
echo "  - Quiet mode: pytest tests/ -q"
echo "  - Stop on failure: pytest tests/ -x"
echo ""
