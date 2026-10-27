import json
import re
from copy import deepcopy
from io import BytesIO

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .models import Document
from .forms import RegistrationForm
from .templates import TEMPLATES

EMPTY_CONTENT = {
    "name": "",
    "job_title": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "website": "",
    "summary": "",
    "experience": [],
    "education": [],
    "skills": [],
    "projects": [],
    "certifications": [],
}


def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    documents = request.user.documents.all()
    query = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    if query:
        documents = documents.filter(title__icontains=query)
    if kind in Document.Kind.values:
        documents = documents.filter(kind=kind)
    return render(request, "builder/dashboard.html", {
        "documents": documents,
        "query": query,
        "kind": kind,
        "kinds": Document.Kind.choices,
    })


@login_required
@require_POST
def create_document(request):
    kind = request.POST.get("kind", Document.Kind.CV)
    if kind not in Document.Kind.values:
        return JsonResponse({"error": "Choose a valid document type."}, status=400)
    title = request.POST.get("title", "").strip()[:120]
    if not title:
        title = dict(Document.Kind.choices).get(kind, "New document")
    document = Document.objects.create(owner=request.user, title=title, kind=kind, content=deepcopy(EMPTY_CONTENT))
    return redirect("edit_document", pk=document.pk)


@login_required
def edit_document(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    return render(request, "builder/editor.html", {
        "document": document,
        "content_json": json.dumps(document.content, ensure_ascii=False),
        "template_choices": [(key, value[0]) for key, value in TEMPLATES.items()],
    })


@login_required
@require_POST
def save_document(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), dict):
        return JsonResponse({"error": "Document content must be an object."}, status=400)
    title = str(payload.get("title", document.title)).strip()[:120]
    template = payload.get("template", document.template)
    if not title or template not in TEMPLATES:
        return JsonResponse({"error": "A title and valid template are required."}, status=400)
    document.title = title
    document.template = template
    document.content = clean_content(payload["content"])
    document.save(update_fields=["title", "template", "content", "updated_at"])
    return JsonResponse({"saved": True, "updated_at": document.updated_at.isoformat()})


def clean_content(raw):
    cleaned = {}
    scalar_keys = ("name", "job_title", "email", "phone", "location", "linkedin", "website", "summary")
    for key in scalar_keys:
        value = raw.get(key, "")
        cleaned[key] = str(value)[:5000] if isinstance(value, (str, int, float)) else ""
    for key in ("experience", "education", "projects", "certifications"):
        entries = raw.get(key, [])
        if not isinstance(entries, list):
            entries = []
        cleaned[key] = []
        for entry in entries[:50]:
            if isinstance(entry, dict):
                cleaned[key].append({
                    str(k)[:50]: str(v)[:3000]
                    for k, v in entry.items()
                    if isinstance(v, (str, int, float))
                })
    skills = raw.get("skills", [])
    if isinstance(skills, str):
        skills = skills.splitlines()
    cleaned["skills"] = [str(item)[:120] for item in skills[:100] if str(item).strip()] if isinstance(skills, list) else []
    return cleaned


@login_required
@require_POST
def duplicate_document(request, pk):
    original = get_object_or_404(Document, pk=pk, owner=request.user)
    copy = Document.objects.create(
        owner=request.user,
        title=f"{original.title} (copy)"[:120],
        kind=original.kind,
        template=original.template,
        content=deepcopy(original.content),
    )
    return redirect("edit_document", pk=copy.pk)


@login_required
@require_POST
def delete_document(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    document.delete()
    messages.success(request, "Document deleted.")
    return redirect("dashboard")


@login_required
def download_pdf(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    content = clean_content(document.content)
    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title=document.title,
    )
    styles = getSampleStyleSheet()
    accent = colors.HexColor("#315cba")
    name_style = ParagraphStyle("Name", parent=styles["Title"], alignment=TA_LEFT, textColor=accent, fontSize=22, leading=26)
    heading_style = ParagraphStyle("Section", parent=styles["Heading2"], textColor=accent, fontSize=11, leading=14, spaceBefore=11, spaceAfter=4)
    body_style = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=3)
    story = []
    story.append(Paragraph(escape_pdf(content.get("name") or "Your Name"), name_style))
    story.append(Paragraph(escape_pdf(content.get("job_title", "")), styles["Heading3"]))
    contact = " · ".join(filter(None, [
        content.get("email"), content.get("phone"), content.get("location"),
        content.get("linkedin"), content.get("website"),
    ]))
    if contact:
        story.append(Paragraph(escape_pdf(contact), body_style))
    for key, heading in (
        ("summary", "Professional Summary"),
        ("experience", "Experience"),
        ("education", "Education"),
        ("projects", "Projects"),
        ("skills", "Skills"),
        ("certifications", "Certifications"),
    ):
        values = content.get(key)
        if not values:
            continue
        story.append(Paragraph(heading, heading_style))
        if isinstance(values, str):
            story.append(Paragraph(escape_pdf(values).replace("\n", "<br/>"), body_style))
        elif key == "skills":
            story.append(Paragraph(escape_pdf(" · ".join(values)), body_style))
        else:
            for entry in values:
                label = " — ".join(value for value in (
                    entry.get("title", ""), entry.get("company", entry.get("institution", "")),
                    entry.get("dates", ""),
                ) if value)
                if label:
                    story.append(Paragraph(f"<b>{escape_pdf(label)}</b>", body_style))
                description = entry.get("description", "")
                if description:
                    story.append(Paragraph(escape_pdf(description).replace("\n", "<br/>"), body_style))
                story.append(Spacer(1, 3))
    pdf.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{safe_filename(document.title)}.pdf"'
    return response


def escape_pdf(value):
    from xml.sax.saxutils import escape
    return escape(str(value))


def safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "document"
