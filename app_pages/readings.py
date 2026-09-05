from datetime import date
from io import StringIO

import altair as alt
import pandas as pd
import streamlit as st

from solar_crm.calculations import calculate_coverage, calculate_performance, calculate_savings, money, number_br, percent
from solar_crm.db import available_months, query, query_df, query_one, upsert_beneficiary_reading, upsert_reading
from solar_crm.ui import date_br, flash, month_label, page_intro, plant_options, render_delete_control, show_flash

page_intro("Registre consumo, geração, compensação e valores da concessionária para calcular economia e desempenho.")
show_flash()

plants = query(
    """SELECT p.id, p.name, p.expected_monthly_kwh, p.client_id, c.name AS client_name
       FROM plants p JOIN clients c ON c.id=p.client_id WHERE p.status!='Desativada'
       ORDER BY c.name, p.name"""
)
if not plants:
    st.warning("Cadastre ao menos uma usina antes de lançar leituras.", icon=":material/warning:")
    st.stop()

p_map = plant_options(plants)

with st.container(horizontal=True, horizontal_alignment="right"):
    add_reading = st.popover("Lançar leitura", icon=":material/add_chart:")
    import_data = st.popover("Importar planilha", icon=":material/upload_file:")
    template = pd.DataFrame(columns=["usina_id", "mes_referencia", "consumo_kwh", "geracao_kwh", "energia_injetada_kwh", "energia_compensada_kwh", "tarifa_rs_kwh", "valor_fatura_rs", "custo_sem_solar_rs", "disponibilidade_pct", "horas_indisponivel", "ocorrencias", "observacoes"])
    st.download_button("Baixar modelo", template.to_csv(index=False).encode("utf-8-sig"), "modelo_leituras.csv", "text/csv", icon=":material/download:")

with add_reading:
    with st.form("reading_form"):
        plant_label = st.selectbox("Usina", list(p_map))
        ref_date = st.date_input("Mês de referência", value=date.today().replace(day=1))
        c1, c2 = st.columns(2)
        consumption = c1.number_input("Consumo (kWh)", min_value=0.0, step=100.0)
        generation = c2.number_input("Geração (kWh)", min_value=0.0, step=100.0)
        injected = c1.number_input("Energia injetada (kWh)", min_value=0.0, step=100.0)
        compensated = c2.number_input("Energia compensada (kWh)", min_value=0.0, step=100.0)
        tariff = c1.number_input("Tarifa média (R$/kWh)", min_value=0.0, value=0.95, step=0.01)
        billed = c2.number_input("Valor da fatura (R$)", min_value=0.0, step=50.0)
        reference = st.number_input("Custo estimado sem energia solar (R$)", min_value=0.0, step=50.0, help="Valor que seria pago sem os créditos/compensações de energia.")
        availability = c1.number_input("Disponibilidade (%)", min_value=0.0, max_value=100.0, value=100.0, step=0.1)
        downtime = c2.number_input("Indisponibilidade (horas)", min_value=0.0, step=0.5)
        incidents = c1.number_input("Número de ocorrências", min_value=0, step=1)
        failure_notes = st.text_area("Falhas e observações do mês")
        meter = st.text_input("Referência da leitura/arquivo")
        submitted = st.form_submit_button("Salvar leitura", type="primary", icon=":material/save:")
        if submitted:
            plant_id = p_map[plant_label]
            plant = next(row for row in plants if row["id"] == plant_id)
            performance = calculate_performance(generation, plant["expected_monthly_kwh"])
            upsert_reading({
                "plant_id": plant_id,
                "reference_month": ref_date.replace(day=1).isoformat(),
                "consumption_kwh": consumption,
                "generation_kwh": generation,
                "injected_kwh": injected,
                "compensated_kwh": compensated,
                "tariff": tariff,
                "billed_amount": billed,
                "reference_amount": reference,
                "availability_pct": availability,
                "performance_ratio": performance,
                "downtime_hours": downtime,
                "incidents": incidents,
                "failure_notes": failure_notes,
                "meter_reading": meter,
            })
            flash("Leitura salva. Um lançamento do mesmo mês e usina é atualizado automaticamente.")
            st.rerun()

