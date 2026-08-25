"""Stage 5 - Render (plain code, no LLM).

Renders a one-page PDF brief per prospect: header, findings table,
hook_strength + agent_notes, draft connection note, draft email sequence,
risk flags -- in that order, per spec.

WeasyPrint (HTML+CSS -> PDF, via app/templates/brief.html) is the preferred
renderer. WeasyPrint needs GTK3/Pango native libraries that are frequently
missing on a stock Windows machine, so if it fails to even import, we fall
back to fpdf2 (pure Python, no system deps) with a simpler but still
complete one-page layout covering the same sections. This is documented
again in the README's "PDF rendering" section.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from app.models import Company, Finding, OutreachDraft, Prospect, ResearchFindings

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _render_html(
    prospect: Prospect,
    company: Company,
    findings: list[Finding],
    research: ResearchFindings | None,
    draft: OutreachDraft | None,
    risk_flags: list[dict],
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("brief.html")
    return template.render(
        prospect=prospect,
        company=company,
        findings=findings,
        research=research,
        draft=draft,
        risk_flags=risk_flags,
    )


def _try_weasyprint(html: str, out_path: Path) -> bool:
    try:
        from weasyprint import HTML  # heavy native-lib import, guarded
    except Exception:
        return False
    try:
        HTML(string=html).write_pdf(str(out_path))
        return True
    except Exception:
        return False


def _safe(text: str) -> str:
    """fpdf2's core (non-Unicode) fonts only support latin-1. Replace anything
    outside that range rather than crashing PDF generation on a stray em-dash
    or curly quote coming back from the LLM."""
    if text is None:
        return ""
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


def _render_with_fpdf2(
    prospect: Prospect,
    company: Company,
    findings: list[Finding],
    research: ResearchFindings | None,
    draft: OutreachDraft | None,
    risk_flags: list[dict],
    out_path: Path,
) -> None:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, _safe(prospect.full_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _safe(f"{prospect.title_raw} - {company.name}"), new_x="LMARGIN", new_y="NEXT")
    meta_bits = [company.city]
    if prospect.linkedin_url:
        meta_bits.append(prospect.linkedin_url)
    if prospect.email:
        meta_bits.append(prospect.email)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _safe(" | ".join(meta_bits)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    def section_header(title: str) -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, _safe(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(200, 200, 200)
        y = pdf.get_y()
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(2)

    section_header("Findings")
    pdf.set_font("Helvetica", "", 8.5)
    if findings:
        for f in findings:
            slot = f.slot.value if hasattr(f.slot, "value") else f.slot
            line = f"[{slot}] {f.claim} (confidence {f.confidence:.2f})"
            pdf.multi_cell(0, 4.5, _safe(line), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(80, 80, 160)
            pdf.multi_cell(0, 4.5, _safe(f.source_url), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
    else:
        pdf.cell(0, 5, "No findings recorded.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    section_header("Research Summary")
    pdf.set_font("Helvetica", "", 9.5)
    if research is not None:
        terminal = research.terminal_reason.value if hasattr(research.terminal_reason, "value") else research.terminal_reason
        pdf.cell(0, 5, _safe(f"Hook strength: {research.hook_strength} / 3   Terminal reason: {terminal}"), new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 4.5, _safe(research.agent_notes or "(no notes)"), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 5, "No research run yet.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    section_header("Draft Connection Note")
    pdf.set_font("Helvetica", "I", 9.5)
    if draft is not None and not draft.disqualify:
        pdf.multi_cell(0, 5, _safe(draft.connection_note), new_x="LMARGIN", new_y="NEXT")
    elif draft is not None and draft.disqualify:
        pdf.multi_cell(0, 5, _safe(f"Disqualified at synthesis: {draft.disqualify_reason}"), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 5, "No draft yet.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if draft is not None and draft.email_sequence:
        section_header("Email Sequence")
        pdf.set_font("Helvetica", "", 9)
        for step in draft.email_sequence:
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.cell(
                0,
                5,
                _safe(f"Step {step.get('step')} ({step.get('purpose')}) - send after {step.get('send_after_days')} day(s)"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, _safe(f"Subject: {step.get('subject')}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 4.5, _safe(step.get("body", "")), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

    section_header("Risk Flags")
    pdf.set_font("Helvetica", "", 9)
    if risk_flags:
        for rf in risk_flags:
            pdf.multi_cell(0, 4.5, _safe(f"- {rf['flag']}: {rf['detail']}"), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 5, "None.", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(out_path))


def render_prospect_pdf(
    prospect: Prospect,
    company: Company,
    findings: list[Finding],
    research: ResearchFindings | None,
    draft: OutreachDraft | None,
    risk_flags: list[dict],
) -> Path:
    """Renders the PDF and returns its path. Tries WeasyPrint first, falls
    back to fpdf2. Never raises for a missing WeasyPrint install -- that is
    the expected, documented path on a stock Windows machine."""
    settings = get_settings()
    settings.PDF_DIR.mkdir(parents=True, exist_ok=True)
    out_path = settings.PDF_DIR / f"{prospect.prospect_id}.pdf"

    html = _render_html(prospect, company, findings, research, draft, risk_flags)
    if _try_weasyprint(html, out_path):
        return out_path

    _render_with_fpdf2(prospect, company, findings, research, draft, risk_flags, out_path)
    return out_path
