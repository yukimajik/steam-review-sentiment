import pytest

from app.sentiment import label_for, score


@pytest.mark.parametrize("compound, label", [
    (0.05, "positive"),    # exactly on the threshold counts as positive
    (0.0499, "neutral"),
    (0.0, "neutral"),
    (-0.0499, "neutral"),
    (-0.05, "negative"),   # exactly on the threshold counts as negative
])
def test_label_thresholds(compound, label):
    assert label_for(compound) == label


def test_bbcode_tags_are_ignored():
    assert score("[b]great[/b]") == score("great")
    assert score("[url=https://example.com]great[/url]") == score("great")


def test_censored_profanity_does_not_count_as_positive():
    # VADER alone scores "this game is ♥♥♥♥" around +0.96
    assert score("this game is ♥♥♥♥") == (0.0, "neutral")


def test_scores_obvious_sentiment():
    assert score("I love this game, it's amazing")[1] == "positive"
    assert score("Terrible. Broken and boring.")[1] == "negative"
