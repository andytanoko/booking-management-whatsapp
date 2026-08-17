#!/bin/bash
# Build script for Booking Management WhatsApp Application
# Runs linting, tests, and builds the application

set -e

echo "=== Booking Management WhatsApp - Build Script ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv .venv
fi

# Step 2: Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source .venv/bin/activate

# Step 3: Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt

# Step 4: Run flake8 linting (skip on server - already done locally)
if [ -z "${DEPLOYING+x}" ]; then
    echo -e "${YELLOW}Running flake8 linting...${NC}"
    if command -v flake8 &> /dev/null; then
        flake8 --format=pylint app > flake8-report.txt 2>&1 || true

        if [ -s flake8-report.txt ]; then
            echo -e "${YELLOW}Flake8 issues found:${NC}"
            cat flake8-report.txt
            echo ""
            echo -e "${YELLOW}Note: Linting issues detected. Please fix them before committing.${NC}"
        else
            echo -e "${GREEN}Flake8 passed! No issues found.${NC}"
        fi
    else
        echo -e "${YELLOW}flake8 not found, skipping linting${NC}"
        echo "Skipping flake8 linting"
    fi
else
    echo "Skipping flake8 linting (deploy mode)"
fi

# Step 5: Run tests
echo -e "${YELLOW}Running tests...${NC}"
pytest tests --cov=app --cov-report=term-missing -v

# Step 6: Summary
echo ""
echo -e "${GREEN}=== Build Complete ===${NC}"
echo ""
echo "Output files:"
echo "  - flake8-report.txt  (linting results)"
echo "  - coverage.xml       (test coverage report)"
echo ""
