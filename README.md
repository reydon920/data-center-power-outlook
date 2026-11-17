![Data Center Power Outlook](assets/banner.png)

Two offline checks on where new data centers can realistically be built: how much outdoor heat a site faces, and how long new power projects take to actually reach the grid.

# Data Center Power Outlook

Data centers need two things that are easy to underestimate from headlines: a site where cooling is not fighting the weather all summer, and electricity that actually arrives. This repository puts two small, tested tools side by side, each built on public data that ships with the repo:

| Part | Question it answers | Data | Run it |
|---|---|---|---|
| [`heat/`](heat/) | How many hours, how intensely and for how long in a row does a location stay above a chosen temperature? | NASA POWER hourly temperatures for Ashburn, Phoenix and Sacramento (full 2025 sample) | static dashboard you can open without a server |
| [`grid_queue/`](grid_queue/) | Which proposed U.S. power projects reached operation, withdrew, or are still waiting, and how long did completed ones take? | Berkeley Lab *Queued Up 2026* (all 38,201 interconnection requests, snapshot December 31, 2025) | local Streamlit dashboard |

## What the bundled data shows

- **Heat:** above 30°C, Phoenix logged 2,322 hot hours in 2025 with a 44-hour longest spell, against 835 hours for Sacramento and 457 for Ashburn. Sacramento has more hot hours than Ashburn, but Ashburn's longest spell is one hour longer, which is why the tool reports hours, degree-hours and spell length separately.
- **Grid queue:** of 38,201 requests, 24,221 were withdrawn, 8,513 are still active and 4,789 reached operation. For the 3,098 operating projects with usable dates, the median wait from application to operation was 3.58 years.

## Limits

Heat screening is not a cooling cost model, and the queue data covers generation and storage projects, not data center load connections, so neither part can say when a specific facility will get power. Each part's README lists its checks, exclusions and known data gaps (for example the one ERCOT count that does not match Berkeley Lab's summary table).

## Quick start

Each part has its own Python 3.12 environment and tests. On Windows PowerShell:

```powershell
cd heat
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe -m heat_exposure report

cd ..\grid_queue
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux use `.venv/bin/python` instead. GitHub Actions runs both test suites and rebuilds the reports on every push ([workflow](.github/workflows/check.yml)).

## Layout

```text
heat/         outdoor heat screening: package heat_exposure, dashboard in heat/docs/site
grid_queue/   interconnection queue outcomes: app.py dashboard, queue_pipeline.py, findings in grid_queue/docs
assets/       logo and banner
```

Code is under the [MIT License](LICENSE). NASA POWER data follow NASA's data guidance; the queue extract is derived from Berkeley Lab and GridTracker's *Queued Up 2026* data file under CC BY 4.0.
