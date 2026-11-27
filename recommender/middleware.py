from django.conf import settings
from django.shortcuts import redirect


class StaffAdminOnlyMiddleware:
    """Keep staff accounts inside the administration area."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return response
        if not request.user.is_staff:
            return response

        path = request.path
        allowed_prefixes = ('/admin/', '/accounts/logout/', '/favicon.ico')
        if getattr(settings, 'STATIC_URL', None):
            allowed_prefixes += (settings.STATIC_URL,)

        if path.startswith(allowed_prefixes):
            return response

        return redirect('admin:index')
