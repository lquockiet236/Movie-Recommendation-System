import csv
import json
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from recommender import tmdb_service as tmdb

QUALITY_THRESHOLDS = {
    'low': 5,
    'medium': 50,
    'high': 500,
}
MAX_DISCOVER_PAGES = 500
MAX_DISCOVER_RESULTS = 20 * MAX_DISCOVER_PAGES
CSV_COLUMNS = [
    'id',
    'title',
    'status',
    'vote_count',
    'genres',
    'keywords',
    'production_companies',
    'production_countries',
    'overview',
    'tagline',
    'vote_average',
    'popularity',
    'release_date',
    'imdb_id',
    'poster_path',
]


class Command(BaseCommand):
    help = 'Collect paginated TMDB movies, write a training CSV, then train a new offline model.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-movies',
            type=int,
            default=1000,
            help='Maximum number of released movies to collect (2-10000).',
        )
        parser.add_argument(
            '--quality',
            choices=QUALITY_THRESHOLDS,
            default='medium',
            help='Minimum TMDB vote count tier used by the trainer.',
        )
        parser.add_argument(
            '--request-delay',
            type=float,
            default=0.25,
            help='Seconds to wait between movie-detail API calls.',
        )
        parser.add_argument(
            '--dataset-path',
            default=None,
            help='CSV output path; defaults to data/tmdb_training_dataset.csv.',
        )
        parser.add_argument(
            '--output-dir',
            default=None,
            help='New model directory; defaults to a timestamped models_tmdb_* directory.',
        )
        parser.add_argument('--top-k', type=int, default=50)
        parser.add_argument('--components', type=int, default=100)
        parser.add_argument('--chunk-size', type=int, default=512)

    def handle(self, *args, **options):
        max_movies = options['max_movies']
        delay = options['request_delay']
        if not 2 <= max_movies <= MAX_DISCOVER_RESULTS:
            raise CommandError(
                f'--max-movies must be between 2 and {MAX_DISCOVER_RESULTS}.'
            )
        if delay < 0:
            raise CommandError('--request-delay cannot be negative.')
        if options['top_k'] < 1:
            raise CommandError('--top-k must be at least 1.')
        if options['components'] < 1:
            raise CommandError('--components must be at least 1.')
        if options['chunk_size'] < 1:
            raise CommandError('--chunk-size must be at least 1.')
        if not tmdb.settings.TMDB_ACCESS_TOKEN:
            raise CommandError(
                'TMDB_ACCESS_TOKEN is not configured in this environment.'
            )

        dataset_path = self._resolve_path(
            options['dataset_path'] or 'data/tmdb_training_dataset.csv'
        )
        output_dir = self._resolve_output_dir(options['output_dir'])
        if output_dir == Path(settings.MODEL_DIR).resolve():
            raise CommandError(
                'Choose a new --output-dir instead of overwriting the active MODEL_DIR.'
            )

        records = self._collect_movies(
            max_movies=max_movies,
            min_votes=QUALITY_THRESHOLDS[options['quality']],
            delay=delay,
        )
        if len(records) < 2:
            raise CommandError(
                f'TMDB returned only {len(records)} usable movie(s); at least two are required.'
            )

        self._write_csv(dataset_path, records)
        self.stdout.write(
            f'Collected {len(records):,} released movies into {dataset_path}'
        )

        try:
            from training.train import MovieRecommenderTrainer
        except ModuleNotFoundError as exc:
            raise CommandError(
                'Training dependencies are missing. Run '
                '`python -m pip install -r requirements-train.txt` first.'
            ) from exc

        trainer = MovieRecommenderTrainer(
            output_dir=output_dir,
            use_dimensionality_reduction=True,
            n_components=options['components'],
            top_k=options['top_k'],
            chunk_size=options['chunk_size'],
        )
        trained_movies, _ = trainer.train(
            dataset_path,
            quality_threshold=options['quality'],
            max_movies=max_movies,
        )
        if len(trained_movies) < 2:
            raise CommandError(
                'Training produced fewer than two usable movies; no new model is ready.'
            )

        model_path = output_dir.resolve()
        self.stdout.write(self.style.SUCCESS(
            f'Trained model with {len(trained_movies):,} movies at {model_path}'
        ))
        auto_discoverable = (
            getattr(settings, 'MODEL_DIR_AUTO', False)
            and model_path.parent == Path(settings.BASE_DIR).resolve()
            and model_path.name.startswith('models_tmdb_')
        )
        if auto_discoverable:
            self.stdout.write(
                'After restart, the app will select the newest valid models_tmdb_* '
                'directory when MODEL_DIR is unset.'
            )
        else:
            self.stdout.write(f'PowerShell: $env:MODEL_DIR = "{model_path}"')
            self.stdout.write(
                'Set MODEL_DIR in the web environment and restart the '
                'Django/Gunicorn process to load this model.'
            )

    def _collect_movies(self, max_movies, min_votes, delay):
        records = []
        seen_ids = set()
        today = date.today().isoformat()

        for page in range(1, MAX_DISCOVER_PAGES + 1):
            payload = self._tmdb_get(
                '/discover/movie',
                {
                    'page': page,
                    'sort_by': 'popularity.desc',
                    'vote_count.gte': min_votes,
                    'primary_release_date.lte': today,
                    'include_adult': 'false',
                    'include_video': 'false',
                    'language': 'en-US',
                },
            )
            movies = payload.get('results') or []
            if not movies:
                break

            for movie in movies:
                movie_id = movie.get('id')
                if movie_id is None or movie_id in seen_ids:
                    continue
                seen_ids.add(movie_id)

                details = self._tmdb_get(
                    f'/movie/{int(movie_id)}',
                    {
                        'append_to_response': 'keywords',
                        'language': 'en-US',
                    },
                )
                if delay:
                    time.sleep(delay)

                try:
                    vote_count = int(details.get('vote_count') or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
                if (
                    details.get('status') != 'Released'
                    or vote_count < min_votes
                    or not details.get('title')
                ):
                    continue

                keywords = details.get('keywords') or {}
                if isinstance(keywords, dict):
                    keywords = keywords.get('keywords', keywords.get('results', []))
                records.append({
                    'id': int(details.get('id') or movie_id),
                    'title': details.get('title') or '',
                    'status': details.get('status') or '',
                    'vote_count': vote_count,
                    'genres': self._json_names(details.get('genres')),
                    'keywords': self._json_names(keywords),
                    'production_companies': self._json_names(
                        details.get('production_companies')
                    ),
                    'production_countries': self._json_names(
                        details.get('production_countries')
                    ),
                    'overview': details.get('overview') or '',
                    'tagline': details.get('tagline') or '',
                    'vote_average': details.get('vote_average') or 0,
                    'popularity': details.get('popularity') or 0,
                    'release_date': details.get('release_date') or '',
                    'imdb_id': details.get('imdb_id') or '',
                    'poster_path': details.get('poster_path') or '',
                })
                if len(records) >= max_movies:
                    return records

            try:
                total_pages = min(int(payload.get('total_pages') or page), MAX_DISCOVER_PAGES)
            except (TypeError, ValueError, OverflowError):
                total_pages = page
            if page >= total_pages:
                break

            self.stdout.write(
                f'Page {page}: collected {len(records):,}/{max_movies:,} movies',
                ending='\r',
            )
            self.stdout.flush()

        self.stdout.write('')
        return records

    def _tmdb_get(self, endpoint, params):
        try:
            return tmdb.tmdb_get(endpoint, params=params, cache_seconds=0)
        except tmdb.TMDBError as exc:
            raise CommandError(str(exc)) from exc

    @staticmethod
    def _json_names(items):
        if not isinstance(items, list):
            return '[]'
        names = [
            {'name': str(item['name'])}
            for item in items
            if isinstance(item, dict) and item.get('name')
        ]
        return json.dumps(names, ensure_ascii=False)

    @staticmethod
    def _resolve_path(path):
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = Path(settings.BASE_DIR) / resolved
        return resolved.resolve()

    @classmethod
    def _resolve_output_dir(cls, path):
        if path:
            return cls._resolve_path(path)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return cls._resolve_path(f'models_tmdb_{timestamp}')

    @staticmethod
    def _write_csv(path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                newline='',
                dir=path.parent,
                prefix=f'.{path.stem}_',
                suffix='.tmp',
                delete=False,
            ) as file:
                temp_path = Path(file.name)
                writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(records)
            os.replace(temp_path, path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
