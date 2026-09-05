from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from solar_crm.db import query
from solar_crm.engineering import calculate_complete_project, extract_datasheet_hints, generate_roof_croqui
from solar_crm.records import create_pv_inverter, create_pv_module, create_sizing_project
from solar_crm.sizing import (
    ENERGISA_PB_MONO_230,
    ENERGISA_PB_THREE_380_220,
    circuit_current,
    energisa_pb_service_category,
    size_cable,
    size_conduit,
    size_pv_system,
    size_strings,
)
from solar_crm.ui import page_intro, render_delete_control, show_flash


NDU_001_URL = "https://www.energisa.com.br/sites/energisa/files/media/documents/2026-01/NDU%20001%20-%20Fornecimento%20de%20Energia%20El%C3%A9trica%20em%20Tens%C3%A3o%20Secund%C3%A1ria%20a%20Edifica%C3%A7%C3%B5es%20Individuais.pdf"
NDU_013_URL = "https://www.energisa.com.br/sites/energisa/files/media/documents/2026-05/NDU%20013%20-%20Crit%C3%A9rios%20para%20a%20Conex%C3%A3o%20em%20Baixa%20Tens%C3%A3o%20de%20Acessantes%20de%20Gera%C3%A7%C3%A3o%20Distribu%C3%ADda%20ao%20Sistema%20de%20Distribui%C3%A7%C3%A3o.pdf"
NORMS_URL = "https://www.energisa.com.br/normas-tecnicas"


def show_warnings(warnings: tuple[str, ...]) -> None:
    for warning in warnings:
        st.warning(warning, icon=":material/warning:")


def decimal(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_memorial() -> str:
    lines = [
        "# SolarOS — memorial de pré-dimensionamento",
        "",
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}.",
        "",
        "> Documento preliminar. Não substitui projeto elétrico, ART/TRT, análise de curto-circuito, seletividade, aterramento, SPDA nem aprovação da distribuidora.",
    ]
    system = st.session_state.get("sizing_system")
    if system:
        lines.extend([
            "", "## Sistema fotovoltaico",
            f"- Energia-alvo: {decimal(system['target_energy_kwh'], 0)} kWh/mês",
            f"- Potência necessária: {decimal(system['required_kwp'])} kWp",
            f"- Arranjo: {system['module_count']} módulos; {decimal(system['installed_kwp'])} kWp",
            f"- Inversor informado: {decimal(system['inverter_kw'])} kW; relação CC/CA {decimal(system['dc_ac_ratio'])}",
            f"- Geração estimada: {decimal(system['estimated_monthly_kwh'], 0)} kWh/mês",
        ])
    strings = st.session_state.get("sizing_strings")
    if strings:
        lines.extend([
            "", "## Arranjo CC",
            f"- Faixa calculada: {strings['min_modules_series']} a {strings['max_modules_series']} módulos/string",
            f"- Configuração avaliada: {strings['suggested_modules_series']} módulos/string; {strings['string_count']} strings",
            f"- Voc corrigida da string: {decimal(strings['cold_open_circuit_v'])} V",
            f"- Vmp quente da string: {decimal(strings['operating_vmp_v'])} V",
            f"- Corrente de projeto por MPPT: {decimal(strings['current_per_mppt_a'])} A",
        ])
    cable = st.session_state.get("sizing_cable")
    if cable:
        lines.extend([
            "", "## Circuito e proteção",
            f"- Corrente de projeto: {decimal(cable['design_current_a'])} A",
            f"- Cabo de cobre/PVC preliminar: {decimal(cable['section_mm2'], 1)} mm²",
            f"- Queda de tensão resistiva: {decimal(cable['voltage_drop_pct'])}%",
            f"- Condutor de proteção simplificado: {decimal(cable['protective_conductor_mm2'], 1)} mm²",
            f"- Disjuntor preliminar: {cable['breaker_a'] or 'fora da faixa'} A",
        ])
    conduit = st.session_state.get("sizing_conduit")
    if conduit:
        lines.extend([
            "", "## Eletroduto",
            f"- Diâmetro interno mínimo calculado: {decimal(conduit['minimum_internal_diameter_mm'])} mm",
            f"- Referência comercial: {conduit['recommended_conduit']}",
            f"- Ocupação estimada: {decimal(conduit['occupancy_pct'], 1)}%",
        ])
    service = st.session_state.get("sizing_service")
    if service:
        lines.extend([
            "", "## Padrão de entrada Energisa PB",
            f"- Fornecimento: {service['connection']}",
            f"- Categoria: {service['category']}",
            f"- Disjuntor: {service['breaker']}",
            f"- Ramal de entrada cobre/PVC: {service['entry_pvc_cu']} mm²",
            f"- Eletroduto: {service['conduit']}; caixa {service['box']}",
            "- Referência: NDU 001 v7.0, Tabela 20 (230 V) ou Tabela 18 (380/220 V).",
        ])
    lines.extend([
        "", "## Verificações obrigatórias antes da execução",
        "- Conferir dados de placa e manuais do módulo, inversor, DPS, seccionador e disjuntores.",
        "- Confirmar temperatura, agrupamento, método de instalação, curto-circuito, capacidade de interrupção e coordenação das proteções.",
        "- Validar aterramento, equipotencialização, SPDA, queda de tensão total e exigências atualizadas da Energisa.",
        "- Emitir responsabilidade técnica e submeter a documentação aplicável à distribuidora.",
    ])
    return "\n".join(lines)


