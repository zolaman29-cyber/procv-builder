from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("documents/new/", views.create_document, name="create_document"),
    path("documents/<int:pk>/", views.edit_document, name="edit_document"),
    path("documents/<int:pk>/save/", views.save_document, name="save_document"),
    path("documents/<int:pk>/duplicate/", views.duplicate_document, name="duplicate_document"),
    path("documents/<int:pk>/delete/", views.delete_document, name="delete_document"),
    path("documents/<int:pk>/pdf/", views.download_pdf, name="download_pdf"),
]
