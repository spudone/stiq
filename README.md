# Stiq

**Stiq** is a high-density, browser-based stock quote tracker for tracking global markets and individual quotes.

## Features

- **High-Density UI:** Compact financial layout designed for maximum information at a glance.
- **Market Overview:** Top-bar tracking of global indices (Dow, Nasdaq, S&P 500), commodities (Oil, Gold), and crypto.
- **Dynamic Watchlist:** Add and remove stock quotes instantly.
- **Sparklines:** 30-day historical trend charts for every quote in your list.
- **100% Node-Free:** Built with Python, HTMX, and Alpine.js. No `npm`, `node_modules`, or complex JS build tools.

## Tech Stack

- **Backend:** Python (built-in HTTP server, zero external dependencies)
- **Data Provider:** Custom zero-dependency scraper or [yfinance](https://github.com/ranaroussi/yfinance)
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
   ```bash
   make run
   ```

---

## Distribution

To package Stiq as a standalone executable:

**Custom lightweight build (Recommended):**
```bash
make dist
```

**Heavy yfinance build (Fallback):**
```bash
make dist-yfinance
```

The resulting executable will be found in the `dist/` directory.