with import_data:
    st.caption("Use o modelo CSV e mantenha os nomes das colunas. O ID da usina aparece na tabela abaixo.")
    uploaded = st.file_uploader("Arquivo CSV", type=["csv"], label_visibility="collapsed")
    if uploaded is not None:
        try:
            incoming = pd.read_csv(uploaded, sep=None, engine="python")
            required = {"usina_id", "mes_referencia", "consumo_kwh", "geracao_kwh", "valor_fatura_rs", "custo_sem_solar_rs"}
            missing = sorted(required - set(incoming.columns))
            if missing:
                st.error("Colunas obrigatórias ausentes: " + ", ".join(missing))
            else:
                st.dataframe(incoming.head(10), hide_index=True)
                if st.button("Confirmar importação", type="primary", icon=":material/upload:"):
                    plant_lookup = {int(row["id"]): row for row in plants}
                    imported = 0
                    for _, row in incoming.iterrows():
                        pid = int(row["usina_id"])
                        if pid not in plant_lookup:
                            continue
                        month = pd.to_datetime(row["mes_referencia"]).date().replace(day=1).isoformat()
                        upsert_reading({
                            "plant_id": pid,
                            "reference_month": month,
                            "consumption_kwh": float(row.get("consumo_kwh", 0) or 0),
                            "generation_kwh": float(row.get("geracao_kwh", 0) or 0),
                            "injected_kwh": float(row.get("energia_injetada_kwh", 0) or 0),
                            "compensated_kwh": float(row.get("energia_compensada_kwh", 0) or 0),
                            "tariff": float(row.get("tarifa_rs_kwh", 0) or 0),
                            "billed_amount": float(row.get("valor_fatura_rs", 0) or 0),
                            "reference_amount": float(row.get("custo_sem_solar_rs", 0) or 0),
                            "availability_pct": float(row.get("disponibilidade_pct", 100) or 100),
                            "performance_ratio": calculate_performance(float(row.get("geracao_kwh", 0) or 0), plant_lookup[pid]["expected_monthly_kwh"]),
                            "downtime_hours": float(row.get("horas_indisponivel", 0) or 0),
                            "incidents": int(row.get("ocorrencias", 0) or 0),
                            "failure_notes": str(row.get("observacoes", "") or ""),
                            "meter_reading": "Importação CSV",
                        })
                        imported += 1
                    flash(f"{imported} leitura(s) importada(s).")
                    st.rerun()
        except Exception as exc:
            st.error(f"Não foi possível ler o arquivo: {exc}")

months = available_months()
selected_month = st.selectbox("Mês analisado", months, format_func=month_label, key="readings_month")
data = query_df(
    """SELECT p.id AS usina_id, c.name AS Cliente, p.name AS Usina, p.unit_code AS UC,
              p.expected_monthly_kwh AS Esperado, r.consumption_kwh AS Consumo,
              r.generation_kwh AS Geração, r.injected_kwh AS Injetada,
              r.compensated_kwh AS Compensada, r.availability_pct AS Disponibilidade,
              COALESCE((SELECT SUM(br.allocated_kwh) FROM beneficiary_readings br
                        JOIN beneficiaries b ON b.id=br.beneficiary_id
                        WHERE b.plant_id=p.id AND br.reference_month=r.reference_month),0) AS Beneficiada,
              r.performance_ratio AS Desempenho, r.billed_amount AS Fatura,
              r.reference_amount AS 'Custo sem solar',
              (r.reference_amount-r.billed_amount) AS Economia,
              r.incidents AS Ocorrências, r.failure_notes AS Observações
       FROM readings r JOIN plants p ON p.id=r.plant_id
       JOIN clients c ON c.id=p.client_id
       WHERE r.reference_month=? ORDER BY c.name, p.name""",
    (selected_month,),
)

st.subheader("Rateio entre unidades beneficiárias", icon=":material/account_tree:")
st.caption("Informe em kWh quanto cada unidade recebeu e compensou no mês. O relatório do cliente mostrará esse detalhamento por usina.")
allocation_plant_label = st.selectbox("Usina geradora para rateio", list(p_map), key="beneficiary_reading_plant")
allocation_plant_id = p_map[allocation_plant_label]
beneficiaries = query(
    """SELECT b.id, b.name, b.unit_code, b.allocation_pct,
              COALESCE(br.allocated_kwh, r.generation_kwh * b.allocation_pct / 100, 0) AS allocated_kwh,
              COALESCE(br.compensated_kwh, r.compensated_kwh * b.allocation_pct / 100, 0) AS compensated_kwh,
              COALESCE(br.billed_consumption_kwh, 0) AS billed_consumption_kwh,
              COALESCE(br.previous_credit_kwh, 0) AS previous_credit_kwh,
              COALESCE(br.ending_credit_kwh, 0) AS ending_credit_kwh,
              COALESCE(br.notes, '') AS notes
       FROM beneficiaries b
       LEFT JOIN readings r ON r.plant_id=b.plant_id AND r.reference_month=?
       LEFT JOIN beneficiary_readings br ON br.beneficiary_id=b.id AND br.reference_month=?
       WHERE b.plant_id=? AND b.status='Ativo'
       ORDER BY b.name""",
    (selected_month, selected_month, allocation_plant_id),
)
plant_reading = query_one(
    """SELECT generation_kwh, compensated_kwh FROM readings
       WHERE plant_id=? AND reference_month=?""",
    (allocation_plant_id, selected_month),
)

