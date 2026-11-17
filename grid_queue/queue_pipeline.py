"""Explicit online download and offline workbook/database commands."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile
from datetime import date

import pandas as pd

from grid_queue import (DATA_DIR, REQUIRED, SNAPSHOT, capacity_totals, load_bundled,
                        normalize, parse_dates, read_database, save_database)

SHEET = '03. Complete Queue Data'
CODEBOOK = '04. Data Codebook'
EXTRACT_FIELDS = ['q_id', 'entity', 'region', 'q_status', 'q_year', 'q_date',
                  'on_date', 'type_clean', 'type_1', 'type_2', 'type_3',
                  'mw_1', 'mw_2', 'mw_3']
DOWNLOAD_URLS = [
    'https://emp.lbl.gov/sites/default/files/2026-05/LBNL_Ix_Queue_Data_File_thru2025.xlsx?download=1',
    'https://eta-publications.lbl.gov/sites/default/files/2026-05/lbnl_ix_queue_data_file_thru2025.xlsx',
]


def read_workbook(path):
    with pd.ExcelFile(path) as workbook:
        if not {SHEET, CODEBOOK}.issubset(workbook.sheet_names):
            raise ValueError('Unsupported workbook: queue data or codebook sheet is missing.')
        codebook = pd.read_excel(workbook, sheet_name=CODEBOOK, header=1)
        if 'Field Name' not in codebook or not REQUIRED.issubset(set(codebook['Field Name'])):
            raise ValueError('Unsupported codebook: expected fields are missing.')
        return pd.read_excel(workbook, sheet_name=SHEET, header=1, dtype={'q_id': 'string'})


def workbook_metadata(path, snapshot=None):
    """Only the recorded checksum establishes the pinned workbook's edition."""
    recorded = json.loads((DATA_DIR / 'manifest.json').read_text())
    checksum = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    recognized = checksum == recorded['workbook_sha256']
    if not recognized and snapshot is None:
        raise ValueError('Unrecognized workbook checksum. Supply --snapshot YYYY-MM-DD '
                         'from the source documentation; its edition will be labeled unverified.')
    snapshot = snapshot or recorded['snapshot_date']
    date.fromisoformat(snapshot)
    if recognized and snapshot != recorded['snapshot_date']:
        raise ValueError('Snapshot conflicts with the recorded workbook edition.')
    return {
        'title': recorded['title'] if recognized else 'Local Queued Up workbook (edition unverified)',
        'snapshot_date': snapshot, 'workbook_sha256': checksum,
        'source_page': recorded['source_page'],
        'edition': recorded['edition'] if recognized else 'Unverified; user-supplied snapshot date',
        'publisher': recorded['publisher'], 'license': 'CC BY 4.0', 'sheet': SHEET,
        'imported_at': datetime.now(timezone.utc).isoformat(),
    }


def extract_workbook(workbook, output, snapshot=None):
    """Create a public, documented extract without copying unrelated source fields."""
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Extract output must be a new or empty directory.')
    metadata = workbook_metadata(workbook, snapshot)
    raw = read_workbook(workbook)
    # Optional component fields stay present even when an edition omits them.
    extract = raw.reindex(columns=EXTRACT_FIELDS).copy()
    for column in ['q_date', 'on_date']:
        extract[column] = parse_dates(extract[column]).dt.strftime('%Y-%m-%d')
    with pd.ExcelFile(workbook) as book:
        codebook = pd.read_excel(book, sheet_name=CODEBOOK, header=1)
    output.mkdir(parents=True, exist_ok=True)
    csv = output / 'public_queue.csv'
    extract.to_csv(csv, index=False, lineterminator='\n')
    codebook.to_csv(output / 'codebook.csv', index=False, lineterminator='\n')
    metadata.update({
        'csv_sha256': hashlib.sha256(csv.read_bytes()).hexdigest(),
        'source_rows': len(extract), 'header_row': 2,
        'transformation': 'All rows; selected public request, date, type and MW fields. No imputation.',
        'license_url': 'https://creativecommons.org/licenses/by/4.0/',
    })
    (output / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


def download_workbook(destination):
    """Validate a complete download before replacing any previous workbook."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix('.download.xlsx')
    errors = []
    for url in DOWNLOAD_URLS:
        try:
            request = Request(url, headers={'User-Agent': 'GridQueueRealityCheck/1.0'})
            with urlopen(request, timeout=45) as response, staging.open('wb') as output:
                while block := response.read(1024 * 256):
                    output.write(block)
            read_workbook(staging)
            workbook_metadata(staging)
            staging.replace(destination)
            receipt = {
                'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                'edition': 'Queued Up 2026, through 2025', 'snapshot_date': SNAPSHOT,
            }
            destination.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            return receipt
        except (URLError, OSError, ValueError, BadZipFile) as error:
            errors.append(f'{url}: {error}')
        finally:
            staging.unlink(missing_ok=True)
    raise ValueError('Download failed. Download the 2026 workbook manually from '
                     'https://emp.lbl.gov/queues/ and use build --workbook PATH. '
                     + ' | '.join(errors))


def summarize(data, quality, metadata):
    active = data[data.status.eq('active')]
    return {
        'snapshot_date': metadata['snapshot_date'], 'requests': len(data),
        'outcomes': {str(k): int(v) for k, v in data.status.value_counts().items()},
        'active_known_capacity_mw': capacity_totals(active),
        'valid_completed_waits': quality['valid_operating_waits'],
        'median_completed_wait_years': (float(data.wait_years.median())
                                         if data.valid_wait.any() else None),
    }


def build_snapshot(database, workbook=None, snapshot=None):
    if workbook is None:
        data, quality, metadata = load_bundled()
    else:
        metadata = workbook_metadata(workbook, snapshot)
        data, quality = normalize(read_workbook(workbook), metadata['snapshot_date'])
    save_database(data, quality, metadata, database)
    return summarize(data, quality, metadata)


def reconcile_workbook(workbook, snapshot=None):
    """Compare every region/status count to the workbook's recorded summary tab."""
    metadata = workbook_metadata(workbook, snapshot)
    data, _ = normalize(read_workbook(workbook), metadata['snapshot_date'])
    table = pd.read_excel(workbook, sheet_name='02. Data Sample by Region', header=None)
    checks = []
    for _, row in table.iterrows():
        label = str(row.iloc[0])
        region = label.replace(' (non-ISO)', '')
        if region not in set(data.region):
            continue
        for column, status in [(1, 'active'), (3, 'operating'), (5, 'withdrawn')]:
            expected = int(row.iloc[column])
            actual = int(((data.region == region) & (data.status == status)).sum())
            checks.append({'region': region, 'status': status, 'summary_count': expected,
                           'raw_count': actual, 'difference': actual - expected})
    if not checks:
        raise ValueError('No recognizable summary rows were found.')
    return {
        'sheet': '02. Data Sample by Region', 'snapshot_date': metadata['snapshot_date'],
        'workbook_sha256': hashlib.sha256(Path(workbook).read_bytes()).hexdigest(),
        'checks': checks, 'mismatches': sum(c['difference'] != 0 for c in checks),
        'note': 'Differences are exposed, never patched. Summary methodology may differ; '
                'investigate mismatches before comparing report headlines.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    download = sub.add_parser('download', help='Online: download the pinned public 2026 workbook')
    download.add_argument('--output', type=Path, default=DATA_DIR / 'source.xlsx')
    build = sub.add_parser('build', help='Offline: normalize the bundle or a supported workbook into DuckDB')
    build.add_argument('--workbook', type=Path)
    build.add_argument('--snapshot', help='YYYY-MM-DD; required for unrecognized workbook checksums')
    build.add_argument('--database', type=Path, default=DATA_DIR / 'queue.duckdb')
    summary = sub.add_parser('summary', help='Offline: print summary from a built database')
    summary.add_argument('--database', type=Path, default=DATA_DIR / 'queue.duckdb')
    reconcile = sub.add_parser('reconcile', help='Offline: compare workbook summary counts')
    reconcile.add_argument('workbook', type=Path)
    reconcile.add_argument('--snapshot', help='YYYY-MM-DD; required for unrecognized workbook checksums')
    extract = sub.add_parser('extract', help='Offline: reproduce a public CSV and codebook extract')
    extract.add_argument('workbook', type=Path)
    extract.add_argument('--output', type=Path, required=True, help='New or empty output directory')
    extract.add_argument('--snapshot', help='YYYY-MM-DD; required for unrecognized workbook checksums')
    args = parser.parse_args()
    try:
        if args.command == 'download':
            result = download_workbook(args.output)
        elif args.command == 'build':
            if args.snapshot and not args.workbook:
                raise ValueError('--snapshot requires --workbook; the bundled snapshot is fixed.')
            result = build_snapshot(args.database, args.workbook, args.snapshot)
        elif args.command == 'summary':
            result = summarize(*read_database(args.database))
        elif args.command == 'extract':
            result = extract_workbook(args.workbook, args.output, args.snapshot)
        else:
            result = reconcile_workbook(args.workbook, args.snapshot)
    except (OSError, ValueError, BadZipFile) as error:
        parser.exit(1, f'Error: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
