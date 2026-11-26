"""Public TMDB browse pages. No API secret is sent to the browser."""
from collections.abc import Callable
from datetime import date

from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import tmdb_service as tmdb
from .models import FavoriteMovie, MovieInteraction, MovieRating

MOVIES_PER_PAGE = 24
TMDB_PAGE_SIZE = 20
MAX_TMDB_PAGE = 500
MAX_BROWSE_PAGE = TMDB_PAGE_SIZE * MAX_TMDB_PAGE // MOVIES_PER_PAGE


def _page(value):
    try:
        return min(max(int(value), 1), MAX_BROWSE_PAGE)
    except (TypeError, ValueError):
        return 1


def _page_movies(fetch_page: Callable[[int], list[dict]], page: int) -> list[dict]:
    offset = (page - 1) * MOVIES_PER_PAGE
    api_page, offset = divmod(offset, TMDB_PAGE_SIZE)
    api_page += 1
    movies = []
    while len(movies) < MOVIES_PER_PAGE and api_page <= MAX_TMDB_PAGE:
        batch = fetch_page(api_page)
        if not batch:
            break
        movies.extend(batch[offset:])
        if len(batch) < TMDB_PAGE_SIZE:
            break
        api_page += 1
        offset = 0
    return movies[:MOVIES_PER_PAGE]


TMDB_GENRES = (
    (28, 'Action'),
    (12, 'Adventure'),
    (16, 'Animation'),
    (35, 'Comedy'),
    (80, 'Crime'),
    (99, 'Documentary'),
    (18, 'Drama'),
    (10751, 'Family'),
    (14, 'Fantasy'),
    (36, 'History'),
    (27, 'Horror'),
    (10402, 'Music'),
    (9648, 'Mystery'),
    (10749, 'Romance'),
    (878, 'Science Fiction'),
    (10770, 'TV Movie'),
    (53, 'Thriller'),
    (10752, 'War'),
    (37, 'Western'),
)


def _genre_key(value):
    return ''.join(char for char in str(value).lower() if char.isalnum())


def _imdb_id(value):
    value = str(value).strip() if value is not None else ''
    return value if value.startswith('tt') and value[2:].isdigit() else ''


def get_offline_movie_details(tmdb_id):
    from .views import _get_recommender

    recommender = _get_recommender()
    if recommender is None:
        return None
    match = recommender.metadata[recommender.metadata['id'] == tmdb_id]
    if match.empty:
        return None

    movie = match.iloc[0]
    raw_genres = movie.get('genres')
    if hasattr(raw_genres, 'tolist'):
        genres = raw_genres.tolist()
    elif isinstance(raw_genres, (list, tuple)):
        genres = list(raw_genres)
    else:
        genres = []
    return {
        'id': int(movie['id']),
        'title': str(movie['title']),
        'imdb_id': _imdb_id(movie.get('imdb_id')),
        'release_date': str(movie.get('release_date') or ''),
        'poster_path': str(movie.get('poster_path') or ''),
        'vote_average': float(movie.get('vote_average') or 0),
        'vote_count': int(movie.get('vote_count') or 0),
        'genres': [{'name': str(item).replace('sciencefiction', 'Science Fiction').title()} for item in genres],
        'runtime': None,
        'overview': str(movie.get('overview') or ''),
    }


