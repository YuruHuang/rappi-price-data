import copy

import pytest

from rappi_co.qc.beverage_coverage import country_report


def inputs():
    plan = {"country_code": "mx", "country": "Mexico", "city": "Mexico City", "currency": "MXN",
            "full_protocol": True, "queries": ["agua", "refresco"], "addresses": [
                {"slug": "centro", "address": "Test location", "lat": 1, "lng": 2}]}
    rows = [{"country_code": "mx", "zone_slug": "centro", "store_id": "10", "product_id": "20",
             "beverage_category": "review", "beverage_subcategory": "soft_drink",
             "sugar_g_per_100ml": "", "abv_pct": "nan", "total_volume_ml": "500"}]
    queries = [{"country_code": "mx", "zone_slug": "centro", "query": term, "new_items": new,
                "raw_rows": 20, "store_groups": 1, "group_sizes_json": "[20]", "skipped_rows": 0}
               for term, new in [("agua", 1), ("refresco", 0)]]
    return plan, rows, queries, copy.deepcopy(rows)


def test_country_specific_upper_tail_and_missing_sugar_are_explicit():
    report = country_report(*inputs())
    assert report["observed_maximum_group_size"] == 20
    assert report["groups_at_observed_maximum"] == 2
    assert report["historical_groups_at_least_25"] == 0
    assert report["quantitative_field_coverage"]["ssb_candidates"] == {
        "observations": 1, "volume_per_unit_ml_present": 0, "pack_count_present": 0,
        "total_volume_ml_present": 1, "sugar_g_per_100ml_present": 0,
        "sugar_g_per_serving_present": 0, "serving_volume_ml_present": 0, "abv_pct_present": 0}


@pytest.mark.parametrize("mutation,reason", [
    (lambda p, r, q, c: r.append(dict(r[0])), "duplicate"),
    (lambda p, r, q, c: q.reverse(), "planned order"),
    (lambda p, r, q, c: q[0].update(new_items=2), "reconcile"),
    (lambda p, r, q, c: q[0].update(group_sizes_json="[19]"), "group sizes"),
    (lambda p, r, q, c: c[0].update(product_id="unknown"), "unique subset"),
    (lambda p, r, q, c: c.clear(), "exact eligible"),
    (lambda p, r, q, c: c[0].update(sugar_g_per_100ml="0"), "quantitative fields"),
    (lambda p, r, q, c: r[0].update(country_code="ar"), "out-of-scope"),
])
def test_mismatched_release_evidence_fails(mutation, reason):
    args = inputs()
    mutation(*args)
    with pytest.raises(ValueError, match=reason):
        country_report(*args)
