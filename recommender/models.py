from django.db import models


class Movie(models.Model):
    tmdb_id = models.IntegerField(unique=True)

    title = models.CharField(max_length=255)
    overview = models.TextField(blank=True)
    genres = models.JSONField(default=list)
    keywords = models.JSONField(default=list)

    release_date = models.DateField(
        null=True,
        blank=True
    )

    poster_path = models.CharField(
        max_length=255,
        blank=True
    )

    vote_average = models.FloatField(default=0)
    vote_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.title

from django.conf import settings


class FavoriteMovie(models.Model):
    # Titles refer to the recommender dataset, which is not the Movie SQL table.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='favorite_movies')
    movie_title = models.CharField(max_length=255)  # Legacy favorites remain accessible
    tmdb_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    poster_path = models.CharField(max_length=255, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [models.UniqueConstraint(fields=['user', 'movie_title'], name='unique_user_favorite_title'), models.UniqueConstraint(fields=['user', 'tmdb_id'], condition=models.Q(tmdb_id__isnull=False), name='unique_user_tmdb_favorite')]

    def __str__(self):
        return f'{self.user}: {self.movie_title}'


class SearchHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='movie_searches')
    query = models.CharField(max_length=200)
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-searched_at']

    def __str__(self):
        return f'{self.user}: {self.query}'


class MovieInteraction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='movie_interactions')
    tmdb_id = models.PositiveIntegerField(db_index=True)
    action = models.CharField(max_length=24, choices=[('detail', 'Xem chi tiết'), ('favorite', 'Yêu thích'), ('unfavorite', 'Bỏ yêu thích'), ('rating', 'Đánh giá')])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class MovieRating(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='movie_ratings')
    tmdb_id = models.PositiveIntegerField(db_index=True)
    rating = models.PositiveSmallIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'tmdb_id'], name='unique_user_tmdb_rating')]
