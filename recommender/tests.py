"""
Tests for the Movie Recommendation System.

The recommender is backed by model files on disk, so the suite builds a tiny
synthetic model in a temporary directory and points MODEL_DIR at it. That keeps
the tests fast and means they exercise the real loading path -- parquet list
columns included, since those are a common source of subtle breakage.
"""
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import tmdb_views, views
from .models import FavoriteMovie, Movie, MovieInteraction, MovieRating, SearchHistory

# Tests run with DEBUG=False, where the manifest static storage insists on a
# collectstatic manifest that does not exist in a source checkout. Swap in the
# plain backend so templates can resolve {% static %} during tests.
TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

MOVIES = [
    # title, company, genres, rating, votes, imdb_id, poster
    ("The Matrix", "Warner Bros.", ["Action", "Science Fiction"], 8.2, 24000, "tt0133093", "/matrix.jpg"),
    ("The Matrix Reloaded", "Warner Bros.", ["Action", "Science Fiction"], 7.0, 12000, "tt0234215", "/reloaded.jpg"),
    ("Inception", "Legendary Pictures", ["Action", "Thriller"], 8.4, 35000, "tt1375666", "/inception.jpg"),
    ("Interstellar", "Legendary Pictures", ["Adventure", "Drama"], 8.4, 33000, "tt0816692", None),
    ("Tom & Jerry", "Warner Bros.", ["Comedy", "Family"], 7.0, 3000, "tt1361336", "/tomjerry.jpg"),
    ("A Quiet Place", "Platinum Dunes", ["Horror", "Thriller"], 7.4, 9000, None, None),
]


def build_model(directory: Path, with_neighbors: bool = False) -> Path:
    """Write a minimal but complete set of model artifacts to `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    n = len(MOVIES)

    frame = pd.DataFrame({
        'id': list(range(1, n + 1)),
        'title': [m[0] for m in MOVIES],
        'release_date': ['1999-03-30', '2003-05-15', '2010-07-16', '2014-11-05', '2021-02-11', '2018-04-03'],
        'primary_company': [m[1] for m in MOVIES],
        'genres': [m[2] for m in MOVIES],
        'vote_average': [m[3] for m in MOVIES],
        'vote_count': [m[4] for m in MOVIES],
        'popularity': [10.0] * n,
        'overview': [f"Synthetic overview for {m[0]}. " * 6 for m in MOVIES],
        'imdb_id': [m[5] for m in MOVIES],
        'poster_path': [m[6] for m in MOVIES],
    })
    frame.to_parquet(directory / 'movie_metadata.parquet', index=True)

    # Deterministic similarity: adjacent indices are the most similar.
    similarity = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            similarity[i, j] = 1.0 if i == j else max(0.05, 1.0 - abs(i - j) * 0.15)

    if with_neighbors:
        order = np.argsort(-similarity, axis=1)[:, 1:4]
        np.save(directory / 'neighbors_idx.npy', order.astype(np.int32))
        np.save(directory / 'neighbors_scores.npy',
                np.take_along_axis(similarity, order, axis=1).astype(np.float32))
    else:
        np.save(directory / 'similarity_matrix.npy', similarity)

    with open(directory / 'title_to_idx.json', 'w', encoding='utf-8') as handle:
        json.dump({m[0]: i for i, m in enumerate(MOVIES)}, handle)

    with open(directory / 'config.json', 'w', encoding='utf-8') as handle:
        json.dump({'n_movies': n, 'use_svd': False, 'dataset': 'synthetic-test'}, handle)

    return directory


def wait_until_ready(timeout: float = 20.0) -> str:
    """Block until the background loader settles, then report its status."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = views._model_state()['status']
        if status != 'loading':
            return status
        time.sleep(0.02)
    return views._model_state()['status']


