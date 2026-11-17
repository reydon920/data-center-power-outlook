"""Normalize Berkeley Lab queue records and calculate descriptive metrics."""

import gzip
import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

SNAPSHOT = '2025-12-31'
STATUSES = ['active', 'operating', 'withdrawn', 'suspended', 'unknown']
STORAGE_TYPES = {'battery', 'other storage'}
# Resource names from the recorded data dictionary; new labels need review.
GENERATION_TYPES = {'solar', 'wind', 'gas', 'hydro', 'coal', 'offshore wind',
                    'nuclear', 'geothermal', 'diesel', 'oil', 'hydrogen', 'other'}
REQUIRED = {'q_id', 'entity', 'region', 'q_status', 'q_year', 'q_date',
            'on_date', 'type_clean', 'type_1', 'mw_1'}
DATA_DIR = Path(__file__).parent / 'data'


def text_column(frame, name):
    """Use an empty nullable column for optional source fields."""
    return frame.get(name, pd.Series(pd.NA, index=frame.index)).astype('string').str.strip()


def parse_dates(values):
    # Reject numeric Excel serials unless the workbook reader has decoded them.
    values = values.where(~values.map(lambda value: isinstance(value, (int, float))))
    return pd.to_datetime(values, errors='coerce', format='mixed')


def normalize(raw, snapshot=SNAPSHOT):
    """Keep source rows, flag collisions, and never substitute proposed dates."""
    missing = REQUIRED - set(raw.columns)
    if missing:
        raise ValueError(f'Missing required source fields: {sorted(missing)}')
    cutoff = pd.Timestamp(snapshot)
    raw = raw.reset_index(drop=True)
    out = pd.DataFrame(index=raw.index)
    out['source_row'] = raw.index + 3  # Two workbook header rows precede data.
    out['entity'] = text_column(raw, 'entity').replace('', pd.NA).fillna('Unknown')
    out['queue_id'] = text_column(raw, 'q_id')
    missing_id = out['queue_id'].isna() | out['queue_id'].str.lower().isin(
        ['', 'not assigned', 'unknown', 'n/a'])
    # Structured pairs keep separators in source IDs from creating collisions.
    key = pd.Series([
        json.dumps([entity, None if pd.isna(queue_id) else queue_id], ensure_ascii=False)
        for entity, queue_id in zip(out['entity'], out['queue_id'])
    ], index=out.index, dtype='string')
    duplicate = key.duplicated(keep=False) & ~missing_id
    out['project_id'] = key
    needs_row_id = missing_id | duplicate
    out.loc[needs_row_id, 'project_id'] = (
        key[needs_row_id] + ':row-' + out.loc[needs_row_id, 'source_row'].astype(str))
    out['region'] = text_column(raw, 'region').replace('', pd.NA).fillna('Unknown')
    out['technology'] = text_column(raw, 'type_clean').replace('', pd.NA).fillna('Unknown')
    status = text_column(raw, 'q_status').str.lower()
    out['status'] = status.map({
        'active': 'active', 'operational': 'operating', 'withdrawn': 'withdrawn',
        'suspended': 'suspended', 'unknown': 'unknown',
    }).fillna('unknown')
    out['status_raw'] = status
    out['application_date'] = parse_dates(raw['q_date'])
    out['operating_date'] = parse_dates(raw['on_date'])
    year = pd.to_numeric(raw['q_year'], errors='coerce')
    year = year.where(year.mod(1).eq(0) & year.between(1900, cutoff.year))
    out['application_year'] = year.astype('Int64')
    out['wait_years'] = (out['operating_date'] - out['application_date']).dt.days / 365.25
    valid_dates = (out['application_date'].notna() & out['operating_date'].notna()
                   & out['application_date'].le(cutoff) & out['operating_date'].le(cutoff)
                   & out['wait_years'].ge(0))
    out['valid_wait'] = out['status'].eq('operating') & valid_dates
    out.loc[~out['valid_wait'], 'wait_years'] = float('nan')

    capacities = {'generation': [], 'storage': []}
    required_components = {'generation': [], 'storage': []}
    invalid_capacity = 0
    unclassified_capacity = 0
    for component in (1, 2, 3):
        technology = text_column(raw, f'type_{component}').str.lower()
        original = raw.get(f'mw_{component}', pd.Series(pd.NA, index=raw.index))
        mw = pd.to_numeric(original, errors='coerce')
        valid_mw = mw.ge(0) & mw.lt(float('inf'))
        invalid_capacity += int((original.notna() & ~valid_mw.fillna(False)).sum())
        mw = mw.where(valid_mw)
        storage = technology.isin(STORAGE_TYPES)
        generation = technology.isin(GENERATION_TYPES)
        unclassified_capacity += int((mw.notna() & ~storage & ~generation).sum())
        for name, mask in [('generation', generation), ('storage', storage)]:
            capacities[name].append(mw.where(mask))
            required_components[name].append(mask)
    for name, components in capacities.items():
        present = pd.concat(required_components[name], axis=1, ignore_index=True)
        values = pd.concat(components, axis=1, ignore_index=True)
        out[f'{name}_mw'] = values.sum(axis=1, min_count=1).where(present.any(axis=1), 0.0)
        out[f'{name}_capacity_incomplete'] = (present & values.isna()).any(axis=1)

    quality = {
        'source_rows': len(raw), 'retained_rows': len(out),
        'exact_duplicate_rows': int(raw.duplicated().sum()),
        'duplicate_identifier_rows': int(duplicate.sum()),
        'missing_identifiers': int(missing_id.sum()),
        'unknown_statuses': int(out['status'].eq('unknown').sum()),
        'missing_application_year': int(out['application_year'].isna().sum()),
        'missing_application_date': int(out['application_date'].isna().sum()),
        'year_date_disagreements': int((out['application_year'].notna()
            & out['application_date'].notna()
            & out['application_year'].ne(out['application_date'].dt.year)).sum()),
        'invalid_operating_dates': int((out['status'].eq('operating') & ~valid_dates).sum()),
        'valid_operating_waits': int(out['valid_wait'].sum()),
        'invalid_capacity_values': invalid_capacity,
        'unclassified_capacity_components': unclassified_capacity,
        'missing_generation_capacity': int(out['generation_capacity_incomplete'].sum()),
        'missing_storage_capacity': int(out['storage_capacity_incomplete'].sum()),
    }
    return out, quality