page_intro("Pré-dimensione sistemas residenciais, arranjos CC, inversores, cabos, proteções, eletrodutos e o padrão de entrada da Energisa Paraíba.")
show_flash()
st.warning(
    "Ferramenta de apoio técnico. Os resultados não autorizam execução e devem ser validados por profissional habilitado, com dados de fabricante, normas ABNT aplicáveis e padrão vigente da distribuidora.",
    icon=":material/engineering:",
)

project_tab, catalog_tab, system_tab, strings_tab, circuits_tab, conduit_tab, energisa_tab, memorial_tab = st.tabs([
    ":material/architecture: Projeto completo",
    ":material/inventory_2: Equipamentos",
    ":material/solar_power: Sistema FV",
    ":material/account_tree: Strings e inversor",
    ":material/electrical_services: Cabos e disjuntores",
    ":material/cable: Eletrodutos",
    ":material/home_work: Energisa PB",
    ":material/description: Memorial",
])

with catalog_tab:
    st.subheader("Catálogo técnico", icon=":material/inventory_2:")
    st.caption("Cadastre os valores de placa e anexe o datasheet original. A leitura local do PDF é apenas uma ajuda; confirme cada valor na tabela elétrica do fabricante.")
    module_catalog, inverter_catalog = st.tabs(["Módulos", "Inversores"])
    with module_catalog:
        with st.form("new_pv_module"):
            c1, c2 = st.columns(2)
            module_manufacturer = c1.text_input("Fabricante do módulo")
            module_model = c2.text_input("Modelo do módulo")
            c1, c2, c3, c4 = st.columns(4)
            module_power = c1.number_input("Potência Pmax (Wp)", min_value=1.0, value=585.0, step=5.0)
            module_voc = c2.number_input("Voc (V)", min_value=0.1, value=52.1, step=0.1)
            module_vmp = c3.number_input("Vmp (V)", min_value=0.1, value=44.0, step=0.1)
            module_isc = c4.number_input("Isc (A)", min_value=0.1, value=14.3, step=0.1)
            c1, c2, c3, c4 = st.columns(4)
            module_imp = c1.number_input("Imp (A)", min_value=0.1, value=13.3, step=0.1)
            module_voc_coeff = c2.number_input("Coef. Voc (%/°C)", min_value=-1.0, max_value=0.0, value=-0.25, step=0.01)
            module_pmax_coeff = c3.number_input("Coef. Pmax/Vmp (%/°C)", min_value=-1.0, max_value=0.0, value=-0.35, step=0.01)
            module_fuse = c4.number_input("Fusível máximo em série (A)", min_value=1.0, value=25.0, step=1.0)
            c1, c2 = st.columns(2)
            module_width = c1.number_input("Largura (mm)", min_value=100.0, value=1134.0, step=1.0)
            module_height = c2.number_input("Altura (mm)", min_value=100.0, value=2278.0, step=1.0)
            module_datasheet = st.file_uploader("Datasheet do módulo (PDF)", type=["pdf"], key="module_datasheet")
            module_notes = st.text_area("Observações do módulo")
            save_module = st.form_submit_button("Cadastrar módulo", type="primary", icon=":material/save:")
        if module_datasheet:
            hints = extract_datasheet_hints(module_datasheet.getvalue(), "module")
            if hints:
                st.info("Valores encontrados automaticamente no PDF — confirme antes de usar: " + ", ".join(f"{key}={value}" for key, value in hints.items()))
        if save_module:
            try:
                create_pv_module({
                    "manufacturer": module_manufacturer, "model": module_model,
                    "power_wp": module_power, "voc_v": module_voc, "vmp_v": module_vmp,
                    "isc_a": module_isc, "imp_a": module_imp,
                    "temp_coeff_voc_pct": module_voc_coeff, "temp_coeff_pmax_pct": module_pmax_coeff,
                    "max_series_fuse_a": module_fuse, "width_mm": module_width,
                    "height_mm": module_height,
                    "datasheet_name": module_datasheet.name if module_datasheet else None,
                    "datasheet_mime": module_datasheet.type if module_datasheet else None,
                    "notes": module_notes,
                }, module_datasheet.getvalue() if module_datasheet else None)
                st.success("Módulo cadastrado.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível cadastrar o módulo: {exc}")

        module_rows = query("SELECT id, manufacturer, model, power_wp, voc_v, vmp_v, isc_a, imp_a, max_series_fuse_a FROM pv_modules ORDER BY manufacturer, model")
        if module_rows:
            st.dataframe(pd.DataFrame(module_rows), hide_index=True)
            module_delete_map = {
                f"{row['manufacturer'] or ''} {row['model']} · {row['power_wp']:.0f} Wp".strip(): row
                for row in module_rows
            }
            module_delete_label = st.selectbox("Módulo para administrar", list(module_delete_map), key="module_delete_selector")
            module_to_delete = module_delete_map[module_delete_label]
            render_delete_control("pv_module", module_to_delete["id"], f"módulo {module_to_delete['model']}")

    with inverter_catalog:
        with st.form("new_pv_inverter"):
            c1, c2 = st.columns(2)
            inverter_manufacturer = c1.text_input("Fabricante do inversor")
            inverter_model = c2.text_input("Modelo do inversor")
            c1, c2, c3 = st.columns(3)
            inverter_power = c1.number_input("Potência nominal CA (kW)", min_value=0.1, value=6.0, step=0.5)
            inverter_dc_power = c2.number_input("Potência CC máxima (kW)", min_value=0.1, value=9.0, step=0.5)
            inverter_dc_voltage = c3.number_input("Tensão CC máxima (V)", min_value=50.0, value=600.0, step=10.0)
            c1, c2, c3, c4 = st.columns(4)
            inverter_mppt_min = c1.number_input("MPPT mínima (V)", min_value=1.0, value=80.0, step=10.0)
            inverter_mppt_max = c2.number_input("MPPT máxima (V)", min_value=1.0, value=550.0, step=10.0)
            inverter_mppts = c3.number_input("Quantidade de MPPTs", min_value=1, value=2, step=1)
            inverter_strings_mppt = c4.number_input("Entradas por MPPT", min_value=1, value=1, step=1)
            c1, c2, c3 = st.columns(3)
            inverter_input_current = c1.number_input("Corrente máxima por MPPT (A)", min_value=0.1, value=32.0, step=1.0)
            inverter_short_current = c2.number_input("Isc máxima por MPPT (A)", min_value=0.1, value=40.0, step=1.0)
            inverter_efficiency = c3.number_input("Eficiência máxima (%)", min_value=50.0, max_value=100.0, value=98.0, step=0.1)
            c1, c2 = st.columns(2)
            inverter_phases = c1.selectbox("Sistema CA", ["Monofásico", "Trifásico"])
            inverter_ac_voltage = c2.number_input("Tensão CA (V)", min_value=12.0, value=230.0, step=1.0)
            inverter_datasheet = st.file_uploader("Datasheet do inversor (PDF)", type=["pdf"], key="inverter_datasheet")
            inverter_notes = st.text_area("Observações do inversor")
            save_inverter = st.form_submit_button("Cadastrar inversor", type="primary", icon=":material/save:")
        if inverter_datasheet:
            hints = extract_datasheet_hints(inverter_datasheet.getvalue(), "inverter")
            if hints:
                st.info("Valores encontrados automaticamente no PDF — confirme antes de usar: " + ", ".join(f"{key}={value}" for key, value in hints.items()))
        if save_inverter:
            try:
                create_pv_inverter({
                    "manufacturer": inverter_manufacturer, "model": inverter_model,
                    "nominal_power_kw": inverter_power, "max_dc_power_kw": inverter_dc_power,
                    "max_dc_voltage_v": inverter_dc_voltage, "mppt_min_v": inverter_mppt_min,
                    "mppt_max_v": inverter_mppt_max, "mppt_count": inverter_mppts,
                    "strings_per_mppt": inverter_strings_mppt,
                    "max_input_current_mppt_a": inverter_input_current,
                    "max_short_circuit_current_mppt_a": inverter_short_current,
                    "ac_voltage_v": inverter_ac_voltage, "phases": inverter_phases,
                    "efficiency_pct": inverter_efficiency,
                    "datasheet_name": inverter_datasheet.name if inverter_datasheet else None,
                    "datasheet_mime": inverter_datasheet.type if inverter_datasheet else None,
                    "notes": inverter_notes,
                }, inverter_datasheet.getvalue() if inverter_datasheet else None)
                st.success("Inversor cadastrado.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível cadastrar o inversor: {exc}")

        inverter_rows = query("SELECT id, manufacturer, model, nominal_power_kw, max_dc_voltage_v, mppt_min_v, mppt_max_v, mppt_count, strings_per_mppt, max_input_current_mppt_a FROM pv_inverters ORDER BY manufacturer, model")
        if inverter_rows:
            st.dataframe(pd.DataFrame(inverter_rows), hide_index=True)
            inverter_delete_map = {
                f"{row['manufacturer'] or ''} {row['model']} · {row['nominal_power_kw']:.1f} kW".strip(): row
                for row in inverter_rows
            }
            inverter_delete_label = st.selectbox("Inversor para administrar", list(inverter_delete_map), key="inverter_delete_selector")
            inverter_to_delete = inverter_delete_map[inverter_delete_label]
            render_delete_control("pv_inverter", inverter_to_delete["id"], f"inversor {inverter_to_delete['model']}")

with project_tab:
    modules = query("""SELECT id, manufacturer, model, power_wp, voc_v, vmp_v, isc_a, imp_a,
                              temp_coeff_voc_pct, temp_coeff_pmax_pct, max_series_fuse_a,
                              width_mm, height_mm FROM pv_modules ORDER BY manufacturer, model""")
    inverters = query("""SELECT id, manufacturer, model, nominal_power_kw, max_dc_power_kw,
                                max_dc_voltage_v, mppt_min_v, mppt_max_v, mppt_count,
                                strings_per_mppt, max_input_current_mppt_a,
                                max_short_circuit_current_mppt_a, ac_voltage_v, phases,
                                efficiency_pct FROM pv_inverters ORDER BY manufacturer, model""")
    clients = query("SELECT id, name, address, city, state FROM clients WHERE status='Ativo' ORDER BY name")
    if not modules or not inverters:
        st.info("Cadastre pelo menos um módulo e um inversor na aba Equipamentos para iniciar o projeto completo.", icon=":material/info:")
    else:
        with st.form("complete_sizing_project"):
            st.subheader("Identificação e equipamentos", icon=":material/solar_power:")
            client_map = {"Projeto sem cliente vinculado": None}
            client_map.update({row["name"]: row["id"] for row in clients})
            module_map = {f"{row['manufacturer']} {row['model']} · {row['power_wp']:.0f} Wp": row for row in modules}
            inverter_map = {f"{row['manufacturer']} {row['model']} · {row['nominal_power_kw']:.1f} kW": row for row in inverters}
            c1, c2 = st.columns(2)
            project_name = c1.text_input("Nome do projeto", placeholder="Ex.: Residência José da Silva")
            project_client = c2.selectbox("Cliente", list(client_map))
            project_address = st.text_input("Endereço da instalação")
            c1, c2 = st.columns(2)
            selected_module_label = c1.selectbox("Módulo", list(module_map))
            selected_inverter_label = c2.selectbox("Inversor", list(inverter_map))

            st.subheader("Arranjo e planta baixa", icon=":material/roofing:")
            c1, c2, c3, c4 = st.columns(4)
            project_module_count = c1.number_input("Quantidade de módulos", min_value=1, value=12, step=1)
            project_modules_string = c2.number_input("Módulos por string preferidos", min_value=1, value=6, step=1)
            layout_rows = c3.number_input("Linhas no croqui", min_value=1, value=2, step=1)
            layout_columns = c4.number_input("Colunas no croqui", min_value=1, value=6, step=1)
            c1, c2, c3, c4 = st.columns(4)
            orientation = c1.selectbox("Orientação dos módulos", ["Retrato", "Paisagem"])
            roof_type = c2.selectbox("Tipo de cobertura", ["Cerâmica", "Fibrocimento", "Metálica", "Laje", "Solo", "Outro"])
            azimuth = c3.number_input("Azimute (graus)", min_value=0.0, max_value=359.0, value=0.0, step=1.0)
            tilt = c4.number_input("Inclinação (graus)", min_value=0.0, max_value=90.0, value=15.0, step=1.0)
            roof_photo = st.file_uploader("Foto aérea, telhado ou planta para fundo do croqui", type=["png", "jpg", "jpeg"])

            st.subheader("Condições elétricas", icon=":material/electrical_services:")
            c1, c2, c3, c4 = st.columns(4)
            minimum_temperature = c1.number_input("Temperatura mínima (°C)", min_value=-20.0, max_value=40.0, value=12.0, step=1.0)
            maximum_cell_temperature = c2.number_input("Temperatura máxima da célula (°C)", min_value=25.0, max_value=90.0, value=70.0, step=1.0)
            dc_length = c3.number_input("Trecho CC unidirecional (m)", min_value=0.0, value=20.0, step=1.0)
            ac_length = c4.number_input("Trecho CA unidirecional (m)", min_value=0.0, value=15.0, step=1.0)
            c1, c2 = st.columns(2)
            drop_limit = c1.number_input("Queda máxima por trecho (%)", min_value=0.1, max_value=5.0, value=1.5, step=0.1)
            correction_factor = c2.number_input("Fator de correção combinado", min_value=0.1, max_value=1.0, value=0.8, step=0.05)
            has_spda = st.checkbox("Edificação com SPDA externo ou condição que exija DPS Tipo 1+2")
            project_notes = st.text_area("Observações do levantamento")
            calculate_complete = st.form_submit_button("Calcular projeto e gerar croqui", type="primary", icon=":material/calculate:")

        if calculate_complete:
            selected_module = module_map[selected_module_label]
            selected_inverter = inverter_map[selected_inverter_label]
            project_values = {
                "name": project_name,
                "client_id": client_map[project_client],
                "address": project_address,
                "module_id": selected_module["id"],
                "inverter_id": selected_inverter["id"],
                "module_count": project_module_count,
                "modules_per_string": project_modules_string,
                "layout_rows": layout_rows,
                "layout_columns": layout_columns,
                "module_orientation": orientation,
                "roof_type": roof_type,
                "roof_azimuth_deg": azimuth,
                "roof_tilt_deg": tilt,
                "minimum_temperature_c": minimum_temperature,
                "maximum_cell_temperature_c": maximum_cell_temperature,
                "dc_cable_length_m": dc_length,
                "ac_cable_length_m": ac_length,
                "voltage_drop_limit_pct": drop_limit,
                "correction_factor": correction_factor,
                "has_external_spda": has_spda,
                "roof_image_name": roof_photo.name if roof_photo else None,
                "roof_image_mime": roof_photo.type if roof_photo else None,
                "notes": project_notes,
                "status": "Rascunho",
            }
            try:
                complete_result = calculate_complete_project(selected_module, selected_inverter, project_values)
                croqui = generate_roof_croqui(project_values, selected_module, selected_inverter, complete_result, roof_photo.getvalue() if roof_photo else None)
                st.session_state["complete_sizing"] = {
                    "values": project_values, "module": selected_module,
                    "inverter": selected_inverter, "result": complete_result,
                    "roof_image": roof_photo.getvalue() if roof_photo else None,
                    "croqui": croqui,
                }
            except ValueError as exc:
                st.error(str(exc))

        complete = st.session_state.get("complete_sizing")
        if complete:
            result = complete["result"]
            with st.container(horizontal=True):
                st.metric("Potência instalada", f"{decimal(result['installed_kwp'], 3)} kWp", border=True)
                st.metric("Relação CC/CA", decimal(result["dc_ac_ratio"]), border=True)
                st.metric("Strings", result["string_count"], border=True)
                st.metric("Cabo CC", f"{decimal(result['dc_cable']['section_mm2'], 1)} mm²", border=True)
                st.metric("Cabo CA", f"{decimal(result['ac_cable']['section_mm2'], 1)} mm²", border=True)
                st.metric("Disjuntor CA", f"{result['ac_breaker_a'] or '-'} A", border=True)
            protection_rows = [
                {"Item": "Strings", "Dimensionamento": " | ".join(f"S{i + 1}: {value} módulos" for i, value in enumerate(result["string_lengths"]))},
                {"Item": "Faixa permitida", "Dimensionamento": f"{result['minimum_modules_series']} a {result['maximum_modules_series']} módulos por string"},
                {"Item": "Tensões críticas", "Dimensionamento": f"Voc frio {decimal(result['cold_voc_v'])} V | Vmp quente {decimal(result['hot_vmp_v'])} V"},
                {"Item": "Proteção CC", "Dimensionamento": f"Fusível gPV {result['string_fuse_a'] or '-'} A | Seccionador {result['dc_switch_a'] or '-'} A | DPS {result['dc_spd_type']} Ucpv {result['dc_spd_ucpv_v'] or '-'} V"},
                {"Item": "Saída CA", "Dimensionamento": f"Ib {decimal(result['ac_current_a'])} A | Cabo {decimal(result['ac_cable']['section_mm2'], 1)} mm² | Disjuntor {result['ac_breaker_a'] or '-'} A | DPS {result['ac_spd_type']} Uc {result['ac_spd_uc_v']} V"},
            ]
            st.dataframe(pd.DataFrame(protection_rows), hide_index=True)
            for warning in result["warnings"]:
                st.warning(warning, icon=":material/warning:")
            st.image(complete["croqui"], caption="Croqui esquemático de vista superior e divisão por strings")
            with st.container(horizontal=True):
                st.download_button("Baixar croqui em PNG", complete["croqui"], file_name="solaros-croqui-strings.png", mime="image/png", icon=":material/download:")
                if st.button("Salvar projeto", type="primary", icon=":material/save:"):
                    try:
                        project_id = create_sizing_project(complete["values"], result, complete["roof_image"])
                        st.success(f"Projeto DIM salvo com o identificador {project_id}.")
                    except ValueError as exc:
                        st.error(str(exc))

    saved_projects = query("""SELECT sp.id, sp.number, sp.name, c.name AS client_name, sp.module_count,
                                     sp.status, sp.created_at FROM sizing_projects sp
                              LEFT JOIN clients c ON c.id=sp.client_id ORDER BY sp.created_at DESC""")
    if saved_projects:
        st.subheader("Projetos salvos", icon=":material/history:")
        st.dataframe(pd.DataFrame(saved_projects), hide_index=True)
        project_delete_map = {
            f"{row['number']} · {row['name']}": row for row in saved_projects
        }
        project_delete_label = st.selectbox(
            "Projeto para administrar",
            list(project_delete_map),
            key="sizing_project_delete_selector",
        )
        project_to_delete = project_delete_map[project_delete_label]
        render_delete_control(
            "sizing_project",
            project_to_delete["id"],
            f"projeto de dimensionamento {project_to_delete['number']}",
        )

with system_tab:
    left, right = st.columns([1.05, 0.95])
    with left:
        with st.form("pv_system_form"):
            st.subheader("Demanda energética", icon=":material/energy_savings_leaf:")
            c1, c2 = st.columns(2)
            consumption = c1.number_input("Consumo médio (kWh/mês)", min_value=1.0, value=650.0, step=10.0)
            offset = c2.number_input("Compensação desejada (%)", min_value=1.0, max_value=120.0, value=95.0, step=1.0)
            psh = c1.number_input("Horas de sol pico (h/dia)", min_value=1.0, max_value=9.0, value=5.4, step=0.1, help="Use dado solarimétrico do local e da orientação do telhado.")
            performance_ratio = c2.number_input("Rendimento global PR (%)", min_value=50.0, max_value=95.0, value=80.0, step=1.0)
            st.subheader("Equipamentos e área", icon=":material/roofing:")
            c1, c2 = st.columns(2)
            module_power = c1.number_input("Potência do módulo (Wp)", min_value=100.0, value=585.0, step=5.0)
            inverter_power = c2.number_input("Potência nominal do inversor (kW)", min_value=0.5, value=6.0, step=0.5)
            module_area = c1.number_input("Área por módulo (m²)", min_value=0.5, value=2.58, step=0.01)
            calculate_system = st.form_submit_button("Calcular sistema", type="primary", icon=":material/calculate:")
    if calculate_system:
        result = size_pv_system(consumption, offset, psh, performance_ratio, module_power, inverter_power, module_area)
        st.session_state["sizing_system"] = result.__dict__
    result = st.session_state.get("sizing_system")
    with right:
        with st.container(border=True):
            st.subheader("Resultado preliminar", icon=":material/analytics:")
            if not result:
                st.info("Preencha os parâmetros e calcule para ver a recomendação.")
            else:
                st.metric("Potência fotovoltaica", f"{decimal(result['installed_kwp'])} kWp", border=True)
                c1, c2 = st.columns(2)
                c1.metric("Módulos", result["module_count"], border=True)
                c2.metric("Geração estimada", f"{decimal(result['estimated_monthly_kwh'], 0)} kWh/mês", border=True)
                c1.metric("Relação CC/CA", decimal(result["dc_ac_ratio"]), border=True)
                c2.metric("Área líquida", f"{decimal(result['roof_area_m2'], 1)} m²", border=True)
                if not 1.0 <= result["dc_ac_ratio"] <= 1.35:
                    st.warning("A relação CC/CA está fora da faixa usual de triagem de 1,00 a 1,35. Confirme o limite do fabricante e simule perdas por clipping.", icon=":material/warning:")
                st.caption("A área é apenas a soma dos módulos; acrescente recuos, corredores, obstáculos e requisitos de acesso/manutenção.")

