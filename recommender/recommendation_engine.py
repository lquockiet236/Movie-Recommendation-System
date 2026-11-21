"""Personalized TMDB recommendations: TF-IDF cosine + genre preference + quality.
No training dataset required. Candidate retrieval and detailed metadata are cached by tmdb_service.
"""
from collections import Counter, defaultdict
from math import log, sqrt
import re
from . import tmdb_service as tmdb
from .models import FavoriteMovie, MovieRating, MovieInteraction
from .collaborative_filtering import collaborative_scores


def tokens(movie):
    """Language-agnostic tokenization, weighted for genres and keywords."""
    genres = [g.get('name', '') for g in movie.get('genres', [])]
    raw_keywords = movie.get('keywords') or {}
    keywords = raw_keywords.get('keywords', raw_keywords.get('results', [])) if isinstance(raw_keywords, dict) else []
    terms = []
    for value, repeat in [(genres, 4), ([k.get('name', '') for k in keywords], 3), ([movie.get('overview') or ''], 1)]:
        for v in value:
            terms.extend(re.findall(r'\w+', v.lower(), flags=re.UNICODE) * repeat)
    return Counter(t for t in terms if len(t) > 2)


def cosine_scores(profile, candidates):
    """TF-IDF cosine similarity with IDF calculated from this candidate pool."""
    docs = [profile] + [tokens(m) for m in candidates]
    df = Counter()
    for doc in docs:
        df.update(doc.keys())
    n = len(docs)
    def vector(doc):
        return {t: (1 + log(count)) * (log((n + 1) / (df[t] + 1)) + 1) for t, count in doc.items() if count > 0}
    a = vector(profile)
    norm_a = sqrt(sum(x*x for x in a.values()))
    scores = []
    for doc in docs[1:]:
        b = vector(doc)
        denom = norm_a * sqrt(sum(x*x for x in b.values()))
        scores.append(sum(value * b.get(term, 0) for term, value in a.items()) / denom if denom else 0)
    return scores


def recommend(user, limit=12):
    favorites = list(FavoriteMovie.objects.filter(user=user, tmdb_id__isnull=False).values_list('tmdb_id', flat=True)[:60])
    ratings = dict(MovieRating.objects.filter(user=user).values_list('tmdb_id', 'rating')[:100])
    recent = list(MovieInteraction.objects.filter(user=user, action='detail').values_list('tmdb_id', flat=True)[:80])
    positive = defaultdict(float)
    for mid in favorites: positive[mid] += 3.0
    for mid, rating in ratings.items():
        if rating >= 4: positive[mid] += (rating - 2) * 1.5
    for mid in set(recent): positive[mid] += 0.25
    cf_scores, cf_support = collaborative_scores(user.pk)
    seeds = sorted(positive, key=lambda mid: -positive[mid])[:8]
    excluded = set(favorites) | set(ratings)
    if not seeds:
        movies = tmdb.popular_movies()[:limit]
        return {'movies': [{'movie': m, 'score': None, 'reason': 'Phim phổ biến trên TMDB'} for m in movies], 'cold_start': True, 'hybrid': False}
    details = []
    for mid in seeds:
        try: details.append((tmdb.get_movie_details(mid), positive[mid]))
        except tmdb.TMDBError: continue
    if not details:
        raise tmdb.TMDBError('Không thể tải thông tin các phim bạn đã tương tác.')
    profile = Counter()
    genres = defaultdict(float)
    for movie, weight in details:
        for term, count in tokens(movie).items(): profile[term] += count * weight
        for genre in movie.get('genres', []): genres[genre['id']] += weight
    pool = {}
    def add(items):
        for movie in items:
            mid = movie.get('id')
            if mid and mid not in excluded and movie.get('title') and movie.get('adult') is not True:
                pool[mid] = movie
    for mid in seeds[:3]:
        try: add(tmdb.similar_movies(mid))
        except tmdb.TMDBError: pass
    for gid in sorted(genres, key=lambda k: -genres[k])[:3]:
        try: add(tmdb.discover_movies(genre_id=gid))
        except tmdb.TMDBError: pass
    # Include movies liked by similar users even when TMDB does not list them as popular.
    for mid in sorted(cf_scores, key=lambda k: -cf_scores[k])[:25]:
        if mid in excluded or mid in pool:
            continue
        try:
            add([tmdb.get_movie_details(mid)])
        except tmdb.TMDBError:
            pass
    try: add(tmdb.popular_movies())
    except tmdb.TMDBError:
        if not pool: raise
    candidates = list(pool.values())[:180]
    if not candidates: return {'movies': [], 'cold_start': False, 'hybrid': False}
    content = cosine_scores(profile, candidates)
    maximum = max(genres.values(), default=1) or 1
    result = []
    for movie, sim in zip(candidates, content):
        affinity = max((genres.get(gid, 0) / maximum for gid in movie.get('genre_ids', [])), default=0)
        rating = max(0.0, min(float(movie.get('vote_average') or 0) / 10, 1))
        votes = max(0, int(movie.get('vote_count') or 0))
        quality = rating * min(1.0, log(1 + votes) / log(1001))
        content_score = 0.5 * sim + 0.3 * affinity + 0.2 * quality
        cf = cf_scores.get(movie['id'])
        # Blend only where CF has actual evidence; otherwise retain Phase 3.
        score = 0.65 * content_score + 0.35 * cf if cf is not None else content_score
        matching = [g.get('name', '') for d, _ in details for g in d.get('genres', []) if g.get('id') in movie.get('genre_ids', [])]
        reason = ('Người dùng có sở thích tương tự cũng đánh giá cao' if cf is not None
                  else 'Phù hợp thể loại ' + matching[0] if matching
                  else 'Nội dung gần với phim bạn quan tâm')
        result.append({'movie': movie, 'score': round(score * 100, 1), 'reason': reason,
                       'collaborative': cf is not None, 'support': cf_support.get(movie['id'], 0)})
    result.sort(key=lambda item: (-item['score'], item['movie']['id']))
    return {'movies': result[:limit], 'cold_start': False, 'hybrid': bool(cf_scores)}
