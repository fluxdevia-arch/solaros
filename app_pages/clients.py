from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.calculations import contract_monthly_value, money, number_br
from solar_crm.db import execute, query, query_df, query_one
from solar_crm.finance import sync_invoice_to_cash
from solar_crm.plant_equipment import ensure_equipment_inventory_schema, equipment_summary_for_client
from solar_crm.ui import client_options, date_br, flash, page_intro, render_delete_control, show_flash, status_badge

page_intro("Centralize contatos, escopo contratado, mensalidades e histórico de cobrança do pós-venda.")
show_flash()
ensure_equipment_inventory_schema()

clients = query("SELECT * FROM clients ORDER BY CASE status WHEN 'Ativo' THEN 1 ELSE 2 END, name")

with st.container(horizontal=True, horizontal_alignment="right"):
    add_client = st.popover("Novo cliente", icon=":material/person_add:")
    export_df = query_df("SELECT name AS \"Cliente\", document AS \"Documento\", contact_name AS \"Contato\", email AS \"Email\", phone AS \"Telefone\", city AS \"Cidade\", state AS \"UF\", status AS \"Status\" FROM clients ORDER BY name")
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
billable_plants = [plant for plant in plants if plant["status"] != "Desativada"]
contracts = query("SELECT * FROM contracts WHERE client_id=? ORDER BY id DESC", (client_id,))
recurring_contract = next(
    (
        row for row in contracts
        if row["status"] == "Ativo" and row["billing_cycle"] != "Parcela única"
    ),
    None,
)
one_time_contracts = [row for row in contracts if row["billing_cycle"] == "Parcela única"]
capacity = sum(float(plant["installed_kwp"] or 0) for plant in billable_plants)
equipment_summary = equipment_summary_for_client(client_id)
total_inverters = sum(types.get("Inversor", 0) for types in equipment_summary.values())
total_panels = sum(types.get("Painel solar", 0) for types in equipment_summary.values())
monthly = contract_monthly_value(recurring_contract, len(billable_plants), capacity) if recurring_contract else 0
total_savings = query_one(
    """SELECT COALESCE(SUM(r.reference_amount-r.billed_amount),0) AS value
       FROM readings r JOIN plants p ON p.id=r.plant_id WHERE p.client_id=?""",
    (client_id,),
)["value"]

with st.container(horizontal=True):
    st.metric("Usinas", len(plants), border=True)
    st.metric("Potência", f"{number_br(capacity, 1)} kWp", border=True)
    st.metric("Inversores", total_inverters, border=True)
    st.metric("Painéis", total_panels, border=True)
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
        plant_df["Inversores"] = plant_df["id"].map(lambda value: equipment_summary.get(int(value), {}).get("Inversor", 0))
        plant_df["Painéis"] = plant_df["id"].map(lambda value: equipment_summary.get(int(value), {}).get("Painel solar", 0))
        plant_df["Próxima limpeza"] = plant_df["Próxima limpeza"].map(date_br)
        st.dataframe(plant_df[["Usina", "UC", "Distribuidora", "Potência (kWp)", "Inversores", "Painéis", "Status", "Próxima limpeza"]], hide_index=True, column_config={"Usina": st.column_config.TextColumn(pinned=True), "Potência (kWp)": st.column_config.NumberColumn(format="%.1f kWp")})
    else:
        st.caption("Nenhuma usina vinculada.")

    render_delete_control(
        "client",
        client_id,
        f"cliente {client['name']}",
        state_keys=("selected_client_id", "report_pdf", "report_key"),
        extra_warning="Usinas, cobranças, documentos e registros operacionais vinculados serão tratados conforme a lista abaixo.",
    )