with strings_tab:
    default_modules = int(st.session_state.get("sizing_system", {}).get("module_count", 12))
    with st.form("strings_form"):
        st.subheader("Módulo fotovoltaico", icon=":material/grid_on:")
        c1, c2, c3 = st.columns(3)
        module_count = c1.number_input("Quantidade de módulos", min_value=1, value=default_modules, step=1)
        module_voc = c2.number_input("Voc do módulo (V)", min_value=1.0, value=52.1, step=0.1)
        module_vmp = c3.number_input("Vmp do módulo (V)", min_value=1.0, value=44.0, step=0.1)
        module_isc = c1.number_input("Isc do módulo (A)", min_value=0.1, value=14.3, step=0.1)
        voc_coeff = c2.number_input("Coef. térmico Voc (%/°C)", min_value=-1.0, max_value=0.0, value=-0.25, step=0.01, format="%.2f")
        vmp_coeff = c3.number_input("Coef. térmico Vmp (%/°C)", min_value=-1.0, max_value=0.0, value=-0.29, step=0.01, format="%.2f")
        min_temp = c1.number_input("Temperatura mínima local (°C)", min_value=-20.0, max_value=40.0, value=12.0, step=1.0)
        max_cell_temp = c2.number_input("Temperatura máxima da célula (°C)", min_value=25.0, max_value=90.0, value=70.0, step=1.0)
        modules_per_string = c3.number_input("Módulos por string a avaliar", min_value=1, value=min(default_modules, 12), step=1)
        st.subheader("Inversor", icon=":material/power:")
        c1, c2, c3 = st.columns(3)
        max_dc = c1.number_input("Tensão CC máxima (V)", min_value=50.0, value=600.0, step=10.0)
        mppt_min = c2.number_input("MPPT mínima (V)", min_value=10.0, value=80.0, step=10.0)
        mppt_max = c3.number_input("MPPT máxima (V)", min_value=10.0, value=550.0, step=10.0)
        mppt_count = c1.number_input("Quantidade de MPPTs", min_value=1, value=2, step=1)
        max_current_mppt = c2.number_input("Corrente máxima por MPPT (A)", min_value=1.0, value=32.0, step=1.0)
        calculate_strings = st.form_submit_button("Validar arranjo", type="primary", icon=":material/calculate:")
    if calculate_strings:
        result = size_strings(
            module_count, module_voc, module_vmp, module_isc, voc_coeff, vmp_coeff,
            min_temp, max_cell_temp, max_dc, mppt_min, mppt_max, mppt_count,
            max_current_mppt, modules_per_string,
        )
        st.session_state["sizing_strings"] = result.__dict__
    result = st.session_state.get("sizing_strings")
    if result:
        with st.container(horizontal=True):
            st.metric("Faixa por string", f"{result['min_modules_series']}–{result['max_modules_series']} módulos", border=True)
            st.metric("Strings", result["string_count"], border=True)
            st.metric("Voc no frio", f"{decimal(result['cold_open_circuit_v'])} V", border=True)
            st.metric("Vmp no calor", f"{decimal(result['operating_vmp_v'])} V", border=True)
            st.metric("Corrente/MPPT", f"{decimal(result['current_per_mppt_a'])} A", border=True)
        if result["valid"]:
            st.success("A configuração atende aos limites informados nesta triagem.", icon=":material/check_circle:")
        show_warnings(result["warnings"])
        st.caption("A corrente inclui fator de 1,25 sobre Isc e pressupõe distribuição uniforme das strings. Confira número de entradas, fusíveis internos e corrente de curto-circuito admissível no manual do inversor.")

