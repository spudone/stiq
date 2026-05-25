.PHONY: setup build run clean dist-clean dist watch

USE_RATE_LIMIT ?= 1
export USE_RATE_LIMIT
# Helper to detect OS for the binary name (used for build/watch targets)
TAILWIND_BIN = $(shell python3 -c "import platform; print('tailwindcss.exe' if platform.system() == 'Windows' else 'tailwindcss')")

# Automatically determine required uv extras based on config.json
CONFIG_EXTRAS = $(shell python3 -c "import json, os; c = json.load(open(os.path.expanduser('~/.stiq/config.json'))); e = set(); [e.add('tiingo-ws') for v in c.values() if v == 'tiingo']; [e.add('yfinance') for v in c.values() if v == 'yfinance']; print(' '.join(['--extra ' + x for x in e]))" 2>/dev/null || true)

# Default target
all: setup build

# Sync python dependencies
setup:
	@echo "Synchronizing dependencies..."
	uv sync $(CONFIG_EXTRAS)
	uv run python3 scripts/get_tailwind.py

# Compile Tailwind CSS
$(TAILWIND_BIN):
	@echo "Tailwind binary missing. Downloading..."
	uv run python3 scripts/get_tailwind.py

build: $(TAILWIND_BIN)
	@echo "Building CSS..."
	./$(TAILWIND_BIN) -i web/input.css -o web/style.css

# Launch the application (uses config.json or defaults to yahoo)
run: setup
	@echo "Launching Stiq..."
	uv run python -m stiq.main

# Create a standalone executable (uses config.json defaults)
dist: setup build
	@echo "Creating standalone executable..."
	uv run python3 scripts/build.py

# Watch for CSS changes
watch: $(TAILWIND_BIN)
	@echo "Watching for CSS changes..."
	./$(TAILWIND_BIN) -i web/input.css -o web/style.css --watch

# Standard cleanup (preserves tailwind binary)
clean:
	@echo "Cleaning up build artifacts..."
	uv run python3 -c "import shutil, os; \
		[shutil.rmtree(p) for p in ['build', 'dist', '.venv'] if os.path.exists(p)]; \
		[os.remove(f) for f in ['stiq.spec', 'web/style.css'] if os.path.exists(f)]"

# Deep cleanup (removes everything including tailwind binary)
dist-clean: clean
	@echo "Cleaning up tailwind binaries..."
	uv run python3 -c "import os; \
		[os.remove(f) for f in ['tailwindcss', 'tailwindcss.exe'] if os.path.exists(f)]"
