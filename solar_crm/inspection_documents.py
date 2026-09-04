from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solar_crm.db import query_one
from solar_crm.inspections import inspection_details, inspection_items, inspection_photos
from solar_crm.service_documents import BORDER, DARK, GREEN, MUTED, PALE, _footer, _header, _info_table, _safe, _styles, _technical_signature, _text_block
from solar_crm.ui import date_br


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGO = PROJECT_ROOT / "assets" / "ongrid_logo.png"
STATUS_COLORS = {
    "Conforme": colors.HexColor("#DDF3E8"),
    "Atenção": colors.HexColor("#FFF0C7"),
    "Não conforme": colors.HexColor("#FADBD8"),
    "Não aplicável": colors.HexColor("#EDF0EE"),
    "Não verificado": colors.HexColor("#F5F5F5"),
}


def _inspection_header(company: dict, inspection: dict, styles) -> list:
    brand: object = Paragraph(_safe(company["company_name"]), styles["DocBrand"])
    if DEFAULT_LOGO.exists():
        logo = Image(str(DEFAULT_LOGO))
        scale = min(6.3 * cm / logo.imageWidth, 1.65 * cm / logo.imageHeight)
        logo.drawWidth = logo.imageWidth * scale
        logo.drawHeight = logo.imageHeight * scale
        logo.hAlign = "LEFT"
        brand = logo
    header = Table(
        [[brand, Paragraph(
            f"<b>RELATÓRIO DE VISTORIA</b><br/><font size='8' color='#65736B'>{_safe(inspection['number'])}</font>",
            styles["DocRight"],
        )]],
        colWidths=[10.7 * cm, 6.5 * cm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 1.0, GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [
        header,
        Paragraph("Relatório técnico de vistoria fotográfica", styles["DocTitle"]),
        Paragraph(
            f"{_safe(inspection['inspection_type'])} · Status: {_safe(inspection['status'])}",
            styles["DocSmall"],
        ),
        Spacer(1, 0.3 * cm),
    ]


def _measurement(value: object, unit: str) -> str:
    if value is None or value == "":
        return "-"
    return f"{float(value):g} {unit}"


def _photo_cell(photo: dict, styles) -> Table:
    raw = bytes(photo["image_data"])
    image = Image(BytesIO(raw))
    scale = min(8.05 * cm / image.imageWidth, 5.3 * cm / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    caption = photo.get("caption") or photo.get("filename") or "Evidência fotográfica"
    cell = Table(
        [[image], [Paragraph(f"<b>{_safe(photo['category'])}</b> · {_safe(caption)}", styles["DocSmallCenter"])]],
        colWidths=[8.15 * cm],
    )
    cell.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("BACKGROUND", (0, 1), (-1, 1), PALE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return cell


def generate_inspection_pdf(inspection_id: int, save_path: str | Path | None = None) -> bytes:
    company = query_one("SELECT * FROM settings WHERE id=1")
    inspection = inspection_details(inspection_id)
    if not inspection:
        raise ValueError("Vistoria não encontrada.")
    items = inspection_items(inspection_id)
    photos = inspection_photos(inspection_id)
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.45 * cm,
        leftMargin=1.45 * cm,
        topMargin=1.25 * cm,
        bottomMargin=1.8 * cm,
        title=f"{inspection['number']} - Relatório de vistoria",
        author=company["company_name"],
    )
    story = _inspection_header(company, inspection, styles)
    story.append(_info_table([
        ["CLIENTE", inspection["client_name"], "DOCUMENTO", inspection.get("client_document")],
        ["USINA / UC", f"{inspection.get('plant_name') or 'Instalação do cliente'} / {inspection.get('unit_code') or '-'}", "DATA", date_br(inspection["inspected_at"])],
        ["TÉCNICO", inspection.get("technician"), "URGÊNCIA", inspection.get("urgency")],
        ["CONTATO", inspection.get("contact_name"), "TELEFONE", inspection.get("contact_phone")],
    ], styles, [2.55 * cm, 6.1 * cm, 2.55 * cm, 6.1 * cm]))
    story += _text_block("Local vistoriado", inspection.get("address"), styles)
    if inspection.get("service_order_number"):
        story.append(Paragraph(
            f"Ordem de serviço vinculada: <b>{_safe(inspection['service_order_number'])}</b> · {_safe(inspection.get('service_order_title'))}",
            styles["DocBody"],
        ))

    story.append(Paragraph("Condições do local e posição solar", styles["DocSection"]))
    coordinates = "-"
    if inspection.get("latitude") is not None and inspection.get("longitude") is not None:
        coordinates = f"{float(inspection['latitude']):.6f}, {float(inspection['longitude']):.6f}"
    story.append(_info_table([
        ["CLIMA", inspection.get("weather"), "TEMPERATURA", _measurement(inspection.get("ambient_temperature_c"), "°C")],
        ["COBERTURA", inspection.get("roof_type"), "CONDIÇÃO", inspection.get("roof_condition")],
        ["ORIENTAÇÃO", inspection.get("solar_orientation"), "AZIMUTE / INCLINAÇÃO", f"{_measurement(inspection.get('azimuth_deg'), '°')} / {_measurement(inspection.get('tilt_deg'), '°')}"],
        ["SOMBREAMENTO", inspection.get("shading_level"), "COORDENADAS", coordinates],
    ], styles, [2.55 * cm, 6.1 * cm, 2.55 * cm, 6.1 * cm]))
    if inspection.get("shading_sources"):
        story += _text_block("Fontes e horários de sombreamento", inspection["shading_sources"], styles)

    story.append(Paragraph("Medições registradas", styles["DocSection"]))
    story.append(_info_table([
        ["TENSÃO CC", _measurement(inspection.get("dc_voltage_v"), "V"), "CORRENTE CC", _measurement(inspection.get("dc_current_a"), "A")],
        ["TENSÃO CA", _measurement(inspection.get("ac_voltage_v"), "V"), "CORRENTE CA", _measurement(inspection.get("ac_current_a"), "A")],
        ["ISOLAÇÃO", _measurement(inspection.get("insulation_mohm"), "MΩ"), "ATERRAMENTO", _measurement(inspection.get("grounding_ohm"), "Ω")],
        ["POTÊNCIA NO ATO", _measurement(inspection.get("generation_power_kw"), "kW"), "ALARME", inspection.get("inverter_alarms")],
    ], styles, [2.55 * cm, 6.1 * cm, 2.55 * cm, 6.1 * cm]))

    story += [PageBreak(), Paragraph("Checklist técnico", styles["DocTitle"])]
    checklist_data = [[
        Paragraph("SISTEMA", styles["DocLabel"]),
        Paragraph("ITEM VERIFICADO", styles["DocLabel"]),
        Paragraph("RESULTADO", styles["DocLabel"]),
        Paragraph("OBSERVAÇÃO", styles["DocLabel"]),
    ]]
    checklist_style = [
        ("BOX", (0, 0), (-1, -1), 0.55, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_number, item in enumerate(items, start=1):
        checklist_data.append([
            Paragraph(_safe(item["category"]), styles["DocSmall"]),
            Paragraph(_safe(item["item"]), styles["DocSmall"]),
            Paragraph(_safe(item["status"]), styles["DocSmallCenter"]),
            Paragraph(_safe(item.get("notes")), styles["DocSmall"]),
        ])
        checklist_style.append(("BACKGROUND", (2, row_number), (2, row_number), STATUS_COLORS.get(item["status"], colors.white)))
    checklist = Table(checklist_data, colWidths=[3.1 * cm, 6.4 * cm, 2.65 * cm, 5.05 * cm], repeatRows=1)
    checklist.setStyle(TableStyle(checklist_style))
    story.append(checklist)

    for title, field in [
        ("Riscos e condições de segurança", "safety_risks"),
        ("Constatações técnicas", "findings"),
        ("Serviços realizados durante a visita", "actions_performed"),
        ("Recomendações e correções necessárias", "recommendations"),
        ("Materiais necessários", "materials_needed"),
    ]:
        story += _text_block(title, inspection.get(field), styles)
    if inspection.get("follow_up_date"):
        story.append(Paragraph(f"Retorno recomendado para: <b>{date_br(inspection['follow_up_date'])}</b>", styles["DocBody"]))

    if photos:
        story += [PageBreak(), Paragraph("Registro fotográfico", styles["DocTitle"])]
        photo_rows = []
        for index in range(0, len(photos), 2):
            row = [_photo_cell(photos[index], styles)]
            row.append(_photo_cell(photos[index + 1], styles) if index + 1 < len(photos) else "")
            photo_rows.append(row)
        gallery = Table(photo_rows, colWidths=[8.35 * cm, 8.35 * cm], hAlign="CENTER")
        gallery.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0.1 * cm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0.1 * cm),
            ("TOPPADDING", (0, 0), (-1, -1), 0.12 * cm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.12 * cm),
        ]))
        story.append(gallery)

    story += [
        Spacer(1, 0.45 * cm),
        Paragraph("Ciência e encerramento", styles["DocSection"]),
        Paragraph(_safe(inspection.get("client_acknowledgement") or "O responsável foi informado sobre as condições encontradas e as recomendações registradas neste relatório."), styles["DocBody"]),
        Spacer(1, 0.55 * cm),
        KeepTogether([_technical_signature(company, styles)]),
        Spacer(1, 0.35 * cm),
        Paragraph(
            "Relatório baseado em inspeção visual, medições registradas e evidências coletadas no local. Intervenções elétricas devem observar os procedimentos de segurança e as normas aplicáveis.",
            styles["DocSmall"],
        ),
    ]
    doc.build(
        story,
        onFirstPage=lambda canvas, document: _footer(canvas, document, company, inspection["number"]),
        onLaterPages=lambda canvas, document: _footer(canvas, document, company, inspection["number"]),
    )
    pdf = buffer.getvalue()
    buffer.close()
    if save_path:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    return pdf
