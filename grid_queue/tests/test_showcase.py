from pathlib import Path

from PIL import Image


def test_showcase_generates_readable_pngs_offline(scratch_dir):
    from showcase import generate_showcase

    paths = generate_showcase(scratch_dir)
    assert len(paths) == 3
    for path in paths:
        with Image.open(path) as picture:
            assert picture.format == 'PNG'
            assert picture.width >= 1000
            assert picture.height >= 700
            assert len(picture.convert('RGB').getcolors(picture.width * picture.height)) > 20


def test_bundled_extract_is_small_and_complete():
    from grid_queue import load_bundled

    assert Path('data/public_queue.csv.gz').stat().st_size < 1_000_000
    data, quality, metadata = load_bundled()
    assert len(data) == metadata['source_rows'] == quality['retained_rows']
