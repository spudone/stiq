def fmt_price(val):
    try:
        return f"{float(val):,.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_number(val):
    try:
        val = float(val)
        if abs(val) >= 1000:
            return f"{val:,.2f}"
        elif abs(val) >= 1:
            return f"{val:.2f}"
        else:
            return f"{val:.4f}"
    except (TypeError, ValueError):
        return "—"


def fmt_volume(val):
    try:
        val = float(val)
        if val >= 1_000_000_000:
            return f"{val / 1_000_000_000:.1f}B"
        elif val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        elif val >= 1_000:
            return f"{val / 1_000:.1f}K"
        else:
            return str(int(val))
    except (TypeError, ValueError):
        return "—"


def fmt_large_val(val):
    try:
        v = float(val)
        unit = ""
        if v >= 1.0e12:
            v /= 1.0e12
            unit = "T"
        elif v >= 1.0e9:
            v /= 1.0e9
            unit = "B"
        elif v >= 1.0e6:
            v /= 1.0e6
            unit = "M"
        elif v >= 1.0e5:
            v /= 1.0e3
            unit = "K"
        else:
            unit = ""
        return f"{v:.3f}{unit}"
    except (TypeError, ValueError):
        return "—"
