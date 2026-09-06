from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solar_crm.branding import configured_app_name
from solar_crm.db import query_one
from solar_crm.service_documents import BORDER, DARK, GREEN, MUTED, PALE, _footer, _header, _info_table, _safe, _styles, _technical_signature


def _decimal(value: object, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "-"


def _company() -> dict:
    company = query_one("SELECT * FROM settings WHERE id=1")
    if not company:
        raise ValueError("Configure os dados da empresa antes de gerar o PDF.")
    return company


def _notice(text: str, styles) -> Table:
    table = Table([[Paragraph(_safe(text), styles["DocSmall"])]], colWidths=[17.2 * cm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, GREEN),
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _section(title: str, styles) -> Paragraph:
    return Paragraph(_safe(title), styles["DocSection"])


def _bullet(text: object, styles) -> Paragraph:
    return Paragraph(f"• {_safe(text)}", styles["DocBody"])


def _components_table(components: list[dict], styles) -> LongTable:
    data = [[
        Paragraph("GRUPO", styles["DocLabel"]),
        Paragraph("ITEM", styles["DocLabel"]),
        Paragraph("ESPECIFICAÇÃO PRELIMINAR", styles["DocLabel"]),
    ]]
    for item in components:
        data.append([
            Paragraph(_safe(item.get("Grupo")), styles["DocValue"]),
            Paragraph(_safe(item.get("Item")), styles["DocValue"]),
            Paragraph(_safe(item.get("Especificação preliminar")), styles["DocValue"]),
        ])
    table = LongTable(data, colWidths=[3.0 * cm, 4.2 * cm, 10.0 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _loads_table(loads: list[dict], styles) -> LongTable:
    data = [[Paragraph(label, styles["DocLabel"]) for label in ("CARGA", "QTD.", "POTÊNCIA", "USO", "PRIOR.", "AUTONOMIA", "PARTIDA")]]
    for load in loads:
        data.append([
            Paragraph(_safe(load.get("name")), styles["DocValue"]),
            Paragraph(str(load.get("quantity", "-")), styles["DocCenter"]),
            Paragraph(f"{_decimal(load.get('power_w'), 0)} W", styles["DocRight"]),
            Paragraph(f"{_decimal(load.get('daily_hours'), 1)} h/dia", styles["DocRight"]),
            Paragraph("Sim" if load.get("priority") else "Não", styles["DocCenter"]),
            Paragraph(f"{_decimal(load.get('backup_hours'), 1)} h", styles["DocRight"]),
            Paragraph(f"{_decimal(load.get('surge_multiplier'), 1)} x", styles["DocRight"]),
        ])
    widths = [4.1, 1.2, 2.3, 2.1, 1.6, 2.4, 2.0]
    table = LongTable(data, colWidths=[value * cm for value in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _finish_pdf(doc: SimpleDocTemplate, story: list, buffer: BytesIO, company: dict, label: str, save_path: str | Path | None) -> bytes:
    story += [
        Spacer(1, 0.35 * cm),
        Paragraph("Responsabilidade técnica", _styles()["DocSection"]),
        Paragraph(
            f"Documento gerado pelo {_safe(configured_app_name(company))}. Os resultados devem ser conferidos e validados pelo profissional responsável antes da execução.",
            _styles()["DocSmall"],
        ),
        Spacer(1, 0.5 * cm),
        KeepTogether([_technical_signature(company, _styles(), include_client=False)]),
    ]
    doc.build(
        story,
        onFirstPage=lambda canvas, document: _footer(canvas, document, company, label),
        onLaterPages=lambda canvas, document: _footer(canvas, document, company, label),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf


def generate_special_sizing_pdf(project: dict, result: dict, save_path: str | Path | None = None) -> bytes:
    company = _company()
    styles = _styles()
    buffer = BytesIO()
    system_type = str(result.get("system_type") or project.get("system_type") or "Sistema especial")
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.25 * cm, bottomMargin=1.8 * cm,
        title=f"Dimensionamento preliminar - {system_type}", author=company["company_name"],
    )
    story = _header(
        company,
        "Memorial de pré-dimensionamento",
        f"{system_type} · Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        styles,
    )
    story.append(_info_table([
        ["PROJETO", project.get("name") or "Sem identificação", "CLIENTE", project.get("client_name") or "Não vinculado"],
        ["ENDEREÇO", project.get("address") or "-", "SITUAÇÃO", project.get("status") or "Preliminar"],
        ["SISTEMA", system_type, "REDE", f"{project.get('phases') or '-'} / {_decimal(project.get('ac_voltage_v'), 0)} V"],
    ], styles, [2.4 * cm, 6.2 * cm, 2.4 * cm, 6.2 * cm]))
    story += [Spacer(1, 0.3 * cm), _notice(
        "DOCUMENTO PRELIMINAR — Não substitui projeto executivo, TRT/ART, análise de curto-circuito, seletividade, aterramento, SPDA, aprovação da distribuidora nem validação dos datasheets.", styles,
    ), _section("Resumo do dimensionamento", styles)]
    if system_type == "Bombeamento solar":
        story.append(_info_table([
            ["VAZÃO", f"{_decimal(result.get('flow_m3_h'))} m³/h", "BOMBA", f"{_decimal(result.get('pump_input_kw'))} kW"],
            ["GERADOR FV", f"{_decimal(result.get('installed_pv_kwp'), 3)} kWp", "MÓDULOS", result.get("module_count")],
            ["CONTROLADOR", f">= {_decimal(result.get('drive_kw'))} kW", "ENERGIA", f"{_decimal(result.get('daily_energy_kwh'))} kWh/dia"],
            ["TUBULAÇÃO", f"DN {result.get('pipe_dn') or '> 200'}", "RESERVAÇÃO", f"{_decimal(result.get('reservoir_m3'), 1)} m³"],
        ], styles, [2.6 * cm, 6.0 * cm, 2.6 * cm, 6.0 * cm]))
    else:
        battery_text = "Não prevista" if not result.get("battery_units") else f"{_decimal(result.get('installed_battery_kwh'))} kWh / {result.get('battery_units')} un."
        story.append(_info_table([
            ["CONSUMO", f"{_decimal(result.get('daily_load_kwh'))} kWh/dia", "META SOLAR", f"{_decimal(result.get('solar_target_kwh_day'))} kWh/dia"],
            ["GERADOR FV", f"{_decimal(result.get('installed_pv_kwp'), 3)} kWp", "MÓDULOS", result.get("module_count")],
            ["INVERSOR", f">= {_decimal(result.get('inverter_continuous_kw'))} kW", "PICO", f">= {_decimal(result.get('inverter_surge_kw'))} kW"],
            ["BACKUP", f"{_decimal(result.get('backup_energy_kwh'))} kWh", "BATERIAS", battery_text],
            ["GERAÇÃO EST.", f"{_decimal(result.get('estimated_generation_kwh_month'), 0)} kWh/mês", "POTÊNCIA CARGAS", f"{_decimal(result.get('peak_load_kw'))} kW"],
        ], styles, [2.6 * cm, 6.0 * cm, 2.6 * cm, 6.0 * cm]))
        if result.get("loads"):
            story += [_section("Quadro de cargas", styles), _loads_table(result["loads"], styles)]
    story += [_section("Lista técnica preliminar", styles), _components_table(result.get("components") or [], styles)]
    warnings = list(result.get("warnings") or [])
    if warnings:
        story += [_section("Alertas e validações", styles)] + [_bullet(item, styles) for item in warnings]
    story += [
        _section("Verificações executivas obrigatórias", styles),
        _bullet("Confirmar dados de placa, curvas, compatibilidade elétrica e comunicação entre todos os equipamentos.", styles),
        _bullet("Validar capacidade de interrupção, seletividade, método de instalação, agrupamento, temperatura e queda de tensão total.", styles),
        _bullet("Validar aterramento, equipotencialização, SPDA, DR quando aplicável, seccionamento, sinalização e acesso seguro.", styles),
        _bullet("Em sistemas conectados, atender à NDU 013 vigente e concluir o processo da distribuidora antes da energização.", styles),
    ]
    return _finish_pdf(doc, story, buffer, company, f"Dimensionamento {system_type}", save_path)


def generate_general_sizing_pdf(memorial: str, save_path: str | Path | None = None) -> bytes:
    company = _company()
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.25 * cm, bottomMargin=1.8 * cm,
        title="Memorial de pré-dimensionamento", author=company["company_name"],
    )
    story = _header(company, "Memorial de pré-dimensionamento", f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles)
    for raw_line in memorial.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("# SolarOS") or line.startswith("Gerado em "):
            continue
        if line.startswith("> "):
            story += [_notice(line[2:], styles), Spacer(1, 0.18 * cm)]
        elif line.startswith("## "):
            story.append(_section(line[3:], styles))
        elif line.startswith("- "):
            story.append(_bullet(line[2:].replace("**", ""), styles))
        else:
            story.append(Paragraph(_safe(line.replace("**", "")), styles["DocBody"]))
    return _finish_pdf(doc, story, buffer, company, "Memorial de dimensionamento", save_path)
