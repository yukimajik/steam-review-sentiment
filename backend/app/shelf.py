"""
The front page's shelf: every stored game with its sentiment split, most reviews first. Also one
game's name and cover, for a dashboard opened straight from its web address.

The reviews table only knows app IDs, so names and covers come from Steam's store details, looked
up the first time a game appears and kept in game_details. If Steam can't be reached the game is
still listed, without a name, and the lookup is tried again next time.
"""

import logging

import psycopg

from app import steam
from app.steam import SteamError

logger = logging.getLogger(__name__)

# Steam serves every game's header image at this address too; used when the lookup hasn't worked yet
FALLBACK_IMAGE = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"

GAMES_SQL = """
    SELECT r.app_id,
           count(*),
           count(*) FILTER (WHERE r.sentiment_label = 'negative'),
           count(*) FILTER (WHERE r.sentiment_label = 'neutral'),
           count(*) FILTER (WHERE r.sentiment_label = 'positive'),
           d.name,
           d.image_url
    FROM reviews r LEFT JOIN game_details d USING (app_id)
    WHERE r.sentiment_label IS NOT NULL
    GROUP BY r.app_id, d.name, d.image_url
    ORDER BY count(*) DESC, r.app_id
"""
DETAILS_SQL = "SELECT name, image_url FROM game_details WHERE app_id = %s"
SAVE_SQL = """
    INSERT INTO game_details (app_id, name, image_url) VALUES (%s, %s, %s)
    ON CONFLICT (app_id) DO UPDATE SET name = EXCLUDED.name, image_url = EXCLUDED.image_url, looked_up = now()
"""


def stored_games(conn: psycopg.Connection) -> list[dict]:
    games = []
    steam_ok = True  # after one failed lookup, skip the rest: Steam is probably down or limiting us
    for app_id, total, negative, neutral, positive, name, image_url in conn.execute(GAMES_SQL).fetchall():
        if name is None and steam_ok:
            try:
                details = steam.fetch_app_details(app_id)
            except SteamError as error:
                logger.warning("Couldn't look up app %s on Steam: %s", app_id, error)
                steam_ok = False
                details = None
            if details:
                name, image_url = details
                conn.execute(SAVE_SQL, (app_id, name, image_url))
                conn.commit()
        games.append({
            "app_id": app_id,
            "name": name,
            "image_url": image_url or FALLBACK_IMAGE.format(app_id=app_id),
            "total_reviews": total,
            "negative_pct": round(100 * negative / total, 1),
            "neutral_pct": round(100 * neutral / total, 1),
            "positive_pct": round(100 * positive / total, 1),
        })
    return games


def game_details(conn: psycopg.Connection, app_id: int) -> dict | None:
    """One game's name and cover: from the database if it was looked up before, otherwise from Steam
    (and kept). None if Steam has no store page for it. Raises SteamError if Steam can't be reached."""
    row = conn.execute(DETAILS_SQL, (app_id,)).fetchone()
    if row is None:
        row = steam.fetch_app_details(app_id)
        if row is None:
            return None
        conn.execute(SAVE_SQL, (app_id, *row))
        conn.commit()
    name, image_url = row
    return {"app_id": app_id, "name": name, "image_url": image_url or FALLBACK_IMAGE.format(app_id=app_id)}
