"""Personalized TMDB recommendations: TF-IDF cosine + genre preference + quality.
No training dataset required. Candidate retrieval and detailed metadata are cached by tmdb_service.
"""
import re
from collections import Counter, defaultdict
from math import log, sqrt

from . import tmdb_service as tmdb
from .collaborative_filtering import collaborative_scores
from .models import FavoriteMovie, MovieInteraction, MovieRating


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


def _favorite_movie_ids(user, limit=60):
    favorite_rows = FavoriteMovie.objects.filter(user=user).values_list(
        'tmdb_id', 'movie_title'
    )[:limit]
    favorite_ids = []
    legacy_titles = []
    for tmdb_id, title in favorite_rows:
        if tmdb_id is not None:
            favorite_ids.append(tmdb_id)
        else:
            legacy_titles.append(title)

    if legacy_titles and len(favorite_ids) < limit:
        from .views import _get_recommender

        recommender = _get_recommender()
        if recommender is not None:
            indices_by_title = {
                title.casefold(): index
                for title, index in recommender.title_to_idx.items()
            }
            for title in legacy_titles:
                index = indices_by_title.get(title.strip().casefold())
                if index is None:
                    continue
                try:
                    tmdb_id = int(recommender.metadata.iloc[int(index)]['id'])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if tmdb_id not in favorite_ids:
                    favorite_ids.append(tmdb_id)
                if len(favorite_ids) >= limit:
                    break

    return favorite_ids


