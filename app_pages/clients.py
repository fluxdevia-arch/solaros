from datetime import date

import pandas as pd
import streamlit as st

from solar_crm.calculations import contract_monthly_value, money, number_br
from solar_crm.db import execute, query, query_df, query_one
from solar_crm.ui import client_options, date_br, flash, page_intro, show_flash, status_badge

page_intro("Centralize contatos, escopo contratado, mensalidades e histórico de cobrança do pós-venda.")
show_flash()

clients = query("SELECT * FROM clients ORDER BY CASE status WHEN 'Ativo' THEN 1 ELSE 2 END, name")

with st.container(horizontal=True, horizontal_alignment="right"):
    add_client = st.popover("Novo cliente", icon=":material/person_add:")
    export_df = query_df("SELECT name AS Cliente, document AS Documento, contact_name AS Contato, email AS Email, phone AS Telefone, city AS Cidade, state AS UF, status AS Status FROM clients ORDER BY name")
    st.download_button("Exportar", export_df.to_csv(index=False).encode("utf-8-sig"), "clientes.csv", "text/csv", icon=":material/download:")

with add_client:
    with st.form("new_client", clear_on_submit=True):
        name = st.text_input("Nome ou razão social")
        client_type = st.segmented_control("Tipo", ["Pessoa jurídica", "Pessoa física"], default="Pessoa jurídica")
        document = st.text_input("CPF ou CNPJ")
        contact = st.text_input("Contato principal")
        email = st.text_input("E-mail")
        phone = st.text_input("Telefone")
        address = st.text_input("Endereço")
        city = st.text_input("Cidade")
        state = st.text_input("UF", max_chars=2)
        notes = st.text_area("Observações")
        submitted = st.form_submit_button("Cadastrar cliente", type="primary", icon=":material/save:")
        if submitted:
            if not name.strip():
                st.error("Informe o nome do cliente.")
            else:
                new_id = execute(
                    """INSERT INTO clients (name, document, client_type, contact_name, email, phone, address, city, state, status, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Ativo', ?)""",
                    (
                        name.strip(), document.strip(), client_type, contact.strip(), email.strip(),
                        phone.strip(), address.strip(), city.strip(), state.strip().upper(), notes.strip(),
                    ),
                )
                st.session_state.selected_client_id = new_id
                flash("Cliente cadastrado com sucesso.")
                st.rerun()

if not clients:
    st.info("Cadastre o primeiro cliente para começar.", icon=":material/info:")
    st.stop()

option_map = client_options(clients)
default_name = next((name for name, cid in option_map.items() if cid == st.session_state.get("selected_client_id")), list(option_map)[0])
selected_name = st.selectbox("Cliente", list(option_map), index=list(option_map).index(default_name), key="client_selector")
client_id = option_map[selected_name]
st.session_state.selected_client_id = client_id
client = query_one("SELECT * FROM clients WHERE id=?", (client_id,))

with st.container(horizontal=True, horizontal_alignment="right"):
    edit_client = st.popover("Editar cliente", icon=":material/edit:")

with edit_client:
    st.caption("Altere os dados cadastrais e salve para atualizar relatórios, contratos e ordens de serviço.")
    with st.form("edit_client"):
        name_edit = st.text_input("Nome ou razão social", value=client["name"] or "", key="client_edit_name")
        type_options = ["Pessoa jurídica", "Pessoa física"]
        current_type = client["client_type"] if client["client_type"] in type_options else type_options[0]
        client_type_edit = st.segmented_control(
            "Tipo",
            type_options,
            default=current_type,
            key="client_edit_type",
        )
        document_edit = st.text_input("CPF ou CNPJ", value=client["document"] or "", key="client_edit_document")
        contact_edit = st.text_input("Contato principal", value=client["contact_name"] or "", key="client_edit_contact")
        email_edit = st.text_input("E-mail", value=client["email"] or "", key="client_edit_email")
        phone_edit = st.text_input("Telefone", value=client["phone"] or "", key="client_edit_phone")
        address_edit = st.text_input("Endereço", value=client["address"] or "", key="client_edit_address")
        city_edit = st.text_input("Cidade", value=client["city"] or "", key="client_edit_city")
        state_edit = st.text_input("UF", value=client["state"] or "", max_chars=2, key="client_edit_state")
        status_options = ["Ativo", "Inativo"]
        status_edit = st.selectbox(
            "Status",
            status_options,
            index=status_options.index(client["status"]) if client["status"] in status_options else 0,
            key="client_edit_status",
        )
        notes_edit = st.text_area("Observações", value=client["notes"] or "", key="client_edit_notes")
        if st.form_submit_button(
            "Salvar alterações",
            type="primary",
            icon=":material/save:",
            key="client_edit_submit",
        ):
            if not name_edit.strip():
                st.error("Informe o nome do cliente.")
            else:
                execute(
                    """UPDATE clients
                       SET name=?, document=?, client_type=?, contact_name=?, email=?, phone=?,
                           address=?, city=?, state=?, status=?, notes=?
                       WHERE id=?""",
                    (
                        name_edit.strip(), document_edit.strip(), client_type_edit, contact_edit.strip(),
                        email_edit.strip(), phone_edit.strip(), address_edit.strip(), city_edit.strip(),
                        state_edit.strip().upper(), status_edit, notes_edit.strip(), client_id,
                    ),
                )
                flash("Cadastro do cliente atualizado.")
                st.rerun()