with circuits_tab:
    circuit_type = st.segmented_control("Circuito", ["Saída CA do inversor", "Trecho CC da string"], default="Saída CA do inversor")
    phases = st.segmented_control("Sistema elétrico", ["Monofásico", "Trifásico"], default="Monofásico") if circuit_type == "Saída CA do inversor" else "CC"
    with st.form("circuit_form"):
        c1, c2, c3 = st.columns(3)
        if circuit_type == "Saída CA do inversor":
            power_kw = c1.number_input("Potência CA (kW)", min_value=0.1, value=6.0, step=0.5)
            default_voltage = 380.0 if phases == "Trifásico" else 230.0
            voltage = c2.number_input("Tensão (V)", min_value=12.0, value=default_voltage, step=1.0, key=f"voltage_{phases}")
            power_factor = c3.number_input("Fator de potência", min_value=0.5, max_value=1.0, value=1.0, step=0.01)
            efficiency = c1.number_input("Rendimento do inversor", min_value=0.5, max_value=1.0, value=0.98, step=0.01)
            operating_current = circuit_current(power_kw, voltage, phases, power_factor, efficiency)
        else:
            voltage = c1.number_input("Tensão de operação CC (V)", min_value=12.0, value=400.0, step=10.0)
            operating_current = c2.number_input("Corrente da string (A)", min_value=0.1, value=14.0, step=0.1)
        length = c3.number_input("Comprimento unidirecional (m)", min_value=0.0, value=25.0, step=1.0)
        c1, c2, c3 = st.columns(3)
        drop_limit = c1.number_input("Queda máxima no trecho (%)", min_value=0.1, max_value=10.0, value=1.5, step=0.1)
        continuous_factor = c2.number_input("Fator de projeto da corrente", min_value=1.0, max_value=2.0, value=1.25, step=0.05)
        correction_factor = c3.number_input("Fator de correção combinado", min_value=0.1, max_value=1.0, value=0.80, step=0.05, help="Produto dos fatores de temperatura, agrupamento e outras condições aplicáveis.")
        loaded = 3 if phases == "Trifásico" else 2
        st.caption(f"Corrente operacional calculada/informada: {decimal(operating_current)} A · referência conservadora B1, cobre/PVC 70 °C, {loaded} condutores carregados.")
        calculate_cable = st.form_submit_button("Dimensionar circuito", type="primary", icon=":material/calculate:")
    if calculate_cable:
        result = size_cable(operating_current, voltage, length, phases, drop_limit, continuous_factor, correction_factor, loaded)
        st.session_state["sizing_cable"] = result.__dict__
    result = st.session_state.get("sizing_cable")
    if result:
        with st.container(horizontal=True):
            st.metric("Cabo fase/polo", f"{decimal(result['section_mm2'], 1)} mm²", border=True)
            st.metric("Disjuntor preliminar", f"{result['breaker_a']} A" if result["breaker_a"] else "Fora da faixa", border=True)
            st.metric("Queda no trecho", f"{decimal(result['voltage_drop_pct'])}%", border=True)
            st.metric("Condutor PE", f"{decimal(result['protective_conductor_mm2'], 1)} mm²", border=True)
            st.metric("Critério dominante", result["criterion"].capitalize(), border=True)
        if result["valid"]:
            st.success("O cabo atende simultaneamente à capacidade de corrente e à queda de tensão configuradas.", icon=":material/check_circle:")
        show_warnings(result["warnings"])
        st.info("O disjuntor é uma seleção preliminar pela corrente. Curva, polos, tensão, capacidade de interrupção, coordenação, DR, DPS, seccionamento CC e proteção de strings exigem análise própria.", icon=":material/info:")

with conduit_tab:
    st.caption("Informe o diâmetro externo real do cabo, disponível na ficha técnica do fabricante — a seção em mm² não é o diâmetro externo.")
    with st.form("conduit_form"):
        c1, c2, c3 = st.columns(3)
        phase_quantity = c1.number_input("Cabos fase/polos", min_value=1, value=2, step=1)
        phase_diameter = c2.number_input("Diâmetro externo fase/polo (mm)", min_value=0.1, value=6.5, step=0.1)
        pe_quantity = c1.number_input("Cabos PE", min_value=0, value=1, step=1)
        pe_diameter = c2.number_input("Diâmetro externo PE (mm)", min_value=0.1, value=5.8, step=0.1)
        fill_limit = c3.number_input("Ocupação máxima (%)", min_value=10.0, max_value=60.0, value=40.0, step=1.0)
        calculate_conduit = st.form_submit_button("Dimensionar eletroduto", type="primary", icon=":material/calculate:")
    if calculate_conduit:
        cables = [(phase_quantity, phase_diameter)]
        if pe_quantity:
            cables.append((pe_quantity, pe_diameter))
        result = size_conduit(cables, fill_limit)
        st.session_state["sizing_conduit"] = result.__dict__
    result = st.session_state.get("sizing_conduit")
    if result:
        with st.container(horizontal=True):
            st.metric("Diâmetro interno mínimo", f"{decimal(result['minimum_internal_diameter_mm'])} mm", border=True)
            st.metric("Eletroduto de referência", result["recommended_conduit"], border=True)
            st.metric("Ocupação estimada", f"{decimal(result['occupancy_pct'], 1)}%", border=True)
        st.caption("Os diâmetros internos variam por material, classe e fabricante. Confirme curvatura, quantidade de curvas, distância de puxamento, dissipação e a ocupação normativa aplicável.")

