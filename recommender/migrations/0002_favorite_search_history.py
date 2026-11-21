from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('recommender', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='FavoriteMovie',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movie_title', models.CharField(max_length=255)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='favorite_movies', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-added_at']},
        ),
        migrations.CreateModel(
            name='SearchHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('query', models.CharField(max_length=200)),
                ('searched_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movie_searches', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-searched_at']},
        ),
        migrations.AddConstraint(
            model_name='favoritemovie',
            constraint=models.UniqueConstraint(fields=('user', 'movie_title'), name='unique_user_favorite_title'),
        ),
    ]