def _offline_recommendations(seeds, excluded, limit):
    from .views import _get_recommender

    recommender = _get_recommender()
    if recommender is None:
        raise tmdb.TMDBError(
            'Model offline đang tải hoặc chưa sẵn sàng. Vui lòng thử lại sau.'
        )

    metadata = recommender.metadata
    results_by_id = {}
    for seed_id in seeds:
        source_rows = metadata[metadata['id'] == seed_id]
        if source_rows.empty:
            continue
        source_title = str(source_rows.iloc[0]['title'])
        result = recommender.get_recommendations(source_title, n=limit * 2)
        for movie in result.get('recommendations', []):
            movie_id = movie.get('id')
            if movie_id is None:
                continue
            try:
                movie_id = int(movie_id)
                score = float(movie.get('similarity_percent', 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if movie_id in excluded:
                continue

            item = {
                'movie': {
                    'id': movie_id,
                    'title': movie.get('title') or '',
                    'poster_url': movie.get('poster_url'),
                    'vote_average': movie.get('rating_value') or 0,
                },
                'score': score,
                'reason': f'Tương tự với {source_title}',
            }
            current = results_by_id.get(movie_id)
            if current is None or item['score'] > current['score']:
                results_by_id[movie_id] = item

    recommendations = sorted(
        results_by_id.values(),
        key=lambda item: (-item['score'], item['movie']['id']),
    )[:limit]
    if not recommendations:
        raise tmdb.TMDBError(
            'Không tìm thấy phim tương tự trong model offline. '
            'Cấu hình TMDB_ACCESS_TOKEN hoặc dùng model có chứa các phim yêu thích.'
        )
    return {
        'movies': recommendations,
        'cold_start': False,
        'hybrid': False,
    }


def recommend_for_favorites(user, limit=6):
    favorite_rows = list(
        FavoriteMovie.objects.filter(user=user).values_list('tmdb_id', 'movie_title')
    )
    if not favorite_rows:
        return []

    offline_model = None
    offline_model_checked = False

    def get_offline_model():
        nonlocal offline_model, offline_model_checked
        if not offline_model_checked:
            from .views import _get_recommender

            offline_model = _get_recommender()
            offline_model_checked = True
        return offline_model

    uses_tmdb = bool(tmdb.settings.TMDB_ACCESS_TOKEN)
    has_legacy_favorites = any(
        tmdb_id is None for tmdb_id, _ in favorite_rows
    )
    title_indices = {}
    if not uses_tmdb or has_legacy_favorites:
        offline_model = get_offline_model()
        if has_legacy_favorites and offline_model is not None:
            title_indices = {
                title.casefold(): index
                for title, index in offline_model.title_to_idx.items()
            }

    favorites = []
    for tmdb_id, title in favorite_rows:
        model_title = None
        if tmdb_id is None and offline_model is not None:
            index = title_indices.get(title.strip().casefold())
            if index is not None:
                row = offline_model.metadata.iloc[int(index)]
                tmdb_id = int(row['id'])
                model_title = str(row['title'])
        favorites.append({
            'id': tmdb_id,
            'title': title,
            'model_title': model_title,
            'error': None,
        })

    if uses_tmdb:
        for favorite in favorites:
            if favorite['id'] is not None:
                continue
            try:
                matches = tmdb.search_movies(favorite['title'])
            except tmdb.TMDBError as exc:
                favorite['error'] = str(exc)
                continue
            exact_match = next(
                (
                    movie for movie in matches
                    if str(movie.get('title') or '').casefold()
                    == favorite['title'].strip().casefold()
                ),
                None,
            )
            if exact_match and exact_match.get('id') is not None:
                favorite['id'] = int(exact_match['id'])

    favorite_ids = {
        favorite['id'] for favorite in favorites
        if favorite['id'] is not None
    }
    groups = []
    for favorite in favorites:
        candidates = []
        api_error = favorite['error']
        if uses_tmdb and favorite['id'] is not None:
            try:
                candidates = tmdb.similar_movies(favorite['id'])
            except tmdb.TMDBError as exc:
                api_error = str(exc)

        recommendations = []
        seen_ids = set(favorite_ids)
        if favorite['id'] is not None:
            seen_ids.add(favorite['id'])
        for movie in candidates:
            movie_id = movie.get('id')
            if movie_id is None:
                continue
            try:
                movie_id = int(movie_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if movie_id in seen_ids or movie.get('adult') is True:
                continue
            if not movie.get('title'):
                continue
            seen_ids.add(movie_id)
            recommendations.append({**movie, 'id': movie_id})
            if len(recommendations) == limit:
                break

        if not recommendations:
            offline_model = get_offline_model()
            if offline_model is not None:
                model_title = favorite['model_title']
                if model_title is None and favorite['id'] is not None:
                    source_rows = offline_model.metadata[
                        offline_model.metadata['id'] == favorite['id']
                    ]
                    if not source_rows.empty:
                        model_title = str(source_rows.iloc[0]['title'])
                if model_title:
                    offline_result = offline_model.get_recommendations(
                        model_title, n=limit * 2
                    )
                    for movie in offline_result.get('recommendations', []):
                        movie_id = movie.get('id')
                        if movie_id is None:
                            continue
                        try:
                            movie_id = int(movie_id)
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if movie_id in seen_ids:
                            continue
                        seen_ids.add(movie_id)
                        recommendations.append({
                            'id': movie_id,
                            'title': movie.get('title') or '',
                            'poster_url': movie.get('poster_url'),
                            'vote_average': movie.get('rating_value') or 0,
                        })
                        if len(recommendations) == limit:
                            break

        group = {
            'favorite_id': favorite['id'],
            'favorite_title': favorite['title'],
            'recommendations': recommendations,
            'error': None,
        }
        if not recommendations:
            if api_error:
                group['error'] = api_error
            elif offline_model is None:
                group['error'] = (
                    'Model offline đang tải hoặc chưa sẵn sàng. Vui lòng thử lại sau.'
                )
            else:
                group['error'] = 'Chưa tìm thấy phim tương tự cho phim yêu thích này.'
        groups.append(group)

    return groups


def recommend(user, limit=12):
    favorites = _favorite_movie_ids(user)
    ratings = dict(MovieRating.objects.filter(user=user).values_list('tmdb_id', 'rating')[:100])
    recent = list(MovieInteraction.objects.filter(user=user, action='detail').values_list('tmdb_id', flat=True)[:80])
    positive = defaultdict(float)
    for mid in favorites:
        positive[mid] += 3.0
    for mid, rating in ratings.items():
        if rating >= 4:
            positive[mid] += (rating - 2) * 1.5
    for mid in set(recent):
        positive[mid] += 0.25
    cf_scores, cf_support = collaborative_scores(user.pk)
    seeds = sorted(positive, key=lambda mid: -positive[mid])[:8]
    excluded = set(favorites) | set(ratings)
    if not seeds:
        movies = tmdb.popular_movies()[:limit]
        return {
            'movies': [
                {'movie': movie, 'score': None, 'reason': 'Phim phổ biến trên TMDB'}
                for movie in movies
            ],
            'cold_start': True,
            'hybrid': False,
        }
    if not tmdb.settings.TMDB_ACCESS_TOKEN:
        return _offline_recommendations(seeds, excluded, limit)

    details = []
    for mid in seeds:
        try:
            details.append((tmdb.get_movie_details(mid), positive[mid]))
        except tmdb.TMDBError:
            continue
    if not details:
        return _offline_recommendations(seeds, excluded, limit)
    profile = Counter()
    genres = defaultdict(float)
    for movie, weight in details:
        for term, count in tokens(movie).items():
            profile[term] += count * weight
        for genre in movie.get('genres', []):
            genres[genre['id']] += weight
    pool = {}

    def add(items):
        for movie in items:
            mid = movie.get('id')
            if mid and mid not in excluded and movie.get('title') and movie.get('adult') is not True:
                pool[mid] = movie

    for mid in seeds[:3]:
        try:
            add(tmdb.similar_movies(mid))
        except tmdb.TMDBError:
            pass
    for gid in sorted(genres, key=lambda k: -genres[k])[:3]:
        try:
            add(tmdb.discover_movies(genre_id=gid))
        except tmdb.TMDBError:
            pass
    # Include movies liked by similar users even when TMDB does not list them as popular.
    for mid in sorted(cf_scores, key=lambda k: -cf_scores[k])[:25]:
        if mid in excluded or mid in pool:
            continue
        try:
            add([tmdb.get_movie_details(mid)])
        except tmdb.TMDBError:
            pass
    try:
        add(tmdb.popular_movies())
    except tmdb.TMDBError:
        if not pool:
            raise
    candidates = list(pool.values())[:180]
    if not candidates:
        return _offline_recommendations(seeds, excluded, limit)
    content = cosine_scores(profile, candidates)
    maximum = max(genres.values(), default=1) or 1
    result = []
    for movie, sim in zip(candidates, content, strict=False):
        affinity = max((genres.get(gid, 0) / maximum for gid in movie.get('genre_ids', [])), default=0)
        rating = max(0.0, min(float(movie.get('vote_average') or 0) / 10, 1))
        votes = max(0, int(movie.get('vote_count') or 0))
        quality = rating * min(1.0, log(1 + votes) / log(1001))
        content_score = 0.5 * sim + 0.3 * affinity + 0.2 * quality
        cf = cf_scores.get(movie['id'])
        # Blend only where CF has actual evidence; otherwise retain Phase 3.
        score = 0.65 * content_score + 0.35 * cf if cf is not None else content_score
        matching = [
            genre.get('name', '')
            for detail, _ in details
            for genre in detail.get('genres', [])
            if genre.get('id') in movie.get('genre_ids', [])
        ]
        reason = (
            'Người dùng có sở thích tương tự cũng đánh giá cao'
            if cf is not None
            else 'Phù hợp thể loại ' + matching[0]
            if matching
            else 'Nội dung gần với phim bạn quan tâm'
        )
        result.append({
            'movie': movie,
            'score': round(score * 100, 1),
            'reason': reason,
            'collaborative': cf is not None,
            'support': cf_support.get(movie['id'], 0),
        })
    result.sort(key=lambda item: (-item['score'], item['movie']['id']))
    return {'movies': result[:limit], 'cold_start': False, 'hybrid': bool(cf_scores)}
