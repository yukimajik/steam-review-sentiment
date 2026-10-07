"""
Compare three ways to label review sentiment, using Steam's voted_up (the player's own
Recommended / Not recommended) as the answer key:

  1. VADER, what the app uses now
  2. cardiffnlp/twitter-roberta-base-sentiment-latest, a pretrained transformer for informal text
  3. TF-IDF + logistic regression, trained on our own Steam reviews to predict voted_up

The test set is whole games (TEST_GAMES) that the classifier never sees while training,
so it can't score well by memorising game-specific words. Each model runs in its own
fresh process, so its peak memory is measured on its own.

Usage (from the project root, with the database running):
    pip install -r backend/experiments/requirements.txt
    python backend/experiments/compare_models.py
Prints a report and writes it to backend/experiments/results.md.
"""

import multiprocessing
import os
import pickle
import random
import re
import resource
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lets this script import the app package
from app.sentiment import BBCODE_TAG, CENSORED_WORD  # noqa: E402

TRANSFORMER = "cardiffnlp/twitter-roberta-base-sentiment-latest"
TEST_GAMES = {  # held out from training; together ~24% of reviews, 19% Not recommended
    1716740: "Starfield",
    252490: "Rust",
    2358720: "Black Myth: Wukong",
    413150: "Stardew Valley",
}
PHRASES = [
    "worth every hour",
    "this game is sick",
    "10/10 would get scammed again",
    "great game, too bad the servers never work",
    "Zero regrets. Outstanding visuals, insane boss fights, and peak combat. Absolutely worth every second!",
]
SEED = 42
RESULTS_FILE = Path(__file__).with_name("results.md")


def clean(text: str) -> str:
    """The same cleanup the app does before scoring: drop Steam's BBCode tags and ♥ censoring."""
    return CENSORED_WORD.sub(" ", BBCODE_TAG.sub(" ", text))


def peak_memory_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3  # bytes on macOS, KB on Linux


# ---------- the three models; each runs in a child process ----------
# Each returns one prediction per text: (label, score), where label is "positive" /
# "neutral" / "negative" and score is the model's confidence that the review is positive.

def run_vader(texts: list[str]) -> dict:
    from app.sentiment import score
    start = time.perf_counter()
    preds = [score(t) for t in texts]  # (compound, label); score() does the cleanup itself
    seconds = time.perf_counter() - start
    return {"preds": [(label, compound) for compound, label in preds], "seconds": seconds, "peak_mb": peak_memory_mb()}


def run_transformer(texts: list[str]) -> dict:
    import torch
    from transformers import pipeline
    torch.manual_seed(SEED)
    clf = pipeline("text-classification", model=TRANSFORMER, top_k=None, truncation=True, max_length=512, device="cpu")

    def prep(text: str) -> str:
        # The model card's preprocessing: links become "http", @mentions become "@user"
        text = re.sub(r"http\S+", "http", clean(text))
        return re.sub(r"@\w+", "@user", text).strip() or "."

    # Score shortest first so each batch pads less, then put results back in order
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    start = time.perf_counter()
    outputs = clf([prep(texts[i]) for i in order], batch_size=32)
    seconds = time.perf_counter() - start
    preds = [None] * len(texts)
    for i, out in zip(order, outputs):
        probs = {d["label"]: d["score"] for d in out}
        label = max(probs, key=probs.get)
        preds[i] = (label, probs["positive"] - probs["negative"])  # >0 leans positive
    return {"preds": preds, "seconds": seconds, "peak_mb": peak_memory_mb()}


def train_tfidf(train_texts: list[str], train_labels: list[bool], train_groups: list[int], model_path: str) -> dict:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV, GroupKFold
    from sklearn.pipeline import make_pipeline

    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True),
        LogisticRegression(class_weight="balanced", max_iter=2000),  # weights the rarer Not recommended class up
    )
    # Pick the regularisation strength with cross-validation grouped by game, on training games only
    search = GridSearchCV(pipe, {"logisticregression__C": [0.25, 1, 4, 16]}, cv=GroupKFold(n_splits=5),
                          scoring="balanced_accuracy")
    start = time.perf_counter()
    search.fit([clean(t) for t in train_texts], train_labels, groups=train_groups)
    seconds = time.perf_counter() - start
    with open(model_path, "wb") as f:
        pickle.dump(search.best_estimator_, f)
    vocab = len(search.best_estimator_.named_steps["tfidfvectorizer"].vocabulary_)
    return {"seconds": seconds, "peak_mb": peak_memory_mb(), "best_c": search.best_params_["logisticregression__C"],
            "vocab": vocab, "size_mb": os.path.getsize(model_path) / 1e6}


