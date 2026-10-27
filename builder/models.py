from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.db.models import F
from django.utils import timezone


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


class DailySiteStat(models.Model):
    date = models.DateField(unique=True)
    page_views = models.PositiveIntegerField(default=0)
    pdf_downloads = models.PositiveIntegerField(default=0)
    registrations = models.PositiveIntegerField(default=0)

    @classmethod
    def record(cls, metric):
        if metric not in {"page_views", "pdf_downloads", "registrations"}:
            raise ValueError(f"Unknown site-stat metric: {metric}")

        today = timezone.localdate()
        try:
            with transaction.atomic():
                stats, _ = cls.objects.get_or_create(date=today)
                cls.objects.filter(pk=stats.pk).update(**{metric: F(metric) + 1})
        except IntegrityError:
            cls.objects.filter(date=today).update(**{metric: F(metric) + 1})

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Site stats for {self.date}"
