"""
Label review text positive / neutral / negative with our trained classifier: TF-IDF +
logistic regression that predicts whether the player recommends the game (Steam's voted_up).

Train or retrain it with backend/scripts/train_model.py, which saves sentiment_model.pkl
next to this file. Chosen over VADER after the comparison in backend/experiments/results.md.
"""

import pickle
import re
from functools import cache
from pathlib import Path

MODEL_PATH = Path(__file__).with_name("sentiment_model.pkl")

# Steam's formatting tags, e.g. [b]...[/b], [url=...], [*]. Removed so "[b]great[/b]" reads as "great".
BBCODE_TAG = re.compile(
    r"\[/?(?:h[1-3]|b|u|i|strike|spoiler|noparse|hr|url|quote|code|list|olist|table|tr|th|td|\*)"
    r"(?:=[^\]]*)?\]",
    re.IGNORECASE,
)

# Steam hides profanity as hearts ("this game is ♥♥♥♥"). The hearts aren't the reviewer's
# words, so they're removed too.
CENSORED_WORD = re.compile("♥+")


def clean(text: str) -> str:
    # Replace with spaces so "a[hr]b" doesn't become "ab"
    return CENSORED_WORD.sub(" ", BBCODE_TAG.sub(" ", text))


@cache  # loaded once, on first use, so importing this module stays cheap
def model() -> dict:
    import sklearn
    with open(MODEL_PATH, "rb") as f:
        artifact = pickle.load(f)  # only ever our own file, built by train_model.py
    if artifact["sklearn_version"] != sklearn.__version__:
        raise RuntimeError(
            f"{MODEL_PATH.name} was trained with scikit-learn {artifact['sklearn_version']} but "
            f"{sklearn.__version__} is installed. Install that version or retrain with backend/scripts/train_model.py."
        )
    return artifact


def label_for(score: float) -> str:
    """Turn a score (-1 = surely Not recommended, +1 = surely Recommended) into a label.
    Scores inside the model's neutral band, where it isn't confident, are "neutral"."""
    low, high = model()["neutral_band"]  # in P(Recommended) terms
    p = (score + 1) / 2
    if p >= high:
        return "positive"
    if p <= low:
        return "negative"
    return "neutral"


def predict(pipeline, texts: list[str]) -> list[float | None]:
    """P(Recommended) for each text, or None when the model recognises none of its words
    (empty, emoji-only, another language). Then the model would just fall back to its
    built-in lean toward Recommended, which isn't evidence, so callers treat it as neutral."""
    words = pipeline.named_steps["tfidfvectorizer"].transform([clean(t) for t in texts])
    probs = pipeline.named_steps["logisticregression"].predict_proba(words)[:, list(pipeline.classes_).index(True)]
    return [float(p) if n else None for p, n in zip(probs, words.getnnz(axis=1))]


def score_many(texts: list[str]) -> list[tuple[float, str]]:
    """(score, label) for each text. The score is 2·P(Recommended) − 1, from −1 to +1."""
    results = []
    for p in predict(model()["pipeline"], texts):
        s = 0.0 if p is None else round(2 * p - 1, 4)
        results.append((s, "neutral" if p is None else label_for(s)))
    return results


def score(text: str) -> tuple[float, str]:
    """(score, label) for one review's text."""
    return score_many([text])[0]
