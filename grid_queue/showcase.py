"""Render the dashboard's three main analyses as offline PNG reports."""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from grid_queue import STATUSES, cohort_outcomes, load_bundled, wait_times

WIDTH, HEIGHT = 1600, 1100
INK, MUTED, GRID = '#182d3b', '#526676', '#d9e3e9'
COLORS = ['#277f98', '#348363', '#c06c47', '#8b75a7', '#a5afb8']


def font(size):
    # Pillow ships a readable default; OS fonts improve larger exports if present.
    for name in ('DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def page(title, subtitle, metadata):
    picture = Image.new('RGB', (WIDTH, HEIGHT), '#f7fafc')
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 0, WIDTH, 12), fill=COLORS[0])
    draw.text((65, 38), 'GRID QUEUE / GRID QUEUE REALITY CHECK', font=font(23), fill=MUTED)
    draw.text((65, 88), title, font=font(40), fill=INK)
    draw.text((65, 152), subtitle, font=font(24), fill=MUTED)
    draw.line((65, 975, 1535, 975), fill=GRID, width=2)
    draw.text((65, 1000), f"Snapshot {metadata['snapshot_date']} | LBNL + GridTracker | Queued Up 2026 | CC BY 4.0",
              font=font(21), fill=MUTED)
    draw.text((65, 1040), 'Generation and storage requests; these data do not establish data-center power availability.',
              font=font(20), fill=MUTED)
    return picture, draw


def backlog_report(data, metadata):
    active = data.loc[data.status.eq('active')]
    counts = active.groupby('region').size().sort_values(ascending=False)
    picture, draw = page('Where proposed projects are still waiting',
                         f'{len(active):,} active request records across {len(counts)} regions; counts are not delivered MW.', metadata)
    left, right, top, bottom = 250, 1380, 250, 820
    maximum = int(counts.max())
    for fraction in (0, .25, .5, .75, 1):
        x = left + (right - left) * fraction
        draw.line((x, top - 15, x, bottom), fill=GRID)
        draw.text((x, bottom + 15), f'{maximum * fraction:,.0f}', font=font(20), fill=MUTED, anchor='mt')
    step = (bottom - top) / len(counts)
    for index, (region, count) in enumerate(counts.items()):
        y = top + index * step
        draw.text((left - 22, y + 17), region, font=font(24), fill=INK, anchor='rm')
        end = left + count / maximum * (right - left)
        draw.rectangle((left, y, end, y + 34), fill=COLORS[0])
        draw.text((end + 12, y + 17), f'{count:,}', font=font(23), fill=INK, anchor='lm')
    draw.text((800, 884), 'Active request records by region', font=font(24), fill=INK, anchor='mt')
    draw.text((65, 936), 'Raw rows retained: ERCOT has 269 more active records than the source summary; discrepancy unresolved.',
              font=font(21), fill=MUTED)
    return picture


def cohort_report(data, metadata):
    cohorts = cohort_outcomes(data)
    picture, draw = page('Outcomes depend on time spent in the pipeline',
                         'All known-year requests stay in the denominator, including active, suspended and unknown outcomes.', metadata)
    left, right, top, bottom = 125, 1510, 300, 800
    for index, status in enumerate(STATUSES):
        x = 115 + index * 290
        draw.rectangle((x, 225, x + 25, 250), fill=COLORS[index])
        draw.text((x + 37, 224), status.title(), font=font(23), fill=INK)
    for percent in (0, 25, 50, 75, 100):
        y = bottom - (bottom - top) * percent / 100
        draw.line((left, y, right, y), fill=GRID)
        draw.text((left - 15, y), f'{percent}%', font=font(20), fill=MUTED, anchor='rm')
    step = (right - left) / len(cohorts)
    for index, row in cohorts.iterrows():
        x = left + index * step
        y = float(bottom)
        for status, color in zip(STATUSES, COLORS):
            end = y - float(row[f'{status}_share']) * (bottom - top)
            if end < y:
                draw.rectangle((x + 2, end, x + step - 2, y), fill=color)
            y = end
        if index % 5 == 0 or index == len(cohorts) - 1:
            draw.text((x + step / 2, bottom + 16), str(int(row.application_year)), font=font(20), fill=INK, anchor='mt')
    draw.text((800, 866), 'Application year | share of request records', font=font(25), fill=INK, anchor='mt')
    missing = int(data.application_year.isna().sum())
    draw.text((65, 912), f'n = {int(cohorts.projects.sum()):,} known-year records; {missing:,} unknown-year records excluded.', font=font(22), fill=MUTED)
    draw.text((65, 944), 'Recent cohorts have had less time to mature. Active requests are unfinished, not failed.', font=font(22), fill=MUTED)
    return picture


def waits_report(data, metadata):
    waits = wait_times(data)
    annual = waits.groupby(waits.operating_date.dt.year).wait_years.agg(['median', 'size'])
    operating = int(data.status.eq('operating').sum())
    picture, draw = page('Completed-project waits, with coverage visible',
                         f'{len(waits):,} of {operating:,} operating records have valid dates | Overall median: {waits.wait_years.median():.2f} years', metadata)
    left, right, top, bottom = 125, 1510, 260, 735
    ceiling = max(1, int(annual['median'].max()) + 1)
    for tick in range(ceiling + 1):
        y = bottom - tick / ceiling * (bottom - top)
        draw.line((left, y, right, y), fill=GRID)
        draw.text((left - 18, y), str(tick), font=font(21), fill=MUTED, anchor='rm')
    step = (right - left) / len(annual)
    points = []
    for index, (year, row) in enumerate(annual.iterrows()):
        x = left + (index + .5) * step
        y = bottom - row['median'] / ceiling * (bottom - top)
        points.append((x, y))
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=COLORS[1])
        # Every observed completion year and sample count is visible.
        label = Image.new('RGB', (150, 26), '#f7fafc')
        ImageDraw.Draw(label).text((0, 0), f'{year}  n={int(row["size"])}', font=font(17), fill=INK)
        picture.paste(label.rotate(90, expand=True), (int(x) - 13, bottom + 18))
    if len(points) > 1:
        draw.line(points, fill=COLORS[1], width=4)
    draw.text((125, 216), 'Median years from application to actual operation', font=font(23), fill=INK)
    draw.text((800, 915), 'Actual operating year | n = valid completed records in that year', font=font(23), fill=INK, anchor='mt')
    draw.text((65, 949), 'Missing, reversed and post-snapshot dates excluded. Completed waits do not predict waits for active projects.', font=font(21), fill=MUTED)
    return picture


def generate_showcase(directory):
    data, _, metadata = load_bundled()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, render in [('backlog', backlog_report), ('cohorts', cohort_report), ('waits', waits_report)]:
        path = directory / f'{name}.png'
        render(data, metadata).save(path)
        paths.append(path)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--showcase', type=Path, default=Path('docs/showcase'))
    for output in generate_showcase(parser.parse_args().showcase):
        print(output)
