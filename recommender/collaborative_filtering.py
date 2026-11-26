"""User-based collaborative filtering on explicit ratings and favorites.

No external ML dependency. A neighbor must share at least two rated movies
with the target user; shrinkage avoids overconfident similarities on sparse data.
"""
from collections import defaultdict
from math import sqrt

from .models import FavoriteMovie, MovieRating


def build_preferences():
    preferences = defaultdict(dict)
    for user_id, movie_id, rating in MovieRating.objects.values_list('user_id', 'tmdb_id', 'rating'):
        preferences[user_id][movie_id] = float(rating)
    # Favorites are a weaker positive signal; explicit ratings always win.
    for user_id, movie_id in FavoriteMovie.objects.filter(tmdb_id__isnull=False).values_list('user_id', 'tmdb_id'):
        preferences[user_id].setdefault(movie_id, 4.0)
    return preferences


def collaborative_scores(user_id, preferences=None, min_overlap=2):
    """Return movie_id -> normalized 0..1 positive preference and evidence count.

    Excludes already-seen movies. Negative/neutral neighbor ratings do not
    become positive recommendations. With insufficient overlap returns {}.
    """
    preferences = build_preferences() if preferences is None else preferences
    target = preferences.get(user_id, {})
    if len(target) < min_overlap:
        return {}, {}
    weighted = defaultdict(float)
    weights = defaultdict(float)
    support = defaultdict(int)
    for other_id, other in preferences.items():
        if other_id == user_id:
            continue
        shared = target.keys() & other.keys()
        if len(shared) < min_overlap:
            continue
        # Center scores around neutral rating 3 to distinguish dislikes.
        a = [target[mid] - 3.0 for mid in shared]
        b = [other[mid] - 3.0 for mid in shared]
        denom = sqrt(sum(x*x for x in a) * sum(y*y for y in b))
        if not denom:
            continue
        similarity = sum(x * y for x, y in zip(a, b, strict=False)) / denom
        similarity = max(0.0, similarity) * len(shared) / (len(shared) + 3.0)
        if similarity <= 0:
            continue
        for mid, rating in other.items():
            if mid in target or rating <= 3:
                continue
            weighted[mid] += similarity * (rating - 3) / 2.0
            weights[mid] += similarity
            support[mid] += 1
    scores = {mid: min(1.0, weighted[mid] / weights[mid]) for mid in weights if weights[mid] > 0}
    return scores, dict(support)
