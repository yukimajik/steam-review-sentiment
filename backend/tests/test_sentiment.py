"""The trained sentiment classifier (backend/app/sentiment_model.pkl)."""

import pytest

from app.sentiment import label_for, model, score, score_many


def test_model_file_loads_and_has_a_neutral_band():
    m = model()
    low, high = m["neutral_band"]
    assert 0 < low < 0.5 < high < 1
    assert m["reviews"] > 0 and m["games"] > 0


def test_labels_follow_the_neutral_band():
    low, high = model()["neutral_band"]  # in P(Recommended); scores are 2P − 1
    assert label_for(2 * high - 1) == "positive"   # the edge of the band counts as confident
    assert label_for(2 * low - 1) == "negative"
    assert label_for(0.0) == "neutral"             # P = 0.5: no lean either way


@pytest.mark.parametrize("text", ["", "   ", "👍👍👍"])
def test_texts_with_no_known_words_are_neutral(text):
    # The model would otherwise fall back to its built-in lean toward Recommended
    assert score(text) == (0.0, "neutral")


def test_bbcode_tags_are_ignored():
    assert score("[b]great[/b]") == score("great")
    assert score("[url=https://example.com]great[/url]") == score("great")


def test_censored_profanity_is_ignored():
    assert score("this game is ♥♥♥♥") == score("this game is")


def test_scores_obvious_sentiment():
    assert score("I love this game, it's amazing")[1] == "positive"
    assert score("Terrible. Broken and boring. Refunded.")[1] == "negative"


def test_scores_stay_between_minus_one_and_one():
    for s, _ in score_many(["masterpiece", "refund", "worth every hour", "worst game ever"]):
        assert -1 <= s <= 1


def test_scoring_no_texts_returns_nothing():
    assert score_many([]) == []


def test_batch_scoring_matches_one_at_a_time():
    texts = ["great", "", "Terrible. Broken and boring."]
    assert score_many(texts) == [score(t) for t in texts]
