from __future__ import annotations

import re
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import pandas as pd
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solar_crm.calculations import number_br
from solar_crm.db import query_one
from solar_crm.service_documents import BORDER, DARK, GREEN, MUTED, PALE, _footer, _header, _info_table, _safe as _document_safe, _styles, _technical_signature
from solar_crm.ui import date_br


SERIES_COLORS = [GREEN, HexColor("#E67E22"), HexColor("#2878B5"), HexColor("#8E5DA2"), HexColor("#C43D3D"), HexColor("#4E8B57")]
SEVERITY_COLORS = {
    "Crítica": HexColor("#FADBD8"),
    "Atenção": HexColor("#FFF0C7"),
    "Observação": HexColor("#E8F0F8"),
}


def _safe(value: object) -> str:
    return _document_safe(value).replace("Ω", "Ohm").replace("℃", "graus C")


def _series_label(field: str) -> str:
    labels = {
        "timestamp": "Data / hora",
        "active_power_kw": "Potência ativa",
        "pv_power_kw": "Potência FV",
        "daily_energy_kwh": "Geração acumulada",
        "grid_voltage_v": "Tensão monitorada",
        "frequency_hz": "Frequência",
        "heatsink_temp_c": "Inversor / radiador",
        "internal_temp_c": "Interna",
        "insulation_kohm": "Isolamento",
        "leakage_ma": "Fuga",
        "power_factor": "Fator de potência",
        "phase_a_voltage_v": "Fase A",
        "phase_b_voltage_v": "Fase B",
        "phase_c_voltage_v": "Fase C",
    }
    match = re.match(r"mppt_(\d+)_(current_a|voltage_v)", field)
    if match:
        return f"MPPT {match.group(1)}"
    phase = re.match(r"phase_([abc])_(current_a|voltage_v)", field)
    if phase:
        measurement = "Corrente" if phase.group(2) == "current_a" else "Tensão"
        return f"{measurement} fase {phase.group(1).upper()}"
    return labels.get(field, field.replace("_", " ").title())


def _line_chart(data: pd.DataFrame, fields: list[str], title: str, unit: str, *, zero: bool = False) -> Drawing:
    fields = [field for field in fields if field in data and data[field].notna().any()]
    width, height = 490, 178
    left, right, bottom, top = 46, 14, 29, 31
    plot_width = width - left - right
    plot_height = height - bottom - top
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 13, title, fontName="Helvetica-Bold", fontSize=9.2, fillColor=DARK))
    if not fields:
        drawing.add(String(left, height / 2, "Dados não disponíveis neste arquivo.", fontName="Helvetica", fontSize=8, fillColor=MUTED))
        return drawing

    times = pd.to_datetime(data["timestamp"], errors="coerce")
    valid_times = times.dropna()
    if valid_times.empty:
        return drawing
    start, end = valid_times.min(), valid_times.max()
    span_seconds = max((end - start).total_seconds(), 1)
    values = pd.concat([pd.to_numeric(data[field], errors="coerce") for field in fields]).dropna()
    if values.empty:
        return drawing
    y_min = 0.0 if zero else float(values.min())
    y_max = float(values.max())
    if y_max <= y_min:
        y_max = y_min + 1
    padding = (y_max - y_min) * 0.07
    if not zero:
        y_min -= padding
    y_max += padding

    drawing.add(Rect(left, bottom, plot_width, plot_height, strokeColor=BORDER, fillColor=colors.white, strokeWidth=0.6))
    for index in range(5):
        y = bottom + plot_height * index / 4
        value = y_min + (y_max - y_min) * index / 4
        drawing.add(Line(left, y, left + plot_width, y, strokeColor=HexColor("#E7EEE9"), strokeWidth=0.35))
        drawing.add(String(left - 5, y - 2.5, f"{value:.1f}", fontName="Helvetica", fontSize=6.2, fillColor=MUTED, textAnchor="end"))
    for index in range(5):
        x = left + plot_width * index / 4
        timestamp = start + (end - start) * (index / 4)
        drawing.add(String(x, bottom - 13, timestamp.strftime("%H:%M"), fontName="Helvetica", fontSize=6.2, fillColor=MUTED, textAnchor="middle"))

    for series_index, field in enumerate(fields):
        numeric = pd.to_numeric(data[field], errors="coerce")
        points = []
        for timestamp, value in zip(times, numeric):
            if pd.isna(timestamp) or pd.isna(value):
                continue
            x = left + ((timestamp - start).total_seconds() / span_seconds) * plot_width
            y = bottom + ((float(value) - y_min) / (y_max - y_min)) * plot_height
            points.extend([x, y])
        if len(points) >= 4:
            color = SERIES_COLORS[series_index % len(SERIES_COLORS)]
            drawing.add(PolyLine(points, strokeColor=color, strokeWidth=1.45, fillColor=None))
            legend_x = left + series_index * (plot_width / max(len(fields), 1))
            drawing.add(Line(legend_x, height - 25, legend_x + 14, height - 25, strokeColor=color, strokeWidth=2))
            drawing.add(String(legend_x + 18, height - 28, _series_label(field), fontName="Helvetica", fontSize=6.8, fillColor=DARK))
    drawing.add(String(2, bottom + plot_height / 2, unit, fontName="Helvetica", fontSize=6.3, fillColor=MUTED, angle=90))
    return drawing