if beneficiaries:
    allocation_df = pd.DataFrame(beneficiaries).rename(columns={
        "id": "beneficiary_id",
        "name": "Beneficiária",
        "unit_code": "UC",
        "allocation_pct": "Rateio (%)",
        "allocated_kwh": "Destinada (kWh)",
        "compensated_kwh": "Compensada (kWh)",
        "billed_consumption_kwh": "Consumo faturado (kWh)",
        "previous_credit_kwh": "Crédito anterior (kWh)",
        "ending_credit_kwh": "Saldo final (kWh)",
        "notes": "Observações",
    })
    allocation_df = allocation_df[[
        "beneficiary_id", "Beneficiária", "UC", "Rateio (%)", "Destinada (kWh)",
        "Compensada (kWh)", "Consumo faturado (kWh)", "Crédito anterior (kWh)",
        "Saldo final (kWh)", "Observações",
    ]]
    numeric_columns = [
        "Rateio (%)", "Destinada (kWh)", "Compensada (kWh)", "Consumo faturado (kWh)",
        "Crédito anterior (kWh)", "Saldo final (kWh)",
    ]
    allocation_df[numeric_columns] = allocation_df[numeric_columns].astype(float)

    generation_for_plant = float(plant_reading["generation_kwh"] or 0) if plant_reading else 0
    compensated_for_plant = float(plant_reading["compensated_kwh"] or 0) if plant_reading else 0
    with st.container(horizontal=True):
        st.metric("Geração da usina", f"{number_br(generation_for_plant, 0)} kWh", border=True)
        st.metric("Compensação total", f"{number_br(compensated_for_plant, 0)} kWh", border=True)
        st.metric("Unidades beneficiárias", len(beneficiaries), border=True)

    if not plant_reading:
        st.warning("Lance primeiro a leitura desta usina no mês selecionado para validar o rateio contra a geração.", icon=":material/warning:")

    edited_allocation = st.data_editor(
        allocation_df,
        key=f"beneficiary_editor_{allocation_plant_id}_{selected_month}",
        hide_index=True,
        num_rows="fixed",
        disabled=["beneficiary_id", "Beneficiária", "UC", "Rateio (%)"],
        column_config={
            "beneficiary_id": None,
            "Beneficiária": st.column_config.TextColumn(pinned=True),
            "Rateio (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Destinada (kWh)": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.1f kWh"),
            "Compensada (kWh)": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.1f kWh"),
            "Consumo faturado (kWh)": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.1f kWh"),
            "Crédito anterior (kWh)": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.1f kWh"),
            "Saldo final (kWh)": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.1f kWh"),
        },
    )
    allocated_total = float(edited_allocation["Destinada (kWh)"].sum())
    compensated_total = float(edited_allocation["Compensada (kWh)"].sum())
    with st.container(horizontal=True):
        st.metric("Total destinado", f"{number_br(allocated_total, 1)} kWh", border=True)
        st.metric("Total compensado nas UCs", f"{number_br(compensated_total, 1)} kWh", border=True)
        st.metric("Saldo final de créditos", f"{number_br(float(edited_allocation['Saldo final (kWh)'].sum()), 1)} kWh", border=True)

    allocation_exceeds_generation = bool(plant_reading) and allocated_total > generation_for_plant + 0.1
    if allocation_exceeds_generation:
        st.error("O total destinado às beneficiárias ultrapassa a geração registrada da usina neste mês.")
    if st.button("Salvar rateio do mês", type="primary", icon=":material/save:", disabled=not plant_reading or allocation_exceeds_generation):
        for _, row in edited_allocation.iterrows():
            upsert_beneficiary_reading({
                "beneficiary_id": int(row["beneficiary_id"]),
                "reference_month": selected_month,
                "allocated_kwh": float(row["Destinada (kWh)"]),
                "compensated_kwh": float(row["Compensada (kWh)"]),
                "billed_consumption_kwh": float(row["Consumo faturado (kWh)"]),
                "previous_credit_kwh": float(row["Crédito anterior (kWh)"]),
                "ending_credit_kwh": float(row["Saldo final (kWh)"]),
                "notes": str(row["Observações"] or ""),
            })
        flash(f"Rateio de {len(edited_allocation)} unidade(s) beneficiária(s) salvo para {month_label(selected_month)}.")
        st.rerun()
