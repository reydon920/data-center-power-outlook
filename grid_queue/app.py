"""Local dashboard: python -m streamlit run app.py."""
import altair as alt
import duckdb
import pandas as pd
import streamlit as st

from grid_queue import (DATA_DIR, STATUSES, capacity_totals, cohort_outcomes,
                        filter_projects, load_bundled, read_database,
                        wait_times)

st.set_page_config(page_title='Grid Queue Reality Check', page_icon='⚡', layout='wide')
st.title('Grid Queue Reality Check')
st.caption('Grid Queue Reality Check')
st.write('Follow proposed power projects from application to operation, withdrawal, or continued waiting.')


@st.cache_data
def load_snapshot(source, modified):
    if source == 'Bundled public snapshot':
        data, quality, metadata = load_bundled()
        # An in-memory DuckDB roundtrip keeps startup read-only and session-safe.
        with duckdb.connect() as con:
            con.register('records', data)
            data = con.sql('SELECT * FROM records').df()
        return data, quality, metadata
    return read_database(DATA_DIR / 'queue.duckdb')


with st.sidebar:
    st.header('Explore requests')
    options = ['Bundled public snapshot']
    database = DATA_DIR / 'queue.duckdb'
    if database.exists():
        options.append('Local DuckDB snapshot')
    source = st.selectbox('Data source', options)

try:
    data, quality, metadata = load_snapshot(source, database.stat().st_mtime_ns if database.exists() else 0)
except (ValueError, OSError, KeyError, duckdb.Error) as error:
    st.error(f'Could not load the snapshot: {error}')
    st.info('Choose the bundled public snapshot, or rebuild the local file with python -m queue_pipeline build.')
    st.stop()

st.caption(f"{metadata['title']} · snapshot {metadata['snapshot_date']} · "
           f"{len(data):,} recorded requests · Lawrence Berkeley National Laboratory and GridTracker · CC BY 4.0")
st.info('These are generation and storage interconnection requests. They cannot establish when a data center will receive power.')

with st.sidebar:
    regions = st.multiselect('Region', sorted(data['region'].unique()))
    technologies = st.multiselect('Technology (exact hybrid label)', sorted(data['technology'].unique()))
    st.caption('No selections means all. A hybrid label is one request, not two projects.')
    restrict_year = st.checkbox('Filter application years', value=False)
    known_years = data['application_year'].dropna().astype(int)
    years = None
    if restrict_year and known_years.empty:
        st.warning('This snapshot has no known application years. Year filtering is unavailable.')
    elif restrict_year and known_years.min() == known_years.max():
        only_year = int(known_years.iloc[0])
        st.caption(f'Only application year {only_year} is available.')
        years = (only_year, only_year)
    elif restrict_year:
        years = st.slider('Application year', int(known_years.min()), int(known_years.max()),
                          (int(known_years.min()), int(known_years.max())))
    if years is not None:
        st.caption('Requests with an unknown application year are excluded by this filter.')

selected = filter_projects(data, regions or None, technologies or None, years)
if selected.empty:
    st.warning('No requests match these filters. Clear a filter to continue.')
    st.stop()

active = selected[selected['status'].eq('active')]
capacity = capacity_totals(active)
cols = st.columns(4)
cols[0].metric('Selected requests', f'{len(selected):,}')
cols[1].metric('Active requests', f'{len(active):,}')
cols[2].metric('Active generation · known GW', f"{capacity['generation_mw'] / 1000:,.1f}")
cols[3].metric('Active storage · known GW', f"{capacity['storage_mw'] / 1000:,.1f}")
st.caption('Capacity is reported MW ÷ 1,000. Missing component MW are not imputed; totals can understate capacity. Suspended requests are shown separately from active requests.')

backlog_tab, cohort_tab, wait_tab, source_tab = st.tabs(
    ['Active backlog', 'Cohort outcomes', 'Completed wait times', 'Data & quality'])

