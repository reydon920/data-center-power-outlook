# Heat exposure walkthrough

Start with an operating question: how much outdoor heat might different locations face? An annual mean can hide both hot afternoons and long uninterrupted spells. Heat Exposure keeps those measures separate.

The sample contains a full UTC year of NASA POWER hourly average temperatures for three city reference coordinates. At a 30°C threshold, Phoenix has 2,322 hot hours and a 44-hour longest spell. Sacramento has 835 hot hours and an 11-hour longest spell. Ashburn has 457 hot hours and a 12-hour longest spell. All three have 100% hourly coverage. These are results for this snapshot and assumption, not forecasts.

Read `heat_exposure/core.py` first. The loader verifies the checksum, checks the records, loads a DuckDB table and orders the rows. It then creates a complete hourly grid for every site. That step matters: otherwise a missing record could make two separated readings look consecutive. The calculation function increments a counter during hot hours and resets it during missing or cooler hours. A year boundary alone does not reset it.

Read `heat_exposure/fetch.py` next. Request URLs encode the coordinates, dates, units-related parameter and UTC time standard. The snapshot manifest retains the retrieval time and hashes. Repeated requests reuse a cache unless refresh is requested. No network call is needed to demonstrate the project.

The dashboard uses the same definitions in JavaScript. Its slider changes one threshold used by every calculation. Tests compare those results with Python across multiple thresholds, then execute the dashboard's event handler and verify the table, chart and downloaded CSV. The DOM adapter catches logic errors; it does not prove how a real browser renders the page.

The central limitation is the link from weather to engineering. Degree-hours combine heat intensity and duration, but they cannot become energy or money without a facility model. The strongest conclusion here is which locations deserve more detailed investigation under the chosen screening assumption.

## Next improvements, smallest first

1. Add a Celsius/Fahrenheit display toggle while retaining Celsius internally.
2. Add an export of hourly observations with explicit missing-value flags.
3. Report start and end timestamps for the longest hot spell, including ties.
4. Add a minimum coverage filter to the dashboard comparison.
5. Add a real-browser smoke test for keyboard controls and CSV downloads.
6. Add a multi-year comparison using separate, source-attributed snapshots.