class ModelBackedTestCase(SimpleTestCase):
    """Base case with a loaded synthetic model. No database is involved."""

    with_neighbors = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_dir = Path(tempfile.mkdtemp(prefix='movie-model-'))
        build_model(cls.model_dir, with_neighbors=cls.with_neighbors)
        cls._settings = override_settings(MODEL_DIR=cls.model_dir, STORAGES=TEST_STORAGES)
        cls._settings.enable()
        views._reset_for_tests()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        views._reset_for_tests()
        shutil.rmtree(cls.model_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client()
        views._start_model_loading()
        self.assertEqual(wait_until_ready(), 'ready')


class RecommenderCoreTests(ModelBackedTestCase):
    def test_model_loads_movie_count(self):
        self.assertEqual(views._get_recommender().movie_count, len(MOVIES))

    def test_exact_title_match_is_case_insensitive(self):
        recommender = views._get_recommender()
        self.assertEqual(recommender.find_movie('the matrix'), 'The Matrix')
        self.assertEqual(recommender.find_movie('  INCEPTION  '), 'Inception')

    def test_prefix_match_prefers_the_shorter_title(self):
        # "The Matrix" must win over "The Matrix Reloaded".
        self.assertEqual(views._get_recommender().find_movie('The Matrix R'),
                         'The Matrix Reloaded')
        self.assertEqual(views._get_recommender().find_movie('Matrix'), 'The Matrix')

    def test_fuzzy_match_handles_typos(self):
        self.assertEqual(views._get_recommender().find_movie('Inceptoin'), 'Inception')

    def test_unknown_title_returns_none(self):
        self.assertIsNone(views._get_recommender().find_movie('zzzzz nonexistent film'))

    def test_genres_survive_the_parquet_round_trip(self):
        """Parquet list columns load as numpy arrays, not Python lists."""
        result = views._get_recommender().get_recommendations('The Matrix', n=3)
        for movie in result['recommendations']:
            self.assertNotEqual(movie['genres'], 'N/A', movie['title'])
        self.assertIn('Action', result['source_movie']['genres'])

    def test_recommendations_exclude_the_source_and_are_ranked(self):
        result = views._get_recommender().get_recommendations('The Matrix', n=4)
        titles = [m['title'] for m in result['recommendations']]
        self.assertNotIn('The Matrix', titles)
        self.assertEqual(len(titles), 4)
        scores = [float(m['similarity_score']) for m in result['recommendations']]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_min_rating_filter(self):
        result = views._get_recommender().get_recommendations(
            'The Matrix', n=5, min_rating=8.0)
        for movie in result['recommendations']:
            self.assertGreaterEqual(movie['rating_value'], 8.0)

    def test_suggestions_are_offered_when_nothing_matches(self):
        """A failed search must still give the visitor somewhere to go."""
        recommender = views._get_recommender()
        query = 'Jerry and friends adventure'
        self.assertIsNone(recommender.find_movie(query))
        self.assertIn('Tom & Jerry', recommender.suggest(query))

    def test_unknown_movie_returns_suggestions(self):
        result = views._get_recommender().get_recommendations('Matri', n=5)
        self.assertNotIn('error', result)  # substring match resolves it

        result = views._get_recommender().get_recommendations('qqqq', n=5)
        self.assertIn('error', result)
        self.assertIn('suggestions', result)

    def test_links_are_url_encoded(self):
        payload = views._get_recommender()._movie_payload(4, 0.5)  # "Tom & Jerry"
        self.assertEqual(payload['title'], 'Tom & Jerry')
        self.assertNotIn(' ', payload['google_link'])
        self.assertNotIn('&', payload['google_link'].split('?q=')[1])
        self.assertEqual(payload['imdb_link'], 'https://www.imdb.com/title/tt1361336/')

    def test_missing_imdb_id_yields_no_link(self):
        payload = views._get_recommender()._movie_payload(5, 0.5)  # "A Quiet Place"
        self.assertIsNone(payload['imdb_link'])
        self.assertIsNone(payload['poster_url'])

    def test_poster_url_is_built_for_movies_that_have_one(self):
        payload = views._get_recommender()._movie_payload(0, 0.9)
        self.assertEqual(payload['poster_url'],
                         'https://image.tmdb.org/t/p/w342/matrix.jpg')

    def test_search_ranks_prefix_before_substring(self):
        results = views._get_recommender().search_movies('matrix')
        self.assertEqual(results[0], 'The Matrix')

    def test_year_is_extracted(self):
        payload = views._get_recommender()._movie_payload(0, 0.9)
        self.assertEqual(payload['year'], '1999')


class NeighborFileTests(ModelBackedTestCase):
    """The same behaviour must hold for pre-computed top-K neighbour files."""

    with_neighbors = True

    def test_recommendations_from_neighbor_files(self):
        result = views._get_recommender().get_recommendations('The Matrix', n=3)
        titles = [m['title'] for m in result['recommendations']]
        self.assertNotIn('The Matrix', titles)
        self.assertEqual(titles[0], 'The Matrix Reloaded')


class ViewTests(ModelBackedTestCase):
    def test_login_page_uses_signup_account_layout(self):
        response = self.client.get('/accounts/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="account-main signup-card"')
        self.assertContains(response, 'class="signup-header"')
        self.assertContains(response, 'class="signup-mark"')
        self.assertContains(response, 'class="account-form"')
        self.assertContains(response, '.account-form button{width:100%;margin-top:4px}')
        self.assertContains(response, 'class="signup-footer"')

    @override_settings(TMDB_ACCESS_TOKEN='')
    def test_browse_filters_render_all_controls_in_the_responsive_form(self):
        response = self.client.get('/movies/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="browse-filters"')
        self.assertContains(response, '<footer class="site-footer">© ')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'role="combobox"')
        self.assertContains(response, 'aria-controls="browseMovieSuggestions"')
        self.assertContains(response, 'role="listbox"')
        self.assertContains(response, 'name="genre"')
        self.assertContains(response, 'class="browse-genre-toggle"')
        self.assertContains(response, 'id="browseGenreOptions"')
        self.assertContains(response, '.browse-genre-menu[hidden]{display:none}')
        self.assertContains(response, 'name="year"')
        self.assertContains(response, 'type="text" inputmode="numeric" pattern="[0-9]{4}"')
        self.assertContains(response, 'maxlength="4"')
        self.assertContains(response, 'aria-label="Năm" autocomplete="off"')
        self.assertContains(response, 'aria-describedby="browseYearError"')
        self.assertContains(response, 'id="browseYearError" role="alert"')
        self.assertContains(response, '.browse-year-error{position:absolute')
        self.assertContains(response, 'Không tìm thấy phim.')

    @override_settings(TMDB_ACCESS_TOKEN='')
    def test_browse_year_filter_requires_four_ascii_digits(self):
        for year in ('199', '01999', '20x0', '２０２０'):
            with self.subTest(year=year):
                response = self.client.get('/movies/', {'year': year})
                self.assertEqual(response.context['year'], '')

        response = self.client.get('/movies/', {'year': '2020'})
        self.assertEqual(response.context['year'], '2020')

    @override_settings(TMDB_ACCESS_TOKEN='')
    def test_empty_browse_message_spans_the_movie_grid(self):
        response = self.client.get('/movies/', {'q': 'no matching movie'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="muted tmdb-empty-message"')
        self.assertContains(response, '.tmdb-empty-message{grid-column:1/-1;white-space:nowrap}')

    def test_browse_page_fills_24_movies_across_tmdb_pages(self):
        requested_pages = []

        def fetch_page(page):
            requested_pages.append(page)
            first_id = (page - 1) * 20 + 1
            return [{'id': movie_id} for movie_id in range(first_id, first_id + 20)]

        movies = tmdb_views._page_movies(fetch_page, page=1)

        self.assertEqual(len(movies), 24)
        self.assertEqual([movie['id'] for movie in movies], list(range(1, 25)))
        self.assertEqual(requested_pages, [1, 2])

    def test_following_browse_page_does_not_repeat_movies(self):
        def fetch_page(page):
            first_id = (page - 1) * 20 + 1
            return [{'id': movie_id} for movie_id in range(first_id, first_id + 20)]

        movies = tmdb_views._page_movies(fetch_page, page=2)

        self.assertEqual([movie['id'] for movie in movies], list(range(25, 49)))

    def test_signup_page_uses_account_creation_layout(self):
        response = self.client.get('/accounts/signup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tạo tài khoản mới')
        self.assertContains(response, 'Tối thiểu 8 ký tự')
        self.assertContains(response, 'autocomplete="new-password"')
        self.assertContains(response, 'class="account-main signup-card"')

    @override_settings(TMDB_ACCESS_TOKEN='')
    @patch.object(views.MovieRecommender, 'get_recommendations')
    def test_root_redirects_to_canonical_movie_browse_path(self, get_recommendations):
        response = self.client.get('/?q=matrix')
        self.assertRedirects(response, '/movies/?q=matrix', fetch_redirect_response=False)

        browse_response = self.client.get(response['Location'])
        self.assertContains(browse_response, 'Khám phá phim')
        self.assertContains(browse_response, 'The Matrix')
        get_recommendations.assert_not_called()

    @patch('recommender.views._get_recommender')
    def test_recommendation_form_does_not_load_model_until_used(self, get_recommender):
        response = self.client.get('/recommendation')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CineRec')
        self.assertContains(response, 'role="combobox"')
        self.assertContains(response, 'id="movieSuggestionsList"')
        self.assertNotContains(response, '<datalist')
        self.assertNotContains(response, 'Gợi ý chỉ được tạo sau khi bạn nhấn nút')
        get_recommender.assert_not_called()

    @override_settings(TMDB_ACCESS_TOKEN='')
    @patch.object(views.MovieRecommender, 'get_recommendations')
    def test_movie_detail_does_not_generate_similar_movies_automatically(self, get_recommendations):
        response = self.client.get('/movies/1/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tìm phim tương tự')
        self.assertNotContains(response, 'Chi tiết offline từ model demo.')
        self.assertNotContains(response, 'This product uses the TMDB API but is not endorsed or certified by TMDB.')
        get_recommendations.assert_not_called()

    def test_post_returns_recommendation_cards(self):
        response = self.client.post('/', {'movie_name': 'The Matrix'})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertTrue('The Matrix Reloaded' in body, 'recommendation missing')
        self.assertTrue('image.tmdb.org' in body, 'posters are not rendered')

    def test_recommendation_page_generates_results_after_submission(self):
        response = self.client.post('/recommendation', {'movie_name': 'The Matrix'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The Matrix Reloaded')
        self.assertContains(response, 'class="topbar"')
        self.assertContains(response, 'aria-label="Điều hướng chính"')
        self.assertNotContains(response, 'class="account-nav"')
        self.assertContains(response, 'href="/recommendation" class="back-button">← New search</a>')
        self.assertContains(response, '.logout-button{min-height:38px')
        self.assertContains(response, '.header{position:relative;top:auto;z-index:auto')
        self.assertContains(response, '<footer class="site-footer">© ')
        self.assertContains(response, 'CineRec</footer>')
        self.assertNotContains(response, 'Made with')
        self.assertNotContains(response, 'Movie data and images from')

    def test_post_with_blank_input_shows_a_message(self):
        response = self.client.post('/', {'movie_name': '   '})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Vui lòng nhập tên phim', response.content.decode())

    def test_post_with_a_near_miss_still_finds_the_movie(self):
        """Typos should resolve rather than dead-end the visitor."""
        response = self.client.post('/', {'movie_name': 'Matrx Reloded'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue('Movies like' in response.content.decode(),
                        'expected the results page')

    def test_post_with_unknown_movie_shows_an_explanation(self):
        response = self.client.post('/', {'movie_name': 'zzzz not a film zzzz'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue("couldn" in response.content.decode().lower(),
                        'expected a not-found message')

    def test_failed_search_renders_clickable_suggestions(self):
        response = self.client.post('/', {'movie_name': 'Jerry and friends adventure'})
        body = response.content.decode()
        self.assertTrue('Có phải bạn đang tìm' in body, 'suggestions block missing')
        self.assertTrue('suggestion-chip' in body, 'suggestion chips missing')
        self.assertTrue('Tom &amp; Jerry' in body, 'expected suggestion not rendered')

    def test_overlong_query_is_truncated_not_rejected(self):
        response = self.client.post('/', {'movie_name': 'The Matrix' + 'x' * 5000})
        self.assertEqual(response.status_code, 200)

    def test_put_is_rejected(self):
        self.assertEqual(self.client.put('/').status_code, 405)

    def test_search_api(self):
        response = self.client.get('/api/search/', {'q': 'matrix'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['movies'][0], 'The Matrix')
        self.assertEqual(payload['count'], len(payload['movies']))

        fuzzy_payload = self.client.get('/api/search/', {'q': 'Matrx Reloded'}).json()
        self.assertEqual(fuzzy_payload['movies'][0], 'The Matrix Reloaded')

    def test_search_api_ignores_short_queries(self):
        payload = self.client.get('/api/search/', {'q': 'm'}).json()
        self.assertEqual(payload, {'movies': [], 'count': 0})

    def test_search_api_is_cached_between_calls(self):
        first = self.client.get('/api/search/', {'q': 'matrix'}).json()
        second = self.client.get('/api/search/', {'q': 'MATRIX'}).json()
        self.assertEqual(first['movies'], second['movies'])

    def test_model_status_reports_ready(self):
        payload = self.client.get('/api/model-status/').json()
        self.assertTrue(payload['loaded'])
        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['progress'], 100)

    def test_health_check_is_healthy(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'healthy')
        self.assertEqual(payload['movies_loaded'], len(MOVIES))

    def test_poster_layering_is_declared(self):
        """Guard the poster/badge stacking order.

        The placeholder icon is absolutely positioned, so without explicit
        z-index the artwork renders underneath it -- a bug that is invisible
        until real posters actually load.
        """
        css = self.client.post('/', {'movie_name': 'The Matrix'}).content.decode()
        poster = css.index('.poster {')
        badge = css.index('.movie-rank {')
        self.assertIn('z-index: 1', css[poster:poster + 800])
        self.assertIn('z-index: 2', css[badge:badge + 300])

    def test_custom_404_page_is_rendered(self):
        with self.settings(DEBUG=False):
            response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        body = response.content.decode()
        self.assertTrue('Page not found' in body, 'custom 404 title missing')
        self.assertTrue('Back to the movies' in body, 'no way back from the 404')
        self.assertIn('<footer class="site-footer">© ', body)

    def test_favicon_redirects(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 301)
        self.assertIn('logo.ico', response['Location'])


@override_settings(STORAGES=TEST_STORAGES)
class SearchHistoryRemovalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='viewer', password='test-password'
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_history_pages_are_removed(self):
        self.assertEqual(self.client.get('/history/').status_code, 404)
        self.assertEqual(self.client.post('/history/clear/').status_code, 404)

    def test_recommendation_search_does_not_save_history(self):
        recommender = Mock()
        recommender.get_recommendations.return_value = {
            'query_movie': 'The Matrix',
            'source_movie': {},
            'recommendations': [],
        }

        with patch.object(views, '_get_recommender', return_value=recommender):
            response = self.client.post('/recommendation', {'movie_name': 'The Matrix'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SearchHistory.objects.exists())

    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    @patch.object(tmdb_views.tmdb, 'movie_genres', return_value=[])
    @patch.object(tmdb_views.tmdb, 'search_movies', return_value=[])
    def test_tmdb_search_does_not_save_history(self, movie_genres, search_movies):
        response = self.client.get('/movies/', {'q': 'matrix'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SearchHistory.objects.exists())
        search_movies.assert_called_once()
        movie_genres.assert_called_once()


@override_settings(STORAGES=TEST_STORAGES)
class FavoriteFunctionalityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='favorite-viewer', password='test-password'
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.metadata = pd.DataFrame([
            {
                'id': tmdb_id,
                'title': 'Same Title',
                'poster_path': '/same-title.jpg',
                'release_date': '2020-01-01',
                'vote_average': 8.0,
                'vote_count': 100,
                'genres': ['Drama'],
                'overview': 'An offline movie.',
            }
            for tmdb_id in (42, 43)
        ])

    @override_settings(TMDB_ACCESS_TOKEN='')
    @patch('recommender.views._get_recommender')
    def test_offline_tmdb_movies_can_be_added_and_shown_as_favorites(self, get_recommender):
        get_recommender.return_value = Mock(metadata=self.metadata)

        for tmdb_id in (42, 43):
            response = self.client.post(f'/movies/{tmdb_id}/favorite/')
            self.assertEqual(response.status_code, 302)

        self.assertEqual(FavoriteMovie.objects.filter(user=self.user).count(), 2)
        self.assertSetEqual(
            set(FavoriteMovie.objects.filter(user=self.user).values_list('tmdb_id', flat=True)),
            {42, 43},
        )
        response = self.client.get('/movies/42/')
        self.assertContains(response, 'Bỏ yêu thích')
        self.assertTrue(
            MovieInteraction.objects.filter(
                user=self.user, tmdb_id=42, action='detail'
            ).exists()
        )

    def test_removing_tmdb_favorite_from_favorites_stays_on_favorites(self):
        favorite = FavoriteMovie.objects.create(
            user=self.user, tmdb_id=42, movie_title='Same Title'
        )
        favorites_response = self.client.get('/favorites/')
        self.assertContains(favorites_response, 'name="return_to" value="favorites"')

        response = self.client.post(
            '/movies/42/favorite/',
            {'return_to': 'favorites'},
        )

        self.assertRedirects(response, '/favorites/', fetch_redirect_response=False)
        self.assertFalse(FavoriteMovie.objects.filter(pk=favorite.pk).exists())
        self.assertTrue(
            MovieInteraction.objects.filter(
                user=self.user, tmdb_id=42, action='unfavorite'
            ).exists()
        )


@override_settings(STORAGES=TEST_STORAGES, TMDB_ACCESS_TOKEN='test-token')
class NavigationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='navigation-viewer', password='test-password'
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_movies_and_favorites_share_the_same_navigation(self):
        with (
            patch.object(tmdb_views.tmdb, 'movie_genres', return_value=[]),
            patch.object(tmdb_views.tmdb, 'popular_movies', return_value=[]),
            patch.object(tmdb_views.tmdb, 'trending_movies', return_value=[]),
        ):
            movies_response = self.client.get('/movies/')
        favorites_response = self.client.get('/favorites/')

        nav_pattern = r'<nav class="nav-inner"[^>]*>(.*?)</nav>'
        movies_nav = re.search(nav_pattern, movies_response.content.decode(), re.DOTALL)
        favorites_nav = re.search(nav_pattern, favorites_response.content.decode(), re.DOTALL)
        self.assertIsNotNone(movies_nav)
        self.assertIsNotNone(favorites_nav)
        self.assertEqual(
            re.findall(r'<a[^>]+href="([^"]+)"', movies_nav.group(1)),
            re.findall(r'<a[^>]+href="([^"]+)"', favorites_nav.group(1)),
        )
        self.assertNotContains(movies_response, 'Tương tác')
        self.assertNotContains(favorites_response, 'Tương tác')

    def test_interactions_page_is_removed(self):
        self.assertEqual(self.client.get('/interactions/').status_code, 404)

    def test_recommendation_results_use_the_shared_logged_in_navigation(self):
        response = self.client.post('/recommendation', {'movie_name': 'The Matrix'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="logout-button"')
        self.assertContains(response, 'Gợi ý cho bạn')
        self.assertContains(response, 'Yêu thích')

    @patch(
        'recommender.recommendation_views.recommend',
        side_effect=tmdb_views.tmdb.TMDBError(
            'Không thể tải thông tin các phim bạn đã tương tác.'
        ),
    )
    def test_unavailable_seed_movie_notice_is_hidden(self, recommend):
        response = self.client.get('/for-you/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gợi ý dành cho bạn')
        self.assertNotContains(response, 'Không thể tải thông tin các phim bạn đã tương tác.')
        self.assertNotContains(response, 'Chưa có phim gợi ý.')
        self.assertNotContains(response, 'Điểm phù hợp là điểm xếp hạng nội bộ')

    @patch(
        'recommender.recommendation_views.recommend',
        side_effect=tmdb_views.tmdb.TMDBError('Lỗi TMDB khác.'),
    )
    def test_other_recommendation_errors_remain_visible(self, recommend):
        response = self.client.get('/for-you/')

        self.assertContains(response, 'Lỗi TMDB khác.')

    def test_empty_favorites_page_does_not_show_an_empty_state_panel(self):
        response = self.client.get('/favorites/')

        self.assertContains(response, 'Phim yêu thích')
        self.assertNotContains(response, 'favorite-empty')
        self.assertNotContains(response, 'Danh sách của bạn đang trống')

    def test_favorite_is_rendered_as_a_movie_card(self):
        FavoriteMovie.objects.create(
            user=self.user,
            movie_title='The Matrix',
            tmdb_id=603,
            poster_path='/matrix.jpg',
        )

        response = self.client.get('/favorites/')

        self.assertContains(response, 'class="favorite-card"')
        self.assertContains(response, 'alt="Poster The Matrix"')
        self.assertContains(response, 'Xem chi tiết')
        self.assertContains(response, 'Bỏ lưu')

    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    @patch.object(tmdb_views.tmdb, 'get_movie_details')
    def test_guest_detail_action_toolbar_fits_its_buttons(self, get_movie_details):
        get_movie_details.return_value = {
            'id': 603,
            'title': 'The Matrix',
            'release_date': '1999-03-30',
            'poster_path': '/matrix.jpg',
            'vote_average': 8.7,
            'vote_count': 1000,
            'genres': [],
            'runtime': 136,
            'overview': 'A test movie.',
        }
        self.client.logout()

        response = self.client.get('/movies/603/')

        self.assertContains(response, 'class="action-toolbar action-toolbar-guest"')
        self.assertContains(
            response,
            '.action-toolbar-guest{width:fit-content;max-width:100%;grid-template-columns:auto auto}',
        )

    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    @patch.object(tmdb_views.tmdb, 'get_movie_details')
    def test_authenticated_detail_renders_the_action_toolbar(self, get_movie_details):
        get_movie_details.return_value = {
            'id': 603,
            'title': 'The Matrix',
            'release_date': '1999-03-30',
            'poster_path': '/matrix.jpg',
            'vote_average': 8.7,
            'vote_count': 1000,
            'genres': [],
            'runtime': 136,
            'overview': 'A test movie.',
        }

        response = self.client.get('/movies/603/')

        self.assertContains(response, 'class="action-toolbar"')
        self.assertContains(response, 'class="toolbar-button toolbar-favorite"')
        self.assertContains(response, '.toolbar-login{grid-column:auto;justify-self:start}')
        self.assertContains(response, 'Đánh giá của bạn')
        self.assertContains(response, 'class="browse-genre-toggle rating-select-toggle"')
        self.assertContains(response, 'class="browse-genre-menu rating-select-menu"')
        self.assertContains(response, 'aria-label="1 sao">1 ★')
        self.assertContains(response, 'Lưu đánh giá')

    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    @patch.object(tmdb_views.tmdb, 'get_movie_details')
    def test_existing_rating_is_shown_without_a_rating_form(self, get_movie_details):
        get_movie_details.return_value = {
            'id': 603,
            'title': 'The Matrix',
            'release_date': '1999-03-30',
            'poster_path': '/matrix.jpg',
            'vote_average': 8.7,
            'vote_count': 1000,
            'genres': [],
            'runtime': 136,
            'overview': 'A test movie.',
        }
        MovieRating.objects.create(user=self.user, tmdb_id=603, rating=4)

        response = self.client.get('/movies/603/')

        self.assertContains(response, 'Bạn đã đánh giá')
        self.assertContains(response, '4 ★')
        self.assertNotContains(response, 'Lưu đánh giá')
        self.assertNotContains(response, 'rating-options-603')

    def test_rating_can_only_be_submitted_once(self):
        first_response = self.client.post('/movies/603/rate/', {'rating': '4'})
        second_response = self.client.post('/movies/603/rate/', {'rating': '2'})

        self.assertRedirects(first_response, '/movies/603/', fetch_redirect_response=False)
        self.assertRedirects(second_response, '/movies/603/', fetch_redirect_response=False)
        rating = MovieRating.objects.get(user=self.user, tmdb_id=603)
        self.assertEqual(rating.rating, 4)
        self.assertEqual(
            MovieInteraction.objects.filter(
                user=self.user, tmdb_id=603, action='rating'
            ).count(),
            1,
        )


@override_settings(STORAGES=TEST_STORAGES)
class AdminDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = get_user_model().objects.create_superuser(
            username='admin', email='admin@example.com', password='test-password'
        )

    def test_dashboard_requires_staff_login(self):
        response = self.client.get('/admin/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])

    def test_staff_dashboard_shows_database_stats_and_links_to_movie_admin(self):
        Movie.objects.create(
            tmdb_id=1,
            title='The Matrix',
            vote_average=8.5,
            vote_count=100,
        )
        self.client.force_login(self.admin_user)

        with patch.object(views, '_start_model_loading'):
            response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['database_movie_count'], 1)
        self.assertEqual(response.context['average_rating'], 8.5)
        self.assertContains(response, 'The Matrix')
        self.assertContains(response, '/admin/recommender/movie/')
        self.assertContains(response, '<footer class="site-footer">© ')
        admin_home = self.client.get('/admin/')
        self.assertEqual(admin_home.status_code, 200)
        self.assertContains(admin_home, 'Tổng quan')


class MissingModelTests(SimpleTestCase):
    """The app must stay up and explain itself when no model is installed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.empty_dir = Path(tempfile.mkdtemp(prefix='movie-empty-'))
        cls._settings = override_settings(MODEL_DIR=cls.empty_dir,
                                          BASE_DIR=cls.empty_dir,
                                          STORAGES=TEST_STORAGES)
        cls._settings.enable()
        views._reset_for_tests()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        views._reset_for_tests()
        shutil.rmtree(cls.empty_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client()
        views._start_model_loading()
        self.assertEqual(wait_until_ready(), 'missing')

    def test_index_still_renders(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_status_reports_missing_with_guidance(self):
        payload = self.client.get('/api/model-status/').json()
        self.assertEqual(payload['status'], 'missing')
        self.assertIn('MODEL_DIR', payload['message'])

    def test_health_check_is_503(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['reason'], 'missing')

    def test_health_check_does_not_leak_filesystem_paths(self):
        body = self.client.get('/api/health/').content.decode()
        self.assertNotIn(str(self.empty_dir), body)

    def test_post_explains_the_problem(self):
        response = self.client.post('/', {'movie_name': 'The Matrix'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('training/train.py', response.content.decode())

    def test_loader_does_not_respawn_threads_on_every_request(self):
        for _ in range(5):
            self.client.get('/api/model-status/')
        threads = [t for t in __import__('threading').enumerate()
                   if t.name == 'model-loader' and t.is_alive()]
        self.assertLessEqual(len(threads), 1)


class GenreLabelTests(SimpleTestCase):
    """The trainer stores genres as lowercase, space-free tokens."""

    def test_trainer_tokens_are_made_readable(self):
        self.assertEqual(views._genre_label('sciencefiction'), 'Science Fiction')
        self.assertEqual(views._genre_label('tvmovie'), 'TV Movie')
        self.assertEqual(views._genre_label('animation'), 'Animation')

    def test_already_cased_genres_are_left_alone(self):
        self.assertEqual(views._genre_label('Science Fiction'), 'Science Fiction')
        self.assertEqual(views._genre_label('TV Movie'), 'TV Movie')
