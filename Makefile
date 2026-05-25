.PHONY: setup build run run-yfinance run-tiingo-ws clean dist watch

USE_RATE_LIMIT ?= 1
export USE_RATE_LIMIT
# Helper to detect OS for the binary name (used for build/watch targets)
TAILWIND_BIN = $(shell python3 -c "import platform; print('tailwindcss.exe' if platform.system() == 'Windows' else 'tailwindcss')")

# Default target
all: setup build

# Sync python dependencies
setup:
	@echo "Synchronizing dependencies..."
	uv sync
	uv run python3 scripts/get_tailwind.py

# Compile Tailwind CSS
$(TAILWIND_BIN):
	@echo "Tailwind binary missing. Downloading..."
	uv run python3 scripts/get_tailwind.py

build: $(TAILWIND_BIN)
	@echo "Building CSS..."
	./$(TAILWIND_BIN) -i web/input.css -o web/style.css

# Launch the application (custom lightweight provider)
run: setup
	@echo "Launching Stiq..."
	STIQ_PROVIDER=yahoo uv run python -m stiq.main

# Launch the application (yfinance provider)
run-yfinance: setup
	@echo "Synchronizing heavy yfinance dependencies..."
	uv sync --extra yfinance
	@echo "Launching Stiq..."
	STIQ_PROVIDER=yfinance uv run python -m stiq.main

# Launch the application (tiingo websocket provider)
run-tiingo: setup
	@echo "Synchronizing websockets dependency..."
	uv sync --extra tiingo-ws
	@echo "Launching Stiq with Tiingo WebSocket provider..."
	STIQ_PROVIDER=tiingo uv run python -m stiq.main

# Create a standalone executable using the custom zero-dependency scraper
dist: setup build
	@echo "Creating standalone executable (custom provider)..."
	STIQ_PROVIDER=yahoo uv run python3 scripts/build.py

# Create a standalone executable using the yfinance library
dist-yfinance: setup
	@echo "Synchronizing yfinance dependencies..."
	uv sync --extra yfinance
	@echo "Building CSS..."
	./$(TAILWIND_BIN) -i web/input.css -o web/style.css
	@echo "Creating standalone executable (yfinance provider)..."
	STIQ_PROVIDER=yfinance uv run python3 scripts/build.py

# Create a standalone executable using the tiingo library
dist-tiingo: setup
	@echo "Synchronizing tiingo dependencies..."
	uv sync --extra tiingo-ws
	@echo "Building CSS..."
	./$(TAILWIND_BIN) -i web/input.css -o web/style.css
	@echo "Creating standalone executable (tiingo provider)..."
	STIQ_PROVIDER=tiingo uv run python3 scripts/build.py

# Watch for CSS changes
watch: $(TAILWIND_BIN)
	@echo "Watching for CSS changes..."
	./$(TAILWIND_BIN) -i web/input.css -o web/style.css --watch

# Cleanup
clean:
	@echo "Cleaning up..."
	uv run python3 -c "import shutil, os, glob; \
		[shutil.rmtree(p) for p in ['build', 'dist', '.venv'] if os.path.exists(p)]; \
		[os.remove(f) for f in ['stiq.spec', 'tailwindcss', 'tailwindcss.exe', 'web/style.css', 'finance_provider.py'] if os.path.exists(f)]"