plants = query(
    "SELECT * FROM plants WHERE client_id=? ORDER BY name",
    (client_id,),
)
contract = query_one("SELECT * FROM contracts WHERE client_id=? ORDER BY id DESC LIMIT 1", (client_id,))
capacity = sum(float(plant["installed_kwp"] or 0) for plant in plants)
monthly = contract_monthly_value(contract, len(plants), capacity) if contract else 0
total_savings = query_one(
    """SELECT COALESCE(SUM(r.reference_amount-r.billed_amount),0) AS value
       FROM readings r JOIN plants p ON p.id=r.plant_id WHERE p.client_id=?""",
    (client_id,),
)["value"]

with st.container(horizontal=True):
    st.metric("Usinas", len(plants), border=True)
    st.metric("Potência", f"{number_br(capacity, 1)} kWp", border=True)
    st.metric("Mensalidade", money(monthly), border=True)
    st.metric("Economia acumulada", money(total_savings), border=True)

profile_tab, contract_tab, billing_tab = st.tabs([
    ":material/id_card: Perfil",
    ":material/contract: Contrato",
    ":material/receipt_long: Cobranças",
])

with profile_tab:
    left, right = st.columns([1.15, 0.85])
    with left:
        with st.container(border=True):
            st.subheader(client["name"])
            st.markdown(status_badge(client["status"]))
            st.table({
                ":material/badge: Documento": client["document"] or "-",
                ":material/person: Contato": client["contact_name"] or "-",
                ":material/mail: E-mail": client["email"] or "-",
                ":material/call: Telefone": client["phone"] or "-",
                ":material/home: Endereço": client["address"] or "-",
                ":material/location_on: Localidade": f"{client['city'] or '-'} / {client['state'] or '-'}",
                ":material/calendar_today: Cliente desde": date_br(client["created_at"]),
            }, border="horizontal", width="stretch")
    with right:
        with st.container(border=True):
            st.subheader("Observações", icon=":material/sticky_note_2:")
            st.write(client["notes"] or "Nenhuma observação cadastrada.")

    st.subheader("Usinas vinculadas", icon=":material/solar_power:")
    if plants:
        plant_df = pd.DataFrame(plants).rename(columns={"name": "Usina", "unit_code": "UC", "distributor": "Distribuidora", "installed_kwp": "Potência (kWp)", "status": "Status", "next_cleaning_date": "Próxima limpeza"})
        plant_df["Próxima limpeza"] = plant_df["Próxima limpeza"].map(date_br)
        st.dataframe(plant_df[["Usina", "UC", "Distribuidora", "Potência (kWp)", "Status", "Próxima limpeza"]], hide_index=True, column_config={"Usina": st.column_config.TextColumn(pinned=True), "Potência (kWp)": st.column_config.NumberColumn(format="%.1f kWp")})
    else:
        st.caption("Nenhuma usina vinculada.")

