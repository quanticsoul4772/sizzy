"""Tests for jqlite.output — the pretty and compact serializers.

Both forms must be byte-for-byte deterministic, preserve object key order
(never sort), echo unicode faithfully, and end each result with a newline.
"""

import json

import pytest

from jqlite.output import dump, dump_compact, dump_pretty


def test_pretty_is_two_space_indented():
    assert dump_pretty({"a": 1, "b": 2}) == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_pretty_nested_indentation():
    assert dump_pretty({"outer": {"inner": [1, 2]}}) == (
        "{\n"
        '  "outer": {\n'
        '    "inner": [\n'
        "      1,\n"
        "      2\n"
        "    ]\n"
        "  }\n"
        "}\n"
    )


def test_compact_is_single_line():
    out = dump_compact({"a": 1, "b": [2, 3]})
    assert out == '{"a":1,"b":[2,3]}\n'
    # exactly one newline, at the very end
    assert out.count("\n") == 1
    assert out.endswith("\n")


def test_compact_has_no_separator_spaces():
    out = dump_compact({"a": 1, "b": 2})
    assert out == '{"a":1,"b":2}\n'
    assert " " not in out


def test_compact_nested_single_line():
    out = dump_compact({"outer": {"inner": [1, 2]}})
    assert out == '{"outer":{"inner":[1,2]}}\n'
    assert out.count("\n") == 1


@pytest.mark.parametrize(
    "value",
    [
        {"b": 1, "a": 2},
        [1, 2, 3],
        "hello",
        42,
        3.5,
        True,
        False,
        None,
        {},
        [],
        {"nested": {"x": [1, {"y": 2}]}},
    ],
)
def test_both_forms_roundtrip(value):
    assert json.loads(dump_pretty(value)) == value
    assert json.loads(dump_compact(value)) == value


@pytest.mark.parametrize("value", [{"b": 1, "a": 2}, [1, 2, 3], "hi", 42, None])
def test_both_forms_deterministic(value):
    assert dump_pretty(value) == dump_pretty(value)
    assert dump_compact(value) == dump_compact(value)


def test_compact_preserves_key_order():
    # Keys are never sorted: order is the dict's insertion order.
    assert dump_compact({"z": 1, "a": 2}) == '{"z":1,"a":2}\n'


def test_pretty_preserves_key_order():
    assert dump_pretty({"z": 1, "a": 2}) == '{\n  "z": 1,\n  "a": 2\n}\n'


def test_unicode_preserved_both_forms():
    assert dump_pretty("caf\u00e9 \u2615") == "\"caf\u00e9 \u2615\"\n"
    assert dump_compact("caf\u00e9 \u2615") == "\"caf\u00e9 \u2615\"\n"


def test_dump_dispatch_defaults_to_pretty():
    value = {"a": 1, "b": 2}
    assert dump(value) == dump_pretty(value)
    assert dump(value, compact=False) == dump_pretty(value)


def test_dump_dispatch_compact():
    value = {"a": 1, "b": 2}
    assert dump(value, compact=True) == dump_compact(value)


def test_each_result_terminated_by_newline():
    for value in ({"a": 1}, [1, 2], "x", 5, None):
        assert dump_pretty(value).endswith("\n")
        assert dump_compact(value).endswith("\n")
