from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('recommender', '0002_favorite_search_history'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='favoritemovie', name='tmdb_id', field=models.PositiveIntegerField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name='favoritemovie', name='poster_path', field=models.CharField(blank=True, max_length=255)),
        migrations.CreateModel(name='MovieInteraction', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('tmdb_id', models.PositiveIntegerField(db_index=True)), ('action', models.CharField(choices=[('detail','Xem chi tiết'),('favorite','Yêu thích'),('unfavorite','Bỏ yêu thích'),('rating','Đánh giá')], max_length=24)), ('created_at', models.DateTimeField(auto_now_add=True)), ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movie_interactions', to=settings.AUTH_USER_MODEL))], options={'ordering':['-created_at']}),
        migrations.CreateModel(name='MovieRating', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('tmdb_id', models.PositiveIntegerField(db_index=True)), ('rating', models.PositiveSmallIntegerField()), ('updated_at', models.DateTimeField(auto_now=True)), ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movie_ratings', to=settings.AUTH_USER_MODEL))]),
        migrations.AddConstraint(model_name='movierating', constraint=models.UniqueConstraint(fields=('user','tmdb_id'), name='unique_user_tmdb_rating')),
        migrations.AddConstraint(model_name='favoritemovie', constraint=models.UniqueConstraint(condition=models.Q(tmdb_id__isnull=False), fields=('user','tmdb_id'), name='unique_user_tmdb_favorite')),
    ]
