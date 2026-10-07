"""
Train the sentiment classifier the app uses: TF-IDF + logistic regression, predicting from a
review's text whether the player recommends the game (Steam's voted_up).

1. Held-out check: train on every game except HELD_OUT_GAMES, choose the neutral band on the
   training games only, and report how the model does on the held-out games.
2. Final model: the same steps on every game, saved to backend/app/sentiment_model.pkl.

"Neutral" means the model isn't confident: its P(Recommended) falls inside a band around 0.5.
The band is the narrowest one where predictions outside it are right at least TARGET_ACCURACY
of the time, measured with out-of-fold predictions (each game scored by a model that didn't
see it), so the choice never peeks at test data.

Usage (from the project root, with the database running):
    python backend/scripts/train_model.py
"""

import pickle
import sys
import time
from datetime import date
from pathlib import Path

import psycopg
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline, make_pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lets the script import the app package
from app import db  # noqa: E402
from app.sentiment import MODEL_PATH, clean, predict  # noqa: E402

HELD_OUT_GAMES = {1716740: "Starfield", 252490: "Rust", 2358720: "Black Myth: Wukong", 413150: "Stardew Valley"}
TARGET_ACCURACY = 0.90  # labels outside the neutral band should be right at least this often
FOLDS = 5


def train(texts: list[str], labels: list[bool], games: list[int]) -> tuple[Pipeline, float, dict]:
    """Fit the pipeline (regularisation chosen by cross-validation grouped by game) and choose
    the neutral band from out-of-fold predictions. Returns (model, band half-width, info)."""
    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True),
        LogisticRegression(class_weight="balanced", max_iter=2000),  # weights the rarer Not recommended class up
    )
    cleaned = [clean(t) for t in texts]
    search = GridSearchCV(pipe, {"logisticregression__C": [0.25, 1, 4, 16]}, cv=GroupKFold(n_splits=FOLDS),
                          scoring="balanced_accuracy")
    search.fit(cleaned, labels, groups=games)
    model = search.best_estimator_

    # Out-of-fold P(Recommended): every review scored by a model trained without its game
    oof = cross_val_predict(model, cleaned, labels, groups=games, cv=GroupKFold(n_splits=FOLDS),
                            method="predict_proba")[:, list(model.classes_).index(True)]
    half_width = choose_band(oof, labels, TARGET_ACCURACY)
    return model, half_width, {"C": search.best_params_["logisticregression__C"]}


def choose_band(probs, labels, target: float) -> float:
    """Narrowest half-width w (in steps of 0.01) such that predictions with P outside
    (0.5 - w, 0.5 + w) are at least `target` accurate."""
    for step in range(50):
        w = step / 100
        confident = [(p >= 0.5, y) for p, y in zip(probs, labels) if p >= 0.5 + w or p <= 0.5 - w]
        if confident and sum(pred == y for pred, y in confident) / len(confident) >= target:
            return w
    return 0.49


def evaluate(model: Pipeline, half_width: float, texts: list[str], labels: list[bool]) -> dict:
    # Same rules as the app: no recognisable words means neutral (and, when forced, the common vote)
    probs = predict(model, texts)
    n = len(labels)
    forced = sum((p is None or p >= 0.5) == y for p, y in zip(probs, labels))
    labeled = [(p >= 0.5, y) for p, y in zip(probs, labels)
               if p is not None and (p >= 0.5 + half_width or p <= 0.5 - half_width)]
    # App-style: positive must match Recommended, negative must match Not recommended, neutral is a miss
    app_agree = sum(pred == y for pred, y in labeled)
    not_rec = [p for p, y in zip(probs, labels) if not y]
    return {
        "reviews": n,
        "baseline": 100 * max(sum(labels), n - sum(labels)) / n,
        "forced_accuracy": 100 * forced / n,
        "app_agreement": 100 * app_agree / n,
        "neutral": 100 * (n - len(labeled)) / n,
        "labeled_accuracy": 100 * app_agree / len(labeled),
        "not_rec_caught": 100 * sum(p is not None and p <= 0.5 - half_width for p in not_rec) / len(not_rec),
        "no_known_words": sum(p is None for p in probs),
    }


def main() -> None:
    with psycopg.connect(db.database_url()) as conn:
        rows = conn.execute("SELECT app_id, review_text, voted_up FROM reviews ORDER BY recommendation_id").fetchall()
    print(f"{len(rows):,} reviews from {len({r[0] for r in rows})} games, "
          f"{sum(not r[2] for r in rows):,} Not recommended\n")

    # 1. Held-out check
    train_rows = [r for r in rows if r[0] not in HELD_OUT_GAMES]
    test_rows = [r for r in rows if r[0] in HELD_OUT_GAMES]
    model, half_width, info = train([r[1] for r in train_rows], [r[2] for r in train_rows], [r[0] for r in train_rows])
    heldout = evaluate(model, half_width, [r[1] for r in test_rows], [r[2] for r in test_rows])
    print(f"Held-out check: trained on {len(train_rows):,} reviews, tested on {heldout['reviews']:,} from "
          f"{', '.join(HELD_OUT_GAMES.values())} (C={info['C']}, neutral band 0.5 ± {half_width:.2f})")
    print(f"  baseline (always Recommended)       {heldout['baseline']:.1f}%")
    print(f"  accuracy, forced to pick a side     {heldout['forced_accuracy']:.1f}%")
    print(f"  app-style agreement (neutral=miss)  {heldout['app_agreement']:.1f}%")
    print(f"  labeled neutral                     {heldout['neutral']:.1f}%")
    print(f"  accuracy of non-neutral labels      {heldout['labeled_accuracy']:.1f}%")
    print(f"  Not recommended labeled negative    {heldout['not_rec_caught']:.1f}%")
    print(f"  reviews with no recognised words    {heldout['no_known_words']} (labeled neutral)\n")

    # 2. Final model on everything
    start = time.perf_counter()
    model, half_width, info = train([r[1] for r in rows], [r[2] for r in rows], [r[0] for r in rows])
    artifact = {
        "pipeline": model,
        "neutral_band": (0.5 - half_width, 0.5 + half_width),  # P(Recommended) strictly inside = neutral
        "sklearn_version": sklearn.__version__,
        "trained_on": date.today().isoformat(),
        "reviews": len(rows),
        "games": len({r[0] for r in rows}),
        "heldout_check": heldout,
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(artifact, f)
    vocab = len(model.named_steps["tfidfvectorizer"].vocabulary_)
    print(f"Final model: {len(rows):,} reviews, C={info['C']}, neutral band 0.5 ± {half_width:.2f}, "
          f"{vocab:,} words and word pairs, trained in {time.perf_counter() - start:.1f}s")
    print(f"Saved {MODEL_PATH} ({MODEL_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
