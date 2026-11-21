from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from .forms import SignUpForm
from .models import FavoriteMovie, SearchHistory, MovieInteraction, MovieRating
from . import tmdb_service as tmdb
from django.urls import reverse
from django.contrib import messages


@require_http_methods(['GET', 'POST'])
def signup(request):
    if request.user.is_authenticated:
        return redirect('recommender:main')
    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('recommender:main')
    return render(request, 'recommender/signup.html', {'form': form})


@login_required
@require_http_methods(['GET'])
def favorites(request):
    return render(request, 'recommender/favorites.html', {'favorites': FavoriteMovie.objects.filter(user=request.user)})


@login_required
@require_POST
def toggle_favorite(request):
    title = request.POST.get('movie_title', '').strip()
    if not title or len(title) > 255:
        return HttpResponseBadRequest('Tên phim không hợp lệ.')
    item, created = FavoriteMovie.objects.get_or_create(user=request.user, movie_title=title)
    if not created:
        item.delete()
    return redirect('recommender:favorites')


@login_required
@require_http_methods(['GET'])
def history(request):
    return render(request, 'recommender/history.html', {'history': SearchHistory.objects.filter(user=request.user)[:100]})


@login_required
@require_POST
def clear_history(request):
    SearchHistory.objects.filter(user=request.user).delete()
    return redirect('recommender:history')


@login_required
@require_POST
def toggle_tmdb_favorite(request, tmdb_id):
    existing = FavoriteMovie.objects.filter(user=request.user, tmdb_id=tmdb_id).first()
    if existing:
        existing.delete()
        action = 'unfavorite'
    else:
        try:
            movie = tmdb.get_movie_details(tmdb_id)
        except tmdb.TMDBError:
            messages.error(request, 'Không thể lấy thông tin phim từ TMDB. Vui lòng thử lại.')
            return redirect('recommender:tmdb_detail', tmdb_id=tmdb_id)
        FavoriteMovie.objects.create(user=request.user, tmdb_id=tmdb_id,
            movie_title=(movie.get('title') or f'Phim #{tmdb_id}')[:255],
            poster_path=(movie.get('poster_path') or '')[:255])
        action = 'favorite'
    MovieInteraction.objects.create(user=request.user, tmdb_id=tmdb_id, action=action)
    return redirect('recommender:tmdb_detail', tmdb_id=tmdb_id)


@login_required
@require_POST
def rate_tmdb_movie(request, tmdb_id):
    try:
        value = int(request.POST.get('rating', ''))
    except (ValueError, TypeError):
        return HttpResponseBadRequest('Điểm đánh giá không hợp lệ.')
    if not 1 <= value <= 5:
        return HttpResponseBadRequest('Điểm đánh giá phải từ 1 đến 5.')
    MovieRating.objects.update_or_create(user=request.user, tmdb_id=tmdb_id, defaults={'rating': value})
    MovieInteraction.objects.create(user=request.user, tmdb_id=tmdb_id, action='rating')
    return redirect('recommender:tmdb_detail', tmdb_id=tmdb_id)


@login_required
@require_http_methods(['GET'])
def interactions(request):
    return render(request, 'recommender/interactions.html', {
        'interactions': MovieInteraction.objects.filter(user=request.user)[:100],
        'ratings': MovieRating.objects.filter(user=request.user).order_by('-updated_at')[:100],
    })
