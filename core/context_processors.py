"""Navigation context for active link highlighting."""

from .service_content import SERVICE_URL_NAMES


def nav_context(request):
    url_name = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
    return {
        'is_service_page': url_name in SERVICE_URL_NAMES,
    }
