"""Tests of the two content hashes.

Two tests compare a hash with a fixed value. Hashes made by these
functions are stored, so a change that alters the result would make
stored hashes stop matching their content.
"""

from bugflow.shared.domain.values.digest import content_hash, digest_rows


def test_rows_hash_to_a_fixed_value() -> None:
    assert digest_rows([("a", "1"), ("", "no id")]) == "5b7aa52a8dfe9752"


def test_no_rows_hash_to_the_hash_of_nothing() -> None:
    assert digest_rows([]) == "e3b0c44298fc1c14"


def test_the_order_of_rows_does_not_change_the_hash() -> None:
    rows = [("b", "2"), ("a", "1")]
    assert digest_rows(rows) == digest_rows(reversed(rows))


def test_moving_a_character_to_the_next_field_changes_the_hash() -> None:
    assert digest_rows([("ab", "c")]) != digest_rows([("a", "bc")])


def test_a_json_value_hashes_to_a_fixed_value() -> None:
    assert content_hash({"b": [1, None], "a": "é"}) == (
        "9b10bedce64e86a275540261fbe95bc6c195bfb10d5def7a5fc12eefcc7d0a87"
    )


def test_the_order_of_keys_does_not_change_the_hash() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
