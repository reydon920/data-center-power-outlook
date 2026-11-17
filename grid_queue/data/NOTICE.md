# Public data attribution

`public_queue.csv.gz`, `codebook.csv` and the summary counts in `reconciliation.json` are derived from the **Queued Up 2026 Edition** workbook, released May 2026, covering requests through December 31, 2025.

Source: [Lawrence Berkeley National Laboratory and GridTracker, Queued Up](https://emp.lbl.gov/queues/).

Queued Up Data File. Copyright © 2026, The Regents of the University of California, through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Department of Energy), and GridTracker.

Licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). Data is provided without warranty; the source authors do not endorse this project.

Changes: retained all 38,201 rows from `03. Complete Queue Data`, selected 14 non-personal request/capacity/date fields, and serialized those fields to CSV, then losslessly gzip-compressed the extract. Dates are represented as ISO date strings. Extracted the data dictionary from `04. Data Codebook`. Recorded region/status summary counts for comparison. Original source MW and statuses are retained in the CSV; normalization happens separately in Python. See `manifest.json` for exact checksums, edition and retrieval URL. No capacity was imputed.