def run_tfidf(texts: list[str], model_path: str) -> dict:
    """Load the trained model and predict, like the API would (measures inference memory only)."""
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    start = time.perf_counter()
    probs = model.predict_proba([clean(t) for t in texts])[:, list(model.classes_).index(True)]
    seconds = time.perf_counter() - start
    preds = [("positive" if p >= 0.5 else "negative", float(p) - 0.5) for p in probs]  # binary: no neutral
    return {"preds": preds, "seconds": seconds, "peak_mb": peak_memory_mb()}


def in_child(func, *args):
    """Run func in a brand-new process, so imports and peak memory don't leak between models."""
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
        return pool.submit(func, *args).result()


# ---------- scoring ----------

def evaluate(votes: list[bool], preds: list[tuple[str, float]]) -> dict:
    n = len(votes)
    # Forced choice: positive vs negative only. Ties (score exactly 0) go to the more common vote.
    forced = [s >= 0 for _, s in preds]
    correct = sum(f == v for f, v in zip(forced, votes))
    rec = [f for f, v in zip(forced, votes) if v]
    notrec = [not f for f, v in zip(forced, votes) if not v]
    # The app's view: three labels, neutral counts as a miss
    app_agree = sum((v and lab == "positive") or (not v and lab == "negative") for (lab, _), v in zip(preds, votes))
    return {
        "accuracy": 100 * correct / n,
        "rec_caught": 100 * sum(rec) / len(rec),
        "notrec_caught": 100 * sum(notrec) / len(notrec),
        "balanced": 50 * (sum(rec) / len(rec) + sum(notrec) / len(notrec)),
        "app_agreement": 100 * app_agree / n,
        "neutral": 100 * sum(lab == "neutral" for lab, _ in preds) / n,
    }


def wrong_examples(texts, votes, preds, k=5) -> list[str]:
    # Only reviews of 5+ words: a one-word review can't show *why* a model got it wrong
    wrong = [i for i, ((_, s), v) in enumerate(zip(preds, votes)) if (s >= 0) != v and len(texts[i].split()) >= 5]
    rng = random.Random(SEED)
    lines = []
    for i in sorted(rng.sample(wrong, min(k, len(wrong)))):
        text = " ".join(texts[i].split())
        text = text[:150] + ("…" if len(text) > 150 else "")
        vote = "Recommended" if votes[i] else "Not recommended"
        lines.append(f"- **{vote}**, labeled {preds[i][0]} ({preds[i][1]:+.2f}): “{text}”")
    return lines


def main() -> None:
    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT app_id, review_text, voted_up FROM reviews ORDER BY recommendation_id"
        ).fetchall()

    train = [r for r in rows if r[0] not in TEST_GAMES]
    test = [r for r in rows if r[0] in TEST_GAMES]
    test_texts, test_votes = [r[1] for r in test], [r[2] for r in test]
    baseline = 100 * max(sum(test_votes), len(test_votes) - sum(test_votes)) / len(test_votes)
    print(f"Train: {len(train)} reviews from {len({r[0] for r in train})} games, "
          f"{sum(not r[2] for r in train)} Not recommended")
    print(f"Test:  {len(test)} reviews from {len(TEST_GAMES)} games ({', '.join(TEST_GAMES.values())}), "
          f"{len(test) - sum(test_votes)} Not recommended. Baseline (always Recommended): {baseline:.1f}%\n")

    model_path = str(Path(__file__).with_name("tfidf_model.pkl"))  # git-ignored
    print("Training TF-IDF + logistic regression...", flush=True)
    training = in_child(train_tfidf, [r[1] for r in train], [r[2] for r in train], [r[0] for r in train], model_path)
    print(f"  done in {training['seconds']:.1f}s, best C={training['best_c']}\n", flush=True)

    results = {}
    for name, func, extra in [("VADER (current)", run_vader, ()),
                              ("Transformer (twitter-roberta)", run_transformer, ()),
                              ("TF-IDF + logistic regression", run_tfidf, (model_path,))]:
        print(f"Running {name} on {len(test_texts)} test reviews...", flush=True)
        out = in_child(func, test_texts + PHRASES, *extra)
        test_preds, phrase_preds = out["preds"][:len(test_texts)], out["preds"][len(test_texts):]
        results[name] = {**out, "metrics": evaluate(test_votes, test_preds), "test_preds": test_preds,
                         "phrases": phrase_preds, "per_second": len(test_texts) / out["seconds"]}
        m = results[name]["metrics"]
        print(f"  accuracy {m['accuracy']:.1f}%, Not recommended caught {m['notrec_caught']:.1f}%, "
              f"{results[name]['per_second']:.0f} reviews/s, peak memory {out['peak_mb']:.0f} MB\n", flush=True)

    sizes = {"VADER (current)": "0.6 MB (word lists)", "Transformer (twitter-roberta)": "501 MB (weights)",
             "TF-IDF + logistic regression": f"{training['size_mb']:.1f} MB (trained model)"}
    report = [
        f"# Sentiment model comparison ({date.today().isoformat()})",
        "",
        "Generated by `backend/experiments/compare_models.py`. Answer key: Steam's `voted_up`.",
        "",
        f"- **Training data** (TF-IDF only): {len(train):,} reviews from {len({r[0] for r in train})} games, "
        f"{sum(not r[2] for r in train):,} Not recommended.",
        f"- **Test data** (all models): {len(test):,} reviews from {len(TEST_GAMES)} games the classifier never saw "
        f"({', '.join(TEST_GAMES.values())}), {len(test) - sum(test_votes):,} Not recommended.",
        f"- **Baseline:** always guessing Recommended scores **{baseline:.1f}%** accuracy.",
        "",
        "## Results",
        "",
        "Forced choice: each model must pick Recommended or Not recommended (VADER: score ≥ 0; transformer: "
        "P(positive) ≥ P(negative); TF-IDF: P(Recommended) ≥ 0.5).",
        "",
        "| Model | Accuracy | Balanced accuracy | Not recommended caught | Recommended caught | "
        "App-style agreement (neutral = miss) | Labeled neutral | Speed (this Mac, CPU) | Peak memory | Size |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in results.items():
        m = r["metrics"]
        app_style = f"{m['app_agreement']:.1f}%" if m["neutral"] or name.startswith(("VADER", "Transformer")) else "n/a (no neutral)"
        report.append(
            f"| {name} | **{m['accuracy']:.1f}%** | {m['balanced']:.1f}% | {m['notrec_caught']:.1f}% | "
            f"{m['rec_caught']:.1f}% | {app_style} | {m['neutral']:.1f}% | {r['per_second']:,.0f} reviews/s | "
            f"{r['peak_mb']:.0f} MB | {sizes[name]} |"
        )
    report += [
        "",
        f"TF-IDF training: {training['seconds']:.1f} s, peak memory {training['peak_mb']:.0f} MB, "
        f"{training['vocab']:,} words and word pairs, regularisation C={training['best_c']} "
        "(chosen by 5-fold cross-validation grouped by game, on training games only).",
        "",
        "## The test phrases",
        "",
        "| Text | " + " | ".join(results) + " |",
        "|---|" + "---|" * len(results),
    ]
    for i, phrase in enumerate(PHRASES):
        cells = [f"{r['phrases'][i][0]} ({r['phrases'][i][1]:+.2f})" for r in results.values()]
        report.append(f"| {phrase} | " + " | ".join(cells) + " |")
    report += ["", "Scores: VADER compound (−1 to +1); transformer P(positive) − P(negative); "
               "TF-IDF P(Recommended) − 0.5.", "", "## Examples each model gets wrong", "",
               "A random sample (fixed seed) of each model's mistakes, from reviews of at least 5 words.", ""]
    for name, r in results.items():
        report += [f"### {name}", *wrong_examples(test_texts, test_votes, r["test_preds"]), ""]

    text = "\n".join(report)
    RESULTS_FILE.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
