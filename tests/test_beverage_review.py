"""Independent regression cases for beverage evidence and completeness."""
import csv
import gzip
import json

import pytest

from rappi_co.parsers.beverage_search import replay_search


def _archive(tmp_path, responses, *, currency="COP", csv_ids=None):
    source = tmp_path / "search_items_20260101_010203.csv"
    raw = tmp_path / "search_raw_20260101_010203"
    raw.mkdir()
    keys = set()
    terms = []
    records = []
    for index, products in enumerate(responses):
        term = f"query {index}"
        terms.append(term)
        filename = f"{index:03}.json.gz"
        with gzip.open(raw / filename, "wt", encoding="utf-8") as handle:
            json.dump({"stores": [{"store_id": "s1", "products": products}]}, handle)
        records.append({"query": term, "raw_file": filename})
        for product in products:
            keys.add(("s1", str(product.get("product_id") or product.get("id")).split("_")[-1]))
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["store_id", "product_id", "country_code"])
        writer.writeheader()
        for sid, pid in sorted(csv_ids if csv_ids is not None else keys):
            writer.writerow({"store_id": sid, "product_id": pid, "country_code": "co"})
    manifest = {"complete": True, "items": source.name, "queries": terms,
                "term_results": records, "raw_directory": raw.name,
                "currency": currency, "n_items": len(keys),
                "search_url": "https://example.com/search"}
    source.with_name("search_manifest_20260101_010203.json").write_text(json.dumps(manifest))
    return source


def _product(**values):
    return {"product_id": "p1", "name": "Agua 500 ml", "price": 100,
            "unit_type": "ml", "quantity": 500, "presentation": "1 x 500 ml", **values}


def test_replay_preserves_full_source_evidence_and_explicit_stock(tmp_path):
    description = "x" * 1200 + " Azúcares 10 g por 100 ml"
    product = _product(description=description, is_available=False, in_stock=True,
                       attributes={"sugar_g_per_100ml": 10}, url="https://example.com/product")
    source = _archive(tmp_path, [[product]])
    rows, coverage = replay_search(source)
    row = rows[0]
    assert row["short_description"] == description
    assert row["unit_type"] == "ml" and row["quantity"] == 500
    assert row["availability"] == "out_of_stock"
    assert json.loads(row["source_product_json"]) == product
    assert json.loads(row["attributes_json"]) == product["attributes"]
    assert row["product_url"] == "https://example.com/product"
    assert coverage[0]["raw_rows"] == coverage[0]["usable_rows"] == 1
    assert coverage[0]["catalog_coverage_complete"] is False


@pytest.mark.parametrize("flags, expected", [
    ({}, "unknown"),
    ({"is_available": "false"}, "out_of_stock"),
    ({"is_available": True, "is_possible_stockout": True}, "possibly_out_of_stock"),
    ({"is_available": True}, "in_stock"),
    ({"in_stock": False}, "out_of_stock"),
])
def test_replay_does_not_invent_stock_status(tmp_path, flags, expected):
    source = _archive(tmp_path, [[_product(**flags)]])
    assert replay_search(source)[0][0]["availability"] == expected


def test_replay_keeps_first_offer_and_reports_disagreement(tmp_path):
    source = _archive(tmp_path, [[_product(price=100)], [_product(price=90)]], currency="MXN")
    rows, coverage = replay_search(source)
    assert len(rows) == 1
    assert rows[0]["price_local"] == 100
    assert rows[0]["price_cop"] is None
    assert rows[0]["source_terms"] == "query 0|query 1"
    assert len(rows[0]["source_evidence_paths"].split("|")) == 2
    assert rows[0]["source_conflict"] is True
    assert json.loads(rows[0]["source_conflicts_json"])[0]["fields"]["price_local"] == {
        "first": 100, "later": 90}
    assert coverage[1]["duplicate_rows"] == 1
    assert coverage[1]["new_items"] == 0


def test_replay_fails_on_normalized_id_collision(tmp_path):
    source = _archive(tmp_path, [[_product(product_id="offer_a"), _product(product_id="different_a")]])
    with pytest.raises(ValueError, match="normalized product key collision"):
        replay_search(source)


def test_replay_reports_capped_groups_without_claiming_completeness(tmp_path):
    source = _archive(tmp_path, [[_product(product_id=str(i)) for i in range(26)]])
    rows, coverage = replay_search(source)
    assert len(rows) == 26
    assert coverage[0]["capped_store_groups"] == 1
    assert coverage[0]["max_group_products"] == 26
    assert coverage[0]["catalog_coverage_complete"] is False


def test_replay_rejects_csv_archive_key_mismatch(tmp_path):
    source = _archive(tmp_path, [[_product()]], csv_ids={("s1", "another")})
    with pytest.raises(ValueError, match="do not match the exact source CSV"):
        replay_search(source)


def test_replay_rejects_incomplete_manifest(tmp_path):
    source = _archive(tmp_path, [[_product()]])
    manifest = source.with_name("search_manifest_20260101_010203.json")
    obj = json.loads(manifest.read_text())
    obj["complete"] = False
    manifest.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="complete search manifest"):
        replay_search(source)


def test_replay_rejects_archive_path_escape(tmp_path):
    source = _archive(tmp_path, [[_product()]])
    manifest = source.with_name("search_manifest_20260101_010203.json")
    obj = json.loads(manifest.read_text())
    obj["term_results"][0]["raw_file"] = "../../outside.json.gz"
    manifest.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="escapes its directory"):
        replay_search(source)
