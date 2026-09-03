from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solar_crm.calculations import money
from solar_crm.db import query_one
from solar_crm.service_documents import _footer, _safe, _styles, _technical_signature, _text_block
from solar_crm.ui import date_br


ORANGE = HexColor("#F58218")
BLUE = HexColor("#3A91C5")
DARK = HexColor("#18323C")
PALE_BLUE = HexColor("#EDF7FC")
BORDER = HexColor("#CFDCE2")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGO = PROJECT_ROOT / "assets" / "ongrid_logo.png"


def _brand_header(proposal: dict, styles) -> Table:
    if DEFAULT_LOGO.exists():
        logo = Image(str(DEFAULT_LOGO))
        scale = min(7.2 * cm / logo.imageWidth, 2.1 * cm / logo.imageHeight)
        logo.drawWidth = logo.imageWidth * scale
        logo.drawHeight = logo.imageHeight * scale
        logo.hAlign = "LEFT"
        brand = logo
    else:
        brand = Paragraph("<b>OnGrid Energia Solar</b>", styles["DocBrand"])
    summary = Paragraph(
        f"<b>PROPOSTA COMERCIAL</b><br/><font size='10'>{_safe(proposal['number'])}</font><br/>"
        f"<font color='#65736B' size='8'>Status: {_safe(proposal['status'])}</font>",
        styles["ProposalRight"],
    )
    table = Table([[brand, summary]], colWidths=[10.5 * cm, 6.7 * cm], rowHeights=[2.45 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 2.2, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def generate_proposal_pdf(proposal_id: int, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1")
    brand_company = dict(company)
    brand_company["company_name"] = "OnGrid Energia Solar"
    proposal = query_one(
        """SELECT pr.*, c.name AS client_name, c.document AS client_document,
                  c.contact_name, c.email AS client_email, c.phone AS client_phone,
                  c.address AS client_address, c.city AS client_city, c.state AS client_state,
                  o.lead_name AS opportunity_name
           FROM proposals pr JOIN clients c ON c.id=pr.client_id
           LEFT JOIN opportunities o ON o.id=pr.opportunity_id
           WHERE pr.id=?""",
        (proposal_id,),
    )
    if not proposal:
        raise ValueError("Proposta não encontrada.")

    styles = _styles()
    styles.add(ParagraphStyle(
        name="ProposalRight", parent=styles["DocRight"], fontSize=9, leading=13,
        textColor=DARK, alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="ProposalHero", parent=styles["DocTitle"], fontSize=22, leading=27,
        textColor=DARK, spaceBefore=12, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="ProposalPrice", parent=styles["DocCenter"], fontName="Helvetica-Bold",
        fontSize=22, leading=25, textColor=ORANGE, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="ProposalPriceLabel", parent=styles["DocSmallCenter"], fontSize=8,
        leading=10, textColor=DARK, alignment=TA_CENTER,
    ))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=1.55 * cm, leftMargin=1.55 * cm,
        topMargin=1.2 * cm, bottomMargin=1.8 * cm,
        title=f"{proposal['number']} - {proposal['title']}", author="OnGrid Energia Solar",
    )

    story: list = [_brand_header(proposal, styles), Spacer(1, 0.34 * cm)]
    story.append(Paragraph(_safe(proposal["title"]), styles["ProposalHero"]))
    story.append(Paragraph(
        f"Solução de {_safe(str(proposal['service_type']).lower())} preparada para <b>{_safe(proposal['client_name'])}</b>.",
        styles["DocBody"],
    ))
    story.append(Spacer(1, 0.32 * cm))

    client_table = Table([
        [Paragraph("CLIENTE", styles["DocLabel"]), Paragraph(_safe(proposal["client_name"]), styles["DocValue"]),
         Paragraph("DOCUMENTO", styles["DocLabel"]), Paragraph(_safe(proposal["client_document"]), styles["DocValue"])],
        [Paragraph("CONTATO", styles["DocLabel"]), Paragraph(_safe(proposal["contact_name"]), styles["DocValue"]),
         Paragraph("E-MAIL / TELEFONE", styles["DocLabel"]), Paragraph(f"{_safe(proposal['client_email'])}<br/>{_safe(proposal['client_phone'])}", styles["DocValue"])],
        [Paragraph("EMISSÃO", styles["DocLabel"]), Paragraph(date_br(proposal["issue_date"]), styles["DocValue"]),
         Paragraph("VALIDADE", styles["DocLabel"]), Paragraph(date_br(proposal["valid_until"]), styles["DocValue"])],
    ], colWidths=[2.45 * cm, 5.45 * cm, 3.2 * cm, 6.1 * cm])
    client_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(client_table)

    price_card = Table([[
        Paragraph("INVESTIMENTO", styles["ProposalPriceLabel"]),
        Paragraph(money(proposal["amount"]), styles["ProposalPrice"]),
        Paragraph(f"Prazo estimado<br/><b>{proposal['deadline_days']} dias</b>", styles["DocCenter"]),
    ]], colWidths=[3.5 * cm, 8.0 * cm, 5.7 * cm], rowHeights=[1.45 * cm])
    price_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.8, BLUE),
        ("LINEBEFORE", (1, 0), (2, 0), 0.5, BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [Spacer(1, 0.38 * cm), price_card]

    story += _text_block("Escopo da solução", proposal["scope"], styles)
    story += _text_block("Entregáveis", proposal["deliverables"], styles)
    story += _text_block("Condições de pagamento", proposal["payment_terms"], styles)
    story += _text_block("Itens não inclusos", proposal["exclusions"], styles)
    if proposal.get("notes"):
        story += _text_block("Observações comerciais", proposal["notes"], styles)

    acceptance = Table([
        [Paragraph("ACEITE DA PROPOSTA", styles["DocSection"])],
        [Paragraph(
            f"Declaro que li e aceito as condições da proposta {_safe(proposal['number'])}, no valor de "
            f"<b>{money(proposal['amount'])}</b>. Data: ____/____/________.",
            styles["DocBody"],
        )],
    ], colWidths=[17.2 * cm])
    acceptance.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, ORANGE),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#FFF4E8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [Spacer(1, 0.45 * cm), acceptance, Spacer(1, 0.65 * cm)]
    story.append(KeepTogether([_technical_signature(company, styles)]))
    story += [Spacer(1, 0.35 * cm), Paragraph(
        "Esta proposta apresenta condições comerciais preliminares. Serviços técnicos sujeitos a responsabilidade profissional, aprovação da distribuidora ou levantamento de campo serão executados conforme o escopo contratado e a legislação aplicável.",
        styles["DocSmall"],
    )]

    doc.build(
        story,
        onFirstPage=lambda canvas, document: _footer(canvas, document, brand_company, proposal["number"]),
        onLaterPages=lambda canvas, document: _footer(canvas, document, brand_company, proposal["number"]),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf
