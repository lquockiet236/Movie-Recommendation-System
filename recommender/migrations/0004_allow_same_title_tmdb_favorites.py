from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('recommender', '0003_tmdb_personalization'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='favoritemovie',
            name='unique_user_favorite_title',
        ),
        migrations.AddConstraint(
            model_name='favoritemovie',
            constraint=models.UniqueConstraint(
                condition=models.Q(tmdb_id__isnull=True),
                fields=('user', 'movie_title'),
                name='unique_user_legacy_favorite_title',
            ),
        ),
    ]
