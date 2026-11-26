from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .recommendation_engine import recommend_for_favorites
from .tmdb_service import TMDBError


@login_required
@require_GET
@never_cache
def for_you(request):
    context = {
        'favorite_groups': [],
        'error': None,
    }
    try:
        context['favorite_groups'] = recommend_for_favorites(request.user)
    except TMDBError as exc:
        context['error'] = str(exc)
    return render(request, 'recommender/for_you.html', context)
