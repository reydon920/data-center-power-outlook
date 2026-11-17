from streamlit.testing.v1 import AppTest
import pandas as pd
import pytest


def test_dashboard_loads_offline_and_filters():
    app = AppTest.from_file('app.py', default_timeout=30).run()
    assert not app.exception
    assert app.metric[0].value == '38,201'
    assert len(app.tabs) == 4
    app.sidebar.multiselect[0].set_value(['CAISO']).run()
    assert not app.exception
    assert app.metric[0].value == '2,868'
    app.sidebar.checkbox[0].check().run()
    assert not app.exception
    assert app.sidebar.slider[0].value[1] == 2025


def test_dashboard_empty_selection_explains_next_step():
    app = AppTest.from_file('app.py', default_timeout=30).run()
    app.sidebar.multiselect[0].set_value(['CAISO'])
    app.sidebar.multiselect[1].set_value(['Coal']).run()
    assert not app.exception
    assert app.warning


def test_dashboard_unreadable_database_explains_recovery(monkeypatch, scratch_dir):
    import grid_queue
    import streamlit as st

    snapshot = grid_queue.load_bundled()
    (scratch_dir / 'queue.duckdb').write_bytes(b'not a database')
    monkeypatch.setattr(grid_queue, 'DATA_DIR', scratch_dir)
    monkeypatch.setattr(grid_queue, 'load_bundled', lambda: snapshot)
    st.cache_data.clear()
    try:
        app = AppTest.from_file('app.py', default_timeout=30).run()
        app.sidebar.selectbox[0].set_value('Local DuckDB snapshot').run()
        assert not app.exception
        assert 'Could not load the snapshot' in app.error[0].value
        assert 'rebuild' in app.info[0].value
    finally:
        st.cache_data.clear()


@pytest.mark.parametrize('year', [2020, None])
def test_dashboard_year_filter_handles_sparse_imports(monkeypatch, year):
    import grid_queue
    import streamlit as st
    data, quality, metadata = grid_queue.load_bundled()
    data = data.iloc[:2].copy()
    data['application_year'] = pd.Series([year, year], dtype='Int64')
    monkeypatch.setattr(grid_queue, 'load_bundled', lambda: (data, quality, metadata))
    st.cache_data.clear()
    try:
        app = AppTest.from_file('app.py', default_timeout=30).run()
        app.sidebar.checkbox[0].check().run()
        assert not app.exception
        assert app.metric[0].value == '2'
        assert not app.sidebar.slider
        if year is None:
            assert any('no known application years' in item.value for item in app.warning)
    finally:
        st.cache_data.clear()
