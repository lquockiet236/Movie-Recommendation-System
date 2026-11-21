from django.core.management.base import BaseCommand
from recommender.evaluation import evaluate


class Command(BaseCommand):
    help = 'Evaluate offline recommendation baselines with held-out positive ratings.'

    def add_arguments(self, parser):
        parser.add_argument('--k', type=int, default=5)

    def handle(self, *args, **options):
        result = evaluate(k=options['k'])
        self.stdout.write(f"Users eligible: {result['eligible_users']} / {result['rating_users']}; catalog: {result['catalog_size']}; cached metadata: {result['metadata_movies']}")
        if not result['eligible_users']:
            self.stdout.write(self.style.WARNING('Insufficient data: need >=3 positive ratings (4-5 stars) per test user. No metrics computed.'))
            return
        self.stdout.write('Algorithm | Precision@K | Recall@K | Coverage | Hits/Users')
        for name, row in result['results'].items():
            def fmt(v):
                return f'{v:.3f}' if v is not None else 'N/A'
            self.stdout.write(f"{name} | {fmt(row['precision'])} | {fmt(row['recall'])} | {fmt(row['coverage'])} | {row['hits']}/{row['users']}")
        self.stdout.write(result['note'])
