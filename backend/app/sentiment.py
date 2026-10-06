"""Score review text with VADER and turn the score into a positive / neutral / negative label."""

import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# VADER's recommended cutoffs for turning the compound score into a label.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# Steam's formatting tags, e.g. [b]...[/b], [url=...], [*]. VADER reads "[b]great[/b]"
# as one unknown word and scores it 0, so the tags are removed before scoring.
BBCODE_TAG = re.compile(
    r"\[/?(?:h[1-3]|b|u|i|strike|spoiler|noparse|hr|url|quote|code|list|olist|table|tr|th|td|\*)"
    r"(?:=[^\]]*)?\]",
    re.IGNORECASE,
)

# Steam hides profanity as hearts ("this game is ♥♥♥♥"). VADER reads ♥ as a strongly
# positive emoji, which makes angry reviews look glowing, so the hearts are removed too.
CENSORED_WORD = re.compile("♥+")

_analyzer = SentimentIntensityAnalyzer()  # loads VADER's word list once


def label_for(compound: float) -> str:
    """Turn VADER's compound score (-1 to +1) into positive, neutral, or negative."""
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def score(text: str) -> tuple[float, str]:
    """Return (compound score, label) for one review's text."""
    # Replace with spaces so "a[hr]b" doesn't become "ab"
    cleaned = CENSORED_WORD.sub(" ", BBCODE_TAG.sub(" ", text))
    compound = _analyzer.polarity_scores(cleaned)["compound"]
    return compound, label_for(compound)
