from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.calculations import contract_monthly_value, money, number_br
from solar_crm.db import execute, query, query_df, query_one
from solar_crm.finance import sync_invoice_to_cash
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
contracts = query("SELECT * FROM contracts WHERE client_id=? ORDER BY id DESC", (client_id,))
recurring_contract = next(
    (
        row for row in contracts
        if row["status"] == "Ativo" and row["billing_cycle"] != "Parcela única"
    ),
    None,
)
one_time_contracts = [row for row in contracts if row["billing_cycle"] == "Parcela única"]
capacity = sum(float(plant["installed_kwp"] or 0) for plant in plants)
monthly = contract_monthly_value(recurring_contract, len(plants), capacity) if recurring_contract else 0
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
               LEFT JOIN invoices i ON i.contract_id=c.id
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

with billing_tab:
    invoices = query_df(
        """SELECT c.plan AS contract_name, i.reference_month AS reference_month,
                  i.due_date AS due_date, i.amount AS amount, i.status AS invoice_status,
                  i.paid_at AS paid_at, i.notes AS notes
           FROM invoices i JOIN contracts c ON c.id=i.contract_id
           WHERE c.client_id=? ORDER BY i.reference_month DESC""",
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
                        "SELECT id FROM invoices WHERE contract_id=? AND reference_month=?",
                        (billing_contract["id"], reference_month),
                    )
                    if duplicate:
                        st.error("Já existe uma cobrança para este contrato no mês informado.")
                    else:
                        paid_at = date.today().isoformat() if status == "Pago" else None
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
