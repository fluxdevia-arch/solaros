import pandas as pd
import streamlit as st

from solar_crm.calculations import calculate_service_price, contract_monthly_value, money, number_br
from solar_crm.db import query, query_df
from solar_crm.ui import page_intro

page_intro("Simule propostas sustentáveis, valide margem e acompanhe a receita recorrente da carteira.")

simulator, portfolio, plans = st.tabs([
    ":material/calculate: Simulador",
    ":material/monitoring: Carteira recorrente",
    ":material/package_2: Referência de planos",
])

with simulator:
    preset = st.segmented_control("Modelo", ["Essencial", "Performance", "Premium", "Personalizado"], default="Performance")
    presets = {
        "Essencial": (250.0, 90.0, 1.2, 0.0),
        "Performance": (390.0, 140.0, 1.8, 180.0),
        "Premium": (520.0, 180.0, 2.0, 260.0),
        "Personalizado": (300.0, 100.0, 1.5, 0.0),
    }
    default_base, default_plant, default_kwp, default_extras = presets[preset]
    st.caption("A formação combina parcela base, complexidade por usina, potência monitorada e serviços adicionais.")

    left, right = st.columns([1.1, 0.9])
    with left:
        with st.container(border=True):
            st.subheader("Escopo e composição", icon=":material/tune:")
            c1, c2 = st.columns(2)
            plant_count = c1.number_input("Quantidade de usinas", min_value=1, value=1, step=1)
            total_kwp = c2.number_input("Potência total (kWp)", min_value=0.0, value=75.0, step=5.0)
            base_fee = c1.number_input("Parcela base (R$)", min_value=0.0, value=default_base, step=10.0, key=f"base_{preset}")
            per_plant = c2.number_input("Valor por usina (R$)", min_value=0.0, value=default_plant, step=10.0, key=f"plant_{preset}")
            per_kwp = c1.number_input("Valor por kWp (R$)", min_value=0.0, value=default_kwp, step=0.1, key=f"kwp_{preset}")
            extras = c2.number_input("Adicionais mensais (R$)", min_value=0.0, value=default_extras, step=10.0, key=f"extras_{preset}")
            discount = st.number_input("Desconto comercial (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.5)

        with st.container(border=True):
            st.subheader("Custos internos", icon=":material/payments:")
            c1, c2 = st.columns(2)
            hours = c1.number_input("Horas da equipe por mês", min_value=0.0, value=5.0, step=0.5)
            hourly_cost = c2.number_input("Custo por hora (R$)", min_value=0.0, value=55.0, step=5.0)
            tools_cost = c1.number_input("Softwares e monitoramento (R$)", min_value=0.0, value=90.0, step=10.0)
            visit_cost = c2.number_input("Provisão para visitas (R$)", min_value=0.0, value=120.0, step=10.0)
            taxes = c1.number_input("Impostos sobre receita (%)", min_value=0.0, max_value=50.0, value=8.0, step=0.5)
            target_margin = c2.number_input("Margem líquida alvo (%)", min_value=0.0, max_value=80.0, value=30.0, step=1.0)

    breakdown = calculate_service_price(base_fee, plant_count, per_plant, total_kwp, per_kwp, extras, discount)
    direct_cost = hours * hourly_cost + tools_cost + visit_cost
    divisor = 1 - (taxes + target_margin) / 100
    minimum_price = direct_cost / divisor if divisor > 0 else 0
    estimated_tax = breakdown.monthly_total * taxes / 100
    estimated_profit = breakdown.monthly_total - direct_cost - estimated_tax
    realized_margin = estimated_profit / breakdown.monthly_total * 100 if breakdown.monthly_total else 0

    with right:
        with st.container(border=True):
            st.subheader("Preço calculado", icon=":material/request_quote:")
            st.metric("Mensalidade sugerida", money(breakdown.monthly_total), border=True)
            st.metric("Valor anual do contrato", money(breakdown.annual_total), border=True)
            st.metric("Preço mínimo pela margem", money(minimum_price), border=True)
            st.metric("Margem estimada", f"{realized_margin:.1f}%", delta=f"Meta {target_margin:.0f}%", delta_color="normal" if realized_margin >= target_margin else "inverse", border=True)
            if breakdown.monthly_total < minimum_price:
                st.warning("O preço comercial está abaixo do mínimo necessário para a margem desejada.", icon=":material/warning:")
            else:
                st.success("O preço cobre os custos e a margem definida.", icon=":material/check_circle:")

        composition = pd.DataFrame({
            "Componente": ["Parcela base", "Usinas", "Potência", "Adicionais", "Desconto"],
            "Valor": [breakdown.base, breakdown.plants, breakdown.capacity, breakdown.extras, -breakdown.discount],
        })
        with st.container(border=True):
            st.subheader("Composição do preço", icon=":material/donut_large:")
            st.bar_chart(composition, x="Componente", y="Valor", x_label=None, y_label="R$")
            st.dataframe(composition, hide_index=True, column_config={"Valor": st.column_config.NumberColumn(format="R$ %.2f")})

    st.subheader("Resumo para proposta", icon=":material/description:")
    proposal_text = f"""Plano {preset} para {plant_count} usina(s), com {number_br(total_kwp, 1)} kWp monitorados. Mensalidade: {money(breakdown.monthly_total)}. Valor anual: {money(breakdown.annual_total)}. Reajuste anual recomendado pelo IPCA."""
    st.code(proposal_text, language=None)

with portfolio:
    contracts = query(
        """SELECT c.*, cl.name AS client_name,
                  COALESCE(p.plant_count, 0) AS plant_count,
                  COALESCE(p.total_kwp, 0) AS total_kwp
           FROM contracts c JOIN clients cl ON cl.id=c.client_id
           LEFT JOIN (
               SELECT client_id, COUNT(*) AS plant_count,
                      COALESCE(SUM(installed_kwp), 0) AS total_kwp
               FROM plants WHERE status!='Desativada' GROUP BY client_id
           ) p ON p.client_id=c.client_id
           WHERE c.status='Ativo'
             AND c.billing_cycle='Mensal'
             AND NOT EXISTS (
                 SELECT 1 FROM contracts newer
                 WHERE newer.client_id=c.client_id
                   AND newer.status='Ativo'
                   AND newer.billing_cycle='Mensal'
                   AND newer.id>c.id
             )
           ORDER BY cl.name"""
    )
    rows = []
    for contract in contracts:
        monthly = contract_monthly_value(contract, contract["plant_count"], contract["total_kwp"])
        rows.append({
            "Cliente": contract["client_name"],
            "Plano": contract["plan"],
            "Usinas": contract["plant_count"],
            "Potência (kWp)": contract["total_kwp"],
            "MRR": monthly,
            "ARR": monthly * 12,
            "Próximo reajuste": contract["next_reajust_date"],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Nenhum contrato ativo.")
    else:
        with st.container(horizontal=True):
            st.metric("MRR total", money(df["MRR"].sum()), border=True)
            st.metric("ARR contratado", money(df["ARR"].sum()), border=True)
            st.metric("Ticket médio", money(df["MRR"].mean()), border=True)
            st.metric("Clientes recorrentes", len(df), border=True)
        st.dataframe(df, hide_index=True, column_config={"Cliente": st.column_config.TextColumn(pinned=True), "Potência (kWp)": st.column_config.NumberColumn(format="%.1f kWp"), "MRR": st.column_config.NumberColumn(format="R$ %.2f"), "ARR": st.column_config.NumberColumn(format="R$ %.2f"), "Próximo reajuste": st.column_config.DateColumn(format="DD/MM/YYYY")})
        st.download_button("Exportar carteira", df.to_csv(index=False).encode("utf-8-sig"), "carteira_recorrente.csv", "text/csv", icon=":material/download:")

with plans:
    plans_df = pd.DataFrame([
        {"Plano": "Essencial", "Indicado para": "Residencial e pequeno comércio", "Monitoramento": "Semanal", "Relatório": "Mensal", "Faturas": "Conferência mensal", "Visitas": "Sob demanda", "SLA sugerido": "24 h"},
        {"Plano": "Performance", "Indicado para": "Comércio e múltiplas unidades", "Monitoramento": "Diário", "Relatório": "Mensal detalhado", "Faturas": "Gestão completa", "Visitas": "2 preventivas/ano", "SLA sugerido": "8 h"},
        {"Plano": "Premium", "Indicado para": "Empresas críticas e alta potência", "Monitoramento": "Diário + alertas", "Relatório": "Mensal + reunião", "Faturas": "Gestão e contestação", "Visitas": "Preventivas inclusas", "SLA sugerido": "4 h"},
    ])
    st.dataframe(plans_df, hide_index=True, column_config={"Plano": st.column_config.TextColumn(pinned=True)})
    st.caption("A composição final deve considerar quantidade de UCs, distância, criticidade, integrações, obrigações de SLA e esforço administrativo.")