@require_GET
def browse(request):
    query = request.GET.get('q', '').strip()[:120]
    genre = request.GET.get('genre', '').strip()
    year = request.GET.get('year', '').strip()
    page = _page(request.GET.get('page'))
    genre = genre if genre.isdigit() and len(genre) <= 8 else ''
    year = (
        year if len(year) == 4 and year.isascii() and year.isdigit()
        and 1900 <= int(year) <= date.today().year + 3 else ''
    )
    context = {'query': query, 'selected_genre': genre, 'year': year, 'page': page,
               'movies': [], 'genres': [], 'error': None, 'mode': 'popular'}
    if not tmdb.settings.TMDB_ACCESS_TOKEN:
        from .views import _get_recommender, _model_state

        recommender = _get_recommender()
        if recommender is None:
            state = _model_state()
            context['fallback_loading'] = state['status'] == 'loading'
            context['fallback'] = (
                'Đang tải danh sách phim offline...'
                if context['fallback_loading']
                else 'Chưa có danh sách phim offline. Hãy cấu hình TMDB_ACCESS_TOKEN để duyệt phim.'
            )
            if not context['fallback_loading']:
                context['error'] = context['fallback']
            return render(request, 'recommender/tmdb_browse.html', context)

        metadata = recommender.metadata
        context['genres'] = [{'id': genre_id, 'name': name} for genre_id, name in TMDB_GENRES]
        genre_names_by_id = {str(genre_id): name for genre_id, name in TMDB_GENRES}
        rows = []
        for _, movie in metadata.iterrows():
            title = str(movie.get('title') or '')
            release_date = str(movie.get('release_date') or '')
            if query and query.lower() not in title.lower():
                continue
            if year and not release_date.startswith(year):
                continue

            raw_genres = movie.get('genres')
            if hasattr(raw_genres, 'tolist'):
                genres = raw_genres.tolist()
            elif isinstance(raw_genres, (list, tuple)):
                genres = list(raw_genres)
            else:
                genres = []
            if genre:
                selected_name = genre_names_by_id.get(genre)
                if not selected_name:
                    continue
                selected_key = _genre_key(selected_name)
                movie_genre_keys = {_genre_key(item) for item in genres}
                if selected_key not in movie_genre_keys:
                    continue

            poster_path = movie.get('poster_path')
            rows.append({
                'id': int(movie['id']),
                'title': title,
                'imdb_id': _imdb_id(movie.get('imdb_id')),
                'release_date': release_date,
                'poster_path': str(poster_path) if poster_path else '',
                'vote_average': float(movie.get('vote_average') or 0),
                'vote_count': int(movie.get('vote_count') or 0),
                'genres': [{'name': str(item).replace('sciencefiction', 'Science Fiction').title()} for item in genres],
                'overview': str(movie.get('overview') or ''),
            })

        if not query and not year and not genre:
            rows.sort(key=lambda item: item['vote_count'], reverse=True)
        context['mode'] = 'search' if query else ('discover' if genre or year else 'popular')
        start = (page - 1) * MOVIES_PER_PAGE
        context['movies'] = rows[start:start + MOVIES_PER_PAGE]
        return render(request, 'recommender/tmdb_browse.html', context)

    try:
        context['genres'] = tmdb.movie_genres()
        if query:
            context['mode'] = 'search'
            context['movies'] = _page_movies(
                lambda api_page: tmdb.search_movies(query, api_page), page
            )
        elif genre or year:
            context['mode'] = 'discover'
            context['movies'] = _page_movies(
                lambda api_page: tmdb.discover_movies(genre, year, api_page), page
            )
        else:
            context['movies'] = _page_movies(tmdb.popular_movies, page)
            if page == 1:
                context['trending'] = tmdb.trending_movies()[:8]
    except tmdb.TMDBError as exc:
        context['error'] = str(exc)
    return render(request, 'recommender/tmdb_browse.html', context)


def _set_movie_user_context(request, context, tmdb_id):
    if not request.user.is_authenticated:
        return
    context['is_favorite'] = FavoriteMovie.objects.filter(user=request.user, tmdb_id=tmdb_id).exists()
    context['my_rating'] = MovieRating.objects.filter(
        user=request.user, tmdb_id=tmdb_id
    ).values_list('rating', flat=True).first()
    MovieInteraction.objects.create(user=request.user, tmdb_id=tmdb_id, action='detail')


@require_GET
def detail(request, tmdb_id):
    context = {'movie': None, 'similar': [], 'error': None}
    if not tmdb.settings.TMDB_ACCESS_TOKEN:
        context['movie'] = get_offline_movie_details(tmdb_id)
        if context['movie']:
            _set_movie_user_context(request, context, tmdb_id)
            return render(request, 'recommender/tmdb_detail.html', context)

    try:
        context['movie'] = tmdb.get_movie_details(tmdb_id)
    except tmdb.TMDBError as exc:
        context['error'] = str(exc)
    if context['movie']:
        _set_movie_user_context(request, context, tmdb_id)
    return render(request, 'recommender/tmdb_detail.html', context)
