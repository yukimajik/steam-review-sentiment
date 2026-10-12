"""
Playtime groups: how long reviewers had played when they wrote their review.

The groups are the same for every game, so "under 2 hours" means the same thing on every page.
The first boundary is Steam's refund window (2 hours played); 10 and 50 hours are round numbers.
Short games barely reach 50 hours, so that group can be small: see MIN_REVIEWS.
"""

from typing import Literal

PlaytimeGroup = Literal["under_2h", "2_to_10h", "10_to_50h", "50h_plus"]

GROUPS: list[PlaytimeGroup] = ["under_2h", "2_to_10h", "10_to_50h", "50h_plus"]  # shortest first

# Minutes where each group after the first begins (2 h, 10 h, 50 h). PostgreSQL's width_bucket
# turns a playtime into its group's position in GROUPS: under 120 -> 0, 120 to 599 -> 1, and so on.
BOUNDARIES = [120, 600, 3000]

# Below this many reviews a group's percentage swings too much to compare (12 reviews: about
# ±28 points; 30: about ±18), so it shows its raw counts instead. Same minimum as updates.py.
MIN_REVIEWS = 30
