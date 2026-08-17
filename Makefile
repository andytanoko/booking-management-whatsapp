# Makefile for Booking Management WhatsApp Application

# Python commands
PYTHON = python3
PIP = $(PYTHON) -m pip
PYTEST = $(PYTHON) -m pytest

# Linter commands
FLAKE8 = $(PYTHON) -m flake8
FLAKE8_OUTPUT = flake8-report.txt

# Project directories
SRC_DIR = app
TEST_DIR = tests

# Default target
.PHONY: all
all: install test lint

# Install dependencies
.PHONY: install
install:
	$(PIP) install -r requirements.txt
	$(PIP) install flake8

# Run tests with coverage
.PHONY: test
test:
	$(PYTEST) $(TEST_DIR) --cov=$(SRC_DIR) --cov-report=term-missing -v

# Run flake8 static analysis (Python)
.PHONY: lint
lint:
	$(FLAKE8) --format=pylint $(SRC_DIR) > $(FLAKE8_OUTPUT) 2>&1 || true
	@echo "Flake8 report: $(FLAKE8_OUTPUT)"

# Run flake8 with verbose output
.PHONY: lint-verbose
lint-verbose:
	$(FLAKE8) --verbose $(SRC_DIR)

# Clean build artifacts
.PHONY: clean
clean:
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf $(FLAKE8_OUTPUT)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Full clean including venv
.PHONY: distclean
distclean: clean
	rm -rf .venv

# Install dev dependencies
.PHONY: dev
dev: install
	$(PIP) install ipdb pytest-cov

# Help
.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make install     - Install dependencies"
	@echo "  make test        - Run tests with coverage"
	@echo "  make lint        - Run flake8 static analysis (Python)"
	@echo "  make lint-verbose - Run flake8 with verbose output"
	@echo "  make clean       - Clean build artifacts"
	@echo "  make distclean   - Clean everything including venv"
	@echo "  make dev         - Install dev dependencies"
	@echo "  make help        - Show this help"
