"""Topic tagging (backend/app/topics.py): which topics a text mentions, and each topic's sentiment."""

import pytest

from app.topics import TOPICS, find_topics, tag_many


@pytest.mark.parametrize("text, topic", [
    ("Constant stutters and the FPS drops below 30", "performance"),
    ("So many bugs, it crashed twice", "bugs"),
    ("Way too expensive for what it is, wait for a sale. On sale it's fine", "price"),
    ("The story and characters are wonderful", "story"),
    ("Combat feels great and the puzzles are clever", "gameplay"),
    ("The graphics are stunning", "graphics"),
    ("Servers are down again and matchmaking takes forever", "multiplayer"),
    ("Not much content, I beat it in 3 hours. Way too short", "content"),
])
def test_finds_each_topic(text, topic):
    assert topic in find_topics(text)


def test_every_topic_has_a_test_above():
    assert len(TOPICS) == 8


@pytest.mark.parametrize("text", [
    "The flagship feature",                # "lag" inside another word
    "The debug menu is handy",             # "bug" at the end of another word
    "I'm optimistic about the updates",     # not "optimized"
    "The performances are touching",        # acting, not frame rate
    "Get a better graphics card",           # hardware, not graphics
    "As of writing this review it's fine",  # not the game's writing
    "Content creators love it",             # not the game's content
    "I'd refund it if I could",             # a verdict, not about price
    "Worth every hour",                     # overall praise, not about price
    "Ping the guards first",                # the in-game marker, not network ping
])
def test_ignores_lookalike_words(text):
    assert find_topics(text) == {}


def test_matching_ignores_case():
    assert "performance" in find_topics("FPS IS TERRIBLE")


def test_excerpt_is_only_the_part_that_mentions_the_topic():
    topics = find_topics("Great game, but it runs terribly. Love the story!")
    assert topics == {"performance": "it runs terribly", "story": "Love the story"}


def test_several_parts_about_one_topic_are_joined():
    topics = find_topics("The story starts slow.\nThe ending is perfect.")
    assert topics == {"story": "The story starts slow … The ending is perfect"}


def test_formatting_tags_are_removed_and_list_items_are_separate_parts():
    topics = find_topics("[list][*][b]Great combat[/b][*]awful servers[/list]")
    assert topics == {"gameplay": "Great combat", "multiplayer": "awful servers"}


def test_unticked_template_boxes_are_ignored():
    template = "---{Bugs}---\r\n☐ Bugs destroy the game\r\n☑ Minor bugs\r\n☐ Nothing encountered"
    assert find_topics(template) == {"bugs": "---{Bugs}--- … ☑ Minor bugs"}


def test_prices_in_dollars_count_as_price():
    assert "price" in find_topics("Not worth $60")
    assert "price" in find_topics("got it for 5$")


def test_text_with_no_topics():
    assert find_topics("") == {}
    assert find_topics("Good game, 10/10") == {}


def test_each_topic_gets_the_sentiment_of_its_own_part():
    [topics] = tag_many(["The story is amazing and I loved every character. But the servers are terrible and broken."])
    assert topics["story"][2] == "positive"
    assert topics["multiplayer"][2] == "negative"
    excerpt, score, _ = topics["multiplayer"]
    assert excerpt == "the servers are terrible and broken"
    assert -1 <= score < 0


def test_tag_many_handles_texts_without_topics():
    assert tag_many([]) == []
    assert tag_many(["good game", "great story"])[0] == {}
