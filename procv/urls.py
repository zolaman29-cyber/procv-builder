from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from builder import views as builder_views

urlpatterns = [
    path("admin/stats/", builder_views.site_stats, name="site_stats"),
    path("admin/users/", builder_views.user_list, name="user_list"),
    path("admin/users/<int:pk>/", builder_views.user_detail, name="user_detail"),
    path("admin/users/<int:pk>/toggle-active/", builder_views.toggle_user_active, name="toggle_user_active"),
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("builder.urls")),
]
