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
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    theme = pdf_theme(document.template)
    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm, title=document.title,
    )
    styles = getSampleStyleSheet()
    accent = colors.HexColor(theme["accent"])
    name_style = ParagraphStyle(
        "ResumeName", parent=styles["Title"], alignment=theme["alignment"],
        textColor=colors.HexColor(theme["name_color"]), fontName=theme["title_font"],
        fontSize=theme["name_size"], leading=theme["name_size"] * 1.15,
        spaceAfter=4,
    )
    job_style = ParagraphStyle(
        "ResumeJob", parent=styles["BodyText"], alignment=theme["alignment"],
        textColor=colors.HexColor(theme["job_color"]), fontName=theme["bold_font"],
        fontSize=10.5, leading=14, spaceAfter=5,
    )
    contact_style = ParagraphStyle(
        "ResumeContact", parent=styles["BodyText"], alignment=theme["alignment"],
        textColor=colors.HexColor(theme["contact_color"]), fontSize=7.5, leading=10,
    )
    heading_style = ParagraphStyle(
        "ResumeSection", parent=styles["Heading2"], textColor=accent,
        fontName=theme["bold_font"], fontSize=9, leading=12,
        spaceBefore=9, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "ResumeBody", parent=styles["BodyText"], textColor=colors.HexColor("#515a68"),
        fontName=theme["body_font"], fontSize=10, leading=15.5, spaceAfter=3,
    )
    entry_style = ParagraphStyle(
        "ResumeEntry", parent=body_style, textColor=colors.HexColor("#333d4e"),
        fontName=theme["bold_font"], fontSize=9, leading=12, spaceAfter=2,
    )
    entry_body_style = ParagraphStyle("ResumeEntryBody", parent=body_style, spaceAfter=0)
    if theme["two_column"]:
        for style in (heading_style, body_style):
            style.leftIndent = 30 * mm
        entry_style.leftIndent = 30 * mm
        entry_body_style.leftIndent = 30 * mm

    job_title = Paragraph(escape_pdf(content.get("job_title", "")), job_style)
    contact = " · ".join(filter(None, [
        content.get("email"), content.get("phone"), content.get("location"),
        content.get("linkedin"), content.get("website"),
    ]))
    header_rows = [
        [Paragraph(escape_pdf(content.get("name") or "Your Name"), name_style)],
        [job_title],
    ]
    if contact:
        header_rows.append([Paragraph(escape_pdf(contact), contact_style)])
    header = Table(header_rows, colWidths=[pdf.width])
    header_style = [
        ("LEFTPADDING", (0, 0), (-1, -1), theme["header_padding"]),
        ("RIGHTPADDING", (0, 0), (-1, -1), theme["header_padding"]),
        ("TOPPADDING", (0, 0), (-1, 0), theme["header_top_padding"]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, -1), (-1, -1), theme["header_bottom_padding"]),
    ]
    if theme["header_background"]:
        header_style.append(("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(theme["header_background"])))
    if theme["header_border"]:
        header_style.append(("LINEBELOW", (0, -1), (-1, -1), 1.5, accent))
    if theme["header_double_border"]:
        header_style.extend([
            ("LINEBELOW", (0, -1), (-1, -1), 2, accent),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, accent),
        ])
    if theme["header_left_border"]:
        header_style.append(("LINEBEFORE", (0, 0), (0, -1), 4, accent))
    header.setStyle(TableStyle(header_style))
    story = [header, Spacer(1, 12)]

    for key, heading in (
        ("summary", "Professional Summary"),
        ("experience", "Experience"),
        ("education", "Education"),
        ("skills", "Skills"),
        ("projects", "Projects"),
        ("certifications", "Certifications"),
    ):
        values = content.get(key)
        if key in {"experience", "education", "projects", "certifications"}:
            values = [entry for entry in values if any(str(value).strip() for value in entry.values())]
        if not values:
            continue
        section_heading = "Profile" if key == "summary" else heading
        if theme["uppercase_sections"]:
            section_heading = section_heading.upper()
        story.append(Paragraph(escape_pdf(section_heading), heading_style))
        if theme["section_rule"]:
            story.append(HRFlowable(
                width=pdf.width - (30 * mm if theme["two_column"] else 0),
                thickness=0.5, color=colors.HexColor("#e5e8ed"),
                spaceBefore=-2, spaceAfter=5,
                hAlign="RIGHT" if theme["two_column"] else "LEFT",
            ))
        if isinstance(values, str):
            story.append(Paragraph(escape_pdf(values).replace("\n", "<br/>"), body_style))
        elif key == "skills":
            story.append(Paragraph(escape_pdf(" · ".join(values)), body_style))
        else:
            for entry in values:
                label = " · ".join(value for value in (
                    entry.get("title", ""), entry.get("company") or entry.get("institution", ""),
                    entry.get("dates", ""),
                ) if value)
                entry_story = []
                if label:
                    entry_story.append(Paragraph(escape_pdf(label), entry_style))
                description = entry.get("description", "")
                if description:
                    entry_story.append(Paragraph(escape_pdf(description), entry_body_style))
                if entry_story:
                    story.append(KeepTogether(entry_story))
                    story.append(Spacer(1, 6))
    draw_page = lambda canvas, doc: draw_pdf_template(canvas, doc, theme)
    pdf.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{safe_filename(document.title)}.pdf"'
    return response


def pdf_theme(template):
    theme = {
        "accent": "#315cba",
        "alignment": TA_LEFT,
        "body_font": "Helvetica",
        "bold_font": "Helvetica-Bold",
        "contact_color": "#6c7482",
        "header_background": None,
        "header_border": True,
        "header_bottom_padding": 5,
        "header_double_border": False,
        "header_left_border": False,
        "header_padding": 0,
        "header_top_padding": 0,
        "job_color": "#315cba",
        "name_color": "#202a3c",
        "name_size": 23,
        "section_rule": True,
        "title_font": "Helvetica-Bold",
        "uppercase_sections": True,
        "two_column": False,
    }
    if template == "modern":
        theme.update(
            accent="#13877c", contact_color="#d2d8e1", header_background="#24334e",
            header_border=False, header_bottom_padding=12, header_padding=13,
            header_top_padding=12, job_color="#b7ece2", name_color="#ffffff",
        )
    elif template == "minimal":
        theme.update(accent="#303640", header_border=False, section_rule=False)
    elif template == "creative":
        theme.update(
            accent="#b65840", header_border=False, header_left_border=True,
            header_padding=12, name_size=27, title_font="Times-Bold",
        )
    elif template == "academic":
        theme.update(
            accent="#3e5874", alignment=TA_CENTER, body_font="Times-Roman",
            bold_font="Times-Bold", title_font="Times-Bold",
        )
    elif template == "graduate":
        theme.update(
            accent="#5e67aa", header_background="#f1f2fa",
            header_border=False, header_bottom_padding=12, header_padding=13,
            header_top_padding=12,
        )
    elif template == "technical":
        theme.update(
            accent="#218261", body_font="Courier", bold_font="Courier-Bold",
            title_font="Courier-Bold",
        )
    elif template == "executive":
        theme.update(
            accent="#8a6c35", body_font="Times-Roman", bold_font="Times-Bold",
            title_font="Times-Bold",
        )
    elif template == "two-column":
        theme.update(accent="#48608c", two_column=True)
    elif template == "ats":
        theme.update(
            accent="#252525", body_font="Helvetica", header_border=True,
            uppercase_sections=False, section_rule=False,
        )
    elif template == "elegant":
        theme.update(
            accent="#765875", body_font="Times-Roman", bold_font="Times-Bold",
            title_font="Times-Bold",
        )
    elif template == "international":
        theme.update(accent="#315b74", header_double_border=True, name_size=20)
    return theme


def draw_pdf_template(canvas, document, theme):
    if theme["two_column"]:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#eef1f7"))
        canvas.rect(0, 0, 26 * mm, A4[1], stroke=0, fill=1)
        canvas.restoreState()


def escape_pdf(value):
    from xml.sax.saxutils import escape
    return escape(str(value))


def safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "document"