with contract_tab:
    if contract:
        st.markdown(status_badge(contract["status"]))
        with st.container(horizontal=True):
            st.metric("Plano", contract["plan"], border=True)
            st.metric("Valor calculado", money(monthly), border=True)
            st.metric("Dia de cobrança", contract["billing_day"], border=True)
            st.metric("Próximo reajuste", date_br(contract["next_reajust_date"]), border=True)
        st.table({
            "Início": date_br(contract["start_date"]),
            "Ciclo": contract["billing_cycle"],
            "Base mensal": money(contract["base_fee"]),
            "Por usina": money(contract["per_plant_fee"]),
            "Por kWp": money(contract["per_kwp_fee"]),
            "Serviços adicionais": money(contract["extras_fee"]),
            "Desconto": f"{contract['discount_pct']:.1f}%",
            "Índice de reajuste": contract["reajust_index"],
        }, border="horizontal", width="content")
        st.subheader("Escopo contratado", icon=":material/checklist:")
        st.write(contract["scope"] or "Escopo não informado.")
    else:
        st.warning("Este cliente ainda não possui contrato de pós-venda.", icon=":material/warning:")

    with st.expander("Cadastrar novo contrato", icon=":material/add_notes:"):
        with st.form("new_contract"):
            plan = st.selectbox("Plano", ["Essencial", "Performance", "Premium", "Personalizado"])
            start_date = st.date_input("Início", value=date.today())
            billing_day = st.number_input("Dia de cobrança", min_value=1, max_value=28, value=10)
            c1, c2 = st.columns(2)
            base_fee = c1.number_input("Base mensal (R$)", min_value=0.0, value=300.0, step=10.0)
            per_plant = c2.number_input("Por usina (R$)", min_value=0.0, value=100.0, step=10.0)
            per_kwp = c1.number_input("Por kWp (R$)", min_value=0.0, value=1.5, step=0.1)
            extras = c2.number_input("Adicionais (R$)", min_value=0.0, value=0.0, step=10.0)
            discount = st.number_input("Desconto (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            scope = st.text_area("Escopo", value="Monitoramento, relatório mensal, gestão de faturas e suporte remoto.")
            if st.form_submit_button("Criar contrato", type="primary", icon=":material/save:"):
                execute("UPDATE contracts SET status='Encerrado' WHERE client_id=? AND status='Ativo'", (client_id,))
                execute(
                    """INSERT INTO contracts (client_id, plan, start_date, billing_day, base_fee, per_plant_fee, per_kwp_fee, extras_fee, discount_pct, billing_cycle, status, scope, reajust_index, next_reajust_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Mensal', 'Ativo', ?, 'IPCA', date(?, '+1 year'))""",
                    (client_id, plan, start_date.isoformat(), billing_day, base_fee, per_plant, per_kwp, extras, discount, scope, start_date.isoformat()),
                )
                flash("Novo contrato criado e contrato anterior encerrado.")
                st.rerun()

with billing_tab:
    invoices = query_df(
        """SELECT i.reference_month AS Referência, i.due_date AS Vencimento, i.amount AS Valor,
                  i.status AS Status, i.paid_at AS Pagamento, i.notes AS Observações
           FROM invoices i JOIN contracts c ON c.id=i.contract_id
           WHERE c.client_id=? ORDER BY i.reference_month DESC""",
        (client_id,),
    )
    if not invoices.empty:
        invoices["Referência"] = invoices["Referência"].str[:7]
        invoices["Vencimento"] = invoices["Vencimento"].map(date_br)
        invoices["Pagamento"] = invoices["Pagamento"].map(date_br)
        st.dataframe(invoices, hide_index=True, column_config={"Valor": st.column_config.NumberColumn(format="R$ %.2f"), "Status": st.column_config.TextColumn(width="small")})
    else:
        st.caption("Nenhuma cobrança registrada.")

    if contract:
        with st.expander("Lançar cobrança", icon=":material/add_card:"):
            with st.form("new_invoice"):
                ref = st.date_input("Mês de referência", value=date.today().replace(day=1))
                due = st.date_input("Vencimento", value=date.today().replace(day=min(contract["billing_day"], 28)))
                amount = st.number_input("Valor (R$)", min_value=0.0, value=float(monthly), step=10.0)
                status = st.selectbox("Status", ["Pendente", "Pago", "Atrasado", "Cancelado"])
                if st.form_submit_button("Registrar cobrança", type="primary", icon=":material/save:"):
                    try:
                        execute("INSERT INTO invoices (contract_id, reference_month, due_date, amount, status, notes) VALUES (?, ?, ?, ?, ?, ?)", (contract["id"], ref.replace(day=1).isoformat(), due.isoformat(), amount, status, "Mensalidade de pós-venda"))
                        flash("Cobrança registrada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível registrar: {exc}")
