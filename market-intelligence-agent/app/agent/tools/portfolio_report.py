"""`generate_portfolio_report` — a self-loading, deterministic tool that
builds a downloadable HTML portfolio brief (positions table + an inline SVG
pie chart) for one named client.

Same rationale as concentration_screen and client_portfolio: a chart needs
real arc-angle math, which an LLM asked to hand-write SVG path data is just
as unreliable at as an LLM asked to sum a portfolio's market value itself
(the bug client_portfolio.py exists to prevent). This module computes the
chart in pure Python -- no LLM arithmetic, no matplotlib/weasyprint
dependency, one self-contained HTML file with the chart inlined as SVG.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# Same categorical palette PortfolioPieChart.tsx already uses in the chat --
# copied here (not shared/imported; there is no shared Python/TS config
# layer in this codebase) so the report's chart looks like the app's other
# charts rather than inventing a second palette.
_CHART_COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"]


def _polar_to_cartesian(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    # -90 so 0% starts at the top (12 o'clock), matching the app's other pie chart.
    angle_rad = math.radians(angle_deg - 90)
    return cx + r * math.cos(angle_rad), cy + r * math.sin(angle_rad)


def build_pie_chart_svg(positions: list[dict], *, size: int = 220) -> str:
    if not positions:
        raise ValueError("build_pie_chart_svg needs at least one position")

    cx = cy = size / 2
    r = size / 2 - 10

    if len(positions) == 1:
        # An SVG arc can't express a full 360° sweep as one path (the start
        # and end points coincide) -- draw a plain circle instead.
        arcs = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{_CHART_COLORS[0]}" />'
    else:
        parts = []
        angle = 0.0
        for i, p in enumerate(positions):
            sweep = p["weight_pct"] / 100 * 360
            end_angle = angle + sweep
            start_x, start_y = _polar_to_cartesian(cx, cy, r, angle)
            end_x, end_y = _polar_to_cartesian(cx, cy, r, end_angle)
            large_arc = 1 if sweep > 180 else 0
            color = _CHART_COLORS[i % len(_CHART_COLORS)]
            parts.append(
                f'<path d="M {cx:.2f} {cy:.2f} L {start_x:.2f} {start_y:.2f} '
                f'A {r:.2f} {r:.2f} 0 {large_arc} 1 {end_x:.2f} {end_y:.2f} Z" fill="{color}" />'
            )
            angle = end_angle
        arcs = "".join(parts)

    legend_parts = []
    for i, p in enumerate(positions):
        color = _CHART_COLORS[i % len(_CHART_COLORS)]
        y = 20 + i * 18
        legend_parts.append(
            f'<circle cx="{size + 15}" cy="{y}" r="5" fill="{color}" />'
            f'<text x="{size + 28}" y="{y + 4}" font-size="12" font-family="sans-serif">'
            f'{p["ticker"]} {p["weight_pct"]:.1f}%</text>'
        )
    legend = "".join(legend_parts)

    width = size + 140
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{size}" '
        f'viewBox="0 0 {width} {size}">{arcs}{legend}</svg>'
    )


def build_portfolio_report_html(portfolio: dict, *, threshold_pct: float = 30.0) -> str:
    client_name = portfolio["client_name"]
    positions = portfolio["positions"]
    totals = portfolio["totals"]
    today = datetime.now(timezone.utc).date().isoformat()

    rows = "".join(
        f'<tr><td>{p["ticker"]}</td><td>{p["shares"]:g}</td>'
        f'<td>${p["price"]:,.2f}</td><td>${p["market_value"]:,.2f}</td>'
        f'<td>{p["weight_pct"]:.1f}%</td></tr>'
        for p in positions
    )

    breaches = [p for p in positions if p["weight_pct"] > threshold_pct]
    concentration_note = ""
    if breaches:
        names = ", ".join(f'{p["ticker"]} ({p["weight_pct"]:.1f}%)' for p in breaches)
        verb = "exceeds" if len(breaches) == 1 else "exceed"
        concentration_note = (
            f'<p class="warning">Concentration note: {names} {verb} '
            f'{threshold_pct:g}% of the portfolio.</p>'
        )

    chart_svg = build_pie_chart_svg([
        {"ticker": p["ticker"], "weight_pct": p["weight_pct"]} for p in positions
    ])

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Portfolio Brief — {client_name}</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; color: #1a1a1a; background: #fff; max-width: 720px; margin: 40px auto; padding: 0 20px; }}
h1 {{ font-size: 20px; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #e2e2e2; font-size: 13px; }}
th {{ color: #666; font-weight: 600; }}
.warning {{ color: #b45309; font-size: 13px; }}
.total {{ font-weight: 600; margin-top: 8px; }}
</style></head>
<body>
<h1>Portfolio Brief — {client_name}</h1>
<p>Generated {today}</p>
<table><thead><tr><th>Ticker</th><th>Shares</th><th>Price</th><th>Market Value</th><th>Weight</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="total">Total market value: ${totals["market_value"]:,.2f}</p>
{concentration_note}
{chart_svg}
</body></html>"""
