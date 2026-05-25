# Stiq

**Stiq** is a high-density, browser-based stock quote tracker for tracking global markets and individual quotes.

## Features

- **High-Density UI:** Compact financial layout designed for maximum information at a glance.
- **Market Overview:** Top-bar tracking of global indices (Dow, S&P 500, Nasdaq, Tokyo, HK, London, Frankfurt), bond yields (10-Year), currencies (Euro, Yen), and commodities (Oil, Gold).
- **Dynamic Watchlist:** Add and remove stock quotes instantly.
- **Sparklines:** 30-day historical trend charts for every quote in your list.
- **100% Node-Free:** Built with Python, HTMX, and Alpine.js. No `npm`, `node_modules`, or complex JS build tools.

## Tech Stack

- **Backend:** Python (built-in HTTP server, using only `pytz` for timezone handling)
- **Data Provider:** Custom zero-dependency scraper, [yfinance](https://github.com/ranaroussi/yfinance), or Tiingo WebSocket API (hybrid/real-time)
- **Frontend:** [HTMX](https://htmx.org/) + [Alpine.js](https://alpinejs.dev/)
- **Styling:** [Tailwind CSS v4](https://tailwindcss.com/) (Standalone CLI)
- **Charts:** [ApexCharts](https://apexcharts.com/)

---

## Getting Started

### Prerequisites

- **Python >=3.13.13**
- **uv** (Recommended Python package manager)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/spudone/stiq.git
   cd stiq
   ```

2. **Run the setup:**
   This will synchronize Python dependencies and download the correct **Tailwind CSS** standalone binary for your operating system (Linux, macOS, or Windows).
   ```bash
   make setup
   ```

### Development

1. **Build the CSS:**
   Compiles the Tailwind `input.css` into the final `web/style.css`.
   ```bash
   make build
   ```
   *Alternatively, run `make watch` in a separate terminal to auto-compile as you edit HTML/CSS.*

2. **Launch the app:**
   Start the application with the custom scraping provider (recommended):
   ```bash
   make run
   ```

   Or start the application with the `yfinance` provider:
   ```bash
   make run-yfinance
   ```

   Or start the application with the **Tiingo WebSocket** provider (requires the `TIINGO_API_KEY` environment variable to be set):
   ```bash
   make run-tiingo-ws
   ```
   *Note: You can optionally set `TIINGO_THRESHOLD=6` as an environment variable to conserve bandwidth by streaming only derived reference price changes (instead of the default level 5 major updates).*
### Debugging in VSCode

To debug the backend server in VSCode, you can create a `.vscode/launch.json` configuration file with the following setup:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Stiq: Custom Scraper (Default)",
      "type": "python",
      "request": "launch",
      "module": "stiq.main",
      "cwd": "${workspaceFolder}",
      "env": {
        "PYTHONPATH": "src",
        "STIQ_PROVIDER": "yahoo"
      },
      "console": "integratedTerminal"
    },
    {
      "name": "Stiq: yfinance Provider",
      "type": "python",
      "request": "launch",
      "module": "stiq.main",
      "cwd": "${workspaceFolder}",
      "env": {
        "PYTHONPATH": "src",
        "STIQ_PROVIDER": "yfinance"
      },
      "console": "integratedTerminal"
    }
  ]
}
```

Once configured:
1. Ensure the **Python** extension by Microsoft is installed.
2. Open the Run and Debug view (`Ctrl+Shift+D`).
3. Select either **Stiq: Custom Scraper (Default)** or **Stiq: yfinance Provider** from the configuration dropdown at the top.
4. Press `F5` or click the green Play button to start debugging.

---

## Distribution

To package Stiq as a standalone executable:

**yahoo build (lightweight custom provider):**
```bash
make dist
```

**yfinance build (fallback):**
```bash
make dist-yfinance
```

**tiingo build (requires API key):**
```bash
make dist-tiingo
```

The resulting executable will be found in the `dist/` directory.