with energisa_tab:
    st.subheader("Padrão de entrada residencial — Energisa Paraíba", icon=":material/electric_meter:")
    st.caption("Referência automática: EPB em 230 V monofásico e 380/220 V trifásico. Valores transcritos da NDU 001 v7.0, novembro de 2024.")
    connection = st.segmented_control("Tipo de fornecimento", ["Monofásico 230 V", "Trifásico 380/220 V"], default="Monofásico 230 V")
    with st.form("energisa_form"):
        c1, c2 = st.columns(2)
        criterion_label = "Carga instalada (kW)" if connection.startswith("Monofásico") else "Demanda calculada (kVA)"
        service_value = c1.number_input(criterion_label, min_value=0.1, value=6.0 if connection.startswith("Monofásico") else 20.0, step=0.1, key=f"service_{connection}")
        calculate_service = st.form_submit_button("Consultar categoria", type="primary", icon=":material/search:")
    if calculate_service:
        category = energisa_pb_service_category(connection, service_value)
        if category:
            st.session_state["sizing_service"] = {**category, "connection": connection, "value": service_value}
        else:
            st.session_state.pop("sizing_service", None)
            st.error("O valor informado está fora das categorias residenciais desta tabela. É necessário estudo específico com a Energisa.", icon=":material/error:")
    result = st.session_state.get("sizing_service")
    if result:
        with st.container(border=True):
            st.subheader(f"Categoria {result['category']}", icon=":material/task_alt:")
            with st.container(horizontal=True):
                st.metric("Disjuntor do padrão", result["breaker"], border=True)
                st.metric("Ramal conexão Al", f"{result['connection_al']} mm²", border=True)
                st.metric("Entrada Cu/PVC", f"{result['entry_pvc_cu']} mm²", border=True)
                st.metric("Entrada Cu/XLPE", f"{result['entry_xlpe_cu']} mm²", border=True)
                st.metric("Eletroduto", result["conduit"], border=True)
                st.metric("Caixa", result["box"], border=True)
            st.write(f"Aterramento indicado na tabela: **{result['ground_cu']} mm²**, com haste 1H.")
    rows = ENERGISA_PB_MONO_230 if connection.startswith("Monofásico") else ENERGISA_PB_THREE_380_220
    reference_df = pd.DataFrame([
        {
            "Categoria": row["category"],
            "Faixa": f"> {decimal(row['min'], 1)} e ≤ {decimal(row['max'], 1)}",
            "Disjuntor": row["breaker"],
            "Entrada Cu/PVC": f"{row['entry_pvc_cu']} mm²",
            "Entrada Cu/XLPE": f"{row['entry_xlpe_cu']} mm²",
            "Aterramento": f"{row['ground_cu']} mm²",
            "Eletroduto": row["conduit"],
            "Caixa": row["box"],
        }
        for row in rows
    ])
    st.dataframe(reference_df, hide_index=True, column_config={"Categoria": st.column_config.TextColumn(pinned=True)})
    st.caption("¹/² As marcações remetem às notas da tabela original. Consulte a NDU para aplicação correta; a categoria não substitui o cálculo de demanda nem a vistoria da distribuidora.")

with memorial_tab:
    memorial = build_memorial()
    has_results = any(key.startswith("sizing_") for key in st.session_state)
    if not has_results:
        st.info("Calcule pelo menos uma das etapas para montar o memorial.")
    else:
        st.download_button(
            "Baixar memorial (.md)",
            memorial.encode("utf-8"),
            file_name="solaros_memorial_dimensionamento.md",
            mime="text/markdown",
            type="primary",
            icon=":material/download:",
        )
        st.markdown(memorial)

st.divider()
st.subheader("Referências técnicas", icon=":material/menu_book:")
st.markdown(
    f"- [NDU 001 v7.0 — fornecimento em baixa tensão]({NDU_001_URL})\n"
    f"- [NDU 013 v9.0 — conexão de geração distribuída em baixa tensão]({NDU_013_URL})\n"
    f"- [Biblioteca oficial de normas da Energisa]({NORMS_URL})"
)
st.caption("Antes de cada projeto, confirme se há versão mais recente, norma complementar, desenho construtivo específico e exigência local da Energisa PB.")
