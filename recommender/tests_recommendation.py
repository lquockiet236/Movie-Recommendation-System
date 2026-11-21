from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from .models import FavoriteMovie, MovieRating
from .recommendation_engine import recommend

class RecommendationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='recommend_tester', password='safe-test-password')

    @patch('recommender.recommendation_engine.tmdb.popular_movies')
    def test_cold_start(self, popular):
        popular.return_value = [{'id': 12, 'title': 'Example'}]
        result = recommend(self.user)
        self.assertTrue(result['cold_start'])
        self.assertEqual(result['movies'][0]['movie']['id'], 12)

    @patch('recommender.recommendation_engine.tmdb.popular_movies')
    @patch('recommender.recommendation_engine.tmdb.discover_movies')
    @patch('recommender.recommendation_engine.tmdb.similar_movies')
    @patch('recommender.recommendation_engine.tmdb.get_movie_details')
    def test_excludes_rated_and_favorite(self, detail, similar, discover, popular):
        FavoriteMovie.objects.create(user=self.user, tmdb_id=1, movie_title='Seed')
        MovieRating.objects.create(user=self.user, tmdb_id=2, rating=2)
        detail.return_value = {'id': 1, 'genres': [{'id': 878, 'name': 'Science Fiction'}], 'overview': 'space future', 'keywords': {'keywords': []}}
        similar.return_value = [{'id': 2, 'title': 'Rated'}, {'id': 3, 'title': 'Candidate', 'genre_ids': [878], 'overview': 'space future', 'vote_average': 8, 'vote_count': 3000}]
        discover.return_value = []
        popular.return_value = []
        ids = [item['movie']['id'] for item in recommend(self.user)['movies']]
        self.assertEqual(ids, [3])

from .collaborative_filtering import collaborative_scores

class CollaborativeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.a = User.objects.create_user(username='cf_a', password='testpass')
        self.b = User.objects.create_user(username='cf_b', password='testpass')
        self.c = User.objects.create_user(username='cf_c', password='testpass')

    def test_sparse_data_falls_back(self):
        MovieRating.objects.create(user=self.a, tmdb_id=1, rating=5)
        scores, _ = collaborative_scores(self.a.pk)
        self.assertEqual(scores, {})

    def test_similar_users_recommend_unseen_positive_movie(self):
        for user in (self.a, self.b):
            MovieRating.objects.create(user=user, tmdb_id=1, rating=5)
            MovieRating.objects.create(user=user, tmdb_id=2, rating=4)
        MovieRating.objects.create(user=self.b, tmdb_id=3, rating=5)
        MovieRating.objects.create(user=self.b, tmdb_id=4, rating=1)
        scores, support = collaborative_scores(self.a.pk)
        self.assertIn(3, scores)
        self.assertNotIn(4, scores)
        self.assertNotIn(1, scores)
        self.assertEqual(support[3], 1)

    def test_opposing_preferences_do_not_recommend(self):
        for mid, ra, rb in [(1, 5, 1), (2, 4, 2)]:
            MovieRating.objects.create(user=self.a, tmdb_id=mid, rating=ra)
            MovieRating.objects.create(user=self.b, tmdb_id=mid, rating=rb)
        MovieRating.objects.create(user=self.b, tmdb_id=3, rating=5)
        scores, _ = collaborative_scores(self.a.pk)
        self.assertEqual(scores, {})
