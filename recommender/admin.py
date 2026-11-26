from django.contrib import admin

from .models import FavoriteMovie, Movie, MovieInteraction, MovieRating


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "tmdb_id",
        "release_date",
        "vote_average",
        "vote_count",
    )

    list_filter = ("release_date",)
    ordering = ("title",)
    search_fields = ("title", "tmdb_id")
    readonly_fields = ("created_at",)


@admin.register(FavoriteMovie)
class FavoriteMovieAdmin(admin.ModelAdmin):
    list_display = ('user', 'movie_title', 'tmdb_id', 'added_at')
    search_fields = ('user__username', 'movie_title')
    readonly_fields = ('added_at',)


@admin.register(MovieInteraction)
class MovieInteractionAdmin(admin.ModelAdmin):
    list_display = ('user', 'tmdb_id', 'action', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('user__username', 'tmdb_id')
    readonly_fields = ('user', 'tmdb_id', 'action', 'created_at')


@admin.register(MovieRating)
class MovieRatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'tmdb_id', 'rating', 'updated_at')
    list_filter = ('rating',)
    search_fields = ('user__username', 'tmdb_id')
