/**
 * Stiq — Browser-based stock ticker
 * Alpine.js data store + ApexCharts sparkline rendering
 */

const STORAGE_KEY = "stiq_quotes";
const INTERVAL_KEY = "stiq_interval";
const DEFAULT_INTERVAL = 300; // 5 minutes

function stiq() {
  return {
    // ── State ──────────────────────────────────────────────
    quotes: [], // List of symbols
    quoteData: [], // List of quote objects
    marketData: [],
    marketOpen: false,
    lastUpdated: null,
    newQuote: "",
    sparkCharts: {},
    pollTimer: null,
    pollInterval: DEFAULT_INTERVAL, // In seconds

    // ── Init ───────────────────────────────────────────────
    async init() {
      // Load saved configuration from backend
      try {
        const resp = await fetch("/api/watchlist");
        const config = await resp.json();
        if (config) {
          this.quotes = config.symbols || [];
          this.pollInterval = config.poll_interval || DEFAULT_INTERVAL;
        }
      } catch (err) {
        console.error("Error loading watchlist:", err);
      }

      // Initial data fetch
      await this.refresh();

      // Start the dynamic polling timer
      this.startTimer();

      // Notify backend when window is closed
      window.addEventListener("beforeunload", () => {
        navigator.sendBeacon("/api/shutdown");
      });
    },

    // ── Timer Management ──────────────────────────────────
    startTimer() {
      if (this.pollTimer) clearInterval(this.pollTimer);
      
      this.pollTimer = setInterval(() => {
        this.refresh();
      }, this.pollInterval * 1000);
    },

    async setPollInterval(seconds) {
      // Floor at 15 seconds to prevent rate limiting/browser thrashing
      const val = Math.max(15, parseInt(seconds));
      try {
        const resp = await fetch("/api/watchlist/interval?seconds=" + val, { method: "POST" });
        const res = await resp.json();
        if (res && res.success) {
          this.pollInterval = val;
          // Restart timer with new interval
          this.startTimer();
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
        const resp = await fetch("/api/watchlist/add?symbol=" + encodeURIComponent(quote), { method: "POST" });
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
        const resp = await fetch("/api/watchlist/remove?symbol=" + encodeURIComponent(quote), { method: "POST" });
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
                  this.renderSparkline(q.quote, q.history, parseFloat(q.change) >= 0);
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
        });
      } catch (err) {
        console.error("Stiq refresh error:", err);
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