with contract_tab:
    st.subheader("Pós-venda recorrente", icon=":material/autorenew:")
    if recurring_contract:
        st.markdown(status_badge(recurring_contract["status"]))
        with st.container(horizontal=True):
            st.metric("Plano", recurring_contract["plan"], border=True)
            st.metric("Mensalidade", money(monthly), border=True)
            st.metric("Dia de cobrança", recurring_contract["billing_day"], border=True)
            st.metric("Próximo reajuste", date_br(recurring_contract["next_reajust_date"]), border=True)
        st.table({
            "Início": date_br(recurring_contract["start_date"]),
            "Ciclo": recurring_contract["billing_cycle"],
            "Base mensal": money(recurring_contract["base_fee"]),
            "Por usina": money(recurring_contract["per_plant_fee"]),
            "Por kWp": money(recurring_contract["per_kwp_fee"]),
            "Serviços adicionais": money(recurring_contract["extras_fee"]),
            "Desconto": f"{recurring_contract['discount_pct']:.1f}%",
            "Índice de reajuste": recurring_contract["reajust_index"],
        }, border="horizontal", width="content")
        st.caption(
            "A mensalidade é calculada somando base mensal, valor por usina ativa, valor por kWp "
            "e adicionais, com o desconto aplicado ao final. Zere os componentes que não fazem parte do contrato."
        )
        st.subheader("Escopo contratado", icon=":material/checklist:")
        st.write(recurring_contract["scope"] or "Escopo não informado.")
    else:
        st.info("Este cliente não possui contrato recorrente ativo.", icon=":material/info:")

    if one_time_contracts:
        st.subheader("Consultorias e serviços avulsos", icon=":material/engineering:")
        one_time_frame = query_df(
            """SELECT c.plan AS service, c.start_date AS start_date, c.base_fee AS amount,
                      c.status AS contract_status, i.due_date AS due_date,
                      COALESCE(i.status, 'Sem cobrança') AS billing_status,
                      COALESCE(i.notes, c.scope, '') AS description
               FROM contracts c
               LEFT JOIN invoices i ON i.contract_id=c.id AND i.deleted_at IS NULL
               WHERE c.client_id=? AND c.billing_cycle='Parcela única'
               ORDER BY c.id DESC, i.reference_month DESC""",
            (client_id,),
        ).rename(columns={
            "service": "Serviço", "start_date": "Contratação", "amount": "Valor",
            "contract_status": "Contrato", "due_date": "Vencimento",
            "billing_status": "Cobrança", "description": "Descrição",
        })
        one_time_frame["Contratação"] = one_time_frame["Contratação"].map(date_br)
        one_time_frame["Vencimento"] = one_time_frame["Vencimento"].map(date_br)
        st.dataframe(
            one_time_frame,
            hide_index=True,
            column_config={
                "Serviço": st.column_config.TextColumn(pinned=True),
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

    with st.expander("Cadastrar contrato ou consultoria", icon=":material/add_notes:"):
        contract_model = st.segmented_control(
            "Modelo de contratação",
            ["Pós-venda recorrente", "Consultoria avulsa"],
            default="Pós-venda recorrente",
            key="new_contract_model",
        )
        with st.form("new_contract"):
            if contract_model == "Pós-venda recorrente":
                plan = st.selectbox(
                    "Plano",
                    ["Essencial", "Performance", "Premium", "Personalizado"],
                    key="recurring_plan",
                )
                start_date = st.date_input("Início", value=date.today(), key="recurring_start_date")
                billing_day = st.number_input(
                    "Dia de cobrança", min_value=1, max_value=28, value=10, key="recurring_billing_day"
                )
                c1, c2 = st.columns(2)
                base_fee = c1.number_input(
                    "Base mensal (R$)", min_value=0.0, value=300.0, step=10.0, key="recurring_base_fee"
                )
                per_plant = c2.number_input(
                    "Por usina (R$)", min_value=0.0, value=100.0, step=10.0, key="recurring_per_plant"
                )
                per_kwp = c1.number_input(
                    "Por kWp (R$)", min_value=0.0, value=1.5, step=0.1, key="recurring_per_kwp"
                )
                extras = c2.number_input(
                    "Adicionais (R$)", min_value=0.0, value=0.0, step=10.0, key="recurring_extras"
                )
                discount = st.number_input(
                    "Desconto (%)", min_value=0.0, max_value=100.0, value=0.0,
                    step=0.5, key="recurring_discount",
                )
                scope = st.text_area(
                    "Escopo",
                    value="Monitoramento, relatório mensal, gestão de faturas e suporte remoto.",
                    key="recurring_scope",
                )
            else:
                consulting_title = st.text_input(
                    "Nome da consultoria ou serviço",
                    value="Consultoria para análise de usina fotovoltaica",
                    key="consulting_title",
                )
                c1, c2 = st.columns(2)
                consulting_start = c1.date_input(
                    "Data da contratação", value=date.today(), key="consulting_start_date"
                )
                consulting_due = c2.date_input(
                    "Vencimento da cobrança", value=date.today() + timedelta(days=15), key="consulting_due_date"
                )
                consulting_amount = st.number_input(
                    "Valor único (R$)", min_value=0.0, value=3000.0, step=100.0, key="consulting_amount"
                )
                consulting_scope = st.text_area(
                    "Serviço que será realizado",
                    value=(
                        "Análise técnica da usina fotovoltaica, conferência de geração e desempenho, "
                        "avaliação dos equipamentos e entrega de relatório com recomendações."
                    ),
                    key="consulting_scope",
                )
                consulting_charge_notes = st.text_area(
                    "Observação da cobrança",
                    value="Parcela única referente à consultoria técnica contratada.",
                    key="consulting_charge_notes",
                )

            submitted_contract = st.form_submit_button(
                "Salvar contrato e cobrança" if contract_model == "Consultoria avulsa" else "Criar contrato",
                type="primary",
                icon=":material/save:",
                key="create_contract_submit",
            )
            if submitted_contract:
                if contract_model == "Pós-venda recorrente":
                    execute(
                        """UPDATE contracts SET status='Encerrado'
                           WHERE client_id=? AND status='Ativo' AND billing_cycle!='Parcela única'""",
                        (client_id,),
                    )
                    recurring_contract_id = execute(
                        """INSERT INTO contracts (client_id, plan, start_date, billing_day, base_fee, per_plant_fee, per_kwp_fee, extras_fee, discount_pct, billing_cycle, status, scope, reajust_index, next_reajust_date)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Mensal', 'Ativo', ?, 'IPCA', date(?, '+1 year'))""",
                        (
                            client_id, plan, start_date.isoformat(), billing_day, base_fee, per_plant,
                            per_kwp, extras, discount, scope.strip(), start_date.isoformat(),
                        ),
                    )
                    first_amount = contract_monthly_value(
                        {
                            "base_fee": base_fee,
                            "per_plant_fee": per_plant,
                            "per_kwp_fee": per_kwp,
                            "extras_fee": extras,
                            "discount_pct": discount,
                        },
                        len(plants),
                        capacity,
                    )
                    first_invoice_id = execute(
                        """INSERT INTO invoices
                           (contract_id, reference_month, due_date, amount, status, notes)
                           VALUES (?, ?, ?, ?, 'Pendente', ?)""",
                        (
                            recurring_contract_id,
                            start_date.replace(day=1).isoformat(),
                            start_date.replace(day=min(int(billing_day), 28)).isoformat(),
                            first_amount,
                            scope.strip() or "Mensalidade de pós-venda.",
                        ),
                    )
                    sync_invoice_to_cash(first_invoice_id)
                    flash("Contrato recorrente criado e primeira mensalidade lançada no caixa.")
                    st.rerun()
                elif not consulting_title.strip() or not consulting_scope.strip():
                    st.error("Informe o nome e a descrição do serviço.")
                elif consulting_amount <= 0:
                    st.error("Informe um valor maior que zero para a consultoria.")
                else:
                    consulting_contract_id = execute(
                        """INSERT INTO contracts
                           (client_id, plan, start_date, billing_day, base_fee, per_plant_fee,
                            per_kwp_fee, extras_fee, discount_pct, billing_cycle, status, scope,
                            reajust_index, next_reajust_date)
                           VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, 'Parcela única', 'Ativo', ?,
                                   'Não aplicável', NULL)""",
                        (
                            client_id, consulting_title.strip(), consulting_start.isoformat(),
                            min(consulting_due.day, 28), consulting_amount, consulting_scope.strip(),
                        ),
                    )
                    consulting_invoice_id = execute(
                        """INSERT INTO invoices
                           (contract_id, reference_month, due_date, amount, status, notes)
                           VALUES (?, ?, ?, ?, 'Pendente', ?)""",
                        (
                            consulting_contract_id, consulting_start.replace(day=1).isoformat(),
                            consulting_due.isoformat(), consulting_amount,
                            consulting_charge_notes.strip() or consulting_scope.strip(),
                        ),
                    )
                    sync_invoice_to_cash(consulting_invoice_id)
                    flash("Consultoria cadastrada e valor lançado automaticamente no caixa.")
                    st.rerun()

    if contracts:
        contract_admin_map = {
            f"#{row['id']} · {row['plan']} · {row['billing_cycle']} · {row['status']}": row
            for row in contracts
        }
        contract_admin_label = st.selectbox(
            "Contrato para administrar",
            list(contract_admin_map),
            key="client_contract_delete_selector",
        )
        contract_to_edit = contract_admin_map[contract_admin_label]

        with st.expander("Editar contrato selecionado", icon=":material/edit_note:"):
            is_one_time = contract_to_edit["billing_cycle"] == "Parcela única"
            with st.form(f"edit_contract_{contract_to_edit['id']}"):
                edit_plan = st.text_input(
                    "Plano, consultoria ou serviço",
                    value=contract_to_edit["plan"] or "",
                    key=f"contract_edit_plan_{contract_to_edit['id']}",
                )
                c1, c2 = st.columns(2)
                edit_start = c1.date_input(
                    "Início",
                    value=date.fromisoformat(str(contract_to_edit["start_date"])[:10]),
                    key=f"contract_edit_start_{contract_to_edit['id']}",
                )
                status_options = ["Ativo", "Encerrado", "Cancelado"]
                current_contract_status = contract_to_edit["status"]
                if current_contract_status not in status_options:
                    status_options.append(current_contract_status)
                edit_contract_status = c2.selectbox(
                    "Status",
                    status_options,
                    index=status_options.index(current_contract_status),
                    key=f"contract_edit_status_{contract_to_edit['id']}",
                )
                edit_billing_day = st.number_input(
                    "Dia de cobrança",
                    min_value=1,
                    max_value=28,
                    value=min(max(int(contract_to_edit["billing_day"] or 10), 1), 28),
                    key=f"contract_edit_billing_day_{contract_to_edit['id']}",
                )
                if is_one_time:
                    edit_base_fee = st.number_input(
                        "Valor único (R$)",
                        min_value=0.0,
                        value=float(contract_to_edit["base_fee"] or 0),
                        step=100.0,
                        key=f"contract_edit_base_{contract_to_edit['id']}",
                    )
                    edit_per_plant = 0.0
                    edit_per_kwp = 0.0
                    edit_extras = 0.0
                    edit_discount = 0.0
                    edit_reajust_index = "Não aplicável"
                    edit_next_reajust = None
                else:
                    p1, p2 = st.columns(2)
                    edit_base_fee = p1.number_input(
                        "Base mensal (R$)", min_value=0.0,
                        value=float(contract_to_edit["base_fee"] or 0), step=10.0,
                        key=f"contract_edit_base_{contract_to_edit['id']}",
                    )
                    edit_per_plant = p2.number_input(
                        "Por usina ativa (R$)", min_value=0.0,
                        value=float(contract_to_edit["per_plant_fee"] or 0), step=10.0,
                        key=f"contract_edit_per_plant_{contract_to_edit['id']}",
                    )
                    edit_per_kwp = p1.number_input(
                        "Por kWp ativo (R$)", min_value=0.0,
                        value=float(contract_to_edit["per_kwp_fee"] or 0), step=0.1,
                        key=f"contract_edit_per_kwp_{contract_to_edit['id']}",
                    )
                    edit_extras = p2.number_input(
                        "Serviços adicionais (R$)", min_value=0.0,
                        value=float(contract_to_edit["extras_fee"] or 0), step=10.0,
                        key=f"contract_edit_extras_{contract_to_edit['id']}",
                    )
                    edit_discount = st.number_input(
                        "Desconto (%)", min_value=0.0, max_value=100.0,
                        value=float(contract_to_edit["discount_pct"] or 0), step=0.5,
                        key=f"contract_edit_discount_{contract_to_edit['id']}",
                    )
                    edit_reajust_index = st.text_input(
                        "Índice de reajuste",
                        value=contract_to_edit["reajust_index"] or "IPCA",
                        key=f"contract_edit_reajust_{contract_to_edit['id']}",
                    )
                    current_next_reajust = (
                        date.fromisoformat(str(contract_to_edit["next_reajust_date"])[:10])
                        if contract_to_edit["next_reajust_date"] else edit_start.replace(year=edit_start.year + 1)
                    )
                    edit_next_reajust = st.date_input(
                        "Próximo reajuste",
                        value=current_next_reajust,
                        key=f"contract_edit_next_reajust_{contract_to_edit['id']}",
                    )
                    preview_amount = contract_monthly_value(
                        {
                            "base_fee": edit_base_fee,
                            "per_plant_fee": edit_per_plant,
                            "per_kwp_fee": edit_per_kwp,
                            "extras_fee": edit_extras,
                            "discount_pct": edit_discount,
                        },
                        len(billable_plants),
                        capacity,
                    )
                    st.info(f"Mensalidade recalculada: {money(preview_amount)}")
                edit_scope = st.text_area(
                    "Escopo e observações",
                    value=contract_to_edit["scope"] or "",
                    key=f"contract_edit_scope_{contract_to_edit['id']}",
                )
                update_open_charges = st.checkbox(
                    "Atualizar também cobranças pendentes e atrasadas deste contrato",
                    value=True,
                    key=f"contract_edit_charges_{contract_to_edit['id']}",
                )
                if st.form_submit_button(
                    "Salvar alterações do contrato",
                    type="primary",
                    icon=":material/save:",
                    key=f"contract_edit_submit_{contract_to_edit['id']}",
                ):
                    if not edit_plan.strip():
                        st.error("Informe o nome do plano, consultoria ou serviço.")
                    else:
                        execute(
                            """UPDATE contracts
                               SET plan=?, start_date=?, billing_day=?, base_fee=?, per_plant_fee=?,
                                   per_kwp_fee=?, extras_fee=?, discount_pct=?, status=?, scope=?,
                                   reajust_index=?, next_reajust_date=?
                               WHERE id=?""",
                            (
                                edit_plan.strip(), edit_start.isoformat(), int(edit_billing_day),
                                edit_base_fee, edit_per_plant, edit_per_kwp, edit_extras,
                                edit_discount, edit_contract_status, edit_scope.strip(),
                                edit_reajust_index.strip() or "IPCA",
                                edit_next_reajust.isoformat() if edit_next_reajust else None,
                                contract_to_edit["id"],
                            ),
                        )
                        if update_open_charges:
                            revised_amount = (
                                edit_base_fee if is_one_time else contract_monthly_value(
                                    {
                                        "base_fee": edit_base_fee,
                                        "per_plant_fee": edit_per_plant,
                                        "per_kwp_fee": edit_per_kwp,
                                        "extras_fee": edit_extras,
                                        "discount_pct": edit_discount,
                                    },
                                    len(billable_plants),
                                    capacity,
                                )
                            )
                            open_invoices = query(
                                """SELECT id FROM invoices
                                   WHERE contract_id=? AND deleted_at IS NULL
                                     AND status IN ('Pendente', 'Atrasado')""",
                                (contract_to_edit["id"],),
                            )
                            for open_invoice in open_invoices:
                                execute(
                                    "UPDATE invoices SET amount=?, notes=? WHERE id=?",
                                    (revised_amount, edit_scope.strip(), open_invoice["id"]),
                                )
                                sync_invoice_to_cash(open_invoice["id"])
                        flash("Contrato atualizado e cobranças em aberto sincronizadas.")
                        st.rerun()

        contract_to_delete = contract_to_edit
        render_delete_control(
            "contract",
            contract_to_delete["id"],
            f"contrato {contract_to_delete['plan']}",
        )

with billing_tab:
    invoices = query_df(
        """SELECT c.plan AS contract_name, i.reference_month AS reference_month,
                  i.due_date AS due_date, i.amount AS amount, i.status AS invoice_status,
                  i.paid_at AS paid_at, i.notes AS notes
           FROM invoices i JOIN contracts c ON c.id=i.contract_id
           WHERE c.client_id=? AND i.deleted_at IS NULL ORDER BY i.reference_month DESC""",
        (client_id,),
    ).rename(columns={
        "contract_name": "Contrato/serviço", "reference_month": "Referência",
        "due_date": "Vencimento", "amount": "Valor", "invoice_status": "Status",
        "paid_at": "Pagamento", "notes": "Observações",
    })
    if not invoices.empty:
        invoices["Referência"] = invoices["Referência"].str[:7]
        invoices["Vencimento"] = invoices["Vencimento"].map(date_br)
        invoices["Pagamento"] = invoices["Pagamento"].map(date_br)
        st.dataframe(
            invoices,
            hide_index=True,
            column_config={
                "Contrato/serviço": st.column_config.TextColumn(pinned=True),
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Status": st.column_config.TextColumn(width="small"),
            },
        )
    else:
        st.caption("Nenhuma cobrança registrada.")

    billable_contracts = [row for row in contracts if row["status"] == "Ativo"]
    if billable_contracts:
        with st.expander("Lançar cobrança", icon=":material/add_card:"):
            billing_contract_map = {
                f"#{row['id']} · {row['plan']} · {row['billing_cycle']}": row
                for row in billable_contracts
            }
            billing_contract_label = st.selectbox(
                "Contrato ou serviço",
                list(billing_contract_map),
                key="invoice_contract",
            )
            billing_contract = billing_contract_map[billing_contract_label]
            default_amount = (
                float(billing_contract["base_fee"] or 0)
                if billing_contract["billing_cycle"] == "Parcela única"
                else contract_monthly_value(billing_contract, len(plants), capacity)
            )
            with st.form("new_invoice"):
                ref = st.date_input("Mês de referência", value=date.today().replace(day=1), key="invoice_reference")
                due = st.date_input(
                    "Vencimento",
                    value=date.today().replace(day=min(billing_contract["billing_day"], 28)),
                    key="invoice_due_date",
                )
                amount = st.number_input(
                    "Valor (R$)", min_value=0.0, value=default_amount, step=10.0, key="invoice_amount"
                )
                status = st.selectbox(
                    "Status", ["Pendente", "Pago", "Atrasado", "Cancelado"], key="invoice_status"
                )
                notes = st.text_area(
                    "Descrição ou observação da cobrança",
                    value=billing_contract["scope"] or "Serviço contratado.",
                    key="invoice_notes",
                )
                if st.form_submit_button(
                    "Registrar cobrança", type="primary", icon=":material/save:", key="invoice_submit"
                ):
                    reference_month = ref.replace(day=1).isoformat()
                    duplicate = query_one(
                        "SELECT id, deleted_at FROM invoices WHERE contract_id=? AND reference_month=?",
                        (billing_contract["id"], reference_month),
                    )
                    if duplicate and not duplicate["deleted_at"]:
                        st.error("Já existe uma cobrança para este contrato no mês informado.")
                    else:
                        paid_at = date.today().isoformat() if status == "Pago" else None
                        if duplicate:
                            invoice_id = duplicate["id"]
                            execute(
                                """UPDATE invoices SET due_date=?, amount=?, status=?, paid_at=?,
                                   notes=?, deleted_at=NULL WHERE id=?""",
                                (due.isoformat(), amount, status, paid_at, notes.strip(), invoice_id),
                            )
                        else:
                            invoice_id = execute(
                                """INSERT INTO invoices
                                   (contract_id, reference_month, due_date, amount, status, paid_at, notes)
                                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    billing_contract["id"], reference_month, due.isoformat(), amount,
                                    status, paid_at, notes.strip(),
                                ),
                            )
                        sync_invoice_to_cash(invoice_id)
                        flash("Cobrança registrada e lançada no caixa.")
                        st.rerun()

    invoice_rows = query(
        """SELECT i.id, i.reference_month, i.due_date, i.amount, i.status, i.paid_at,
                  i.notes, c.plan,
                  (SELECT payment_method FROM cash_transactions ct
                   WHERE ct.source_type='invoice' AND ct.source_id=i.id
                   ORDER BY ct.id DESC LIMIT 1) AS payment_method
           FROM invoices i JOIN contracts c ON c.id=i.contract_id
           WHERE c.client_id=? AND i.deleted_at IS NULL
           ORDER BY i.reference_month DESC, i.id DESC""",
        (client_id,),
    )
    if invoice_rows:
        invoice_delete_map = {
            f"FAT-{row['id']} · {row['plan']} · {row['reference_month'][:7]} · {money(row['amount'])}": row
            for row in invoice_rows
        }
        invoice_delete_label = st.selectbox(
            "Cobrança para administrar",
            list(invoice_delete_map),
            key="client_invoice_delete_selector",
        )
        invoice_to_delete = invoice_delete_map[invoice_delete_label]

        with st.expander("Editar cobrança ou pagamento", icon=":material/edit_square:"):
            invoice_status_options = ["Pendente", "Pago", "Atrasado", "Cancelado"]
            payment_options = ["Não informado", "Pix", "Boleto", "Transferência", "Cartão", "Dinheiro", "Outro"]
            current_payment_method = invoice_to_delete["payment_method"] or "Não informado"
            if current_payment_method not in payment_options:
                payment_options.append(current_payment_method)
            with st.form(f"edit_invoice_{invoice_to_delete['id']}"):
                i1, i2 = st.columns(2)
                edit_invoice_reference = i1.date_input(
                    "Mês de referência",
                    value=date.fromisoformat(str(invoice_to_delete["reference_month"])[:10]),
                    key=f"invoice_edit_reference_{invoice_to_delete['id']}",
                )
                edit_invoice_due = i2.date_input(
                    "Vencimento",
                    value=date.fromisoformat(str(invoice_to_delete["due_date"])[:10]),
                    key=f"invoice_edit_due_{invoice_to_delete['id']}",
                )
                edit_invoice_amount = i1.number_input(
                    "Valor da cobrança (R$)",
                    min_value=0.0,
                    value=float(invoice_to_delete["amount"] or 0),
                    step=10.0,
                    key=f"invoice_edit_amount_{invoice_to_delete['id']}",
                )
                edit_invoice_status = i2.selectbox(
                    "Status",
                    invoice_status_options,
                    index=invoice_status_options.index(invoice_to_delete["status"]),
                    key=f"invoice_edit_status_{invoice_to_delete['id']}",
                )
                current_paid_at = (
                    date.fromisoformat(str(invoice_to_delete["paid_at"])[:10])
                    if invoice_to_delete["paid_at"] else date.today()
                )
                edit_paid_at = i1.date_input(
                    "Data do pagamento",
                    value=current_paid_at,
                    help="A data será usada somente quando o status for Pago.",
                    key=f"invoice_edit_paid_at_{invoice_to_delete['id']}",
                )
                edit_payment_method = i2.selectbox(
                    "Forma de pagamento",
                    payment_options,
                    index=payment_options.index(current_payment_method),
                    key=f"invoice_edit_payment_method_{invoice_to_delete['id']}",
                )
                edit_invoice_notes = st.text_area(
                    "Descrição ou observações",
                    value=invoice_to_delete["notes"] or "",
                    key=f"invoice_edit_notes_{invoice_to_delete['id']}",
                )
                if st.form_submit_button(
                    "Salvar cobrança e pagamento",
                    type="primary",
                    icon=":material/save:",
                    key=f"invoice_edit_submit_{invoice_to_delete['id']}",
                ):
                    reference_month = edit_invoice_reference.replace(day=1).isoformat()
                    duplicate_invoice = query_one(
                        """SELECT id FROM invoices
                           WHERE contract_id=(SELECT contract_id FROM invoices WHERE id=?)
                             AND reference_month=? AND id!=? AND deleted_at IS NULL""",
                        (invoice_to_delete["id"], reference_month, invoice_to_delete["id"]),
                    )
                    if duplicate_invoice:
                        st.error("Já existe outra cobrança deste contrato para o mês informado.")
                    else:
                        paid_at = edit_paid_at.isoformat() if edit_invoice_status == "Pago" else None
                        execute(
                            """UPDATE invoices
                               SET reference_month=?, due_date=?, amount=?, status=?, paid_at=?, notes=?
                               WHERE id=?""",
                            (
                                reference_month, edit_invoice_due.isoformat(), edit_invoice_amount,
                                edit_invoice_status, paid_at, edit_invoice_notes.strip(),
                                invoice_to_delete["id"],
                            ),
                        )
                        sync_invoice_to_cash(invoice_to_delete["id"])
                        execute(
                            """UPDATE cash_transactions SET payment_method=?
                               WHERE source_type='invoice' AND source_id=?""",
                            (
                                None if edit_payment_method == "Não informado" else edit_payment_method,
                                invoice_to_delete["id"],
                            ),
                        )
                        flash("Cobrança e pagamento atualizados no caixa.")
                        st.rerun()

        render_delete_control(
            "invoice",
            invoice_to_delete["id"],
            f"cobrança FAT-{invoice_to_delete['id']}",
        )
