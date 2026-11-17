import pandas as pd
import pytest

from grid_queue import normalize, cohort_outcomes, wait_times, capacity_totals, save_database


@pytest.fixture
def raw():
    # Synthetic edge cases only; the dashboard uses recorded public data.
    return pd.DataFrame([
        dict(q_id='A', entity='ISO', region='West', q_status='operational', q_year=2020,
             q_date='2020-01-01', on_date='2022-01-01', type_clean='Solar+Battery',
             type_1='Solar', type_2='Battery', mw_1=100, mw_2=40),
        dict(q_id='B', entity='ISO', region='West', q_status='withdrawn', q_year=2020,
             q_date='2020-06-01', on_date=None, type_clean='Wind', type_1='Wind', mw_1=50),
        dict(q_id='C', entity='ISO', region='West', q_status='active', q_year=2020,
             q_date='2020-06-01', on_date='2030-01-01', type_clean='Solar', type_1='Solar', mw_1=60),
        dict(q_id='D', entity='ISO', region='East', q_status='suspended', q_year=2020,
             q_date='2020-01-01', on_date=None, type_clean='Battery', type_1='Battery', mw_1=20),
        dict(q_id='E', entity='ISO', region='East', q_status='operational', q_year=2021,
             q_date='2021-01-01', on_date='2020-01-01', type_clean='Wind', type_1='Wind', mw_1=-1),
    ])


def test_outcomes_keep_waiting_and_unknown_in_denominator(raw):
    data, _ = normalize(raw)
    cohort = cohort_outcomes(data).set_index('application_year').loc[2020]
    assert cohort['projects'] == 4
    assert cohort['operating_share'] == .25
    assert cohort['withdrawn_share'] == .25
    assert cohort['active_share'] == .25
    assert cohort['suspended_share'] == .25


def test_waits_only_use_completed_valid_actual_dates(raw):
    data, quality = normalize(raw)
    waits = wait_times(data)
    assert len(waits) == 1
    assert waits.iloc[0]['wait_years'] == pytest.approx(731 / 365.25)
    assert quality['invalid_operating_dates'] == 1


def test_hybrid_is_one_request_with_separate_capacity(raw):
    data, _ = normalize(raw)
    assert len(data) == 5
    totals = capacity_totals(data)
    assert totals['generation_mw'] == 210
    assert totals['storage_mw'] == 60


def test_duplicate_identifiers_and_missing_identifiers_are_reported(raw):
    duplicate = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    data, quality = normalize(duplicate)
    assert len(data) == 6
    assert quality['exact_duplicate_rows'] == 1
    conflicting = raw.copy()
    conflicting.loc[1, 'q_id'] = 'A'
    data, quality = normalize(conflicting)
    assert len(data) == 5
    assert quality['duplicate_identifier_rows'] == 2
    assert data['project_id'].is_unique
    raw.loc[0, 'q_id'] = None
    data, quality = normalize(raw)
    assert len(data) == 5
    assert quality['missing_identifiers'] == 1


def test_identifier_pairs_cannot_collide_with_separators_or_row_suffixes(raw):
    raw.loc[0, ['entity', 'q_id']] = ['ISO:West', 'A']
    raw.loc[1, ['entity', 'q_id']] = ['ISO', 'West:A']
    raw.loc[2, ['entity', 'q_id']] = ['ISO:West', 'A']
    raw.loc[3, ['entity', 'q_id']] = ['ISO:West', 'A:row-3']
    raw.loc[4, ['entity', 'q_id']] = ['', None]
    data, quality = normalize(raw)
    assert data['project_id'].is_unique
    assert quality['duplicate_identifier_rows'] == 2
    assert quality['missing_identifiers'] == 1
    assert data.iloc[4]['entity'] == 'Unknown'


def test_storage_missing_is_not_a_silent_zero(raw):
    raw.loc[0, 'mw_2'] = None
    data, quality = normalize(raw)
    assert pd.isna(data.iloc[0]['storage_mw'])
    assert quality['missing_storage_capacity'] == 1


def test_empty_metrics(raw):
    data, _ = normalize(raw)
    empty = data.iloc[:0]
    assert cohort_outcomes(empty).empty
    assert wait_times(empty).empty
    assert capacity_totals(empty) == {'generation_mw': 0.0, 'storage_mw': 0.0}


def test_database_roundtrip(raw, scratch_dir):
    import duckdb
    data, quality = normalize(raw)
    target = scratch_dir / 'queue.duckdb'
    save_database(data, quality, {'snapshot_date': '2025-12-31'}, target)
    with duckdb.connect(str(target), read_only=True) as con:
        assert con.sql('select count(*) from projects').fetchone()[0] == 5
        assert con.sql('select count(*) from metadata').fetchone()[0] == 1


def test_future_and_missing_dates_are_excluded(raw):
    raw.loc[0, 'on_date'] = '2026-01-01'
    raw.loc[4, 'on_date'] = None
    data, quality = normalize(raw)
    assert wait_times(data).empty
    assert quality['invalid_operating_dates'] == 2


def test_schema_change_fails_loudly(raw):
    with pytest.raises(ValueError, match='Missing required'):
        normalize(raw.drop(columns='q_status'))


def test_unknown_status_and_missing_year_remain_visible(raw):
    raw.loc[0, 'q_status'] = 'new publisher status'
    raw.loc[1, 'q_year'] = float('nan')
    data, quality = normalize(raw)
    assert data.iloc[0]['status'] == 'unknown'
    assert quality['unknown_statuses'] == 1
    assert quality['missing_application_year'] == 1
    assert cohort_outcomes(data)['projects'].sum() == 4
    cohort = cohort_outcomes(data).set_index('application_year').loc[2020]
    assert cohort['projects'] == 3
    assert cohort['unknown_share'] == pytest.approx(1 / 3)
    assert sum(cohort[f'{status}_share'] for status in
               ['active', 'operating', 'withdrawn', 'suspended', 'unknown']) == pytest.approx(1)


def test_three_component_hybrid_and_storage_first(raw):
    raw['type_3'] = None
    raw['mw_3'] = float('nan')
    raw.loc[0, ['type_1', 'type_2', 'type_3']] = ['Battery', 'Solar', 'Wind']
    raw.loc[0, ['mw_1', 'mw_2', 'mw_3']] = [40, 100, 25]
    data, _ = normalize(raw)
    assert data.iloc[0]['storage_mw'] == 40
    assert data.iloc[0]['generation_mw'] == 125
    assert len(data) == 5


def test_unrecognized_resource_type_is_not_assumed_to_be_generation(raw):
    raw.loc[0, 'type_1'] = 'new storage technology'
    data, quality = normalize(raw)
    assert data.iloc[0]['generation_mw'] == 0
    assert data.iloc[0]['storage_mw'] == 40
    assert quality['unclassified_capacity_components'] == 1


@pytest.mark.parametrize('capacity', [float('inf'), float('-inf'), 'not a number'])
def test_invalid_capacity_is_flagged_and_excluded(raw, capacity):
    raw['mw_1'] = raw['mw_1'].astype(object)
    raw.loc[0, 'mw_1'] = capacity
    data, quality = normalize(raw)
    assert pd.isna(data.iloc[0]['generation_mw'])
    assert quality['invalid_capacity_values'] == 2  # Includes the existing negative MW.
    assert capacity_totals(data)['generation_mw'] == 110
