# Stiq

**Stiq** is a high-density, browser-based stock quote tracker for tracking global markets and individual quotes.

## License
This project is licensed under the GNU Affero General Public License v3.0.

## Features

- **High-Density UI:** Compact financial layout designed for maximum information at a glance.
- **Market Overview:** Top-bar tracking of global indices, bond yields, currencies, and commodities.
- **Dynamic Watchlist:** Add and remove stock quotes instantly.
- **Sparklines:** 30-day historical trend charts for every quote in your list.
- **Simple Build:** Built with Python, HTMX, and Alpine.js. No `npm` or complex JS build tools.
- **Real-Time Push Architecture:** Zero-flicker UI powered by a Server-Sent Events (SSE) backend.

## Tech Stack

- **Backend:** Python (asyncio, aiohttp, Server-Sent Events)
- **Data Provider:** Hybrid provider engine (`yahoo`, `yfinance`, or `tiingo` WebSockets)
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
   This will synchronize Python dependencies and download the correct **Tailwind CSS** standalone binary for your OS.
   ```bash
   make setup
   ```

### Development

1. **Build the CSS:**
   ```bash
   make build
   ```
   *(Run `make watch` in a separate terminal to auto-compile as you edit).*

2. **Launch the app:**
   Start the application. The build system will automatically sniff your `config.json` and install only the required library extras.
   ```bash
   make run
   ```

---

## Configuration (`~/.stiq/config.json`)

Stiq dynamically multiplexes data pipelines. On first launch, a configuration file is generated at `~/.stiq/config.json`. You can edit this file to mix and match data providers seamlessly.

```json
{
  "market_provider": "yahoo",
  "quotes_provider": "yahoo",
  "history_provider": "yahoo",
  "poll_interval_secs": 300,
  "use_rate_limit": true,
  "watchlist": [
    "AAPL",
    "MSFT"
  ]
}
```

### Allowed Providers
You may assign any of the following to `market_provider`, `quotes_provider`, or `history_provider`:

- `"yahoo"`: Zero-dependency web scraper. The recommended default for all pipelines.
- `"yfinance"`: Uses the `yfinance` Python library. A reliable alternative fallback.
- `"tiingo"`: Uses the Tiingo IEX WebSocket API for instant real-time quotes, and REST for history.
  - *Note: Requires `TIINGO_API_KEY` to be exported in your environment.*
  - *Note: Tiingo does not provide global market indices; it's recommended to leave `market_provider` as `"yahoo"` even when using Tiingo for quotes.*

---

## Distribution & Cleanup

To package Stiq as a standalone executable (it will bundle whichever dependencies are specified in your current `config.json`):

```bash
make dist
```

To clean up build artifacts (`dist`, `build`, `.venv`):
```bash
make clean
```
*(To also wipe the downloaded Tailwind binary, use `make dist-clean`).*
