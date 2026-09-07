from __future__ import annotations

import json

import streamlit as st

from solar_crm.inspection_documents import generate_inspection_pdf
from solar_crm.curve_documents import generate_inverter_curve_pdf
from solar_crm.inverter_curve import analyze_inverter_curve
from solar_crm.proposal_documents import generate_proposal_pdf
from solar_crm.service_documents import generate_service_contract_pdf, generate_service_order_pdf
from solar_crm.sizing_documents import generate_general_sizing_pdf, generate_special_sizing_pdf


@st.cache_data(ttl="5m", max_entries=64, show_spinner=False)
def inspection_pdf(inspection_id: int, document_version: str) -> bytes:
    return generate_inspection_pdf(inspection_id)


@st.cache_data(ttl="5m", max_entries=64, show_spinner=False)
def proposal_pdf(proposal_id: int, document_version: str) -> bytes:
    return generate_proposal_pdf(proposal_id)


@st.cache_data(ttl="5m", max_entries=64, show_spinner=False)
def service_order_pdf(order_id: int, document_version: str) -> bytes:
    return generate_service_order_pdf(order_id)


@st.cache_data(ttl="5m", max_entries=64, show_spinner=False)
def service_contract_pdf(contract_id: int, document_version: str) -> bytes:
    return generate_service_contract_pdf(contract_id)


@st.cache_data(ttl="10m", max_entries=64, show_spinner=False)
def special_sizing_pdf(project_json: str, result_json: str, document_version: str) -> bytes:
    return generate_special_sizing_pdf(json.loads(project_json), json.loads(result_json))


@st.cache_data(ttl="10m", max_entries=64, show_spinner=False)
def general_sizing_pdf(memorial: str, document_version: str) -> bytes:
    return generate_general_sizing_pdf(memorial)


@st.cache_data(ttl="10m", max_entries=32, show_spinner=False)
def inverter_curve_pdf(
    plant_id: int,
    inverter_name: str,
    source_filename: str,
    file_bytes: bytes,
    sheet_name: str,
    mapping_json: str,
    nominal_power_kw: float,
    nominal_grid_voltage_v: float,
) -> bytes:
    result = analyze_inverter_curve(
        file_bytes,
        source_filename,
        sheet_name=sheet_name,
        column_mapping=json.loads(mapping_json),
        nominal_power_kw=nominal_power_kw,
        nominal_grid_voltage_v=nominal_grid_voltage_v,
    )
    return generate_inverter_curve_pdf(plant_id, inverter_name, source_filename, result)


def clear_document_caches() -> None:
    """Invalidate branded documents after company identity changes."""
    inspection_pdf.clear()
    proposal_pdf.clear()
    service_order_pdf.clear()
    service_contract_pdf.clear()
    special_sizing_pdf.clear()
    general_sizing_pdf.clear()
    inverter_curve_pdf.clear()
