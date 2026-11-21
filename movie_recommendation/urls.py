"""Root URL configuration."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.urls import include, path
from django.views.generic.base import RedirectView

from recommender import views

# Resolved directly from STATIC_URL rather than via the {% static %} machinery:
# the manifest static storage raises at import time if collectstatic has not
# run yet, which would take the whole site down instead of one icon.
FAVICON_URL = settings.STATIC_URL.rstrip('/') + '/logo.ico'

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=FAVICON_URL, permanent=True)),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='recommender/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/', admin.site.urls),
    path('', include('recommender.urls')),
]

# Custom error pages (used when DEBUG=False).
handler404 = 'recommender.views.handler404'
handler500 = 'recommender.views.handler500'
