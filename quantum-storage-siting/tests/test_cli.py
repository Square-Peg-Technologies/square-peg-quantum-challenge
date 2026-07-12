import sys
import os

# Allow importing main without triggering solver imports at module level
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch  # noqa: E402
from main import prompt_optimization, prompt_hours  # noqa: E402


def test_prompt_optimization_rejects_bad():
    with patch("builtins.input", side_effect=["0", "5", "a", "", "1"]):
        result = prompt_optimization()
    assert result == 1


def test_prompt_optimization_accepts_all():
    for val in ["1", "2", "3", "4"]:
        with patch("builtins.input", side_effect=[val]):
            result = prompt_optimization()
        assert result == int(val)


def test_prompt_hours_rejects_bad():
    with patch("builtins.input", side_effect=["abc", "1.5", "0", "25", "-1", "8"]):
        result = prompt_hours(24)
    assert result == 8


def test_prompt_hours_accepts_valid():
    for val, expected in [("1", 1), ("12", 12), ("24", 24)]:
        with patch("builtins.input", side_effect=[val]):
            result = prompt_hours(24)
        assert result == expected


def test_prompt_hours_respects_max_hours():
    # A case with a longer horizon (e.g. ieee14's 168h week) should accept
    # values beyond the old 24h cap, and still reject values past its own max.
    with patch("builtins.input", side_effect=["200", "168"]):
        result = prompt_hours(168)
    assert result == 168
