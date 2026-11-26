from unittest.mock import Mock, patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
import pandas as pd
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

    def test_for_you_prompts_when_user_has_no_favorites(self):
        self.client.force_login(self.user)

        response = self.client.get('/for-you/')

        self.assertEqual(response.context['favorite_groups'], [])
        self.assertContains(response, 'Bạn chưa có phim yêu thích.')

    @patch('recommender.recommendation_engine.tmdb.similar_movies')
    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    def test_for_you_uses_legacy_favorite_title_to_show_similar_movies(
        self, similar
    ):
        FavoriteMovie.objects.create(user=self.user, movie_title='seed')
        self.client.force_login(self.user)
        offline_model = type('OfflineModel', (), {
            'title_to_idx': {'Seed': 0},
            'metadata': pd.DataFrame([{'id': 1, 'title': 'Seed'}]),
        })()
        similar.return_value = [{
            'id': 2,
            'title': 'Candidate',
            'genre_ids': [878],
            'overview': 'space future',
            'vote_average': 8,
            'vote_count': 3000,
        }]
        with patch('recommender.views._get_recommender', return_value=offline_model):
            response = self.client.get('/for-you/')

        similar.assert_called_once_with(1)
        self.assertContains(response, 'Candidate')
        self.assertContains(response, 'href="/movies/2/"')

    @override_settings(TMDB_ACCESS_TOKEN='')
    def test_for_you_uses_offline_model_for_two_favorites(
        self
    ):
        FavoriteMovie.objects.create(
            user=self.user, movie_title='Seed One', tmdb_id=1
        )
        FavoriteMovie.objects.create(
            user=self.user, movie_title='Seed Two', tmdb_id=2
        )
        self.client.force_login(self.user)
        offline_model = Mock()
        offline_model.metadata = pd.DataFrame([
            {'id': 1, 'title': 'Seed One'},
            {'id': 2, 'title': 'Seed Two'},
        ])
        offline_model.get_recommendations.side_effect = lambda title, n: {
            'recommendations': {
                'Seed One': [
                    {'id': 2, 'title': 'Seed Two', 'similarity_percent': 99},
                    {
                        'id': 3,
                        'title': 'Related One',
                        'poster_url': 'https://image.tmdb.org/t/p/w342/related.jpg',
                        'rating_value': 8.2,
                        'similarity_percent': 90,
                    },
                ],
                'Seed Two': [
                    {
                        'id': 4,
                        'title': 'Related Two',
                        'poster_url': None,
                        'rating_value': 7.5,
                        'similarity_percent': 80,
                    },
                ],
            }[title]
        }

        with patch('recommender.views._get_recommender', return_value=offline_model):
            response = self.client.get('/for-you/')
            remove_response = self.client.post(
                '/movies/2/favorite/', {'return_to': 'favorites'}
            )
            updated_response = self.client.get('/for-you/')

        self.assertContains(response, 'Related One')
        self.assertContains(response, 'Related Two')
        self.assertContains(response, 'https://image.tmdb.org/t/p/w342/related.jpg')
        self.assertNotContains(response, 'href="/movies/2/"')
        self.assertRedirects(
            remove_response, '/favorites/', fetch_redirect_response=False
        )
        self.assertContains(updated_response, 'Related One')
        self.assertNotContains(updated_response, 'Related Two')

    @patch('recommender.recommendation_engine.tmdb.similar_movies')
    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    def test_for_you_falls_back_when_tmdb_has_no_candidates(
        self, similar
    ):
        FavoriteMovie.objects.create(
            user=self.user, movie_title='Seed One', tmdb_id=1
        )
        self.client.force_login(self.user)
        similar.return_value = []
        offline_model = Mock()
        offline_model.metadata = pd.DataFrame([
            {'id': 1, 'title': 'Seed One'},
        ])
        offline_model.get_recommendations.return_value = {
            'recommendations': [{
                'id': 3,
                'title': 'Offline Related',
                'poster_url': None,
                'rating_value': 8.0,
                'similarity_percent': 85,
            }]
        }

        with patch('recommender.views._get_recommender', return_value=offline_model):
            response = self.client.get('/for-you/')

        self.assertContains(response, 'Offline Related')
        similar.assert_called_once_with(1)
        offline_model.get_recommendations.assert_called_once_with('Seed One', n=12)

    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    @patch('recommender.recommendation_engine.tmdb.similar_movies')
    def test_for_you_limits_each_favorite_to_six_and_recomputes(self, similar):
        FavoriteMovie.objects.create(
            user=self.user, movie_title='Seed One', tmdb_id=1
        )
        FavoriteMovie.objects.create(
            user=self.user, movie_title='Seed Two', tmdb_id=2
        )
        self.client.force_login(self.user)
        similar.side_effect = lambda tmdb_id: [
            {'id': tmdb_id * 100 + index, 'title': f'Related {index}'}
            for index in range(1, 8)
        ]

        response = self.client.get('/for-you/')
        groups = response.context['favorite_groups']
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            [len(group['recommendations']) for group in groups], [6, 6]
        )
        self.assertContains(response, 'external-google-link', count=12)
        self.assertContains(response, 'external-imdb-link', count=12)
        self.assertIn('no-store', response['Cache-Control'])

        remove_response = self.client.post(
            '/movies/1/favorite/', {'return_to': 'favorites'}
        )
        updated_response = self.client.get('/for-you/')

        self.assertRedirects(
            remove_response, '/favorites/', fetch_redirect_response=False
        )
        updated_groups = updated_response.context['favorite_groups']
        self.assertEqual(len(updated_groups), 1)
        self.assertEqual(updated_groups[0]['favorite_id'], 2)
        self.assertEqual(len(updated_groups[0]['recommendations']), 6)
        self.assertContains(updated_response, 'external-google-link', count=6)
        self.assertContains(updated_response, 'external-imdb-link', count=6)
        call_args = [call.args for call in similar.call_args_list]
        self.assertCountEqual(call_args[:2], [(1,), (2,)])
        self.assertEqual(call_args[2], (2,))

    @patch('recommender.recommendation_engine.tmdb.popular_movies')
    @patch('recommender.recommendation_engine.tmdb.discover_movies')
    @patch('recommender.recommendation_engine.tmdb.similar_movies')
    @patch('recommender.recommendation_engine.tmdb.get_movie_details')
    @override_settings(TMDB_ACCESS_TOKEN='test-token')
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
