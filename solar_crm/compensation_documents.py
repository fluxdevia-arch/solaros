from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solar_crm.branding import configured_logo
from solar_crm.calculations import number_br
from solar_crm.compensation_statement import CompensationStatement
from solar_crm.db import query_one
from solar_crm.service_documents import _footer, _safe, _styles, _technical_signature


NAVY = HexColor("#0D3B66")
BLUE = HexColor("#2A6F97")
ORANGE = HexColor("#F58218")
GREEN = HexColor("#197451")
LIGHT_BLUE = HexColor("#EAF3F8")
LIGHT_GREEN = HexColor("#E8F4EE")
BORDER = HexColor("#CBD8DF")
MUTED = HexColor("#65736B")


def _header(company: dict, statement: CompensationStatement, styles) -> Table:
    try:
        source = configured_logo(company)
        logo = Image(BytesIO(source) if isinstance(source, bytes) else str(source))
        scale = min(7.0 * cm / logo.imageWidth, 2.0 * cm / logo.imageHeight)
        logo.drawWidth = logo.imageWidth * scale
        logo.drawHeight = logo.imageHeight * scale
        brand = logo
    except Exception:
        brand = Paragraph(f"<b>{_safe(company.get('company_name') or 'GRID Engenharia')}</b>", styles["DocBrand"])
    reference = statement.reference_month.replace("-", "/") if statement.reference_month else "não identificada"
    title = Paragraph(
        "<b>RELATÓRIO DE COMPENSAÇÃO DE ENERGIA</b><br/>"
        f"<font size='9' color='#65736B'>Energisa - referência {reference}</font>",
        styles["CompRight"],
    )
    table = Table([[brand, title]], colWidths=[9.1 * cm, 8.1 * cm], rowHeights=[2.35 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 2.2, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _card(label: str, value: str, styles, background=LIGHT_BLUE) -> Table:
    card = Table([
        [Paragraph(label.upper(), styles["CompCardLabel"])],
        [Paragraph(value, styles["CompCardValue"])],
    ], colWidths=[4.1 * cm], rowHeights=[0.45 * cm, 0.78 * cm])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background), ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return card


def _key_values(rows: list[tuple[str, str]], styles) -> Table:
    data = [[Paragraph(_safe(label), styles["DocLabel"]), Paragraph(_safe(value), styles["DocValue"])] for label, value in rows]
    table = Table(data, colWidths=[5.3 * cm, 11.9 * cm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _history_chart(statement: CompensationStatement) -> Drawing | None:
    off_peak = sorted((row for row in statement.history if row.period == "Fora de ponta"), key=lambda row: (row.year, row.month))
    if not off_peak:
        return None
    labels = [f"{row.month:02d}/{str(row.year)[2:]}" for row in off_peak[-13:]]
    values = [row.injected_kwh for row in off_peak[-13:]]
    drawing = Drawing(490, 112)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.height, chart.width = 42, 28, 65, 425
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 35
    chart.categoryAxis.labels.dy = -9
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.gridStrokeColor = HexColor("#E2E9ED")
    chart.bars[0].fillColor = BLUE
    chart.bars[0].strokeColor = BLUE
    drawing.add(chart)
    drawing.add(String(6, 101, "Energia injetada - fora de ponta (kWh)", fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    return drawing


def generate_compensation_statement_pdf(statement: CompensationStatement, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1") or {
        "company_name": "GRID Engenharia", "technical_name": "Carlos Jessé Soares",
        "technical_title": "Téc. Eletrotécnica", "technical_registration": "CFT: 11551320410",
    }
    styles = _styles()
    styles.add(ParagraphStyle(name="CompRight", parent=styles["DocRight"], alignment=TA_RIGHT, fontSize=9, leading=13, textColor=NAVY))
    styles.add(ParagraphStyle(name="CompCardLabel", parent=styles["DocSmall"], alignment=TA_CENTER, fontSize=6.8, leading=8, textColor=MUTED))
    styles.add(ParagraphStyle(name="CompCardValue", parent=styles["DocCenter"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=12.5, leading=14, textColor=NAVY))
    styles.add(ParagraphStyle(name="CompCell", parent=styles["DocSmall"], fontSize=7.2, leading=8.6))

    buffer = BytesIO()
    reference = statement.reference_month or "sem-referencia"
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=1.55 * cm, leftMargin=1.55 * cm,
        topMargin=1.15 * cm, bottomMargin=1.8 * cm,
        title=f"Compensação de energia {statement.unit_code} - {reference}",
        author=company.get("company_name") or "GRID Engenharia",
    )
    story: list = [_header(company, statement, styles), Spacer(1, 0.3 * cm)]
    story += [Paragraph("Identificação da unidade geradora", styles["DocSection"]), _key_values([
        ("Cliente", statement.client_name or "Não identificado"),
        ("Endereço", statement.address or "Não identificado"),
        ("Unidade consumidora", statement.unit_code or "Não identificada"),
        ("Grupo / modalidade", statement.voltage_group or "Não identificado"),
        ("Distribuidora", statement.utility or "Energisa"),
        ("Competência analisada", statement.reference_month.replace("-", "/") if statement.reference_month else "Não identificada"),
    ], styles)]
    story += [Spacer(1, 0.3 * cm), Paragraph("Resumo do ciclo", styles["DocSection"])]
    cards = [
        _card("Energia injetada", f"{number_br(statement.injected_kwh, 0)} kWh", styles),
        _card("Enviada às UCs", f"{number_br(statement.allocated_kwh, 0)} kWh", styles, LIGHT_GREEN),
        _card("Compensada localmente", f"{number_br(statement.compensated_kwh, 0)} kWh", styles),
        _card("Crédito disponível", f"{number_br(statement.available_credit_kwh, 0)} kWh", styles, LIGHT_GREEN),
    ]
    grid = Table([cards], colWidths=[4.3 * cm] * 4)
    grid.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 1.5), ("RIGHTPADDING", (0, 0), (-1, -1), 1.5)]))
    story.append(grid)
    explanation = (
        f"No ciclo, a unidade geradora injetou <b>{number_br(statement.injected_kwh, 0)} kWh</b>. "
        f"Desse volume, <b>{number_br(statement.allocated_kwh, 0)} kWh</b> foram direcionados a "
        f"<b>{len(statement.transfers)} unidade(s) beneficiária(s)</b>, enquanto "
        f"<b>{number_br(statement.compensated_kwh, 0)} kWh</b> compensaram o consumo da própria geradora. "
        f"O demonstrativo encerrou com <b>{number_br(statement.available_credit_kwh, 0)} kWh</b> disponíveis e "
        f"<b>{number_br(statement.expired_kwh, 0)} kWh</b> expirados."
    )
    story += [Spacer(1, 0.18 * cm), Paragraph(explanation, styles["DocBody"])]

    story += [Spacer(1, 0.3 * cm), Paragraph("Rateio para unidades beneficiárias", styles["DocSection"])]
    transfer_rows = [[Paragraph(value, styles["DocLabel"]) for value in ["Rateio", "Unidade beneficiária", "Identificação", "Energia enviada"]]]
    for transfer in statement.transfers:
        transfer_rows.append([
            Paragraph(f"{number_br(transfer.allocation_pct, 1)}%", styles["CompCell"]),
            Paragraph(_safe(transfer.unit_code), styles["CompCell"]),
            Paragraph(_safe(transfer.beneficiary_name or "Não vinculada ao cadastro"), styles["CompCell"]),
            Paragraph(f"{number_br(transfer.total_kwh, 0)} kWh", styles["CompCell"]),
        ])
    transfer_rows.append([
        Paragraph(f"<b>{number_br(sum(t.allocation_pct for t in statement.transfers), 1)}%</b>", styles["CompCell"]),
        Paragraph("<b>Total distribuído</b>", styles["CompCell"]), "",
        Paragraph(f"<b>{number_br(statement.allocated_kwh, 0)} kWh</b>", styles["CompCell"]),
    ])
    transfers = Table(transfer_rows, colWidths=[2.1 * cm, 4.0 * cm, 7.0 * cm, 4.1 * cm], repeatRows=1)
    transfers.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT_GREEN), ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(transfers)

    chart = _history_chart(statement)
    if chart:
        story.append(KeepTogether([Spacer(1, 0.3 * cm), Paragraph("Histórico da energia injetada", styles["DocSection"]), chart]))

    story += [Spacer(1, 0.3 * cm), Paragraph("Movimentação dos créditos", styles["DocSection"])]
    movement_rows = [[Paragraph(value, styles["DocLabel"]) for value in ["Posto", "Classe", "Saldo ant.", "Injetado", "Compensado", "Transferido", "Disponível"]]]
    for movement in statement.movements:
        if not any((movement.previous_balance_kwh, movement.injected_kwh, movement.compensated_kwh, movement.transferred_kwh, movement.available_kwh)):
            continue
        movement_rows.append([
            Paragraph(_safe(movement.period), styles["CompCell"]), Paragraph(movement.generation_class, styles["CompCell"]),
            *[Paragraph(f"{number_br(value, 0)}", styles["CompCell"]) for value in (
                movement.previous_balance_kwh, movement.injected_kwh, movement.compensated_kwh,
                movement.transferred_kwh, movement.available_kwh,
            )],
        ])
    movements = LongTable(movement_rows, colWidths=[3.0 * cm, 2.0 * cm, 2.35 * cm, 2.35 * cm, 2.55 * cm, 2.55 * cm, 2.4 * cm], repeatRows=1)
    movements.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(movements)

    active_credits = [credit for credit in statement.credits if credit.available_kwh > 0]
    if active_credits:
        credit_rows = [[Paragraph(value, styles["DocLabel"]) for value in ["Origem", "Posto", "Saldo disponível", "Validade"]]]
        for credit in active_credits:
            credit_rows.append([
                Paragraph(f"{credit.month:02d}/{credit.year}", styles["CompCell"]), Paragraph(_safe(credit.period), styles["CompCell"]),
                Paragraph(f"{number_br(credit.available_kwh, 2)} kWh", styles["CompCell"]), Paragraph(credit.expiration or "-", styles["CompCell"]),
            ])
        credits = LongTable(credit_rows, colWidths=[4.0 * cm, 5.0 * cm, 4.1 * cm, 4.1 * cm], repeatRows=1)
        credits.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(KeepTogether([
            Spacer(1, 0.3 * cm), Paragraph("Composição do saldo anterior", styles["DocSection"]), credits,
        ]))

    story += [Spacer(1, 0.3 * cm), Paragraph("Conclusão para o cliente", styles["DocSection"])]
    conclusion = (
        f"O rateio declarado totaliza <b>{number_br(sum(t.allocation_pct for t in statement.transfers), 1)}%</b> e "
        f"a energia discriminada nas beneficiárias confere com o total transferido pela geradora "
        f"(<b>{number_br(statement.allocated_kwh, 0)} kWh</b>). "
        f"A própria unidade teve <b>{number_br(statement.compensation_pct, 1)}%</b> do consumo medido compensado no ciclo."
    )
    story.append(Paragraph(conclusion, styles["DocBody"]))
    for warning in statement.warnings:
        story.append(Paragraph(f"- {_safe(warning)}", styles["DocSmall"]))
    story.append(Paragraph(
        "Este relatório interpreta o demonstrativo emitido pela distribuidora. Energia injetada no medidor não equivale necessariamente à geração bruta do inversor; perdas, autoconsumo e regras tarifárias devem ser avaliados com as faturas e o monitoramento da usina.",
        styles["DocSmall"],
    ))
    story += [Spacer(1, 0.25 * cm), _technical_signature(company, styles, include_client=False)]

    report_code = f"COMP-{statement.unit_code or 'SEM-UC'}-{reference}"
    doc.build(
        story,
        onFirstPage=lambda canvas, document: _footer(canvas, document, company, report_code),
        onLaterPages=lambda canvas, document: _footer(canvas, document, company, report_code),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf
