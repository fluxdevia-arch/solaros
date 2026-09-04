from __future__ import annotations

import streamlit as st

from solar_crm.inspection_documents import generate_inspection_pdf
from solar_crm.proposal_documents import generate_proposal_pdf
from solar_crm.service_documents import generate_service_contract_pdf, generate_service_order_pdf


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

