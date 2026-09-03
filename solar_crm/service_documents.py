from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solar_crm.calculations import money
from solar_crm.db import query_one
from solar_crm.ui import date_br


GREEN = HexColor("#0B7A53")
DARK = HexColor("#17231D")
MUTED = HexColor("#65736B")
PALE = HexColor("#EDF4F0")
BORDER = HexColor("#CDDCD4")


def _safe(value: object) -> str:
    return str(value or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocBrand", fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=GREEN))
    styles.add(ParagraphStyle(name="DocTitle", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=DARK, spaceBefore=12, spaceAfter=5))
    styles.add(ParagraphStyle(name="DocSection", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=DARK, spaceBefore=11, spaceAfter=5))
    styles.add(ParagraphStyle(name="DocBody", fontName="Helvetica", fontSize=8.6, leading=12.2, textColor=DARK, alignment=4))
    styles.add(ParagraphStyle(name="DocSmall", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle(name="DocSmallCenter", parent=styles["DocSmall"], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="DocLabel", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED))
    styles.add(ParagraphStyle(name="DocValue", fontName="Helvetica", fontSize=8.3, leading=11, textColor=DARK))
    styles.add(ParagraphStyle(name="DocRight", parent=styles["DocValue"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="DocCenter", parent=styles["DocValue"], alignment=TA_CENTER))
    return styles


def _footer(canvas, doc, company: dict, label: str) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(BORDER)
    canvas.line(1.5 * cm, 1.15 * cm, width - 1.5 * cm, 1.15 * cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(1.5 * cm, 0.75 * cm, f"{company['company_name']} - {label}")
    canvas.drawRightString(width - 1.5 * cm, 0.75 * cm, f"Pag. {doc.page}")
    canvas.restoreState()


def _header(company: dict, title: str, subtitle: str, styles) -> list:
    return [
        Paragraph(_safe(company["company_name"]), styles["DocBrand"]),
        Paragraph(_safe(company.get("legal_name") or company["company_name"]), styles["DocSmall"]),
        Paragraph(_safe(title), styles["DocTitle"]),
        Paragraph(_safe(subtitle), styles["DocSmall"]),
        Spacer(1, 0.3 * cm),
    ]


def _info_table(rows: list[list[object]], styles, widths: list[float] | None = None) -> Table:
    data = []
    for row in rows:
        data.append([
            Paragraph(_safe(row[index]), styles["DocLabel" if index % 2 == 0 else "DocValue"])
            for index in range(len(row))
        ])
    table = Table(data, colWidths=widths)
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _text_block(title: str, text: object, styles) -> list:
    content = str(text or "Não informado.").strip()
    paragraphs = [Paragraph(_safe(line), styles["DocBody"]) for line in content.splitlines() if line.strip()]
    return [Paragraph(title, styles["DocSection"]), *(paragraphs or [Paragraph("Não informado.", styles["DocBody"])])]


def _technical_signature(company: dict, styles, include_client: bool = True) -> Table:
    signature_area = Spacer(1, 1.05 * cm)
    if company.get("signature_image"):
        try:
            handwritten = Image(BytesIO(company["signature_image"]))
            scale = min(5.2 * cm / handwritten.imageWidth, 1.0 * cm / handwritten.imageHeight)
            handwritten.drawWidth = handwritten.imageWidth * scale
            handwritten.drawHeight = handwritten.imageHeight * scale
            handwritten.hAlign = "CENTER"
            signature_area = handwritten
        except Exception:
            signature_area = Spacer(1, 1.05 * cm)

    row_heights = [1.2 * cm, 0.48 * cm, 0.4 * cm, 0.4 * cm]
    common_style = TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 1), (-1, 1), 0.6, MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ])
    technical = Table([
        [signature_area],
        [Paragraph(_safe(company.get("technical_name")), styles["DocCenter"])],
        [Paragraph(_safe(company.get("technical_title")), styles["DocSmallCenter"])],
        [Paragraph(_safe(company.get("technical_registration")), styles["DocSmallCenter"])],
    ], colWidths=[7.4 * cm], rowHeights=row_heights)
    technical.setStyle(common_style)
    if not include_client:
        return technical
    client = Table([
        [Spacer(1, 1.05 * cm)],
        [Paragraph("Responsável do cliente", styles["DocCenter"])],
        [Paragraph("Nome e assinatura", styles["DocSmallCenter"])],
        [Spacer(1, 0.15 * cm)],
    ], colWidths=[7.4 * cm], rowHeights=row_heights)
    client.setStyle(common_style)
    signatures = Table([[technical, client]], colWidths=[8.6 * cm, 8.6 * cm])
    signatures.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0.55 * cm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0.55 * cm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return signatures


def generate_service_order_pdf(order_id: int, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1")
    order = query_one(
        """SELECT so.*, c.name AS client_name, c.document AS client_document,
                  p.name AS plant_name, p.unit_code, p.inverter, p.modules
           FROM service_orders so JOIN clients c ON c.id=so.client_id
           LEFT JOIN plants p ON p.id=so.plant_id WHERE so.id=?""",
        (order_id,),
    )
    if not order:
        raise ValueError("Ordem de serviço não encontrada.")
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.3 * cm, bottomMargin=1.8 * cm,
        title=f"{order['number']} - {order['title']}", author=company["company_name"],
    )
    story = _header(company, "Ordem de serviço", f"{order['number']} - Status: {order['status']}", styles)
    story.append(_info_table([
        ["CLIENTE", order["client_name"], "DOCUMENTO", order["client_document"]],
        ["USINA / UC", f"{order.get('plant_name') or 'Serviço geral'} / {order.get('unit_code') or '-'}", "PRIORIDADE", order["priority"]],
        ["AGENDAMENTO", date_br(order["scheduled_date"]), "RESPONSÁVEL", order["assignee"]],
        ["CONTATO", order["contact_name"], "TELEFONE", order["contact_phone"]],
    ], styles, [2.7 * cm, 5.9 * cm, 2.7 * cm, 5.9 * cm]))
    story += _text_block("Endereço de atendimento", order["address"], styles)
    story += _text_block("Serviço a executar", order["work_description"], styles)
    story += _text_block("Segurança e acesso", order["safety_instructions"], styles)
    story += _text_block("Materiais e ferramentas previstos", order["materials"], styles)
    if order.get("inverter") or order.get("modules"):
        story.append(_info_table([
            ["INVERSOR", order.get("inverter"), "MÓDULOS", order.get("modules")],
        ], styles, [2.7 * cm, 5.9 * cm, 2.7 * cm, 5.9 * cm]))
    story += _text_block("Registro da execução", order.get("completion_notes") or "Preencher após a execução do serviço.", styles)
    story += [Spacer(1, 0.5 * cm), KeepTogether([_technical_signature(company, styles)])]
    doc.build(
        story,
        onFirstPage=lambda c, d: _footer(c, d, company, order["number"]),
        onLaterPages=lambda c, d: _footer(c, d, company, order["number"]),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf


def generate_service_contract_pdf(contract_id: int, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1")
    contract = query_one(
        """SELECT sc.*, c.name AS client_name, c.document AS client_document,
                  c.address AS client_address, c.city AS client_city, c.state AS client_state,
                  c.contact_name, c.email AS client_email
           FROM service_contracts sc JOIN clients c ON c.id=sc.client_id WHERE sc.id=?""",
        (contract_id,),
    )
    if not contract:
        raise ValueError("Contrato não encontrado.")
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=1.65 * cm, leftMargin=1.65 * cm,
        topMargin=1.35 * cm, bottomMargin=1.8 * cm,
        title=f"{contract['number']} - {contract['title']}", author=company["company_name"],
    )
    story = _header(company, contract["title"], f"Instrumento nº {contract['number']} - {contract['status']}", styles)
    parties = (
        f"CONTRATADA: {_safe(company.get('legal_name') or company['company_name'])}, inscrita sob o documento "
        f"{_safe(company.get('document'))}, com endereço em {_safe(company.get('address'))}.<br/><br/>"
        f"CONTRATANTE: {_safe(contract['client_name'])}, inscrito(a) sob o documento "
        f"{_safe(contract['client_document'])}, com endereço em {_safe(contract['client_address'])}, "
        f"{_safe(contract['client_city'])}/{_safe(contract['client_state'])}."
    )
    story += [Paragraph("Qualificação das partes", styles["DocSection"]), Paragraph(parties, styles["DocBody"])]
    clauses = [
        ("1. Objeto e escopo", contract["scope"]),
        ("2. Obrigações da contratada", contract["contractor_obligations"] or "Executar os serviços descritos no escopo com diligência técnica, registrar as atividades realizadas e comunicar impedimentos relevantes."),
        ("3. Obrigações da contratante", contract["client_obligations"] or "Fornecer informações corretas, acesso seguro às instalações, documentos e autorizações necessários, bem como efetuar os pagamentos nas condições pactuadas."),
        ("4. Remuneração e pagamento", f"Valor de {money(contract['amount'])}, com cobrança {str(contract['billing_cycle']).lower()}. {contract['payment_terms'] or 'As datas, meios de pagamento e eventuais despesas extraordinárias deverão ser confirmados entre as partes.'}"),
        ("5. Prazo", f"Vigência de {contract['duration_months']} mes(es), com início em {date_br(contract['start_date'])} e término em {date_br(contract['end_date'])}."),
        ("6. Limites técnicos", "Os resultados de geração dependem de irradiação, clima, disponibilidade da rede, condições dos equipamentos e dados fornecidos por terceiros. Serviços não descritos no escopo exigem aprovação adicional."),
        ("7. Confidencialidade e dados", "As partes utilizarão dados pessoais e operacionais somente para executar o contrato, prestar suporte, emitir documentos e cumprir obrigações aplicáveis, adotando medidas razoáveis de segurança e acesso restrito."),
        ("8. Rescisão", contract["termination_terms"] or "O contrato poderá ser encerrado por acordo escrito ou por descumprimento relevante, assegurada a quitação dos serviços efetivamente prestados e despesas previamente aprovadas."),
        ("9. Condições adicionais", contract["additional_terms"] or "Não há condições adicionais registradas."),
        ("10. Foro", f"As partes indicam o foro de {_safe(contract['venue'] or contract['client_city'])}, ressalvadas as regras legais de competência aplicáveis."),
    ]
    for title, text in clauses:
        story += _text_block(title, text, styles)
    story += [
        PageBreak(),
        Paragraph("Assinaturas", styles["DocTitle"]),
        Paragraph(
            f"As partes declaram que leram e compreenderam as condições do instrumento {contract['number']} e, estando de acordo, o assinam. Data: ____/____/________.",
            styles["DocBody"],
        ),
        Spacer(1, 0.8 * cm),
        KeepTogether([_technical_signature(company, styles)]),
        Spacer(1, 0.7 * cm),
        _info_table([
            ["TESTEMUNHA 1", "Nome: ______________________________  CPF: ____________________"],
            ["TESTEMUNHA 2", "Nome: ______________________________  CPF: ____________________"],
        ], styles, [3.0 * cm, 14.2 * cm]),
        Spacer(1, 0.45 * cm),
        Paragraph("Minuta administrativa gerada pelo SolarOS. Recomenda-se revisão jurídica antes da assinatura, especialmente quanto a tributos, responsabilidade, garantias, foro e regras específicas do serviço contratado.", styles["DocSmall"]),
    ]
    doc.build(
        story,
        onFirstPage=lambda c, d: _footer(c, d, company, contract["number"]),
        onLaterPages=lambda c, d: _footer(c, d, company, contract["number"]),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf
