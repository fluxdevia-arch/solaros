from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as ReportImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from solar_crm.branding import configured_logo
from solar_crm.calculations import calculate_coverage, calculate_savings, money, number_br, percent
from solar_crm.db import query, query_one
from solar_crm.ui import date_br, month_label

GREEN = HexColor("#0B7A53")
DARK = HexColor("#17231D")
MUTED = HexColor("#65736B")
PALE = HexColor("#EDF4F0")
BORDER = HexColor("#CDDCD4")
YELLOW = HexColor("#E3A72F")
RED = HexColor("#C43D3D")
WHITE = colors.white


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=GREEN, spaceAfter=2))
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=DARK, spaceBefore=18, spaceAfter=5))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=DARK, spaceBefore=14, spaceAfter=7))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=DARK))
    styles.add(ParagraphStyle(name="Muted", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=11, textColor=MUTED))
    styles.add(ParagraphStyle(name="KpiLabel", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=MUTED, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="KpiValue", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=DARK, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="TableHead", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=WHITE, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="TableCell", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.2, leading=9, textColor=DARK))
    styles.add(ParagraphStyle(name="RightCell", parent=styles["TableCell"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="SignatureName", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=DARK, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="SignatureDetail", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED, alignment=TA_CENTER))
    return styles


def _safe(text: object) -> str:
    return str(text or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _report_header(company: dict, styles) -> Table:
    brand: object = Paragraph(_safe(company["company_name"]), styles["Brand"])
    try:
        logo_source = configured_logo(company)
        logo = ReportImage(BytesIO(logo_source) if isinstance(logo_source, bytes) else str(logo_source))
        scale = min(6.7 * cm / logo.imageWidth, 1.7 * cm / logo.imageHeight)
        logo.drawWidth = logo.imageWidth * scale
        logo.drawHeight = logo.imageHeight * scale
        brand = logo
    except Exception:
        pass
    table = Table(
        [[brand, Paragraph("GESTÃO E PERFORMANCE DE ENERGIA SOLAR", styles["Muted"])]],
        colWidths=[10.7 * cm, 7.0 * cm],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _page(canvas, doc, company: dict, reference_month: str):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(BORDER)
    canvas.line(1.5 * cm, 1.25 * cm, width - 1.5 * cm, 1.25 * cm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.2)
    canvas.drawString(1.5 * cm, 0.82 * cm, f"{company['company_name']} · Demonstrativo de {month_label(reference_month)}")
    canvas.drawRightString(width - 1.5 * cm, 0.82 * cm, f"Pag. {doc.page}")
    canvas.restoreState()


def _kpi_card(label: str, value: str, styles) -> Table:
    table = Table([[Paragraph(label.upper(), styles["KpiLabel"])], [Paragraph(value, styles["KpiValue"])]], colWidths=[4.1 * cm], rowHeights=[0.55 * cm, 0.85 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _generation_chart(readings: list[dict]) -> Drawing:
    drawing = Drawing(490, 175)
    chart = VerticalBarChart()
    chart.x = 36
    chart.y = 34
    chart.width = 420
    chart.height = 115
    chart.data = [
        [float(row["expected_monthly_kwh"] or 0) / 1000 for row in readings],
        [float(row["generation_kwh"] or 0) / 1000 for row in readings],
    ]
    chart.categoryAxis.categoryNames = [str(row["plant_name"])[:18] for row in readings]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle = 0
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labelTextFormat = "%0.0f"
    chart.bars[0].fillColor = HexColor("#B9CEC3")
    chart.bars[1].fillColor = GREEN
    chart.barWidth = 12
    chart.groupSpacing = 10
    chart.strokeColor = None
    drawing.add(chart)
    drawing.add(String(36, 160, "Geração esperada x realizada (MWh)", fontName="Helvetica-Bold", fontSize=9, fillColor=DARK))
    drawing.add(String(310, 160, "Esperada", fontName="Helvetica", fontSize=7, fillColor=MUTED))
    drawing.add(String(390, 160, "Realizada", fontName="Helvetica", fontSize=7, fillColor=GREEN))
    return drawing


def generate_client_report(client_id: int, reference_month: str, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1")
    client = query_one("SELECT * FROM clients WHERE id=?", (client_id,))
    if not client:
        raise ValueError("Cliente não encontrado.")
    readings = query(
        """SELECT r.*, p.id AS plant_id, p.name AS plant_name, p.unit_code, p.installed_kwp,
                  p.expected_monthly_kwh, p.status AS plant_status, p.distributor
           FROM plants p LEFT JOIN readings r
             ON r.plant_id=p.id AND r.reference_month=?
           WHERE p.client_id=? ORDER BY p.name""",
        (reference_month, client_id),
    )
    if not readings:
        raise ValueError("O cliente não possui usinas cadastradas.")

    beneficiaries = query(
        """SELECT b.id, b.plant_id, b.name, b.unit_code, b.holder_name, b.allocation_pct,
                  COALESCE(br.allocated_kwh,0) AS allocated_kwh,
                  COALESCE(br.compensated_kwh,0) AS compensated_kwh,
                  COALESCE(br.billed_consumption_kwh,0) AS billed_consumption_kwh,
                  COALESCE(br.previous_credit_kwh,0) AS previous_credit_kwh,
                  COALESCE(br.ending_credit_kwh,0) AS ending_credit_kwh,
                  COALESCE(br.notes,'') AS notes
           FROM beneficiaries b
           JOIN plants p ON p.id=b.plant_id
           LEFT JOIN beneficiary_readings br
             ON br.beneficiary_id=b.id AND br.reference_month=?
           WHERE p.client_id=? AND b.status='Ativo'
           ORDER BY b.plant_id, b.name""",
        (reference_month, client_id),
    )
    beneficiaries_by_plant: dict[int, list[dict]] = {}
    for beneficiary in beneficiaries:
        beneficiaries_by_plant.setdefault(int(beneficiary["plant_id"]), []).append(beneficiary)

    tickets = query(
        """SELECT t.*, p.name AS plant_name FROM tickets t
           LEFT JOIN plants p ON p.id=t.plant_id
           WHERE t.client_id=? AND substr(t.opened_at,1,7)=substr(?,1,7)
           ORDER BY t.opened_at""",
        (client_id, reference_month),
    )
    tasks = query(
        """SELECT t.*, p.name AS plant_name FROM tasks t
           LEFT JOIN plants p ON p.id=t.plant_id
           WHERE t.client_id=? AND substr(t.due_date,1,7)=substr(?,1,7)
           ORDER BY t.due_date""",
        (client_id, reference_month),
    )

    for row in readings:
        for field in ("consumption_kwh", "generation_kwh", "injected_kwh", "compensated_kwh", "tariff", "billed_amount", "reference_amount", "availability_pct", "performance_ratio", "downtime_hours", "incidents"):
            row[field] = row.get(field) or 0
        row["savings"] = calculate_savings(row["reference_amount"], row["billed_amount"])

    total_generation = sum(float(row["generation_kwh"]) for row in readings)
    total_consumption = sum(float(row["consumption_kwh"]) for row in readings)
    total_billed = sum(float(row["billed_amount"]) for row in readings)
    total_reference = sum(float(row["reference_amount"]) for row in readings)
    total_savings = calculate_savings(total_reference, total_billed)
    total_allocated = sum(float(row["allocated_kwh"] or 0) for row in beneficiaries)
    expected = sum(float(row["expected_monthly_kwh"] or 0) for row in readings)
    avg_availability = sum(float(row["availability_pct"]) for row in readings) / max(len(readings), 1)
    performance = (total_generation / expected * 100) if expected else 0

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.35 * cm,
        bottomMargin=2.05 * cm,
        title=f"Relatório de energia - {client['name']} - {reference_month[:7]}",
        author=company["company_name"],
    )
    styles = _styles()
    story = [
        _report_header(company, styles),
        Paragraph("Demonstrativo mensal de energia", styles["ReportTitle"]),
        Paragraph(f"{_safe(client['name'])} · {month_label(reference_month)}", styles["BodySmall"]),
        Spacer(1, 0.4 * cm),
    ]

    meta = Table([
        [Paragraph("CLIENTE", styles["Muted"]), Paragraph("DOCUMENTO", styles["Muted"]), Paragraph("CONTATO", styles["Muted"])],
        [Paragraph(_safe(client["name"]), styles["BodySmall"]), Paragraph(_safe(client["document"]), styles["BodySmall"]), Paragraph(_safe(client["contact_name"]), styles["BodySmall"])],
        [Paragraph("E-MAIL", styles["Muted"]), Paragraph("TELEFONE", styles["Muted"]), Paragraph("LOCALIDADE", styles["Muted"])],
        [Paragraph(_safe(client["email"]), styles["BodySmall"]), Paragraph(_safe(client["phone"]), styles["BodySmall"]), Paragraph(_safe(f"{client['city']}/{client['state']}"), styles["BodySmall"])],
    ], colWidths=[6.4 * cm, 5.2 * cm, 6.1 * cm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [meta, Spacer(1, 0.45 * cm), Paragraph("Resumo do mês", styles["Section"])]
    story.append(Table([[
        _kpi_card("Geração", f"{number_br(total_generation / 1000, 2)} MWh", styles),
        _kpi_card("Economia", money(total_savings), styles),
        _kpi_card("Desempenho", percent(performance), styles),
        _kpi_card("Beneficiada", f"{number_br(total_allocated / 1000, 2)} MWh", styles),
    ]], colWidths=[4.35 * cm] * 4, style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)])))
    story += [Spacer(1, 0.28 * cm), Paragraph(
        f"No período, as usinas geraram <b>{number_br(total_generation, 0)} kWh</b> e destinaram <b>{number_br(total_allocated, 0)} kWh</b> às unidades beneficiárias cadastradas, cobrindo aproximadamente <b>{percent(calculate_coverage(total_generation, total_consumption))}</b> do consumo registrado. A diferença estimada entre o custo sem compensação e o valor faturado foi de <b>{money(total_savings)}</b>.",
        styles["BodySmall"],
    )]
    story += [Paragraph("Desempenho por usina", styles["Section"]), _generation_chart(readings)]

    headers = ["Usina / UC", "Consumo", "Geração", "Esperado", "Disponib.", "Fatura", "Economia"]
    data = [[Paragraph(h, styles["TableHead"]) for h in headers]]
    for row in readings:
        data.append([
            Paragraph(f"<b>{_safe(row['plant_name'])}</b><br/><font color='#65736B'>{_safe(row['unit_code'])}</font>", styles["TableCell"]),
            Paragraph(f"{number_br(row['consumption_kwh'], 0)} kWh", styles["RightCell"]),
            Paragraph(f"{number_br(row['generation_kwh'], 0)} kWh", styles["RightCell"]),
            Paragraph(f"{number_br(row['expected_monthly_kwh'], 0)} kWh", styles["RightCell"]),
            Paragraph(percent(row["availability_pct"]), styles["RightCell"]),
            Paragraph(money(row["billed_amount"]), styles["RightCell"]),
            Paragraph(money(row["savings"]), styles["RightCell"]),
        ])
    data.append([
        Paragraph("<b>Total consolidado</b>", styles["TableCell"]),
        Paragraph(f"<b>{number_br(total_consumption, 0)} kWh</b>", styles["RightCell"]),
        Paragraph(f"<b>{number_br(total_generation, 0)} kWh</b>", styles["RightCell"]),
        Paragraph(f"<b>{number_br(expected, 0)} kWh</b>", styles["RightCell"]),
        Paragraph(f"<b>{percent(avg_availability)}</b>", styles["RightCell"]),
        Paragraph(f"<b>{money(total_billed)}</b>", styles["RightCell"]),
        Paragraph(f"<b>{money(total_savings)}</b>", styles["RightCell"]),
    ])
    table = Table(data, colWidths=[4.1 * cm, 2.25 * cm, 2.25 * cm, 2.25 * cm, 1.9 * cm, 2.35 * cm, 2.35 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("BACKGROUND", (0, -1), (-1, -1), PALE),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)

    story += [PageBreak(), Paragraph("Detalhamento técnico e financeiro", styles["ReportTitle"])]
    for row in readings:
        plant_beneficiaries = beneficiaries_by_plant.get(int(row["plant_id"]), [])
        plant_allocated = sum(float(item["allocated_kwh"] or 0) for item in plant_beneficiaries)
        status_color = RED if row["incidents"] else GREEN
        detail = [
            [Paragraph(f"<b>{_safe(row['plant_name'])}</b>", styles["BodySmall"]), Paragraph(f"UC {_safe(row['unit_code'])}", styles["Muted"])],
            [Paragraph("Capacidade instalada", styles["Muted"]), Paragraph(f"{number_br(row['installed_kwp'], 1)} kWp", styles["RightCell"])],
            [Paragraph("Energia injetada", styles["Muted"]), Paragraph(f"{number_br(row['injected_kwh'], 0)} kWh", styles["RightCell"])],
            [Paragraph("Energia compensada", styles["Muted"]), Paragraph(f"{number_br(row['compensated_kwh'], 0)} kWh", styles["RightCell"])],
            [Paragraph("Energia destinada às beneficiárias", styles["Muted"]), Paragraph(f"<b>{number_br(plant_allocated, 0)} kWh</b>", styles["RightCell"])],
            [Paragraph("Tarifa média", styles["Muted"]), Paragraph(f"{money(row['tariff'])}/kWh", styles["RightCell"])],
            [Paragraph("Custo estimado sem solar", styles["Muted"]), Paragraph(money(row["reference_amount"]), styles["RightCell"])],
            [Paragraph("Valor faturado", styles["Muted"]), Paragraph(money(row["billed_amount"]), styles["RightCell"])],
            [Paragraph("Economia estimada", styles["Muted"]), Paragraph(f"<b>{money(row['savings'])}</b>", styles["RightCell"])],
            [Paragraph("Horas de indisponibilidade", styles["Muted"]), Paragraph(f"{number_br(row['downtime_hours'], 1)} h", styles["RightCell"])],
            [Paragraph("Status operacional", styles["Muted"]), Paragraph(f"<font color='{status_color.hexval()}'><b>{'Atenção' if row['incidents'] else 'Normal'}</b></font>", styles["RightCell"])],
        ]
        detail_table = Table(detail, colWidths=[9.0 * cm, 8.4 * cm])
        detail_table.setStyle(TableStyle([
            ("SPAN", (0, 0), (0, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 1), (-1, -1), 0.25, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        note = row.get("failure_notes") or "Nenhuma falha relevante registrada no período."
        story += [detail_table, Spacer(1, 0.08 * cm), Paragraph(f"<b>Observação:</b> {_safe(note)}", styles["BodySmall"])]
        if plant_beneficiaries:
            beneficiary_data = [[Paragraph(h, styles["TableHead"]) for h in [
                "Unidade beneficiária / UC", "Rateio", "Destinada", "Compensada", "Consumo faturado", "Saldo de créditos",
            ]]]
            for beneficiary in plant_beneficiaries:
                beneficiary_data.append([
                    Paragraph(f"<b>{_safe(beneficiary['name'])}</b><br/><font color='#65736B'>{_safe(beneficiary['unit_code'])}</font>", styles["TableCell"]),
                    Paragraph(percent(beneficiary["allocation_pct"]), styles["RightCell"]),
                    Paragraph(f"{number_br(beneficiary['allocated_kwh'], 0)} kWh", styles["RightCell"]),
                    Paragraph(f"{number_br(beneficiary['compensated_kwh'], 0)} kWh", styles["RightCell"]),
                    Paragraph(f"{number_br(beneficiary['billed_consumption_kwh'], 0)} kWh", styles["RightCell"]),
                    Paragraph(f"{number_br(beneficiary['ending_credit_kwh'], 0)} kWh", styles["RightCell"]),
                ])
            beneficiary_data.append([
                Paragraph("<b>Total das beneficiárias</b>", styles["TableCell"]),
                Paragraph(f"<b>{percent(sum(float(item['allocation_pct'] or 0) for item in plant_beneficiaries))}</b>", styles["RightCell"]),
                Paragraph(f"<b>{number_br(plant_allocated, 0)} kWh</b>", styles["RightCell"]),
                Paragraph(f"<b>{number_br(sum(float(item['compensated_kwh'] or 0) for item in plant_beneficiaries), 0)} kWh</b>", styles["RightCell"]),
                Paragraph(f"<b>{number_br(sum(float(item['billed_consumption_kwh'] or 0) for item in plant_beneficiaries), 0)} kWh</b>", styles["RightCell"]),
                Paragraph(f"<b>{number_br(sum(float(item['ending_credit_kwh'] or 0) for item in plant_beneficiaries), 0)} kWh</b>", styles["RightCell"]),
            ])
            beneficiary_table = Table(
                beneficiary_data,
                colWidths=[5.1 * cm, 1.8 * cm, 2.55 * cm, 2.55 * cm, 2.8 * cm, 2.8 * cm],
                repeatRows=1,
            )
            beneficiary_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("BACKGROUND", (0, -1), (-1, -1), PALE),
                ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story += [Spacer(1, 0.11 * cm), Paragraph("Distribuição entre unidades beneficiárias", styles["BodySmall"]), Spacer(1, 0.06 * cm), beneficiary_table]
        else:
            story += [Spacer(1, 0.08 * cm), Paragraph("Nenhuma unidade beneficiária ativa cadastrada para esta usina.", styles["Muted"])]
        story.append(Spacer(1, 0.25 * cm))

    story.append(Paragraph("Ocorrências e ações", styles["Section"]))
    if tickets:
        ticket_data = [[Paragraph(h, styles["TableHead"]) for h in ["Data", "Usina", "Ocorrência", "Severidade", "Status"]]]
        for ticket in tickets:
            ticket_data.append([
                Paragraph(date_br(ticket["opened_at"]), styles["TableCell"]),
                Paragraph(_safe(ticket["plant_name"]), styles["TableCell"]),
                Paragraph(_safe(ticket["title"]), styles["TableCell"]),
                Paragraph(_safe(ticket["severity"]), styles["TableCell"]),
                Paragraph(_safe(ticket["status"]), styles["TableCell"]),
            ])
        ticket_table = Table(ticket_data, colWidths=[2.1 * cm, 3.5 * cm, 6.5 * cm, 2.2 * cm, 3.1 * cm], repeatRows=1)
        ticket_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("GRID", (0, 0), (-1, -1), 0.35, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(ticket_table)
    else:
        story.append(Paragraph("Nenhuma ocorrência aberta no período.", styles["BodySmall"]))

    if tasks:
        story += [Spacer(1, 0.25 * cm), Paragraph("Agenda de relacionamento e manutenção", styles["Section"])]
        task_data = [[Paragraph(h, styles["TableHead"]) for h in ["Prazo", "Usina", "Ação", "Responsável", "Status"]]]
        for task in tasks:
            task_data.append([
                Paragraph(date_br(task["due_date"]), styles["TableCell"]),
                Paragraph(_safe(task["plant_name"]), styles["TableCell"]),
                Paragraph(_safe(task["title"]), styles["TableCell"]),
                Paragraph(_safe(task["assignee"]), styles["TableCell"]),
                Paragraph(_safe(task["status"]), styles["TableCell"]),
            ])
        task_table = Table(task_data, colWidths=[2.1 * cm, 3.5 * cm, 6.5 * cm, 2.2 * cm, 3.1 * cm], repeatRows=1)
        task_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("GRID", (0, 0), (-1, -1), 0.35, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(task_table)

    story += [Spacer(1, 0.2 * cm), Paragraph("Notas sobre o demonstrativo", styles["Section"]), Paragraph(
        "A economia é estimada pela diferença entre o custo de referência sem os créditos de geração e o valor faturado informado. Os valores podem variar em função de impostos, demanda contratada, bandeiras tarifárias, custo de disponibilidade, créditos acumulados e regras da distribuidora. Recomenda-se anexar a fatura original da concessionária ao envio ao cliente.",
        styles["Muted"],
    ), Spacer(1, 0.08 * cm), Paragraph(_safe(company.get("report_footer")), styles["Muted"])]

    signature_rows = []
    signature_name_row = 0
    if company.get("signature_image"):
        try:
            handwritten = ReportImage(BytesIO(company["signature_image"]))
            scale = min(5.8 * cm / handwritten.imageWidth, 1.2 * cm / handwritten.imageHeight)
            handwritten.drawWidth = handwritten.imageWidth * scale
            handwritten.drawHeight = handwritten.imageHeight * scale
            handwritten.hAlign = "CENTER"
            signature_rows.append([handwritten])
            signature_name_row = 1
        except Exception:
            signature_rows = []
            signature_name_row = 0

    signature_rows += [
        [Paragraph(_safe(company.get("technical_name")), styles["SignatureName"])],
        [Paragraph(_safe(company.get("technical_title")), styles["SignatureDetail"])],
        [Paragraph(_safe(company.get("technical_registration")), styles["SignatureDetail"])],
    ]
    signature = Table(signature_rows, colWidths=[8.2 * cm], hAlign="CENTER")
    signature.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEABOVE", (0, signature_name_row), (-1, signature_name_row), 0.6, MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, signature_name_row), (-1, signature_name_row), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [Spacer(1, 0.12 * cm), KeepTogether([signature])]

    doc.build(story, onFirstPage=lambda c, d: _page(c, d, company, reference_month), onLaterPages=lambda c, d: _page(c, d, company, reference_month))
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf
