from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "tmp" / "sample-inspection.db"
OUTPUT = ROOT / "output" / "pdf" / "vistoria_tecnica_exemplo.pdf"
os.environ["SOLAR_CRM_DB"] = str(DATABASE)

from solar_crm.db import init_db, query_one
from solar_crm.inspection_documents import generate_inspection_pdf
from solar_crm.inspections import add_inspection_photo, create_inspection, inspection_details, inspection_items, update_inspection


def sample_photo(title: str, subtitle: str, color: str) -> bytes:
    canvas = Image.new("RGB", (1280, 800), color)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((55, 55, 1225, 745), outline="white", width=8)
    draw.text((95, 105), title, fill="white", stroke_width=1, stroke_fill="#1C2A22")
    draw.text((95, 155), subtitle, fill="white", stroke_width=1, stroke_fill="#1C2A22")
    output = BytesIO()
    canvas.save(output, format="JPEG", quality=90)
    return output.getvalue()


def main() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    DATABASE.unlink(missing_ok=True)
    init_db(seed=True)
    client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
    plant = query_one("SELECT id, address FROM plants WHERE client_id=? ORDER BY id LIMIT 1", (client["id"],))
    inspection_id = create_inspection({
        "client_id": client["id"],
        "plant_id": plant["id"],
        "inspection_type": "Manutenção preventiva",
        "status": "Rascunho",
        "urgency": "Prioritária",
        "inspected_at": "2026-09-04",
        "technician": "Carlos Jessé Soares",
        "contact_name": "Marina Costa",
        "contact_phone": "(83) 99999-0000",
        "address": plant["address"],
    })
    inspection = inspection_details(inspection_id)
    checklist = inspection_items(inspection_id)
    for index, item in enumerate(checklist):
        item["status"] = "Atenção" if index in {4, 11} else "Conforme"
        item["notes"] = "Acúmulo de sujeira" if index == 4 else ("Reaperto recomendado" if index == 11 else "Verificado em campo")
    update_inspection(inspection_id, {
        **inspection,
        "status": "Concluída",
        "urgency": "Prioritária",
        "weather": "Ensolarado",
        "ambient_temperature_c": 31.5,
        "roof_type": "Telha fibrocimento",
        "roof_condition": "Cobertura íntegra, sem infiltrações aparentes.",
        "access_condition": "Acesso por escada extensível; linha de vida disponível.",
        "latitude": -7.119496,
        "longitude": -34.845011,
        "solar_orientation": "Nordeste",
        "azimuth_deg": 32,
        "tilt_deg": 15,
        "shading_level": "Baixo",
        "shading_sources": "Sombra parcial da platibanda entre 16h e 17h em dois módulos da fileira inferior.",
        "dc_voltage_v": 618.4,
        "dc_current_a": 13.1,
        "ac_voltage_v": 381.2,
        "ac_current_a": 56.8,
        "insulation_mohm": 420,
        "grounding_ohm": 6.2,
        "generation_power_kw": 34.7,
        "inverter_alarms": "Sem alarmes ativos no momento da vistoria.",
        "safety_risks": "Manter isolamento da área durante acesso à cobertura.",
        "findings": "Sujidade moderada nos módulos e indício de aquecimento em conexão do circuito CA.",
        "actions_performed": "Inspeção visual, leitura elétrica, reaperto preventivo e limpeza do filtro do inversor.",
        "recommendations": "Programar limpeza dos módulos e termografia do quadro CA em até 15 dias.",
        "materials_needed": "Etiquetas de identificação e terminal tubular 10 mm².",
        "follow_up_date": "2026-09-18",
        "client_acknowledgement": "Responsável informado sobre as recomendações e sobre a necessidade de retorno técnico.",
    }, checklist)
    photos = [
        ("Vista geral", "Vista geral do arranjo fotovoltaico", "#2C82B5"),
        ("Módulos", "Sujidade na fileira inferior", "#D58A24"),
        ("Inversor", "Inversor operando sem alarme", "#3D8B6D"),
        ("Quadros e proteções", "Conexões do quadro CA", "#5F6873"),
    ]
    for index, (category, caption, color) in enumerate(photos, start=1):
        add_inspection_photo(inspection_id, sample_photo(category, caption, color), f"evidencia-{index}.jpg", category, caption)
    generate_inspection_pdf(inspection_id, OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()

