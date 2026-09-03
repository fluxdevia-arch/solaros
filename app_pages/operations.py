from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from solar_crm.db import execute, query, query_df, query_one
from solar_crm.ui import client_options, date_br, flash, page_intro, plant_options, show_flash

page_intro("Organize inspeções, limpezas, contatos periódicos, garantias e atendimento de falhas com prioridade e SLA.")
show_flash()

clients = query("SELECT id, name FROM clients WHERE status='Ativo' ORDER BY name")
plants = query("""SELECT p.id, p.name, p.client_id, c.name AS client_name FROM plants p JOIN clients c ON c.id=p.client_id WHERE p.status!='Desativada' ORDER BY c.name, p.name""")
c_map = client_options(clients)
p_map = plant_options(plants)

with st.container(horizontal=True, horizontal_alignment="right"):
    add_task = st.popover("Nova atividade", icon=":material/add_task:")
    add_ticket = st.popover("Nova ocorrência", icon=":material/report_problem:")

with add_task:
    with st.form("new_task", clear_on_submit=True):
        client_name = st.selectbox("Cliente", list(c_map), key="task_client")
        valid_plants = {label: pid for label, pid in p_map.items() if next(row for row in plants if row["id"] == pid)["client_id"] == c_map[client_name]}
        plant_label = st.selectbox("Usina", ["Atividade geral do cliente", *valid_plants.keys()])
        title = st.text_input("Atividade")
        category = st.selectbox("Categoria", ["Monitoramento", "Relatório", "Relacionamento", "Limpeza", "Manutenção preventiva", "Manutenção corretiva", "Garantia", "Financeiro", "Outro"])
        c1, c2 = st.columns(2)
        priority = c1.selectbox("Prioridade", ["Baixa", "Média", "Alta", "Crítica"], index=1)
        due = c2.date_input("Prazo", value=date.today() + timedelta(days=7))
        recurrence = st.selectbox("Recorrência", ["Única", "Semanal", "Mensal", "Trimestral", "Semestral", "Anual"])
        assignee = st.text_input("Responsável")
        notes = st.text_area("Instruções e checklist")
        if st.form_submit_button("Criar atividade", type="primary", icon=":material/save:"):
            if not title.strip():
                st.error("Informe a atividade.")
            else:
                execute(
                    """INSERT INTO tasks (client_id, plant_id, title, category, priority, due_date, recurrence, status, assignee, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?)""",
                    (c_map[client_name], valid_plants.get(plant_label), title.strip(), category, priority, due.isoformat(), recurrence, assignee, notes),
                )
                flash("Atividade criada.")
                st.rerun()

with add_ticket:
    with st.form("new_ticket", clear_on_submit=True):
        client_name = st.selectbox("Cliente", list(c_map), key="ticket_client")
        valid_plants = {label: pid for label, pid in p_map.items() if next(row for row in plants if row["id"] == pid)["client_id"] == c_map[client_name]}
        plant_label = st.selectbox("Usina afetada", ["Não definida", *valid_plants.keys()])
        title = st.text_input("Título da ocorrência")
        category = st.selectbox("Categoria", ["Geração", "Inversor", "Rede elétrica", "Monitoramento", "Fatura", "Estrutura", "Garantia", "Outro"])
        c1, c2 = st.columns(2)
        severity = c1.selectbox("Severidade", ["Baixa", "Média", "Alta", "Crítica"], index=1)
        sla = c2.number_input("SLA (horas)", min_value=1, value=24, step=1)
        notes = st.text_area("Descrição inicial")
        if st.form_submit_button("Abrir ocorrência", type="primary", icon=":material/save:"):
            if not title.strip():
                st.error("Informe o título da ocorrência.")
            else:
                execute(
                    """INSERT INTO tickets (client_id, plant_id, opened_at, title, category, severity, status, sla_hours, notes)
                       VALUES (?, ?, ?, ?, ?, ?, 'Aberto', ?, ?)""",
                    (c_map[client_name], valid_plants.get(plant_label), datetime.now().isoformat(timespec="seconds"), title.strip(), category, severity, sla, notes),
                )
                flash("Ocorrência aberta.")
                st.rerun()

