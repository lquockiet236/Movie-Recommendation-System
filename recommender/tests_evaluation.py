from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .evaluation import evaluate
from .models import Movie, MovieRating


class EvaluationTests(TestCase):
    def setUp(self):
        self.a = get_user_model().objects.create_user(username='eval_a', password='test-password')
        self.b = get_user_model().objects.create_user(username='eval_b', password='test-password')

    def test_insufficient_data_reports_none_not_fake_zero(self):
        MovieRating.objects.create(user=self.a, tmdb_id=1, rating=5)
        result = evaluate(k=5)
        self.assertEqual(result['eligible_users'], 0)
        self.assertIsNone(result['results']['Collaborative Filtering']['precision'])

    def test_holdout_and_no_database_mutation(self):
        for mid in (1, 2, 3):
            Movie.objects.create(tmdb_id=mid, title=f'Movie {mid}', overview='space heroes', genres=['Action'])
            MovieRating.objects.create(user=self.a, tmdb_id=mid, rating=5)
        for mid in (1, 2, 3, 4):
            MovieRating.objects.create(user=self.b, tmdb_id=mid, rating=5)
        before = list(MovieRating.objects.order_by('pk').values_list('user_id', 'tmdb_id', 'rating'))
        result = evaluate(k=5)
        self.assertEqual(result['eligible_users'], 2)
        self.assertGreaterEqual(result['results']['Collaborative Filtering']['hits'], 1)
        self.assertEqual(before, list(MovieRating.objects.order_by('pk').values_list('user_id', 'tmdb_id', 'rating')))

    def test_dashboard_requires_staff(self):
        self.client.force_login(self.a)
        response = self.client.get(reverse('recommender:evaluation_dashboard'))
        self.assertNotEqual(response.status_code, 200)
        self.a.is_staff = True
        self.a.save()
        response = self.client.get(reverse('recommender:evaluation_dashboard'))
        self.assertEqual(response.status_code, 200)
