"""
Tests for the Movie Recommendation System.

The recommender is backed by model files on disk, so the suite builds a tiny
synthetic model in a temporary directory and points MODEL_DIR at it. That keeps
the tests fast and means they exercise the real loading path -- parquet list
columns included, since those are a common source of subtle breakage.
"""
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import tmdb_views, views
from .models import Movie

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
        self.assertContains(response, 'class="signup-card"')

    @override_settings(TMDB_ACCESS_TOKEN='')
    @patch.object(views.MovieRecommender, 'get_recommendations')
    def test_homepage_lists_movies_without_generating_recommendations(self, get_recommendations):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Khám phá phim', body)
        self.assertIn('The Matrix', body)
        get_recommendations.assert_not_called()

    @patch('recommender.views._get_recommender')
    def test_recommendation_form_does_not_load_model_until_used(self, get_recommender):
        response = self.client.get('/recommendation')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CineRec')
        self.assertNotContains(response, 'Gợi ý chỉ được tạo sau khi bạn nhấn nút')
        get_recommender.assert_not_called()

    @override_settings(TMDB_ACCESS_TOKEN='')
    @patch.object(views.MovieRecommender, 'get_recommendations')
    def test_movie_detail_does_not_generate_similar_movies_automatically(self, get_recommendations):
        response = self.client.get('/movies/1/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tìm phim tương tự')
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

    def test_favicon_redirects(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 301)
        self.assertIn('logo.ico', response['Location'])


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