def _kpi(label: str, value: str, styles) -> Table:
    table = Table(
        [[Paragraph(_safe(label).upper(), styles["DocLabel"])], [Paragraph(_safe(value), styles["DocCenter"])]],
        colWidths=[5.55 * cm],
        rowHeights=[0.5 * cm, 0.72 * cm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.55, BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def generate_inverter_curve_pdf(
    plant_id: int,
    inverter_name: str,
    source_filename: str,
    result: dict,
    save_path: str | Path | None = None,
) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1") or {"company_name": "SolarOS", "legal_name": "SolarOS"}
    plant = query_one(
        """SELECT p.*, c.name AS client_name, c.document AS client_document
           FROM plants p JOIN clients c ON c.id=p.client_id WHERE p.id=?""",
        (plant_id,),
    )
    if not plant:
        raise ValueError("Usina não encontrada para emitir o relatório.")

    summary = result["summary"]
    data = result["data"].copy()
    issues = result["issues"]
    styles = _styles()
    buffer = BytesIO()
    report_label = f"Diagnóstico do inversor - {summary['analysis_date']}"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.45 * cm,
        leftMargin=1.45 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.75 * cm,
        title=f"Relatório de curva do inversor - {plant['name']} - {summary['analysis_date']}",
        author=company["company_name"],
    )
    story = _header(
        company,
        "Relatório técnico de curva do inversor",
        "Análise automática de telemetria diária exportada pelo portal de monitoramento",
        styles,
    )
    story.append(_info_table([
        ["CLIENTE", plant["client_name"], "DOCUMENTO", plant.get("client_document")],
        ["USINA", plant["name"], "UNIDADE CONSUMIDORA", plant.get("unit_code")],
        ["INVERSOR", inverter_name, "DATA ANALISADA", date_br(summary["analysis_date"])],
        ["ARQUIVO DE ORIGEM", source_filename, "PLANILHA", summary.get("sheet")],
    ], styles, [2.55 * cm, 6.05 * cm, 2.75 * cm, 5.85 * cm]))
    story += [Spacer(1, 0.35 * cm), Paragraph("Resumo executivo", styles["DocSection"])]
    first_operation = pd.to_datetime(summary.get("first_operation"), errors="coerce")
    last_operation = pd.to_datetime(summary.get("last_operation"), errors="coerce")
    operation_window = "-"
    if not pd.isna(first_operation) and not pd.isna(last_operation):
        operation_window = f"{first_operation.strftime('%H:%M')} a {last_operation.strftime('%H:%M')}"
    kpis = [
        _kpi("Situação", summary["health_status"], styles),
        _kpi("Geração do dia", f"{number_br(summary['daily_energy_kwh'], 2)} kWh", styles),
        _kpi("Pico de potência", f"{number_br(summary['peak_power_kw'], 2)} kW", styles),
        _kpi("Operação estimada", f"{number_br(summary['operating_hours'], 1)} h", styles),
        _kpi("Janela produtiva", operation_window, styles),
        _kpi("Amostras / achados", f"{summary['sample_count']} / {summary['issue_count']}", styles),
    ]
    story.append(Table([kpis[:3], kpis[3:]], colWidths=[5.72 * cm] * 3, style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ])))
    conclusion = (
        "Foram encontrados indícios que exigem verificação prioritária. Os horários devem ser cruzados com alarmes, clima e medições em campo."
        if summary["health_status"] == "Crítica"
        else "Foram observados desvios que merecem conferência técnica e comparação com dias de irradiância semelhante."
        if summary["health_status"] == "Atenção"
        else "Os limites avaliados não apontaram anomalias evidentes nos dados disponíveis. Recomenda-se manter a comparação histórica."
    )
    story += [Spacer(1, 0.18 * cm), Paragraph(conclusion, styles["DocBody"])]

    power_fields = [field for field in ("active_power_kw", "pv_power_kw") if field in data]
    story += [Paragraph("Curva principal", styles["DocSection"]), _line_chart(data, power_fields, "Potência ao longo do dia", "kW", zero=True)]
    if "daily_energy_kwh" in data:
        story += [_line_chart(data, ["daily_energy_kwh"], "Energia acumulada", "kWh", zero=True)]

    current_fields = sorted(field for field in data if re.match(r"mppt_\d+_current_a", field))
    voltage_fields = sorted(field for field in data if re.match(r"mppt_\d+_voltage_v", field))
    if current_fields or voltage_fields:
        story += [PageBreak(), Paragraph("Comportamento dos MPPTs", styles["DocTitle"])]
        if current_fields:
            story.append(_line_chart(data, current_fields, "Corrente por MPPT", "A", zero=True))
        if voltage_fields:
            story.append(_line_chart(data, voltage_fields, "Tensão por MPPT", "V", zero=False))
        if result.get("mppt_summary"):
            mppt_rows = [[Paragraph("MPPT", styles["DocLabel"]), Paragraph("Corrente máxima", styles["DocLabel"]), Paragraph("Tensão máxima", styles["DocLabel"]), Paragraph("Energia CC estimada", styles["DocLabel"])]]
            for item in result["mppt_summary"]:
                mppt_rows.append([
                    Paragraph(_safe(item["mppt"]), styles["DocValue"]),
                    Paragraph(f"{number_br(item['peak_current_a'], 2)} A", styles["DocRight"]),
                    Paragraph(f"{number_br(item['peak_voltage_v'], 1)} V", styles["DocRight"]),
                    Paragraph(f"{number_br(item['energy_proxy_kwh'], 2)} kWh", styles["DocRight"]),
                ])
            mppt_table = Table(mppt_rows, colWidths=[3.5 * cm, 4.5 * cm, 4.5 * cm, 4.7 * cm], repeatRows=1)
            mppt_table.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
                ("BACKGROUND", (0, 0), (-1, 0), PALE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story += [Spacer(1, 0.15 * cm), mppt_table]

    auxiliary = [
        ([field for field in data if field == "grid_voltage_v" or re.match(r"phase_[abc]_voltage_v", field)], "Tensão da rede", "V", False),
        (["frequency_hz"], "Frequência da rede", "Hz", False),
        ([field for field in ("heatsink_temp_c", "internal_temp_c") if field in data], "Temperaturas", "graus C", False),
        (["insulation_kohm"], "Resistência de isolamento", "kOhm", False),
        (["leakage_ma"], "Corrente de fuga", "mA", True),
        (["power_factor"], "Fator de potência", "f.p.", False),
    ]
    auxiliary = [(fields, title, unit, zero) for fields, title, unit, zero in auxiliary if any(field in data and data[field].notna().any() for field in fields)]
    if auxiliary:
        story += [PageBreak(), Paragraph("Grandezas elétricas e térmicas", styles["DocTitle"])]
        for index, (fields, title, unit, zero) in enumerate(auxiliary):
            story.append(_line_chart(data, fields, title, unit, zero=zero))
            if index % 3 == 2 and index < len(auxiliary) - 1:
                story.append(PageBreak())

    story += [PageBreak(), Paragraph("Diagnóstico e recomendações", styles["DocTitle"])]
    if issues:
        issue_rows = [[
            Paragraph("SEVERIDADE", styles["DocLabel"]),
            Paragraph("PARÂMETRO / EVIDÊNCIA", styles["DocLabel"]),
            Paragraph("POSSÍVEL CAUSA", styles["DocLabel"]),
            Paragraph("AÇÃO RECOMENDADA", styles["DocLabel"]),
        ]]
        issue_style = [
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for row_index, issue in enumerate(issues, start=1):
            item = asdict(issue) if hasattr(issue, "__dataclass_fields__") else issue
            issue_rows.append([
                Paragraph(_safe(item["severity"]), styles["DocSmall"]),
                Paragraph(f"<b>{_safe(item['parameter'])}</b><br/>{_safe(item['finding'])}", styles["DocSmall"]),
                Paragraph(_safe(item["possible_cause"]), styles["DocSmall"]),
                Paragraph(_safe(item["recommendation"]), styles["DocSmall"]),
            ])
            issue_style.append(("BACKGROUND", (0, row_index), (0, row_index), SEVERITY_COLORS.get(item["severity"], colors.white)))
        issue_table = LongTable(issue_rows, colWidths=[2.2 * cm, 5.35 * cm, 4.55 * cm, 5.1 * cm], repeatRows=1)
        issue_table.setStyle(TableStyle(issue_style))
        story.append(issue_table)
    else:
        story.append(Paragraph("Nenhuma anomalia evidente foi identificada pelos critérios disponíveis.", styles["DocBody"]))

    story += [Paragraph("Rastreabilidade dos dados", styles["DocSection"])]
    mapping_rows = [[Paragraph("DADO ANALISADO", styles["DocLabel"]), Paragraph("COLUNA IDENTIFICADA NO EXCEL", styles["DocLabel"])]]
    for field, column in result["mapping"].items():
        mapping_rows.append([Paragraph(_safe(_series_label(field)), styles["DocSmall"]), Paragraph(_safe(column), styles["DocSmall"])])
    mapping_table = LongTable(mapping_rows, colWidths=[6.3 * cm, 10.9 * cm], repeatRows=1)
    mapping_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story += [mapping_table, Spacer(1, 0.45 * cm)]
    story.append(Paragraph(
        "Nota técnica: esta avaliação é baseada nos dados fornecidos pelo portal e em limites gerais de triagem. "
        "Diferenças entre MPPTs devem ser comparadas somente quando os arranjos possuem módulos, orientação e condições equivalentes. "
        "O diagnóstico final deve considerar datasheet, alarmes, irradiância, histórico e inspeção em campo.",
        styles["DocSmall"],
    ))
    story += [Spacer(1, 0.6 * cm), KeepTogether([_technical_signature(company, styles, include_client=False)])]

    doc.build(
        story,
        onFirstPage=lambda canvas, document: _footer(canvas, document, company, report_label),
        onLaterPages=lambda canvas, document: _footer(canvas, document, company, report_label),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf
