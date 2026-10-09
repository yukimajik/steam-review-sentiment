"""
Tag review text with the topics it talks about (performance, bugs, price/value, ...) using
keyword lists, and give each topic its own sentiment.

Only the parts of a review that mention a topic are scored for it, so in "great game, but it
runs terribly" the performance part counts as a complaint even though the review is positive.

Keywords are simple, fast and easy to check, but they only find the words listed here: see
docs/HOW_IT_WORKS.md for what they miss and the smarter alternatives.
"""

import re

from app.sentiment import BBCODE_TAG, score_many

# Each topic's keywords are regular expressions, matched as whole words in any case.
# The judgment calls noted below were checked against the stored reviews.
KEYWORDS: dict[str, list[str]] = {
    "performance": [
        r"fps", r"frame ?rates?", r"frames per second", r"frame ?drops?", r"stutter\w*",
        r"(?:un)?optimi[sz](?:ed|ation)",  # not "optimistic"
        r"performance",  # not "performances", which is about the acting
        r"lag", r"lags", r"laggy", r"lagging",  # usually frame rate, sometimes network lag
        r"runs (?:well|smooth(?:ly)?|great|fine|perfectly|badly|poorly|terribly|horribly|like)",
        r"load(?:ing)? times?", r"gpu", r"cpu", r"vram", r"dlss",
    ],
    "bugs": [
        r"bugs?", r"buggy", r"bugged",  # also Hollow Knight's insect characters: keywords can't tell them apart
        r"glitch\w*",
        r"crash\w*",  # crashes count as bugs, not performance
        r"freez(?:e|es|ing)", r"froze", r"softlock\w*", r"black screen", r"corrupted",
        r"(?:won['’]?t|doesn['’]?t|does not|can['’]?t|cannot) (?:launch|start|load)",
        r"broken",  # usually a broken game, sometimes an overpowered ("broken") perk
    ],
    "price": [
        r"price[ds]?", r"pricey", r"pricing", r"overpriced", r"expensive", r"cheap(?:er|est|ly)?",
        r"\$\s?\d+", r"\d+(?:[.,]\d+)?\s?\$", r"\d+ ?(?:dollars|bucks|usd|euros?)",
        r"on sale", r"discount(?:s|ed)?", r"full price",
        r"worth (?:the |its |it['’]s )?(?:money|price|cost)",  # not a bare "worth": "worth every hour" is overall praise
        r"value for money", r"cash ?grab", r"microtransactions?", r"mtx", r"pay ?(?:to|2) ?win", r"p2w",
        # Not "refund": it's mostly "I'd refund this if I could", a verdict on the whole game
    ],
    "story": [
        r"story", r"stories", r"storyline", r"storytelling", r"plot", r"narrative", r"lore",
        r"writing(?! this)",  # not "as of writing this review"
        r"well[- ]written", r"characters", r"dialog(?:ue)?s?", r"endings?", r"protagonist", r"villains?",
        r"cutscenes?", r"voice acting",
    ],
    "gameplay": [
        r"gameplay", r"game play", r"combat", r"mechanics?", r"controls", r"gunplay", r"movement",
        r"puzzles?", r"level design", r"difficulty", r"grind\w*", r"boss(?:es)?", r"crafting", r"exploration",
    ],
    "graphics": [
        r"graphics?(?! cards?)",  # a graphics card is about performance
        r"graphical(?:ly)?", r"visuals?", r"visually", r"textures?", r"art ?style", r"art direction",
        r"animations?", r"lighting", r"gorgeous", r"ray ?tracing",
        r"looks (?:great|amazing|beautiful|gorgeous|stunning|good|bad|terrible|ugly|dated|awful)",
    ],
    "multiplayer": [
        r"servers?", r"multi-?player", r"online", r"co[- ]?op", r"matchmaking", r"pvp", r"lobby", r"lobbies",
        r"cheaters?", r"cheating", r"hackers?", r"anti-?cheat", r"disconnect\w*", r"desync\w*", r"netcode",
        r"(?:internet|network|server) connection", r"connection (?:issues?|problems?|errors?)",  # not "pipe connection"
        r"with (?:my )?friends", r"teammates?",
        # Not "ping": often the in-game marker ("ping the guards")
    ],
    "content": [
        r"content(?! creators?)", r"replay\w*", r"end-?game", r"end game", r"length",
        r"(?:too|very|really|pretty|quite|super|fairly|so) short", r"short game",
        r"(?:nothing|not much|lots|plenty|a lot|tons) (?:else )?to do",
        r"\d+ hours? (?:long|of content|to (?:beat|finish|complete))",  # not a bare "hours": that's mostly playtime
        r"(?:beat|finished|completed) (?:it|the game) in",
    ],
}
TOPICS = list(KEYWORDS)

PATTERNS = {
    topic: re.compile(r"(?<!\w)(?:" + "|".join(words) + r")(?!\w)", re.IGNORECASE)
    for topic, words in KEYWORDS.items()
}

# Where a review is cut into parts: sentence ends, line breaks, list items, semicolons, and
# "but"/"however", the usual way one sentence mixes praise and complaints.
PART_BREAK = re.compile(r"[.!?]+(?=\s|$)|\n|\[\*\]|;|\b(?:but|however)\b", re.IGNORECASE)

# Steam's checkbox review template lists every option ("☐ Too much grind", "☑ Minor bugs").
# Unticked ones aren't the reviewer's opinion.
UNTICKED_BOX = re.compile(r"^\s*☐.*$", re.MULTILINE)


def parts(text: str) -> list[str]:
    """The text cut into parts, with formatting tags removed and spaces tidied."""
    pieces = PART_BREAK.split(UNTICKED_BOX.sub("", text))
    return [part for part in (" ".join(BBCODE_TAG.sub(" ", p).split()) for p in pieces) if part]


def find_topics(text: str) -> dict[str, str]:
    """{topic: excerpt} for each topic the text mentions. The excerpt is every part of the
    text that mentions the topic, joined with " … "."""
    found: dict[str, list[str]] = {}
    for part in parts(text):
        for topic, pattern in PATTERNS.items():
            if pattern.search(part):
                found.setdefault(topic, []).append(part)
    return {topic: " … ".join(topic_parts) for topic, topic_parts in found.items()}


def tag_many(texts: list[str]) -> list[dict[str, tuple[str, float, str]]]:
    """For each text, {topic: (excerpt, score, label)}, where the score and label are the
    sentiment classifier's verdict on the excerpt alone."""
    found = [find_topics(text) for text in texts]
    scores = iter(score_many([excerpt for topics in found for excerpt in topics.values()]))  # one batch call
    return [{topic: (excerpt, *next(scores)) for topic, excerpt in topics.items()} for topics in found]
