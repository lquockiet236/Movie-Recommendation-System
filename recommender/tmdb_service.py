"""TMDB API integration. API credentials stay server-side."""
from datetime import date
import logging
import requests
from django.conf import settings
from django.core.cache import cache

from .models import Movie

logger = logging.getLogger(__name__)
BASE_URL = 'https://api.themoviedb.org/3'

class TMDBError(Exception):
    """Safe error displayed when TMDB cannot be reached."""


def tmdb_get(endpoint, params=None, cache_seconds=900):
    token = getattr(settings, 'TMDB_ACCESS_TOKEN', '')
    if not token:
        raise TMDBError('Chưa cấu hình TMDB_ACCESS_TOKEN. Xem HUONG_DAN_TMDB.md.')
    if not endpoint.startswith('/') or endpoint.startswith('//'):
        raise ValueError('Invalid TMDB endpoint')
    parameters = {'language': 'vi-VN', **(params or {})}
    cache_key = 'tmdb:v1:' + endpoint + ':' + repr(sorted(parameters.items()))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        response = requests.get(
            BASE_URL + endpoint,
            headers={'Authorization': f'Bearer {token}', 'accept': 'application/json'},
            params=parameters, timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('TMDB request failed for %s: %s', endpoint, type(exc).__name__)
        raise TMDBError('Không thể tải dữ liệu từ TMDB. Vui lòng thử lại sau.') from exc
    if cache_seconds:
        cache.set(cache_key, data, cache_seconds)
    return data


def search_movies(movie_name, page=1):
    return tmdb_get('/search/movie', {'query': movie_name, 'page': page, 'include_adult': 'false'}).get('results', [])


def popular_movies(page=1):
    return tmdb_get('/movie/popular', {'page': page}).get('results', [])


def trending_movies():
    return tmdb_get('/trending/movie/week').get('results', [])


def discover_movies(genre_id=None, year=None, page=1):
    params = {'page': page, 'sort_by': 'popularity.desc', 'include_adult': 'false'}
    if genre_id:
        params['with_genres'] = genre_id
    if year:
        params['primary_release_year'] = year
    return tmdb_get('/discover/movie', params).get('results', [])


def movie_genres():
    return tmdb_get('/genre/movie/list', cache_seconds=86400).get('genres', [])


def get_movie_details(tmdb_id):
    return tmdb_get(f'/movie/{int(tmdb_id)}', {'append_to_response': 'keywords,credits'})


def similar_movies(tmdb_id):
    return tmdb_get(f'/movie/{int(tmdb_id)}/similar').get('results', [])


def save_movie_from_tmdb(tmdb_id):
    data = get_movie_details(tmdb_id)
    release_date = data.get('release_date')
    try:
        parsed_date = date.fromisoformat(release_date) if release_date else None
    except ValueError:
        parsed_date = None
    keywords = data.get('keywords', {})
    movie, created = Movie.objects.update_or_create(
        tmdb_id=data['id'],
        defaults={
            'title': data.get('title') or '',
            'overview': data.get('overview') or '',
            'genres': [g['name'] for g in data.get('genres', [])],
            'keywords': [k['name'] for k in keywords.get('keywords', keywords.get('results', []))],
            'release_date': parsed_date,
            'poster_path': data.get('poster_path') or '',
            'vote_average': data.get('vote_average') or 0,
            'vote_count': data.get('vote_count') or 0,
        },
    )
    return movie, created