with backlog_tab:
    st.subheader('Where requests are still waiting')
    if active.empty:
        st.write('No active requests in this selection.')
    else:
        by_region = active.groupby('region').size().rename('Active requests').reset_index()
        st.bar_chart(by_region, x='region', y='Active requests', color='#287C8E')
        grouped = active.groupby('region').agg(
            requests=('project_id', 'size'), generation_mw=('generation_mw', 'sum'),
            storage_mw=('storage_mw', 'sum'))
        st.dataframe(grouped, width='stretch')
    status_counts = selected['status'].value_counts().reindex(STATUSES, fill_value=0)
    st.write('All selected outcomes')
    st.dataframe(status_counts.rename('Requests'), width='stretch')

with cohort_tab:
    st.subheader('What happened to each application cohort?')
    st.write('Shares use every request with a known application year in that cohort. Recent cohorts have had less time to reach operation; an active request is not a failure.')
    cohorts = cohort_outcomes(selected)
    if cohorts.empty:
        st.write('No known application years in this selection.')
    else:
        long = cohorts.melt(id_vars=['application_year', 'projects'],
                            value_vars=[s + '_share' for s in STATUSES],
                            var_name='Outcome', value_name='Share')
        long['Outcome'] = long['Outcome'].str.removesuffix('_share')
        chart = alt.Chart(long).mark_bar().encode(
            x=alt.X('application_year:O', title='Application year'),
            y=alt.Y('Share:Q', axis=alt.Axis(format='%'), title='Share of cohort requests'),
            color=alt.Color('Outcome:N', sort=STATUSES),
            tooltip=['application_year:O', 'Outcome:N', alt.Tooltip('Share:Q', format='.1%'), 'projects:Q'])
        st.altair_chart(chart, width='stretch')
        st.dataframe(cohorts, width='stretch')
    st.caption(f"Unknown application year in this selection: {selected['application_year'].isna().sum():,} requests; omitted from cohort chart.")

with wait_tab:
    st.subheader('Observed waits for completed projects')
    completed = selected[selected['status'].eq('operating')]
    waits = wait_times(selected)
    st.write(f'{len(waits):,} of {len(completed):,} operating requests have valid application and actual operating dates. Missing, reversed, and post-snapshot dates are excluded. Proposed online dates are never used.')
    if waits.empty:
        st.write('No valid completed waits in this selection.')
    else:
        st.metric('Median completed wait · years', f"{waits['wait_years'].median():.2f}")
        waits['operating_year'] = waits['operating_date'].dt.year
        annual = waits.groupby('operating_year').agg(
            median_years=('wait_years', 'median'), sample_count=('project_id', 'size')).reset_index()
        st.line_chart(annual, x='operating_year', y='median_years', color='#287C8E')
        st.caption('X: actual operating year. Y: median years from application to operation. Only observed completions are included; this is not a forecast for today’s queue.')
        st.dataframe(annual, width='stretch')

with source_tab:
    st.write('Source: [Berkeley Lab Queued Up](https://emp.lbl.gov/queues/). Data file copyright © 2026 The Regents of the University of California, through Lawrence Berkeley National Laboratory, and GridTracker. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Code is MIT licensed.')
    st.write('One source row is one request record. Duplicate provider/queue IDs are retained with a source-row suffix; they are not assumed to represent independent physical plants. Technology filters use complete labels, including hybrids. These row counts can differ from report-level project counts and are not plant delivery probabilities.')
    st.write('Full-snapshot quality counts (before dashboard filters)')
    st.dataframe(pd.Series(quality, name='Count').rename_axis('Check'), width='stretch')
    st.json(metadata, expanded=False)
    st.caption('For the bundled workbook, the ERCOT active summary count is 269 lower than the raw-record count; the reason is unresolved here. See docs/findings.md and data/reconciliation.json. This recorded comparison does not validate a different local import. Headline storage totals also include estimates absent from the public project records.')

with st.expander('Inspect and export selected requests'):
    st.dataframe(selected, width='stretch', hide_index=True)
    st.download_button('Download filtered CSV', selected.to_csv(index=False),
                       'grid-queue-selection.csv', 'text/csv')
