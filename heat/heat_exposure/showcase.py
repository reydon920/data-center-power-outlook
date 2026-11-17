"""Render real, offline report images from the same metrics as the CLI."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .core import compare, metrics, monthly_metrics

WIDTH, HEIGHT = 1440, 940
INK, MUTED, PAPER, LINE = "#192d35", "#566469", "#f5f3e9", "#d2d6cd"
COLORS = ["#ae4b26", "#246a80", "#6657a5", "#397548"]


def font(size, bold=False):
    candidates = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
                  else ["arial.ttf", "DejaVuSans.ttf"])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def text(draw, xy, value, size=22, color=INK, bold=False, anchor=None):
    draw.text(xy, str(value), font=font(size, bold), fill=color, anchor=anchor)


def canvas(title, subtitle, manifest, threshold):
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    text(draw, (60, 35), "HEAT EXPOSURE   /   WEATHER SCREENING", 18, COLORS[0], True)
    text(draw, (60, 85), title, 42, bold=True)
    text(draw, (60, 145), subtitle, 21, MUTED)
    start, end = manifest["start"], manifest["end_exclusive"]
    period = f"{start[:4]}-{start[4:6]}-{start[6:8]} 00:00 to {end[:4]}-{end[4:6]}-{end[6:8]} 00:00 UTC (end exclusive)"
    text(draw, (60, 185), f"{period}  |  Threshold > {threshold:g} °C", 18, MUTED)
    draw.line((60, 840, 1380, 840), fill=LINE, width=2)
    text(draw, (60, 860), "Source: NASA POWER hourly T2M (2 m air temperature). City coordinates; gridded hourly averages.", 18, MUTED)
    text(draw, (60, 892), "Screening only. Degree-hours are not energy; outdoor heat alone cannot estimate cooling cost.", 18, MUTED)
    return image, draw


def legend(draw, sites, y=245):
    # A new row is used as needed for configurable site counts.
    for index, site in enumerate(sites):
        x = 70 + (index % 4) * 330
        row = y + (index // 4) * 35
        draw.rectangle((x, row + 6, x + 18, row + 24), fill=COLORS[index % len(COLORS)])
        text(draw, (x + 30, row), site["name"], 21)


def comparison(output, manifest, series, threshold):
    results = compare(series, threshold)
    image, draw = canvas("How much heat does each location face?",
                         "Frequency, intensity and uninterrupted duration describe different parts of exposure.",
                         manifest, threshold)
    columns = [60, 370, 595, 830, 1080, 1370]
    headers = ["LOCATION", "COVERAGE", "HOT HOURS", "DEGREE-HOURS", "LONGEST SPELL"]
    for x, heading in zip(columns, headers):
        text(draw, (x, 265), heading, 17, MUTED, True)
    text(draw, (830, 294), "°C·h above threshold", 16, MUTED)
    text(draw, (1080, 294), "consecutive hours", 16, MUTED)
    for index, site in enumerate(manifest["sites"]):
        y = 350 + index * 118
        row = results[site["id"]]
        draw.line((60, y - 15, 1380, y - 15), fill=LINE)
        text(draw, (60, y), site["name"], 29, COLORS[index % len(COLORS)], True)
        text(draw, (370, y), f"{row['coverage_pct']:g}%", 29, bold=True)
        text(draw, (370, y + 42), f"{row['valid_hours']:,} / {row['expected_hours']:,} h", 17, MUTED)
        text(draw, (595, y), f"{row['hot_hours']:,}", 33, bold=True)
        text(draw, (830, y), f"{row['degree_hours_c_h']:,.2f}", 29, bold=True)
        text(draw, (1080, y), row["longest_spell_hours"], 33, bold=True)
    complete = all(result["missing_hours"] == 0 for result in results.values())
    text(draw, (60, 740), "Coverage first: " + ("every expected hour is present." if complete else "gaps make observed counts lower bounds."), 24, bold=True)
    text(draw, (60, 780), "Missing and cooler hours end a spell. A temperature equal to the threshold does not count.", 20, MUTED)
    image.save(output / "comparison.png")


def axes(draw, top, bottom, peak, ylabel, xlabel):
    left, right = 130, 1360
    for tick in range(5):
        y = bottom - (bottom - top) * tick / 4
        draw.line((left, y, right, y), fill=LINE)
        text(draw, (left - 15, y), f"{peak * tick / 4:,.0f}", 18, MUTED, anchor="rm")
    text(draw, (60, top - 45), ylabel, 20, MUTED)
    text(draw, ((left + right) / 2, bottom + 57), xlabel, 20, MUTED, anchor="mm")
    return left, right


def seasonal(output, manifest, series, threshold):
    image, draw = canvas("When does heat exposure accumulate?",
                         "Monthly hot hours show when each location faces the most sustained seasonal pressure.",
                         manifest, threshold)
    sites = manifest["sites"]
    legend(draw, sites)
    monthly = {site: monthly_metrics(rows, threshold) for site, rows in series.items()}
    months = list(monthly[sites[0]["id"]])
    peak = max(1, max(row["hot_hours"] for group in monthly.values() for row in group.values()))
    top, bottom = 355, 695
    left, right = axes(draw, top, bottom, peak, "Hours strictly above threshold (h)", "Month (UTC)")
    group_width = (right - left) / len(months)
    bar_width = group_width * .78 / len(sites)
    for month_index, month in enumerate(months):
        for site_index, site in enumerate(sites):
            value = monthly[site["id"]][month]["hot_hours"]
            x = left + month_index * group_width + group_width * .11 + site_index * bar_width
            if value:
                draw.rectangle((x, bottom - value / peak * (bottom - top), x + bar_width - 2, bottom),
                               fill=COLORS[site_index % len(COLORS)])
        text(draw, (left + (month_index + .5) * group_width, bottom + 25), month[5:], 18, anchor="mm")
    text(draw, (60, 788), "Compare equivalent months and coverage. Missing readings are excluded, never filled with zero.", 20, MUTED)
    image.save(output / "seasonal.png")


def sensitivity(output, manifest, series, threshold):
    image, draw = canvas("Does the conclusion depend on the threshold?",
                         "Sweep a screening assumption: hot-hour counts fall as the threshold rises.",
                         manifest, threshold)
    sites = manifest["sites"]
    legend(draw, sites)
    thresholds = sorted(set(range(20, 41)) | {threshold})
    values = {site: [metrics(rows, value)["hot_hours"] for value in thresholds]
              for site, rows in series.items()}
    peak = max(1, max(max(counts) for counts in values.values()))
    top, bottom = 355, 695
    left, right = axes(draw, top, bottom, peak, "Hot hours in the snapshot (h)", "Screening threshold (°C)")
    low, high = min(thresholds), max(thresholds)
    for value in thresholds:
        if value % 5 == 0:
            x = left + (value - low) / (high - low) * (right - left)
            text(draw, (x, bottom + 25), f"{value:g}", 18, anchor="mm")
    for index, site in enumerate(sites):
        points = [(left + (value - low) / (high - low) * (right - left),
                   bottom - count / peak * (bottom - top))
                  for value, count in zip(thresholds, values[site["id"]])]
        draw.line(points, fill=COLORS[index % len(COLORS)], width=5)
        for x, y in points:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=COLORS[index % len(COLORS)])
    text(draw, (60, 788), "Choose the threshold explicitly. This curve describes outdoor conditions, not a safe operating limit.", 20, MUTED)
    image.save(output / "sensitivity.png")


def render(output, manifest, series, threshold):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if len(manifest["sites"]) > 3:
        raise ValueError("PNG report layout supports up to 3 sites; use the dashboard for more")
    for chart in (comparison, seasonal, sensitivity):
        chart(output, manifest, series, threshold)
