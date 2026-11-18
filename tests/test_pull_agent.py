import re

from pull_agent import catalog_pattern, normalize


def test_sorts_id_lists_and_drops_defaults():
    api = {"benchmarks": {"questions": [{"id": "b2", "question": ["y"]}, {"id": "b1", "question": ["x"]}]},
           "data_sources": {"tables": [{"identifier": "t", "column_configs": [
               {"column_name": "c", "enable_format_assistance": True, "enable_entity_matching": True}]}]}}
    n = normalize(api)
    assert [q["id"] for q in n["benchmarks"]["questions"]] == ["b1", "b2"]
    assert n["data_sources"]["tables"][0]["column_configs"][0] == {"column_name": "c", "enable_entity_matching": True}


def test_keeps_format_assistance_when_turned_off():
    n = normalize({"column_configs": [{"column_name": "c", "enable_format_assistance": False}]})
    assert n["column_configs"][0]["enable_format_assistance"] is False


def test_joins_instruction_text_split_into_lines():
    n = normalize({"instructions": {"text_instructions": [{"id": "c1", "content": ["line 1\n", "line 2\n"]}]}})
    assert n["instructions"]["text_instructions"][0]["content"] == ["line 1\nline 2\n"]


def test_catalog_pattern_handles_backticks():
    pattern = catalog_pattern("dev", "genie_sales")
    sql = "SELECT * FROM `dev`.`genie_sales`.`orders` JOIN dev.genie_sales.customers"
    assert re.sub(pattern, "${var.catalog}.${var.schema}.", sql) == \
        "SELECT * FROM ${var.catalog}.${var.schema}.`orders` JOIN ${var.catalog}.${var.schema}.customers"


def test_catalog_pattern_does_not_match_inside_longer_names():
    from pull_agent import catalog_pattern
    sql = "FROM dev.genie_sales.orders JOIN xdev.genie_sales.t JOIN `dev`.`genie_sales`.c"
    out = re.sub(catalog_pattern("dev", "genie_sales"), "${var.catalog}.${var.schema}.", sql)
    assert out == "FROM ${var.catalog}.${var.schema}.orders JOIN xdev.genie_sales.t JOIN ${var.catalog}.${var.schema}.c"


def test_sorts_tables_and_column_configs():
    n = normalize({"tables": [{"identifier": "c.s.orders"}, {"identifier": "c.s.customers"}],
                   "column_configs": [{"column_name": "region"}, {"column_name": "country"}]})
    assert [t["identifier"] for t in n["tables"]] == ["c.s.customers", "c.s.orders"]
    assert [c["column_name"] for c in n["column_configs"]] == ["country", "region"]
