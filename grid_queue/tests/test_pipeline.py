import json
from pathlib import Path

import pandas as pd
import pytest

from grid_queue import load_bundled, normalize, filter_projects, read_database
from queue_pipeline import build_snapshot, reconcile_workbook, extract_workbook, EXTRACT_FIELDS


def test_recorded_snapshot_integrity_and_counts():
    data, quality, manifest = load_bundled()
    assert len(data) == manifest['source_rows'] == 38201
    assert data['project_id'].is_unique
    assert data['status'].value_counts().to_dict() == {
        'withdrawn': 24221, 'active': 8513, 'operating': 4789, 'suspended': 668, 'unknown': 10}
    assert quality['missing_identifiers'] == 1
    assert quality['valid_operating_waits'] > 0


def test_build_persists_matching_snapshot(scratch_dir):
    path = scratch_dir / 'queue.duckdb'
    summary = build_snapshot(path)
    data, quality, manifest = read_database(path)
    assert len(data) == summary['requests'] == 38201
    assert quality['source_rows'] == len(data)
    assert manifest['snapshot_date'] == '2025-12-31'


def test_filters_apply_jointly_and_missing_year_is_not_zero():
    data, _, _ = load_bundled()
    result = filter_projects(data, ['CAISO'], ['Solar+Battery'], [2020, 2025])
    assert not result.empty
    assert result['region'].eq('CAISO').all()
    assert result['technology'].eq('Solar+Battery').all()
    assert result['application_year'].between(2020, 2025).all()
    assert filter_projects(data, regions=[]).empty


def test_recorded_reconciliation_matches_summary():
    recorded = json.loads(Path('data/reconciliation.json').read_text())
    data, _, _ = load_bundled()
    for row in recorded['checks']:
        actual = len(data[(data.region == row['region']) & (data.status == row['status'])])
        assert actual == row['raw_count']
        assert actual - row['summary_count'] == row['difference']
    assert recorded['mismatches'] == 1


def test_workbook_ingestion_and_summary_reconciliation(scratch_dir):
    # A miniature workbook exercises the real Excel parser, without a live download.
    raw = pd.read_csv('data/public_queue.csv.gz', nrows=3)
    workbook = scratch_dir / 'fixture.xlsx'
    codebook = pd.read_csv('data/codebook.csv')
    summary = pd.DataFrame([
        ['RETURN TO CONTENTS', None, None, None, None, None, None],
        ['Summary', None, None, None, None, None, None],
        [None, 'Active Requests', None, 'Operational Plants', None, 'Withdrawn Requests', None],
        ['Region', 'n', 'Capacity', 'n', 'Capacity', 'n', 'Capacity'],
        ['West (non-ISO)', 0, 0, 1, .024, 2, .920],
    ])
    with pd.ExcelWriter(workbook) as writer:
        raw.to_excel(writer, sheet_name='03. Complete Queue Data', startrow=1, index=False)
        codebook.to_excel(writer, sheet_name='04. Data Codebook', startrow=1, index=False)
        summary.to_excel(writer, sheet_name='02. Data Sample by Region', header=False, index=False)
    with pytest.raises(ValueError, match='Unrecognized workbook checksum'):
        build_snapshot(scratch_dir / 'reject.duckdb', workbook)
    report = reconcile_workbook(workbook, snapshot='2025-12-31')
    assert report['mismatches'] == 0
    path = scratch_dir / 'import.duckdb'
    assert build_snapshot(path, workbook, snapshot='2025-12-31')['requests'] == 3
    _, _, metadata = read_database(path)
    assert 'unverified' in metadata['title']
    output = scratch_dir / 'extract'
    manifest = extract_workbook(workbook, output, snapshot='2025-12-31')
    recorded = pd.read_csv(output / 'public_queue.csv')
    assert recorded.columns.tolist() == EXTRACT_FIELDS
    assert len(recorded) == manifest['source_rows'] == 3
    assert normalize(recorded)[0]['status'].value_counts().to_dict() == {'withdrawn': 2, 'operating': 1}
    import hashlib
    assert hashlib.sha256((output / 'public_queue.csv').read_bytes()).hexdigest() == manifest['csv_sha256']
    assert (output / 'codebook.csv').exists()
    with pytest.raises(ValueError, match='new or empty'):
        extract_workbook(workbook, output, snapshot='2025-12-31')


def test_partial_generation_capacity_keeps_known_component():
    raw = pd.read_csv('data/public_queue.csv.gz', nrows=1)
    raw['type_1'] = 'Solar'
    raw['type_2'] = 'Wind'
    raw['mw_1'] = 20
    raw['mw_2'] = float('nan')
    data, quality = normalize(raw)
    assert data.iloc[0]['generation_mw'] == 20
    assert quality['missing_generation_capacity'] == 1


def test_failed_download_preserves_previous_file(scratch_dir, monkeypatch):
    import io
    import queue_pipeline
    previous = scratch_dir / 'source.xlsx'
    previous.write_bytes(b'previous recorded workbook')
    monkeypatch.setattr(queue_pipeline, 'urlopen', lambda *a, **k: io.BytesIO(b'not an Excel workbook'))
    with pytest.raises(ValueError, match='Download failed'):
        queue_pipeline.download_workbook(previous)
    assert previous.read_bytes() == b'previous recorded workbook'
    assert not previous.with_suffix('.download.xlsx').exists()


def test_cli_build_and_summary_launch_with_project_python(scratch_dir):
    """Exercise actual process launches, as the publishing pipeline does."""
    import subprocess
    import sys

    database = scratch_dir / 'cli.duckdb'
    reports = []
    for command in ('build', 'summary'):
        result = subprocess.run(
            [sys.executable, '-m', 'queue_pipeline', command,
             '--database', str(database)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        reports.append(json.loads(result.stdout))
    assert reports[0] == reports[1]
    assert reports[0]['requests'] == 38201
    assert reports[0]['snapshot_date'] == '2025-12-31'
