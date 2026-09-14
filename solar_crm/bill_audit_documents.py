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

from solar_crm.bill_audit import BillAudit
from solar_crm.branding import configured_logo
from solar_crm.calculations import money, number_br
from solar_crm.db import query_one
from solar_crm.service_documents import _footer, _safe, _styles, _technical_signature


NAVY = HexColor("#0D3B66")
BLUE = HexColor("#2A6F97")
ORANGE = HexColor("#F58218")
GREEN = HexColor("#197451")
LIGHT_BLUE = HexColor("#EAF3F8")
LIGHT_ORANGE = HexColor("#FFF3E7")
BORDER = HexColor("#CBD8DF")
MUTED = HexColor("#65736B")


def _header(company: dict, audit: BillAudit, styles) -> Table:
    try:
        source = configured_logo(company)
        logo = Image(BytesIO(source) if isinstance(source, bytes) else str(source))
        scale = min(7.0 * cm / logo.imageWidth, 2.0 * cm / logo.imageHeight)
        logo.drawWidth = logo.imageWidth * scale
        logo.drawHeight = logo.imageHeight * scale
        logo.hAlign = "LEFT"
        brand = logo
    except Exception:
        brand = Paragraph(f"<b>{_safe(company.get('company_name') or 'GRID Engenharia')}</b>", styles["DocBrand"])
    reference = audit.reference_month.replace("-", "/") if audit.reference_month else "não identificada"
    title = Paragraph(
        "<b>AUDITORIA DE FATURA DE ENERGIA</b><br/>"
        f"<font size='9' color='#65736B'>Energisa - referência {reference}</font>",
        styles["AuditRight"],
    )
    table = Table([[brand, title]], colWidths=[9.4 * cm, 7.8 * cm], rowHeights=[2.35 * cm])
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


def _summary_card(label: str, value: str, styles, color=LIGHT_BLUE) -> Table:
    card = Table([
        [Paragraph(label.upper(), styles["AuditCardLabel"])],
        [Paragraph(value, styles["AuditCardValue"])],
    ], colWidths=[4.1 * cm], rowHeights=[0.45 * cm, 0.78 * cm])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return card