def cohort_outcomes(data):
    """All statuses share the same cohort denominator, including unknowns."""
    counts = pd.crosstab(data['application_year'], data['status']).reindex(
        columns=STATUSES, fill_value=0)
    counts['projects'] = counts.sum(axis=1)
    for status in STATUSES:
        counts[f'{status}_share'] = counts[status] / counts['projects']
    return counts.reset_index()


def wait_times(data):
    return data.loc[data['valid_wait']].copy()


def capacity_totals(data):
    """Known component totals only; missing coverage is reported separately."""
    return {name: float(data[name].sum()) for name in ['generation_mw', 'storage_mw']}


def filter_projects(data, regions=None, technologies=None, years=None):
    result = data
    if regions is not None:
        result = result[result['region'].isin(regions)]
    if technologies is not None:
        result = result[result['technology'].isin(technologies)]
    if years is not None:
        result = result[result['application_year'].between(*years).fillna(False)]
    return result.copy()


def save_database(data, quality, metadata, path):
    """Replace all snapshot tables in a single transaction; close before UI use."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as con:
        con.register('normalized', data)
        con.execute('BEGIN')
        con.execute('CREATE OR REPLACE TABLE projects AS SELECT * FROM normalized')
        con.execute('CREATE OR REPLACE TABLE metadata (document JSON)')
        con.execute('INSERT INTO metadata VALUES (?)', [json.dumps(metadata)])
        con.execute('CREATE OR REPLACE TABLE quality (document JSON)')
        con.execute('INSERT INTO quality VALUES (?)', [json.dumps(quality)])
        con.execute('COMMIT')


def read_database(path):
    with duckdb.connect(str(path), read_only=True) as con:
        return (con.sql('SELECT * FROM projects').df(),
                json.loads(con.sql('SELECT document FROM quality').fetchone()[0]),
                json.loads(con.sql('SELECT document FROM metadata').fetchone()[0]))


def load_bundled():
    manifest = json.loads((DATA_DIR / 'manifest.json').read_text(encoding='utf-8'))
    source = DATA_DIR / 'public_queue.csv.gz'
    checksum = hashlib.sha256(gzip.decompress(source.read_bytes())).hexdigest()
    if checksum != manifest['csv_sha256']:
        raise ValueError('Bundled data checksum mismatch; restore the recorded CSV.')
    raw = pd.read_csv(source, dtype={'q_id': 'string'})
    data, quality = normalize(raw, manifest['snapshot_date'])
    return data, quality, manifest
