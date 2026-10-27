from django.conf import settings
from django.db import models


class Document(models.Model):
    class Kind(models.TextChoices):
        CV = "cv", "Professional CV"
        RESUME = "resume", "Résumé"
        COVER_LETTER = "cover-letter", "Cover letter"
        BIO = "bio", "Professional biography"
        REFERENCES = "references", "Reference sheet"
        PORTFOLIO = "portfolio", "Portfolio summary"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CV)
    template = models.CharField(max_length=40, default="classic")
    content = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title
