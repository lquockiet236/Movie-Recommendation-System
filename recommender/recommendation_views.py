from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .recommendation_engine import recommend
from .tmdb_service import TMDBError

@login_required
@require_GET
def for_you(request):
    context = {'recommendations': [], 'cold_start': False, 'hybrid': False, 'error': None}
    try:
        result = recommend(request.user)
        context.update(recommendations=result['movies'], cold_start=result['cold_start'], hybrid=result['hybrid'])
    except TMDBError as exc:
        context['error'] = str(exc)
    return render(request, 'recommender/for_you.html', context)
