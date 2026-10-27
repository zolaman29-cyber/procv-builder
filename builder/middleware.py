from .models import DailySiteStat


class SiteStatsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method == "GET"
            and response.status_code == 200
            and response.get("Content-Type", "").startswith("text/html")
            and not request.path.startswith(("/admin/", "/site-admin/"))
        ):
            DailySiteStat.record("page_views")
        return response