def _key_value_table(rows: list[tuple[str, str]], styles, widths=(4.7 * cm, 12.5 * cm)) -> Table:
    data = [[Paragraph(_safe(label), styles["DocLabel"]), Paragraph(_safe(value), styles["DocValue"])] for label, value in rows]
    table = Table(data, colWidths=list(widths), repeatRows=0)
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _history_chart(audit: BillAudit) -> Drawing | None:
    if not audit.historical_consumption_kwh:
        return None
    data = audit.historical_consumption_kwh[:13]
    labels = [label for label, _ in data]
    values = [value for _, value in data]
    drawing = Drawing(490, 100)
    chart = VerticalBarChart()
    chart.x = 42
    chart.y = 27
    chart.height = 55
    chart.width = 425
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 35
    chart.categoryAxis.labels.dy = -9
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.gridStrokeColor = HexColor("#E2E9ED")
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.bars[0].fillColor = BLUE
    chart.bars[0].strokeColor = BLUE
    drawing.add(chart)
    drawing.add(String(6, 89, "Consumo faturado (kWh)", fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    return drawing


def generate_bill_audit_pdf(audit: BillAudit, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1") or {
        "company_name": "GRID Engenharia",
        "technical_name": "Carlos Jessé Soares",
        "technical_title": "Téc. Eletrotécnica",
        "technical_registration": "CFT: 11551320410",
        "report_footer": "",
    }
    styles = _styles()
    styles.add(ParagraphStyle(
        name="AuditRight", parent=styles["DocRight"], alignment=TA_RIGHT,
        fontSize=9, leading=13, textColor=NAVY,
    ))
    styles.add(ParagraphStyle(
        name="AuditCardLabel", parent=styles["DocSmall"], alignment=TA_CENTER,
        fontSize=6.8, leading=8, textColor=MUTED,
    ))
    styles.add(ParagraphStyle(
        name="AuditCardValue", parent=styles["DocCenter"], alignment=TA_CENTER,
        fontName="Helvetica-Bold", fontSize=12.5, leading=14, textColor=NAVY,
    ))
    styles.add(ParagraphStyle(
        name="AuditFinding", parent=styles["DocSmall"], fontSize=7.1, leading=8.6,
    ))
    styles.add(ParagraphStyle(
        name="AuditNote", parent=styles["DocSmall"], fontSize=7.1, leading=8.6,
    ))

    buffer = BytesIO()
    reference = audit.reference_month or "sem-referencia"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.55 * cm,
        leftMargin=1.55 * cm,
        topMargin=1.15 * cm,
        bottomMargin=1.8 * cm,
        title=f"Auditoria da fatura {audit.unit_code} - {reference}",
        author=company.get("company_name") or "GRID Engenharia",
    )

    story: list = [_header(company, audit, styles), Spacer(1, 0.3 * cm)]
    story.append(Paragraph("Identificação da unidade", styles["DocSection"]))
    story.append(_key_value_table([
        ("Cliente", audit.client_name or "Não identificado"),
        ("Endereço", audit.address or "Não identificado"),
        ("Unidade consumidora", audit.unit_code or "Não identificada"),
        ("Perfil identificado", audit.unit_profile),
        ("Classificação / ligação", f"{audit.classification or '-'} / {audit.connection or '-'}"),
        ("Nota fiscal / vencimento", f"{audit.invoice_number or '-'} / {audit.due_date or '-'}"),
    ], styles))
    story += [Spacer(1, 0.3 * cm), Paragraph("Resumo financeiro", styles["DocSection"])]
    cards = [
        _summary_card("Valor faturado", money(audit.invoice_amount), styles),
        _summary_card("Sem energia solar", money(audit.estimated_without_solar), styles, LIGHT_ORANGE),
        _summary_card("Economia no ciclo", money(audit.estimated_savings_month), styles),
        _summary_card("Economia em 12 meses", money(audit.estimated_savings_year), styles),
    ]
    card_grid = Table([cards], colWidths=[4.3 * cm] * 4)
    card_grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story += [card_grid, Spacer(1, 0.15 * cm)]
    story.append(Paragraph(
        f"Mantido o resultado deste ciclo, a economia projetada para 5 anos é de <b>{money(audit.estimated_savings_5_years)}</b>. "
        "A projeção não representa garantia de desempenho futuro.",
        styles["DocSmall"],
    ))

    injected = "Não disponível no quadro de medição" if audit.injected_measured_kwh is None else f"{number_br(audit.injected_measured_kwh, 2)} kWh"
    if audit.consumption_variation_pct is None:
        comparison = "Não disponível"
    elif audit.consumption_variation_pct > 0:
        comparison = f"Aumento de {number_br(audit.consumption_variation_pct, 1)}%"
    elif audit.consumption_variation_pct < 0:
        comparison = f"Redução de {number_br(abs(audit.consumption_variation_pct), 1)}%"
    else:
        comparison = "Sem variação"
    story += [Spacer(1, 0.3 * cm), Paragraph("Balanço de energia e créditos", styles["DocSection"])]
    energy_rows = [
        ("Energia medida consumida", f"{number_br(audit.consumption_kwh, 2)} kWh"),
        (
            f"Consumo anterior - {audit.previous_month_label or 'não identificado'}",
            f"{number_br(audit.previous_month_consumption_kwh, 2)} kWh" if audit.previous_month_consumption_kwh else "Não disponível",
        ),
        ("Comparação mensal", comparison),
        ("Energia injetada medida", injected),
        ("Energia compensada na fatura", f"{number_br(audit.compensated_kwh, 2)} kWh"),
    ]
    if "Grupo A" in audit.unit_profile:
        energy_rows.extend([
            ("Saldo de créditos - ponta", f"{number_br(audit.credit_balance_peak_kwh, 2)} kWh"),
            ("Saldo de créditos - fora de ponta", f"{number_br(audit.credit_balance_off_peak_kwh, 2)} kWh"),
            ("Saldo total de créditos", f"{number_br(audit.credit_balance_kwh, 2)} kWh"),
        ])
    else:
        energy_rows.append(("Saldo de créditos informado", f"{number_br(audit.credit_balance_kwh, 2)} kWh"))
    energy_rows.extend([
        ("Créditos solares reconhecidos", money(audit.solar_credit_value)),
        ("Fio B / ajuste GD II identificado", money(audit.fio_b_value)),
    ])
    story.append(_key_value_table(energy_rows, styles))

    story += [Spacer(1, 0.3 * cm), Paragraph("Tributos e componentes", styles["DocSection"])]
    tax_data = [
        [Paragraph("ICMS", styles["DocLabel"]), Paragraph(money(audit.icms_value), styles["DocValue"]), Paragraph("Base de ICMS", styles["DocLabel"]), Paragraph(money(audit.icms_base), styles["DocValue"])],
        [Paragraph("PIS", styles["DocLabel"]), Paragraph(money(audit.pis_value), styles["DocValue"]), Paragraph("COFINS", styles["DocLabel"]), Paragraph(money(audit.cofins_value), styles["DocValue"])],
        [Paragraph("Encargo de uso da distribuição", styles["DocLabel"]), Paragraph(money(audit.distribution_use_charge), styles["DocValue"]), Paragraph("Custo bruto do consumo", styles["DocLabel"]), Paragraph(money(audit.gross_consumption_cost), styles["DocValue"])],
    ]
    taxes = Table(tax_data, colWidths=[4.1 * cm, 3.2 * cm, 5.3 * cm, 4.6 * cm])
    taxes.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE),
        ("BACKGROUND", (2, 0), (2, -1), LIGHT_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(taxes)

    if audit.historical_consumption_kwh:
        chart = _history_chart(audit)
        history_block = [Spacer(1, 0.32 * cm), Paragraph("Histórico informado na fatura", styles["DocSection"])]
        if chart:
            history_block.append(chart)
        history_block.append(Paragraph(
            f"Média dos meses legíveis: <b>{number_br(audit.historical_average_kwh, 2)} kWh/mês</b>. "
            "O histórico reproduz os valores impressos pela distribuidora e pode incluir leituras estimadas ou ciclos com durações diferentes.",
            styles["DocSmall"],
        ))
        story.append(KeepTogether(history_block))

    story += [Spacer(1, 0.32 * cm), Paragraph("Achados da auditoria", styles["DocSection"])]
    finding_rows = [[
        Paragraph("Prioridade", styles["DocLabel"]), Paragraph("Achado e evidência", styles["DocLabel"]), Paragraph("Recomendação", styles["DocLabel"])
    ]]
    for finding in audit.findings:
        finding_rows.append([
            Paragraph(_safe(finding["severity"]), styles["AuditFinding"]),
            Paragraph(f"<b>{_safe(finding['title'])}</b><br/>{_safe(finding['evidence'])}", styles["AuditFinding"]),
            Paragraph(_safe(finding["recommendation"]), styles["AuditFinding"]),
        ])
    findings = LongTable(finding_rows, colWidths=[2.0 * cm, 7.5 * cm, 7.7 * cm], repeatRows=1)
    findings.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(findings)

    if audit.items:
        story += [Spacer(1, 0.32 * cm), Paragraph("Itens conferidos na fatura", styles["DocSection"])]
        item_rows = [[
            Paragraph("Descrição", styles["DocLabel"]), Paragraph("Quantidade", styles["DocLabel"]),
            Paragraph("Tarifa unitária", styles["DocLabel"]), Paragraph("Valor", styles["DocLabel"]),
        ]]
        for item in audit.items:
            quantity = "-" if item.quantity is None else f"{number_br(item.quantity, 3)} {item.unit}".strip()
            unit_price = "-" if item.unit_price is None else money(item.unit_price)
            item_rows.append([
                Paragraph(_safe(item.description), styles["AuditFinding"]),
                Paragraph(quantity, styles["AuditFinding"]),
                Paragraph(unit_price, styles["AuditFinding"]),
                Paragraph(money(item.amount), styles["AuditFinding"]),
            ])
        items_table = LongTable(item_rows, colWidths=[8.1 * cm, 3.0 * cm, 3.0 * cm, 3.1 * cm], repeatRows=1)
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        story.append(items_table)

    story += [Spacer(1, 0.32 * cm), Paragraph("Critérios, ressalvas e validação", styles["DocSection"])]
    notes = [
        "O valor sem energia solar é estimado pela recomposição dos créditos visíveis, descontado o ajuste GD II / Fio B quando identificado.",
        "Energia autoconsumida antes do medidor, perdas, indisponibilidades do sistema e créditos de outras competências não podem ser apurados integralmente por uma única fatura.",
        "A conferência definitiva deve usar também o portal da distribuidora, o histórico de pelo menos 12 faturas, o monitoramento do inversor e os comprovantes de rateio.",
        *audit.warnings,
    ]
    for note in dict.fromkeys(notes):
        story.append(Paragraph(f"- {_safe(note)}", styles["AuditNote"]))
    story += [Spacer(1, 0.1 * cm), _technical_signature(company, styles, include_client=False)]

    report_code = f"AUD-{audit.unit_code or 'SEM-UC'}-{reference}"
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
