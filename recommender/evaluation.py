"""Offline leave-one-out evaluation; never calls TMDB or changes user data.

Content-based uses Movie rows already saved locally. This is a local-data
proxy for the live TMDB candidate pipeline, NOT a measurement of the live page.
"""
from collections import Counter, defaultdict

from .collaborative_filtering import collaborative_scores
from .models import Movie, MovieRating
from .recommendation_engine import cosine_scores, tokens


def _metadata():
    return {m.tmdb_id: {
        'id': m.tmdb_id, 'title': m.title, 'overview': m.overview or '',
        'genres': [{'id': g, 'name': str(g)} for g in (m.genres or [])],
        'keywords': {'keywords': [{'name': str(k)} for k in (m.keywords or [])]},
    } for m in Movie.objects.all()}


def evaluate(k=5, min_positive=3):
    """Hold out one positive rating/user; rank unseen catalog items.

    Report coverage and eligible users, and don't fabricate metrics when no
    valid users exist. Only explicit ratings are used to prevent leakage.
    """
    if k < 1:
        raise ValueError('k must be >= 1')
    ratings = defaultdict(dict)
    for uid, mid, score in MovieRating.objects.values_list('user_id', 'tmdb_id', 'rating'):
        ratings[uid][mid] = float(score)
    catalog = set().union(*(set(items) for items in ratings.values())) if ratings else set()
    metadata = _metadata()
    positive = {uid: sorted(mid for mid, score in items.items() if score >= 4)
                for uid, items in ratings.items()}
    eligible = {uid: mids[-1] for uid, mids in positive.items() if len(mids) >= min_positive}
    train = {uid: {mid: score for mid, score in items.items() if eligible.get(uid) != mid}
             for uid, items in ratings.items()}
    algorithms = ('Content-Based (local)', 'Collaborative Filtering', 'Hybrid (local)')
    totals = {name: {'hits': 0, 'recommended': 0, 'users': 0, 'covered': 0} for name in algorithms}
    for uid, heldout in eligible.items():
        seen = set(train[uid])
        candidates = sorted(catalog - seen)
        if not candidates:
            continue
        cf, _ = collaborative_scores(uid, preferences=train)
        seed = Counter()
        for mid, score in train[uid].items():
            if score >= 4 and mid in metadata:
                for term, count in tokens(metadata[mid]).items():
                    seed[term] += count * (score - 2)
        local_candidates = [mid for mid in candidates if mid in metadata]
        cb = {}
        if seed and local_candidates:
            sims = cosine_scores(seed, [metadata[mid] for mid in local_candidates])
            cb = dict(zip(local_candidates, sims, strict=False))
        ranked = {
            'Content-Based (local)': sorted(local_candidates, key=lambda mid: (-cb.get(mid, 0), mid)) if seed else [],
            'Collaborative Filtering': sorted(
                (mid for mid in candidates if mid in cf),
                key=lambda mid: (-cf[mid], mid),
            ),
            'Hybrid (local)': sorted((mid for mid in candidates if mid in cb or mid in cf),
                                     key=lambda mid: (
                                         -(0.65 * cb.get(mid, 0) + 0.35 * cf.get(mid, 0)),
                                         mid,
                                     )),
        }
        for name, ordered in ranked.items():
            stat = totals[name]
            stat['users'] += 1
            if ordered:
                stat['covered'] += 1
            top = ordered[:k]
            stat['recommended'] += len(top)
            stat['hits'] += int(heldout in top)
    results = {}
    for name, stat in totals.items():
        users = stat['users']
        hits = stat['hits']
        results[name] = {
            'precision': hits / stat['recommended'] if stat['recommended'] else None,
            'recall': hits / users if users else None,
            'hit_rate': hits / users if users else None,
            'coverage': stat['covered'] / users if users else None,
            'hits': hits, 'users': users,
        }
    note = (
        'Một phim tích cực được giữ lại mỗi người dùng. Content-Based và Hybrid dùng '
        'metadata lưu trong SQLite; không đo trực tiếp pipeline TMDB trực tuyến. '
        'Precision@K tính trên số gợi ý thực tế; Recall@K trên một phim kiểm thử/người dùng.'
    )
    return {
        'k': k,
        'eligible_users': len(eligible),
        'rating_users': len(ratings),
        'catalog_size': len(catalog),
        'metadata_movies': len(metadata),
        'results': results,
        'method': 'Leave-one-positive-out (deterministic, offline)',
        'note': note,
    }
