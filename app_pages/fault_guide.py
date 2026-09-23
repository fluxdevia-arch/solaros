from datetime import date, timedelta

import pandas as pd
import streamlit as st

from solar_crm.db import query
from solar_crm.faults import (
    CASE_STATUSES,
    FAULT_SEVERITIES,
    KNOWN_MANUFACTURERS,
    RECHECK_RESULTS,
    create_corrective_order,
    create_fault_case,
    create_fault_entry,
    list_fault_cases,
    list_faults,
    list_rechecks,
    matching_faults,
    record_recheck,
    record_solution,
)
from solar_crm.ui import date_br, flash, page_intro, render_delete_control, show_flash, status_badge


page_intro(
    "Consulte falhas por marca, referência ou sintoma e acompanhe o ciclo completo da identificação à reverificação."
)
show_flash()

faults = list_faults()
cases = list_fault_cases()
clients = query(
    "SELECT id, name, contact_name, phone, address, city, state FROM clients WHERE status='Ativo' ORDER BY name"
)
plants = query(
    "SELECT id, client_id, name, unit_code, address, inverter FROM plants WHERE status!='Desativada' ORDER BY name"
)

with st.container(horizontal=True):
    st.metric("Falhas catalogadas", len(faults), border=True)
    st.metric("Fabricantes disponíveis", len(KNOWN_MANUFACTURERS) - 1, border=True)
    st.metric(
        "Casos em acompanhamento",
        sum(row["status"] not in {"Resolvida", "Encerrada sem solução"} for row in cases),
        border=True,
    )
    st.metric(
        "Aguardando reverificação",
        sum(row["status"] == "Aguardando reverificação" for row in cases),
        border=True,
    )

mode = st.segmented_control(
    "Área técnica",
    ["Biblioteca", "Diagnóstico guiado", "Casos e reverificação"],
    default="Biblioteca",
    key="fault_guide_mode",
)