else:
    st.info("Esta usina ainda não possui unidades beneficiárias ativas. Cadastre-as na aba Usinas.", icon=":material/info:")

if data.empty:
    st.info("Nenhuma leitura registrada para este mês.", icon=":material/info:")
    st.stop()

total_consumption = data["Consumo"].sum()
total_generation = data["Geração"].sum()
total_allocated = data["Beneficiada"].sum()
total_savings = data["Economia"].sum()
avg_performance = data["Desempenho"].mean()

with st.container(horizontal=True):
    st.metric("Consumo", f"{number_br(total_consumption / 1000, 1)} MWh", border=True)
    st.metric("Geração", f"{number_br(total_generation / 1000, 1)} MWh", border=True)
    st.metric("Energia beneficiada", f"{number_br(total_allocated / 1000, 1)} MWh", border=True)
    st.metric("Cobertura energética", percent(calculate_coverage(total_generation, total_consumption)), border=True)
    st.metric("Economia estimada", money(total_savings), border=True)
    st.metric("Desempenho médio", percent(avg_performance), border=True)

left, right = st.columns([1.35, 1])
with left:
    with st.container(border=True):
        st.subheader("Esperado x realizado", icon=":material/bar_chart:")
        melted = data.melt(id_vars=["Usina"], value_vars=["Esperado", "Geração"], var_name="Série", value_name="Energia")
        chart = alt.Chart(melted).mark_bar().encode(
            x=alt.X("Usina:N", title=None, sort=None),
            y=alt.Y("Energia:Q", title="Energia (kWh)"),
            color=alt.Color("Série:N", title=None),
            xOffset="Série:N",
            tooltip=["Usina", "Série", alt.Tooltip("Energia:Q", format=".0f")],
        )
        st.altair_chart(chart)
with right:
    with st.container(border=True):
        st.subheader("Distribuição da economia", icon=":material/savings:")
        savings_chart = alt.Chart(data).mark_arc(innerRadius=48).encode(
            theta=alt.Theta("Economia:Q"),
            color=alt.Color("Cliente:N", title="Cliente"),
            tooltip=["Cliente", alt.Tooltip("Economia:Q", format=".2f")],
        )
        st.altair_chart(savings_chart)

st.subheader("Conferência das faturas", icon=":material/fact_check:")
st.dataframe(
    data,
    hide_index=True,
    column_config={
        "usina_id": st.column_config.NumberColumn("ID", width="small"),
        "Usina": st.column_config.TextColumn(pinned=True),
        "Esperado": st.column_config.NumberColumn(format="%.0f kWh"),
        "Consumo": st.column_config.NumberColumn(format="%.0f kWh"),
        "Geração": st.column_config.NumberColumn(format="%.0f kWh"),
        "Injetada": st.column_config.NumberColumn(format="%.0f kWh"),
        "Compensada": st.column_config.NumberColumn(format="%.0f kWh"),
        "Beneficiada": st.column_config.NumberColumn(format="%.0f kWh"),
        "Disponibilidade": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
        "Desempenho": st.column_config.ProgressColumn(min_value=0, max_value=110, format="%.1f%%"),
        "Fatura": st.column_config.NumberColumn(format="R$ %.2f"),
        "Custo sem solar": st.column_config.NumberColumn(format="R$ %.2f"),
        "Economia": st.column_config.NumberColumn(format="R$ %.2f"),
    },
)

st.download_button(
    "Exportar fechamento do mês",
    data.to_csv(index=False).encode("utf-8-sig"),
    f"fechamento_{selected_month[:7]}.csv",
    "text/csv",
    icon=":material/download:",
)

reading_rows = query(
    """SELECT r.id, r.reference_month, p.name AS plant_name, c.name AS client_name
       FROM readings r JOIN plants p ON p.id=r.plant_id
       JOIN clients c ON c.id=p.client_id
       WHERE r.reference_month=? ORDER BY c.name, p.name""",
    (selected_month,),
)
if reading_rows:
    reading_delete_map = {
        f"{row['client_name']} · {row['plant_name']} · {month_label(row['reference_month'])}": row
        for row in reading_rows
    }
    reading_delete_label = st.selectbox(
        "Leitura/relatório para administrar",
        list(reading_delete_map),
        key="reading_delete_selector",
    )
    reading_to_delete = reading_delete_map[reading_delete_label]
    render_delete_control(
        "reading",
        reading_to_delete["id"],
        f"leitura de {reading_to_delete['plant_name']} em {month_label(reading_to_delete['reference_month'])}",
        state_keys=("report_pdf", "report_key"),
        extra_warning="O relatório desse período deixará de usar esta leitura e os respectivos rateios.",
    )