tasks_tab, tickets_tab, calendar_tab = st.tabs([
    ":material/checklist: Atividades",
    ":material/support_agent: Ocorrências",
    ":material/calendar_month: Agenda",
])

with tasks_tab:
    status_filter = st.pills("Status", ["Pendente", "Em andamento", "Atrasada", "Concluída"], default=["Pendente", "Em andamento", "Atrasada"], selection_mode="multi")
    tasks = query_df(
        """SELECT t.id, t.due_date, t.title, t.category, t.priority, t.recurrence, t.status,
                  t.assignee, t.notes, c.name AS client, COALESCE(p.name,'Geral') AS plant
           FROM tasks t JOIN clients c ON c.id=t.client_id
           LEFT JOIN plants p ON p.id=t.plant_id ORDER BY t.due_date"""
    )
    if not tasks.empty:
        today = date.today().isoformat()
        tasks.loc[(tasks["due_date"] < today) & ~tasks["status"].isin(["Concluída", "Cancelada"]), "status"] = "Atrasada"
        if status_filter:
            tasks = tasks[tasks["status"].isin(status_filter)]
        display = tasks.rename(columns={"due_date": "Prazo", "title": "Atividade", "category": "Categoria", "priority": "Prioridade", "recurrence": "Recorrência", "status": "Status", "assignee": "Responsável", "client": "Cliente", "plant": "Usina", "notes": "Observações"})
        display["Prazo"] = display["Prazo"].map(date_br)
        st.dataframe(display[["id", "Prazo", "Atividade", "Cliente", "Usina", "Categoria", "Prioridade", "Recorrência", "Status", "Responsável"]], hide_index=True, column_config={"id": st.column_config.NumberColumn("ID", width="small"), "Atividade": st.column_config.TextColumn(pinned=True)})

        open_tasks = tasks[~tasks["status"].isin(["Concluída", "Cancelada"])]
        if not open_tasks.empty:
            with st.expander("Atualizar atividade", icon=":material/edit:"):
                task_labels = {f"#{row.id} · {row.title}": int(row.id) for row in open_tasks.itertuples()}
                chosen = st.selectbox("Atividade", list(task_labels))
                new_status = st.segmented_control("Novo status", ["Pendente", "Em andamento", "Concluída", "Cancelada"], default="Em andamento")
                if st.button("Aplicar status", type="primary", icon=":material/save:"):
                    task_id = task_labels[chosen]
                    task = query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
                    completed_at = datetime.now().isoformat(timespec="seconds") if new_status == "Concluída" else None
                    execute("UPDATE tasks SET status=?, completed_at=? WHERE id=?", (new_status, completed_at, task_id))
                    if new_status == "Concluída" and task["recurrence"] != "Única":
                        days = {"Semanal": 7, "Mensal": 30, "Trimestral": 90, "Semestral": 180, "Anual": 365}[task["recurrence"]]
                        next_due = date.fromisoformat(task["due_date"]) + timedelta(days=days)
                        execute(
                            """INSERT INTO tasks (client_id, plant_id, title, category, priority, due_date, recurrence, status, assignee, notes)
                               VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?)""",
                            (task["client_id"], task["plant_id"], task["title"], task["category"], task["priority"], next_due.isoformat(), task["recurrence"], task["assignee"], task["notes"]),
                        )
                    flash("Atividade atualizada." + (" A próxima recorrência foi criada." if new_status == "Concluída" and task["recurrence"] != "Única" else ""))
                    st.rerun()
    else:
        st.success("Nenhuma atividade encontrada.", icon=":material/check_circle:")

