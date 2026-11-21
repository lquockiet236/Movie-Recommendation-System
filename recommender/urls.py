"""
URL Configuration for Movie Recommendation System
"""
from django.urls import path

from . import views, account_views, tmdb_views, recommendation_views, evaluation_views

app_name = 'recommender'

urlpatterns = [
    path("evaluation/", evaluation_views.evaluation_dashboard, name="evaluation_dashboard"),
    path("for-you/", recommendation_views.for_you, name="for_you"),
    path("recommendation", views.recommend_page, name="recommend"),
    path("movies/", tmdb_views.browse, name="tmdb_browse"),
    path("movies/<int:tmdb_id>/", tmdb_views.detail, name="tmdb_detail"),
    path('accounts/signup/', account_views.signup, name='signup'),
    path('movies/<int:tmdb_id>/favorite/', account_views.toggle_tmdb_favorite, name='tmdb_favorite'),
    path('movies/<int:tmdb_id>/rate/', account_views.rate_tmdb_movie, name='tmdb_rate'),
    path('interactions/', account_views.interactions, name='interactions'),
    path('favorites/', account_views.favorites, name='favorites'),
    path('favorites/toggle/', account_views.toggle_favorite, name='toggle_favorite'),
    path('history/', account_views.history, name='history'),
    path('history/clear/', account_views.clear_history, name='clear_history'),
    # Main views
    path('', views.main, name='main'),

    # API endpoints
    path('api/search/', views.search_movies, name='search_movies'),
    path('api/model-status/', views.model_status, name='model_status'),
    path('api/health/', views.health_check, name='health_check'),
]
