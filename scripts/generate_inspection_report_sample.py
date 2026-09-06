from __future__ import annotations

import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
OUTPUT_PATH = PROJECT_ROOT / "output" / "pdf" / "Relatorio_Vistoria_SolarOS_Modelo.pdf"
DATABASE_PATH = PROJECT_ROOT / "tmp" / "pdfs" / "inspection-report-model.db"


def _sample_photo(title: str, subtitle: str, color: str) -> bytes:
    image = Image.new("RGB", (1400, 900), "#F5F8F6")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 54)
        small_font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default(size=54)
        small_font = ImageFont.load_default(size=30)
    draw.rounded_rectangle((70, 70, 1330, 830), radius=34, fill="white", outline=color, width=12)
    draw.rectangle((70, 70, 1330, 235), fill=color)
    draw.text((125, 120), title, fill="white", font=font)
    draw.text((125, 315), subtitle, fill="#1C2B24", font=small_font)
    draw.text((125, 735), "IMAGEM DEMONSTRATIVA DO MODELO", fill="#65736B", font=small_font)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def main() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.unlink(missing_ok=True)
    os.environ["SOLAR_CRM_DB"] = str(DATABASE_PATH)
    os.environ.pop("DATABASE_URL", None)

    from solar_crm.db import execute, init_db, query_one
    from solar_crm.inspection_documents import generate_inspection_pdf
    from solar_crm.inspections import (
        add_inspection_photo,
        create_inspection,
        inspection_details,
        inspection_items,
        update_inspection,
    )

    init_db(seed=True)
    logo = (PROJECT_ROOT / "assets" / "ongrid_logo_transparent.png").read_bytes()
    execute(
        """UPDATE settings SET app_name=?, company_name=?, legal_name=?, brand_logo=?,
                  brand_logo_mime=?, technical_name=?, technical_title=?, technical_registration=?
           WHERE id=1""",
        (
            "SolarOS By OnGrid",
            "OnGrid Energia Solar",
            "OnGrid Energia Solar",
            logo,
            "image/png",
            "Carlos Jessé Soares",
            "Téc. Eletrotécnica",
            "CFT: 11551320410",
        ),
    )
    client = query_one("SELECT id FROM clients ORDER BY id LIMIT 1")
    plant = query_one("SELECT id FROM plants WHERE client_id=? ORDER BY id LIMIT 1", (client["id"],))
    execute(
        """UPDATE clients SET name=?, document=?, contact_name=?, phone=?, address=?, city=?, state=?
           WHERE id=?""",
        (
            "Cliente demonstrativo",
            "00.000.000/0001-00",
            "Responsável do cliente",
            "(83) 99999-0000",
            "Rua Exemplo, 100",
            "João Pessoa",
            "PB",
            client["id"],
        ),
    )
    execute(
        "UPDATE plants SET name=?, unit_code=?, address=? WHERE id=?",
        ("Usina Fotovoltaica Modelo", "UC 123456789", "Rua Exemplo, 100 - João Pessoa/PB", plant["id"]),
    )

    inspection_id = create_inspection(
        {
            "client_id": client["id"],
            "plant_id": plant["id"],
            "inspection_type": "Manutenção preventiva",
            "status": "Concluída",
            "urgency": "Prioritária",
            "inspected_at": "2026-09-05",
            "technician": "Carlos Jessé Soares",
            "contact_name": "Responsável do cliente",
            "contact_phone": "(83) 99999-0000",
            "address": "Rua Exemplo, 100 - João Pessoa/PB",
        }
    )
    inspection = inspection_details(inspection_id)
    checklist = inspection_items(inspection_id)
    for index, item in enumerate(checklist):
        item["status"] = "Atenção" if index in {4, 10} else "Conforme"
        item["notes"] = (
            "Limpeza preventiva recomendada." if index == 4 else
            "Ventilação do inversor requer acompanhamento." if index == 10 else
            "Verificado em campo, sem anomalia aparente."
        )

    update_inspection(
        inspection_id,
        {
            **inspection,
            "status": "Concluída",
            "urgency": "Prioritária",
            "weather": "Ensolarado",
            "ambient_temperature_c": 31.5,
            "roof_type": "Telha cerâmica",
            "roof_condition": "Cobertura íntegra, sem sinais aparentes de infiltração.",
            "access_condition": "Acesso por escada; trabalho em altura com linha de vida e EPI.",
            "latitude": -7.11532,
            "longitude": -34.861,
            "solar_orientation": "Norte",
            "azimuth_deg": 4,
            "tilt_deg": 16,
            "shading_level": "Baixo",
            "shading_sources": "Sombreamento parcial por caixa-d'água antes das 8h.",
            "dc_voltage_v": 612.4,
            "dc_current_a": 12.8,
            "ac_voltage_v": 221.7,
            "ac_current_a": 31.2,
            "insulation_mohm": 98.5,
            "grounding_ohm": 6.3,
            "generation_power_kw": 7.15,
            "inverter_alarms": "Sem alarmes ativos no momento da vistoria.",
            "safety_risks": "Manter isolamento da área durante acesso à cobertura.",
            "findings": "Acúmulo leve de sujeira nos módulos e ventilação do inversor parcialmente obstruída.",
            "actions_performed": "Inspeção visual, medições elétricas, reaperto amostral e limpeza da ventilação.",
            "recommendations": "Programar limpeza dos módulos e nova verificação termográfica em até 90 dias.",
            "materials_needed": "Sem materiais para intervenção imediata.",
            "follow_up_date": "2026-12-05",
            "client_acknowledgement": "Responsável informado sobre as constatações e recomendações técnicas.",
        },
        checklist,
    )

    examples = [
        ("Módulos", "Vista geral do arranjo fotovoltaico", "#1685C8"),
        ("Inversor", "Inversor, ventilação e indicação de operação", "#F58220"),
        ("Quadros e proteções", "Quadro CA, disjuntor e DPS", "#0B7F56"),
        ("Aterramento", "Conexão do condutor de proteção", "#687078"),
    ]
    for index, (category, caption, color) in enumerate(examples, start=1):
        add_inspection_photo(
            inspection_id,
            _sample_photo(category.upper(), caption, color),
            f"modelo-{index}.jpg",
            category,
            caption,
        )

    generate_inspection_pdf(inspection_id, OUTPUT_PATH)
    print(OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()