with tickets_tab:
    tickets = query_df(
        """SELECT t.id, t.opened_at, t.title, t.category, t.severity, t.status, t.sla_hours,
                  t.resolved_at, t.root_cause, t.resolution, c.name AS client, COALESCE(p.name,'Não definida') AS plant
           FROM tickets t JOIN clients c ON c.id=t.client_id
           LEFT JOIN plants p ON p.id=t.plant_id ORDER BY CASE t.status WHEN 'Resolvido' THEN 2 ELSE 1 END, t.opened_at DESC"""
    )
    if not tickets.empty:
        now = pd.Timestamp.now()
        tickets["sla_limit"] = pd.to_datetime(tickets["opened_at"]) + pd.to_timedelta(tickets["sla_hours"], unit="h")
        tickets["sla_status"] = tickets.apply(lambda row: "Cumprido" if row["status"] == "Resolvido" else ("Estourado" if row["sla_limit"] < now else "No prazo"), axis=1)
        show = tickets.rename(columns={"opened_at": "Abertura", "title": "Ocorrência", "category": "Categoria", "severity": "Severidade", "status": "Status", "sla_hours": "SLA (h)", "client": "Cliente", "plant": "Usina", "sla_status": "Situação SLA"})
        show["Abertura"] = show["Abertura"].map(date_br)
        st.dataframe(show[["id", "Abertura", "Ocorrência", "Cliente", "Usina", "Categoria", "Severidade", "Status", "SLA (h)", "Situação SLA"]], hide_index=True, column_config={"id": st.column_config.NumberColumn("ID", width="small"), "Ocorrência": st.column_config.TextColumn(pinned=True)})

        active = tickets[tickets["status"] != "Resolvido"]
        if not active.empty:
            with st.expander("Tratar ocorrência", icon=":material/engineering:"):
                labels = {f"#{row.id} · {row.title}": int(row.id) for row in active.itertuples()}
                chosen = st.selectbox("Ocorrência", list(labels))
                status = st.selectbox("Status", ["Aberto", "Em atendimento", "Aguardando cliente", "Resolvido"])
                root_cause = st.text_area("Causa raiz")
                resolution = st.text_area("Solução aplicada / próximo passo")
                if st.button("Atualizar ocorrência", type="primary", icon=":material/save:"):
                    resolved_at = datetime.now().isoformat(timespec="seconds") if status == "Resolvido" else None
                    execute("UPDATE tickets SET status=?, root_cause=?, resolution=?, resolved_at=? WHERE id=?", (status, root_cause, resolution, resolved_at, labels[chosen]))
                    flash("Ocorrência atualizada.")
                    st.rerun()
    else:
        st.success("Nenhuma ocorrência registrada.", icon=":material/check_circle:")

with calendar_tab:
    horizon = date.today() + timedelta(days=45)
    agenda = query_df(
        """SELECT t.due_date AS Data, t.title AS Compromisso, t.category AS Categoria,
                  c.name AS Cliente, COALESCE(p.name,'Geral') AS Usina, t.assignee AS Responsável,
                  t.status AS Status
           FROM tasks t JOIN clients c ON c.id=t.client_id LEFT JOIN plants p ON p.id=t.plant_id
           WHERE date(t.due_date) BETWEEN date('now') AND date(?) AND t.status NOT IN ('Concluída','Cancelada')
           UNION ALL
           SELECT p.next_cleaning_date AS Data, 'Limpeza programada' AS Compromisso, 'Limpeza' AS Categoria,
                  c.name AS Cliente, p.name AS Usina, 'Equipe técnica' AS Responsável, 'Planejar' AS Status
           FROM plants p JOIN clients c ON c.id=p.client_id
           WHERE date(p.next_cleaning_date) BETWEEN date('now') AND date(?)
           ORDER BY Data""",
        (horizon.isoformat(), horizon.isoformat()),
    )
    st.caption("Próximos 45 dias, incluindo limpezas previstas na ficha das usinas.")
    if agenda.empty:
        st.info("Nenhum compromisso previsto no período.")
    else:
        agenda["Data"] = agenda["Data"].map(date_br)
        st.dataframe(agenda, hide_index=True, column_config={"Compromisso": st.column_config.TextColumn(pinned=True)})
        st.download_button("Exportar agenda", agenda.to_csv(index=False).encode("utf-8-sig"), "agenda_pos_venda.csv", "text/csv", icon=":material/download:")
