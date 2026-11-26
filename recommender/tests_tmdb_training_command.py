import csv
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from . import tmdb_service
from . import views as app_views
from .views import MovieRecommender


class CollectTrainTMDBCommandTests(SimpleTestCase):
    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    def test_collects_and_normalizes_movies_before_training(self):
        dataset_path = Path(tempfile.gettempdir()) / 'tmdb-training-command-test.csv'
        output_dir = Path(tempfile.gettempdir()) / 'tmdb-training-command-model'
        trainer_instance = Mock()
        trainer_instance.train.return_value = ([{}, {}], None)
        trainer_class = Mock(return_value=trainer_instance)
        training_module = types.ModuleType('training.train')
        training_module.MovieRecommenderTrainer = trainer_class

        def fake_tmdb_get(endpoint, params=None, cache_seconds=900):
            if endpoint == '/discover/movie':
                return {
                    'page': 1,
                    'total_pages': 1,
                    'results': [{'id': 101}, {'id': 102}],
                }
            movie_id = int(endpoint.rsplit('/', 1)[-1])
            return {
                'id': movie_id,
                'title': f'Movie {movie_id}',
                'status': 'Released',
                'vote_count': 900,
                'genres': [{'id': 18, 'name': 'Drama'}],
                'keywords': {'keywords': [{'id': 1, 'name': 'family'}]},
                'production_companies': [{'id': 2, 'name': 'Studio'}],
                'production_countries': [{'iso_3166_1': 'US', 'name': 'United States'}],
                'overview': 'A sufficiently descriptive movie overview.',
                'tagline': 'A tagline',
                'vote_average': 7.5,
                'popularity': 10.0,
                'release_date': '2020-01-01',
                'imdb_id': 'tt1234567',
                'poster_path': '/poster.jpg',
            }

        with (
            patch.dict(sys.modules, {'training.train': training_module}),
            patch.object(tmdb_service, 'tmdb_get', side_effect=fake_tmdb_get) as api,
        ):
            call_command(
                'collect_train_tmdb',
                max_movies=2,
                quality='high',
                request_delay=0,
                dataset_path=str(dataset_path),
                output_dir=str(output_dir),
                stdout=Mock(),
            )

        try:
            with dataset_path.open(encoding='utf-8', newline='') as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['title'], 'Movie 101')
            self.assertEqual(json.loads(rows[0]['genres']), [{'name': 'Drama'}])
            self.assertEqual(
                json.loads(rows[0]['keywords']), [{'name': 'family'}]
            )
            self.assertEqual(api.call_count, 3)
            self.assertEqual(
                api.call_args_list[0].kwargs['params']['sort_by'],
                'popularity.desc',
            )
            trainer_class.assert_called_once()
            trainer_instance.train.assert_called_once_with(
                dataset_path,
                quality_threshold='high',
                max_movies=2,
            )
        finally:
            dataset_path.unlink(missing_ok=True)

    @override_settings(TMDB_ACCESS_TOKEN='test-token')
    def test_command_trains_and_writes_a_loadable_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_path = root / 'training.csv'
            output_dir = root / 'model'
            listings = [{'id': movie_id} for movie_id in range(201, 209)]

            def fake_tmdb_get(endpoint, params=None, cache_seconds=900):
                if endpoint == '/discover/movie':
                    return {
                        'page': 1,
                        'total_pages': 1,
                        'results': listings,
                    }
                movie_id = int(endpoint.rsplit('/', 1)[-1])
                index = movie_id - 201
                is_scifi = index < 4
                return {
                    'id': movie_id,
                    'title': f'Movie {index}',
                    'status': 'Released',
                    'vote_count': 1000,
                    'genres': [{'id': 878 if is_scifi else 35,
                                'name': 'Science Fiction' if is_scifi else 'Comedy'}],
                    'keywords': {
                        'keywords': [
                            {'id': index + 1, 'name': 'space' if is_scifi else 'family'},
                            {'id': index + 20, 'name': 'future' if is_scifi else 'friends'},
                        ]
                    },
                    'production_companies': [{'id': 1, 'name': 'Studio'}],
                    'production_countries': [
                        {'iso_3166_1': 'US', 'name': 'United States'}
                    ],
                    'overview': (
                        'space galaxy orbital science mission future journey'
                        if is_scifi else
                        'family friends comedy village magic adventure journey'
                    ),
                    'tagline': 'A story about a journey',
                    'vote_average': 7.5,
                    'popularity': 10.0,
                    'release_date': '2020-01-01',
                    'imdb_id': f'tt{movie_id}',
                    'poster_path': f'/poster-{movie_id}.jpg',
                }

            with patch.object(
                tmdb_service, 'tmdb_get', side_effect=fake_tmdb_get
            ):
                call_command(
                    'collect_train_tmdb',
                    max_movies=8,
                    quality='high',
                    request_delay=0,
                    dataset_path=str(dataset_path),
                    output_dir=str(output_dir),
                    top_k=5,
                    components=2,
                    chunk_size=4,
                    stdout=Mock(),
                )

            self.assertTrue((output_dir / 'config.json').is_file())
            self.assertTrue((output_dir / 'movie_metadata.parquet').is_file())
            self.assertTrue((output_dir / 'neighbors_idx.npy').is_file())
            loaded_model = MovieRecommender(output_dir)
            try:
                result = loaded_model.get_recommendations('Movie 0', n=3)
                self.assertEqual(len(result['recommendations']), 3)
            finally:
                loaded_model._neighbor_idx._mmap.close()
                loaded_model._neighbor_scores._mmap.close()


class ModelDirectoryResolutionTests(SimpleTestCase):
    @staticmethod
    def create_model_directory(path):
        path.mkdir(parents=True)
        for artifact in app_views.REQUIRED_ARTIFACTS:
            (path / artifact).touch()

    def test_auto_mode_selects_newest_valid_tmdb_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            older_model = base_dir / 'models_tmdb_20261126_120000'
            newest_model = base_dir / 'models_tmdb_20261126_120100'
            default_model = base_dir / 'models'
            self.create_model_directory(older_model)
            self.create_model_directory(newest_model)
            self.create_model_directory(default_model)

            with override_settings(
                BASE_DIR=base_dir,
                MODEL_DIR=default_model,
                MODEL_DIR_AUTO=True,
            ):
                self.assertEqual(app_views._resolve_model_dir(), newest_model)

            with override_settings(
                BASE_DIR=base_dir,
                MODEL_DIR=default_model,
                MODEL_DIR_AUTO=False,
            ):
                self.assertEqual(app_views._resolve_model_dir(), default_model)