def render_fault_detail(fault: dict, *, key_prefix: str) -> None:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader(f"{fault.get('code') or 'Sem código'} · {fault['title']}", icon=":material/troubleshoot:")
            st.markdown(status_badge(fault["severity"]))
        st.caption(
            f"{fault['manufacturer']} · {fault['symptom_category']} · "
            f"{fault.get('model_scope') or 'Confirmar aplicação no modelo'}"
        )
        st.markdown("**Sintomas**")
        st.write(fault["symptoms"])
        st.markdown("**Causas prováveis**")
        st.write(fault["probable_causes"])
        st.markdown("**Verificações recomendadas**")
        st.write(fault["verification_steps"])
        st.markdown("**Correção orientativa**")
        st.write(fault["correction_steps"])
        if fault.get("safety_notes"):
            st.warning(fault["safety_notes"], icon=":material/health_and_safety:")
        st.caption(
            fault.get("source_reference")
            or "Confirme limites, códigos e procedimentos no manual oficial do modelo antes da intervenção."
        )

    if not clients:
        st.info("Cadastre um cliente para abrir um caso técnico a partir desta falha.", icon=":material/info:")
        return
    with st.expander("Vincular a cliente e abrir caso técnico", icon=":material/add_task:"):
        client_map = {row["name"]: row for row in clients}
        client_label = st.selectbox("Cliente", list(client_map), key=f"{key_prefix}_client")
        client = client_map[client_label]
        client_plants = [row for row in plants if row["client_id"] == client["id"]]
        plant_map = {"Serviço geral do cliente": None}
        plant_map.update(
            {f"{row['name']} · {row.get('unit_code') or '-'}": row for row in client_plants}
        )
        plant_label = st.selectbox("Usina", list(plant_map), key=f"{key_prefix}_plant")
        plant = plant_map[plant_label]
        with st.form(f"{key_prefix}_new_case", clear_on_submit=True):
            observed_at = st.date_input("Data da ocorrência", value=date.today())
            symptom_notes = st.text_area(
                "O que foi observado",
                placeholder="Descreva o comportamento, horário, alarmes e condições do local.",
            )
            measurements = st.text_area(
                "Medições antes da intervenção",
                placeholder="Ex.: Vcc, Icc, tensão por fase, frequência, temperatura, potência e alarmes.",
            )
            diagnosis_notes = st.text_area("Conclusão preliminar / observações")
            if st.form_submit_button("Abrir caso técnico", type="primary", icon=":material/save:"):
                try:
                    create_fault_case(
                        {
                            "fault_id": fault["id"],
                            "client_id": client["id"],
                            "plant_id": plant["id"] if plant else None,
                            "observed_at": observed_at.isoformat(),
                            "symptom_notes": symptom_notes,
                            "measurements_before": measurements,
                            "diagnosis_notes": diagnosis_notes,
                        }
                    )
                    flash("Caso técnico aberto e incluído no acompanhamento.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


if mode == "Biblioteca":
    st.subheader("Biblioteca técnica", icon=":material/menu_book:")
    with st.container(border=True):
        search = st.text_input(
            "Buscar por código, falha, sintoma ou causa",
            placeholder="Ex.: sobretensão, isolamento, GRID-CC-01",
            key="fault_library_search",
        )
        with st.container(horizontal=True):
            manufacturer = st.selectbox(
                "Fabricante",
                ["Todos", *KNOWN_MANUFACTURERS],
                key="fault_library_manufacturer",
            )
            severity = st.pills(
                "Severidade",
                FAULT_SEVERITIES,
                selection_mode="multi",
                key="fault_library_severity",
            )
    filtered = matching_faults(
        manufacturer="" if manufacturer == "Todos" else manufacturer,
        code_or_text=search,
    )
    if severity:
        filtered = [row for row in filtered if row["severity"] in severity]
    if filtered:
        frame = pd.DataFrame(filtered)[
            ["code", "title", "manufacturer", "symptom_category", "severity", "model_scope"]
        ]
        frame.columns = ["Código", "Falha", "Fabricante", "Sintoma", "Severidade", "Aplicação"]
        st.dataframe(
            frame,
            hide_index=True,
            column_config={"Falha": st.column_config.TextColumn(pinned=True)},
        )
        fault_map = {
            f"{row.get('code') or '-'} · {row['title']} · {row['manufacturer']}": row
            for row in filtered
        }
        selected_label = st.selectbox("Abrir orientação técnica", list(fault_map), key="fault_library_selected")
        selected_fault = fault_map[selected_label]
        render_fault_detail(selected_fault, key_prefix="library_case")
        if not int(selected_fault.get("is_system") or 0):
            render_delete_control(
                "fault_catalog",
                selected_fault["id"],
                f"orientação {selected_fault.get('code') or selected_fault['title']}",
            )
    else:
        st.info("Nenhuma orientação encontrada para estes filtros.", icon=":material/search_off:")

    with st.expander("Adicionar orientação verificada", icon=":material/library_add:"):
        st.caption(
            "Use esta área para cadastrar códigos oficiais conferidos no manual do fabricante. "
            "Informe a fonte e o modelo a que a orientação se aplica."
        )
        with st.form("new_fault_entry", clear_on_submit=True):
            manufacturer_new = st.selectbox(
                "Fabricante",
                KNOWN_MANUFACTURERS,
                accept_new_options=True,
                key="new_fault_manufacturer",
            )
            code_new = st.text_input("Código / referência")
            model_scope_new = st.text_input("Modelos ou família aplicável")
            title_new = st.text_input("Nome da falha")
            symptom_category_new = st.text_input("Categoria do sintoma", placeholder="Ex.: Rede elétrica")
            severity_new = st.selectbox("Severidade", FAULT_SEVERITIES, index=2)
            symptoms_new = st.text_area("Sintomas")
            causes_new = st.text_area("Causas prováveis")
            verification_new = st.text_area("Passos de verificação")
            correction_new = st.text_area("Passos de correção")
            safety_new = st.text_area("Alertas de segurança")
            source_new = st.text_input("Fonte técnica", placeholder="Manual, versão e página")
            if st.form_submit_button("Salvar na biblioteca", type="primary", icon=":material/save:"):
                try:
                    create_fault_entry(
                        {
                            "manufacturer": manufacturer_new,
                            "code": code_new,
                            "model_scope": model_scope_new,
                            "title": title_new,
                            "symptom_category": symptom_category_new,
                            "severity": severity_new,
                            "symptoms": symptoms_new,
                            "probable_causes": causes_new,
                            "verification_steps": verification_new,
                            "correction_steps": correction_new,
                            "safety_notes": safety_new,
                            "source_reference": source_new,
                        }
                    )
                    flash("Orientação adicionada à biblioteca técnica.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

elif mode == "Diagnóstico guiado":
    st.subheader("Diagnóstico guiado", icon=":material/account_tree:")
    st.caption(
        "A triagem organiza hipóteses e verificações. Ela não substitui manual, medições, normas aplicáveis ou responsável técnico."
    )
    symptom_categories = sorted({row["symptom_category"] for row in faults})
    with st.form("guided_fault_search"):
        manufacturer = st.selectbox(
            "Fabricante do inversor",
            [item for item in KNOWN_MANUFACTURERS if item != "Multimarcas"],
            key="guided_manufacturer",
        )
        has_code = st.segmented_control(
            "Você possui um código ou mensagem de alarme?",
            ["Não", "Sim"],
            default="Não",
            key="guided_has_code",
        )
        code_text = st.text_input(
            "Código ou mensagem",
            disabled=has_code != "Sim",
            placeholder="Digite exatamente como aparece no equipamento",
        )
        symptom = st.selectbox("Sintoma principal", symptom_categories, key="guided_symptom")
        submitted = st.form_submit_button("Analisar possibilidades", type="primary", icon=":material/search:")
    if submitted:
        st.session_state["guided_fault_result"] = [
            row["id"]
            for row in matching_faults(
                manufacturer=manufacturer,
                symptom_category=symptom,
                code_or_text=code_text if has_code == "Sim" else "",
            )
        ]
    result_ids = st.session_state.get("guided_fault_result", [])
    guided = [row for row in faults if row["id"] in result_ids]
    if submitted and not guided:
        st.warning(
            "O código informado ainda não está na biblioteca. Tente sem o código ou cadastre uma orientação oficial verificada.",
            icon=":material/warning:",
        )
    elif guided:
        st.success(f"{len(guided)} hipótese(s) técnica(s) encontrada(s).", icon=":material/check_circle:")
        guided_map = {f"{row['severity']} · {row.get('code') or '-'} · {row['title']}": row for row in guided}
        guided_label = st.selectbox("Hipótese para detalhar", list(guided_map), key="guided_selected_fault")
        render_fault_detail(guided_map[guided_label], key_prefix="guided_case")

else:
    st.subheader("Casos técnicos e reverificação", icon=":material/fact_check:")
    if not cases:
        st.info("Nenhum caso técnico aberto a partir da biblioteca.", icon=":material/info:")
    else:
        status_filter = st.pills(
            "Status",
            CASE_STATUSES,
            default=["Identificada", "Em correção", "Aguardando reverificação"],
            selection_mode="multi",
            key="fault_case_status_filter",
        )
        filtered_cases = [row for row in cases if not status_filter or row["status"] in status_filter]
        if filtered_cases:
            frame = pd.DataFrame(filtered_cases)[
                ["observed_at", "fault_title", "client_name", "plant_name", "severity", "status", "service_order_number"]
            ]
            frame.columns = ["Data", "Falha", "Cliente", "Usina", "Severidade", "Status", "O.S."]
            frame["Data"] = frame["Data"].map(date_br)
            st.dataframe(frame, hide_index=True, column_config={"Falha": st.column_config.TextColumn(pinned=True)})
            case_map = {
                f"Caso #{row['id']} · {row['client_name']} · {row['fault_title']}": row
                for row in filtered_cases
            }
            selected_case_label = st.selectbox("Abrir caso", list(case_map), key="fault_case_selected")
            selected = case_map[selected_case_label]
            with st.container(border=True):
                with st.container(horizontal=True):
                    st.metric("Status", selected["status"], border=True)
                    st.metric("Severidade", selected["severity"], border=True)
                    st.metric("O.S. vinculada", selected.get("service_order_number") or "Não emitida", border=True)
                st.markdown(f"**Falha:** {selected.get('code') or '-'} · {selected['fault_title']}")
                st.markdown(f"**Cliente / usina:** {selected['client_name']} · {selected['plant_name']}")
                st.markdown(f"**Observado:** {selected.get('symptom_notes') or 'Sem descrição.'}")
                st.markdown(f"**Medições iniciais:** {selected.get('measurements_before') or 'Não registradas.'}")
                if selected.get("solution_applied"):
                    st.markdown(f"**Solução aplicada:** {selected['solution_applied']}")
                    st.markdown(f"**Peças substituídas:** {selected.get('parts_replaced') or 'Nenhuma informada.'}")

            if not selected.get("service_order_id") and selected["status"] not in {"Resolvida", "Encerrada sem solução"}:
                with st.expander("Gerar O.S. corretiva", icon=":material/assignment_add:"):
                    with st.form("fault_case_create_os"):
                        scheduled = st.date_input("Agendamento", value=date.today() + timedelta(days=1))
                        assignee = st.text_input("Equipe / responsável")
                        if st.form_submit_button("Emitir O.S. corretiva", type="primary", icon=":material/save:"):
                            try:
                                create_corrective_order(
                                    selected["id"],
                                    scheduled_date=scheduled.isoformat(),
                                    assignee=assignee,
                                )
                                flash("O.S. corretiva criada e vinculada ao caso.")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

            if selected["status"] not in {"Resolvida", "Encerrada sem solução"}:
                with st.expander("Registrar solução aplicada", icon=":material/handyman:"):
                    with st.form("fault_case_solution"):
                        solution = st.text_area(
                            "O que resolveu ou foi corrigido",
                            value=selected.get("solution_applied") or "",
                        )
                        parts = st.text_area(
                            "Peças substituídas, números de série e materiais",
                            value=selected.get("parts_replaced") or "",
                        )
                        if st.form_submit_button("Salvar e aguardar reverificação", type="primary", icon=":material/save:"):
                            try:
                                record_solution(selected["id"], solution, parts)
                                flash("Solução registrada. O caso agora aguarda reverificação.")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

            if selected["status"] in {"Em correção", "Aguardando reverificação"}:
                with st.expander("Reverificar resultado", icon=":material/verified:"):
                    with st.form("fault_case_recheck"):
                        checked_at = st.date_input("Data da reverificação", value=date.today())
                        technician = st.text_input("Técnico responsável")
                        measurements_after = st.text_area(
                            "Medições após a correção",
                            placeholder="Registre os mesmos indicadores usados antes da intervenção.",
                        )
                        result = st.segmented_control("Resultado", RECHECK_RESULTS, default="Resolvida")
                        notes = st.text_area("Observações da reverificação")
                        if st.form_submit_button("Registrar reverificação", type="primary", icon=":material/save:"):
                            try:
                                record_recheck(
                                    selected["id"],
                                    checked_at=checked_at.isoformat(),
                                    technician=technician,
                                    measurements_after=measurements_after,
                                    result=result,
                                    notes=notes,
                                )
                                flash("Reverificação registrada e status atualizado.")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

            rechecks = list_rechecks(selected["id"])
            if rechecks:
                st.subheader("Histórico de reverificações", icon=":material/history:")
                recheck_frame = pd.DataFrame(rechecks)[
                    ["checked_at", "technician", "measurements_after", "result", "notes"]
                ]
                recheck_frame.columns = ["Data", "Técnico", "Medições", "Resultado", "Observações"]
                recheck_frame["Data"] = recheck_frame["Data"].map(date_br)
                st.dataframe(recheck_frame, hide_index=True)
            render_delete_control(
                "fault_case",
                selected["id"],
                f"caso técnico #{selected['id']}",
            )
        else:
            st.info("Nenhum caso encontrado para os status selecionados.", icon=":material/filter_alt_off:")
