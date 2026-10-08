from app.scan_fields import SCAN_FIELDS, SCAN_FIELDS_BY_KEY, ScanFilter, apply_filters


def test_registry_keys_are_unique_and_indexed():
    keys = [f.key for f in SCAN_FIELDS]
    assert len(keys) == len(set(keys))
    assert set(SCAN_FIELDS_BY_KEY) == set(keys)


def test_apply_filters_no_filters_is_identity():
    rows = [{"price": 10}, {"price": 20}]
    assert apply_filters(rows, []) == rows


def test_apply_filters_min_and_max():
    rows = [{"pe_ratio": 5}, {"pe_ratio": 15}, {"pe_ratio": 25}]
    out = apply_filters(rows, [ScanFilter(field="pe_ratio", min=10, max=20)])
    assert out == [{"pe_ratio": 15}]


def test_apply_filters_excludes_rows_missing_the_field():
    rows = [{"pe_ratio": 15}, {"other": 1}]
    out = apply_filters(rows, [ScanFilter(field="pe_ratio", min=0)])
    assert out == [{"pe_ratio": 15}]


def test_apply_filters_combines_multiple_filters_with_and():
    rows = [{"pe_ratio": 15, "beta": 0.5}, {"pe_ratio": 15, "beta": 2.0}]
    out = apply_filters(rows, [ScanFilter(field="pe_ratio", min=10), ScanFilter(field="beta", min=1.0)])
    assert out == [{"pe_ratio": 15, "beta": 2.0}]
