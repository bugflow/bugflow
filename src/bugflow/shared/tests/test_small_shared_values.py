"""Tests of the acknowledgement and of converting a cost to nanodollars."""

from bugflow.shared.domain.models.call_record import nanodollars
from bugflow.shared.domain.values.acknowledgement import Acknowledgement


def test_wilco_will_comply() -> None:
    assert Acknowledgement.wilco().will_comply is True


def test_unable_will_not_and_says_why() -> None:
    answer = Acknowledgement.unable("nothing was waiting")

    assert answer.will_comply is False
    assert answer.info == ("nothing was waiting",)


def test_roger_makes_no_promise() -> None:
    assert Acknowledgement.roger().will_comply is None


def test_a_cost_in_dollars_becomes_whole_nanodollars() -> None:
    assert nanodollars("0.0000006") == 600
    assert nanodollars("1") == 1_000_000_000
    assert nanodollars("0") == 0


def test_a_cost_that_is_missing_or_not_a_number_is_none() -> None:
    assert nanodollars(None) is None
    assert nanodollars("free") is None
