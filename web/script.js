/*
Stiq - Stock Ticker
Copyright (C) 2026 spudone

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

const STORAGE_KEY = "stiq_quotes";
const INTERVAL_KEY = "stiq_interval";
const DEFAULT_INTERVAL = 300; // 5 minutes

// ── Formatting utilities (ported from Python formatter.py) ──
const fmt = {
  price(val) {
    if (val === null || val === undefined) return "\u2014";
    const n = parseFloat(val);
    if (isNaN(n)) return "\u2014";
    return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  number(val) {
    if (val === null || val === undefined) return "\u2014";
    const n = parseFloat(val);
    if (isNaN(n)) return "\u2014";
    if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (Math.abs(n) >= 1) return n.toFixed(2);
    return n.toFixed(4);
  },
  volume(val) {
    if (val === null || val === undefined) return "\u2014";
    const n = parseFloat(val);
    if (isNaN(n)) return "\u2014";
    if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return Math.floor(n).toString();
  },
  largeVal(val) {
    if (val === null || val === undefined) return "\u2014";
    let n = parseFloat(val);
    if (isNaN(n)) return "\u2014";
    let unit = "";
    if (n >= 1e12) { n /= 1e12; unit = "T"; }
    else if (n >= 1e9) { n /= 1e9; unit = "B"; }
    else if (n >= 1e6) { n /= 1e6; unit = "M"; }
    else if (n >= 1e5) { n /= 1e3; unit = "K"; }
    return n.toFixed(3) + unit;
  },
  change(val) {
    if (val === null || val === undefined) return "\u2014";
    const n = parseFloat(val);
    if (isNaN(n)) return "\u2014";
    return (n >= 0 ? "+" : "") + n.toFixed(2);
  },
  yieldPct(val) {
    if (val === null || val === undefined) return "\u2014";
    const n = parseFloat(val);
    if (isNaN(n)) return "\u2014";
    return (n * 100).toFixed(2) + "%";
  },
  bandwidth(val) {
    if (val === null || val === undefined) return "0.00 MB";
    const n = parseFloat(val);
    if (isNaN(n)) return "0.00 MB";
    return n.toFixed(2) + " MB";
  },
};

function stiq() {
  return {
    // ── State ──────────────────────────────────────────────
    quotes: [], // List of symbols
    quoteData: [], // List of quote objects
    marketData: [],
    marketOpen: false,
    lastUpdated: null,
    currentDate: new Date().toLocaleDateString(undefined, { dateStyle: 'medium' }),
    newQuote: "",
    sparkCharts: {},
    pollTimer: null,
    pollInterval: DEFAULT_INTERVAL, // In seconds
    sortKey: "quote",
    sortAsc: true,
    quotesProvider: "yahoo",
    marketProvider: "yahoo",
    historyProvider: "yahoo",
    tiingoUsage: { hourly_requests: 0, daily_requests: 0, monthly_bandwidth_mb: 0.0 },

    isTiingoActive() {
      return this.quotesProvider === 'tiingo' || 
             this.marketProvider === 'tiingo' || 
             this.historyProvider === 'tiingo';
    },

    // ── Init ───────────────────────────────────────────────
    async init() {
      // Load saved configuration from backend
      try {
        const resp = await fetch("/api/watchlist");
        const config = await resp.json();
        if (config) {
          this.quotes = config.symbols || [];
          this.pollInterval = config.poll_interval_secs || DEFAULT_INTERVAL;
          this.quotesProvider = config.quotes_provider || "yahoo";
          this.marketProvider = config.market_provider || "yahoo";
          this.historyProvider = config.history_provider || "yahoo";
        }
      } catch (err) {
        console.error("Error loading watchlist:", err);
      }

      if (this.isTiingoActive()) {
        try {
          const usageResp = await fetch("/api/tiingo_usage");
          this.tiingoUsage = await usageResp.json();
        } catch (err) {
          console.error("Error loading tiingo usage:", err);
        }
      }

      // Initial data fetch
      await this.refresh();

      // Connect to Server-Sent Events stream
      this.setupSSE();



      if (this.quotesProvider === "tiingo") {
        setInterval(() => {
          this.lastUpdated = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        }, 1000);
      }
    },

    // ── SSE / Stream Management ───────────────────────────
    setupSSE() {
      if (this.evtSource) {
        this.evtSource.close();
      }
      this.evtSource = new EventSource("/api/stream");
      this.evtSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          
          if (payload.type === "market") {
            this.marketData = payload.data.indices || [];
            this.marketOpen = payload.data.is_open || false;
            
          } else if (payload.type === "history") {
            for (const sym of Object.keys(payload.data)) {
              const hi = payload.data[sym];
              let idx = this.quoteData.findIndex((q) => q.quote === sym);
              if (idx !== -1) {
                this.quoteData[idx] = { ...this.quoteData[idx], ...hi };
              } else {
                this.quoteData.push({ quote: sym, ...hi });
                idx = this.quoteData.length - 1;
              }
              const q = this.quoteData[idx];
              if (q.history && q.history.length > 0) {
                if (this.sparkCharts[sym]) {
                  this.sparkCharts[sym].updateSeries([{ data: q.history }]);
                } else {
                  this.$nextTick(() => { this.renderSparkline(sym, q.history, q.change >= 0); });
                }
              }
            }
            
          } else if (payload.type === "quotes") {
            payload.data.forEach((q) => {
              const idx = this.quoteData.findIndex((e) => e.quote === q.quote);
              if (idx !== -1) {
                this.quoteData[idx] = { ...this.quoteData[idx], ...q };
              }
            });
            this.lastUpdated = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            
          } else if (payload.type === "quote") {
            const q = payload.data;
            const idx = this.quoteData.findIndex((e) => e.quote === q.quote);
            if (idx !== -1) {
              this.quoteData[idx] = { ...this.quoteData[idx], ...q };
            }
            this.lastUpdated = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          } else if (payload.type === "tiingo_usage") {
            this.tiingoUsage = payload.data;
          }
        } catch (e) {
          console.error("SSE parse error", e);
        }
      };
      
      this.evtSource.onerror = () => {
        console.log("SSE disconnected. Attempting to reconnect...");
      };
    },

    // ── Timer Management ──────────────────────────────────

    async setPollInterval(seconds) {
      // Floor at 60 seconds to prevent rate limiting/browser thrashing
      const val = Math.max(60, parseInt(seconds));
      try {
        const resp = await fetch("/api/watchlist/interval", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ seconds: val }),
        });
        const res = await resp.json();
        if (res && res.success) {
          this.pollInterval = val;
          // Backend poller will automatically adopt the new interval
          console.log(`[stiq] Polling interval updated to ${val}s`);
        }
      } catch (err) {
        console.error("Error setting poll interval:", err);
      }
    },

    // ── Quote Management ─────────────────────────────────
    async addQuote() {
      const quote = this.newQuote.trim().toUpperCase();
      if (!quote || this.quotes.includes(quote)) {
        this.newQuote = "";
        return;
      }
      try {
        const resp = await fetch("/api/watchlist/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: quote }),
        });
        const res = await resp.json();
        if (res && res.success) {
          this.quotes.push(quote);
          this.newQuote = "";
          await this.refresh();
        }
      } catch (err) {
        console.error("Error adding quote:", err);
      }
    },

    async removeQuote(quote) {
      try {
        const resp = await fetch("/api/watchlist/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: quote }),
        });
        const res = await resp.json();
        if (res && res.success) {
          this.quotes = this.quotes.filter((q) => q !== quote);
          this.quoteData = this.quoteData.filter((q) => q.quote !== quote);

          // Destroy the sparkline chart for this quote
          if (this.sparkCharts[quote]) {
            this.sparkCharts[quote].destroy();
            delete this.sparkCharts[quote];
          }
        }
      } catch (err) {
        console.error("Error removing quote:", err);
      }
    },

    // ── Data Fetching ─────────────────────────────────────
    async refresh() {
      try {
        // Fetch market overview
        const marketResp = await fetch("/api/market");
        const market = await marketResp.json();
        if (market) {
          this.marketData = market.indices || [];
          this.marketOpen = market.is_open || false;
        }

        // Fetch quotes for user quotes
        if (this.quotes.length > 0) {
          const quotesResp = await fetch("/api/quotes?symbols=" + encodeURIComponent(this.quotes.join(",")));
          const data = await quotesResp.json();
          if (data && Array.isArray(data)) {
            this.quoteData = data;

            // Render sparklines after Alpine updates the DOM
            this.$nextTick(() => {
              this.quoteData.forEach((q) => {
                if (q.history && q.history.length > 0) {
                  this.renderSparkline(q.quote, q.history, q.change >= 0);
                }
              });
            });
          }
        }

        // Update timestamp
        const now = new Date();
        this.lastUpdated = now.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit"
        });
      } catch (err) {
        console.error("Stiq refresh error:", err);
      }
    },

    // ── Sorting ───────────────────────────────────────────
    sortBy(key) {
      console.log("[stiq] sortBy called with key:", key);
      try {
        if (this.sortKey === key) {
          this.sortAsc = !this.sortAsc;
        } else {
          this.sortKey = key;
          this.sortAsc = true;
        }
        console.log("[stiq] sortKey set to:", this.sortKey, "sortAsc:", this.sortAsc);
        
        // Force redrawing of sparklines after browser has updated the table DOM layout
        setTimeout(() => {
          console.log("[stiq] redrawing sparklines...");
          this.quoteData.forEach((q) => {
            if (q.history && q.history.length > 0) {
              this.renderSparkline(q.quote, q.history, q.change >= 0);
            }
          });
        }, 0);
      } catch (err) {
        console.error("[stiq] Error in sortBy:", err);
      }
    },

    getSortedQuoteData() {
      console.log("[stiq] getSortedQuoteData called. sortKey:", this.sortKey, "sortAsc:", this.sortAsc);
      try {
        if (!this.sortKey) return this.quoteData;
        const key = this.sortKey;
        const sorted = [...this.quoteData].sort((a, b) => {
          let valA = a[key];
          let valB = b[key];

          // Push null/undefined to the bottom of the list.
          const isAEmpty = valA === null || valA === undefined;
          const isBEmpty = valB === null || valB === undefined;

          if (isAEmpty && isBEmpty) return 0;
          if (isAEmpty) return 1;
          if (isBEmpty) return -1;

          if (key === 'quote') {
            const comp = valA.localeCompare(valB);
            return this.sortAsc ? comp : -comp;
          } else {
            return this.sortAsc ? valA - valB : valB - valA;
          }
        });
        console.log("[stiq] sorted quotes order:", sorted.map(q => q.quote));
        return sorted;
      } catch (err) {
        console.error("[stiq] Error in getSortedQuoteData:", err);
        return this.quoteData;
      }
    },

    // ── Sparkline Rendering ───────────────────────────────
    renderSparkline(quote, data, isGain) {
      const elId = "spark-" + quote;
      const el = document.getElementById(elId);
      if (!el) return;

      const color = isGain ? "#22c55e" : "#ef4444";

      // Destroy existing chart if present
      if (this.sparkCharts[quote]) {
        this.sparkCharts[quote].destroy();
      }

      const options = {
        series: [{ data: data }],
        chart: {
          type: "line",
          height: 24,
          width: 112,
          sparkline: { enabled: true },
          animations: { enabled: true, easing: "easeinout", speed: 600 },
        },
        stroke: { width: 1.5, curve: "smooth" },
        colors: [color],
        tooltip: { enabled: false },
      };

      const chart = new ApexCharts(el, options);
      chart.render();
      this.sparkCharts[quote] = chart;
    },
  };
}
