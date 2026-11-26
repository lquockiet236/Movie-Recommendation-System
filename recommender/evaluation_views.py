from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .evaluation import evaluate


@staff_member_required
@require_GET
def evaluation_dashboard(request):
    try:
        k = int(request.GET.get('k', '5'))
    except (TypeError, ValueError):
        k = 5
    k = max(1, min(20, k))
    return render(request, 'recommender/evaluation_dashboard.html', {'evaluation': evaluate(k=k)})
