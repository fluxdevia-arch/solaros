from __future__ import annotations


BASIC_INSPECTION_CHECKLIST = [
    ("Segurança e acesso", "Acesso ao local e à cobertura", False),
    ("Segurança e acesso", "Condições para trabalho em altura", False),
    ("Segurança e acesso", "Sinalização, bloqueio e uso de EPI/EPC", False),
    ("Módulos e cobertura", "Integridade visual dos módulos", True),
    ("Módulos e cobertura", "Sujeira, manchas, trincas ou pontos quentes visíveis", True),
    ("Módulos e cobertura", "Fixação, grampos e estrutura", True),
    ("Módulos e cobertura", "Telhado, vedação e sinais de infiltração", True),
    ("Circuito CC", "Cabos solares, conectores e organização", True),
    ("Circuito CC", "Tensão e corrente das strings", False),
    ("Circuito CC", "Seccionamento, fusíveis e DPS CC", True),
    ("Inversor e circuito CA", "Estado, ventilação e alarmes do inversor", True),
    ("Inversor e circuito CA", "Cabos, conexões e aquecimento no circuito CA", True),
    ("Inversor e circuito CA", "Disjuntor, seccionamento e DPS CA", True),
    ("Aterramento e identificação", "Condutor de proteção e equipotencialização", True),
    ("Aterramento e identificação", "SPDA, aterramento e integridade das conexões", True),
    ("Aterramento e identificação", "Etiquetas, avisos e identificação dos circuitos", True),
    ("Monitoramento e desempenho", "Datalogger, comunicação e portal de monitoramento", False),
    ("Monitoramento e desempenho", "Geração instantânea e comparação com o esperado", False),
]


PREVENTIVE_71_CHECKLIST = [
    # 1. Segurança e documentação — 6
    ("1. Segurança e documentação", "APR, permissões e escopo da atividade disponíveis", False),
    ("1. Segurança e documentação", "Equipe identificada, autorizada e com treinamentos aplicáveis", False),
    ("1. Segurança e documentação", "EPI e EPC adequados, inspecionados e dentro da validade", False),
    ("1. Segurança e documentação", "Procedimento de bloqueio, etiquetagem e ausência de tensão definido", False),
    ("1. Segurança e documentação", "Diagramas, manuais, projeto e registros anteriores disponíveis", False),
    ("1. Segurança e documentação", "Sinalização de emergência, riscos e contatos acessíveis", True),
    # 2. Acesso e ambiente — 5 (11)
    ("2. Acesso e ambiente", "Acesso ao local, cobertura e equipamentos em condição segura", True),
    ("2. Acesso e ambiente", "Pontos de ancoragem, linha de vida e proteção contra queda adequados", True),
    ("2. Acesso e ambiente", "Ausência de obstruções, vegetação, materiais combustíveis e animais", True),
    ("2. Acesso e ambiente", "Drenagem, ventilação e condições ambientais preservadas", True),
    ("2. Acesso e ambiente", "Portas, cercas, cadeados e controle de acesso íntegros", True),
    # 3. Módulos fotovoltaicos — 6 (17)
    ("3. Módulos fotovoltaicos", "Vidros sem trincas, quebras, delaminação ou descoloração anormal", True),
    ("3. Módulos fotovoltaicos", "Molduras, backsheets e caixas de junção sem danos", True),
    ("3. Módulos fotovoltaicos", "Ausência de hotspots, diodos anormais ou aquecimento localizado", True),
    ("3. Módulos fotovoltaicos", "Módulos sem sujeira crítica, sombreamento novo ou dejetos", True),
    ("3. Módulos fotovoltaicos", "Etiquetas e números de série legíveis quando acessíveis", False),
    ("3. Módulos fotovoltaicos", "Potência, modelo e quantidade compatíveis com o cadastro técnico", False),
    # 4. Estrutura e cobertura — 5 (22)
    ("4. Estrutura e cobertura", "Perfis, suportes e fixadores sem deformação ou corrosão crítica", True),
    ("4. Estrutura e cobertura", "Grampos posicionados e apertados conforme orientação do fabricante", True),
    ("4. Estrutura e cobertura", "Aterramento e continuidade das estruturas metálicas preservados", True),
    ("4. Estrutura e cobertura", "Telhado, impermeabilização e pontos de fixação sem infiltração", True),
    ("4. Estrutura e cobertura", "Afastamentos, circulação e dilatação estrutural preservados", True),
    # 5. Cabeamento CC — 6 (28)
    ("5. Cabeamento CC", "Cabos CC sem cortes, esmagamento, abrasão ou exposição inadequada", True),
    ("5. Cabeamento CC", "Cabos protegidos contra bordas, calor, UV, água e esforço mecânico", True),
    ("5. Cabeamento CC", "Roteamento, amarração e raio de curvatura adequados", True),
    ("5. Cabeamento CC", "Polaridade e identificação positiva/negativa coerentes", False),
    ("5. Cabeamento CC", "Seção dos condutores compatível com projeto e corrente", False),
    ("5. Cabeamento CC", "Ausência de cabos soltos sobre cobertura, solo ou superfícies cortantes", True),
    # 6. Conectores e caixas CC — 5 (33)
    ("6. Conectores e caixas CC", "Conectores de mesmo fabricante/tipo e corretamente acoplados", True),
    ("6. Conectores e caixas CC", "Conectores sem aquecimento, carbonização, trincas ou umidade", True),
    ("6. Conectores e caixas CC", "Crimpagens, prensa-cabos e vedações em condição adequada", True),
    ("6. Conectores e caixas CC", "Caixas de passagem limpas, secas e com grau de proteção preservado", True),
    ("6. Conectores e caixas CC", "Entradas não utilizadas corretamente vedadas", True),
    # 7. String box e proteções CC — 5 (38)
    ("7. String box e proteções CC", "Invólucro, tampa, vedação e identificação da string box íntegros", True),
    ("7. String box e proteções CC", "Fusíveis gPV e porta-fusíveis sem aquecimento ou atuação indevida", True),
    ("7. String box e proteções CC", "DPS CC com indicador normal e coordenação compatível", True),
    ("7. String box e proteções CC", "Seccionadora CC opera e apresenta especificação adequada", True),
    ("7. String box e proteções CC", "Bornes e conexões CC sem folga, oxidação ou aquecimento", True),
    # 8. Inversor — 6 (44)
    ("8. Inversor", "Invólucro, fixação, vedação e identificação do inversor íntegros", True),
    ("8. Inversor", "Afastamentos, ventilação, dissipadores e ventiladores desobstruídos", True),
    ("8. Inversor", "Display, LEDs, alarmes e histórico de eventos conferidos", False),
    ("8. Inversor", "Entradas CC, terminais CA e comunicação sem aquecimento ou dano", True),
    ("8. Inversor", "Parâmetros de país, rede, potência e controle compatíveis", False),
    ("8. Inversor", "Firmware e relógio avaliados conforme orientação do fabricante", False),
    # 9. Circuito CA e quadro — 5 (49)
    ("9. Circuito CA e quadro", "Quadro CA identificado, fechado e sem entrada de água ou poeira", True),
    ("9. Circuito CA e quadro", "Disjuntores e seccionamento CA compatíveis e sem aquecimento", True),
    ("9. Circuito CA e quadro", "DPS CA com indicador normal e coordenação compatível", True),
    ("9. Circuito CA e quadro", "Cabos, terminais, barramentos e torque visualmente adequados", True),
    ("9. Circuito CA e quadro", "Balanceamento de fases e sequência avaliados quando aplicável", False),
    # 10. Aterramento e SPDA — 5 (54)
    ("10. Aterramento e SPDA", "Condutor de proteção presente, identificado e protegido", True),
    ("10. Aterramento e SPDA", "Equipotencialização de módulos, estruturas, quadros e inversores", True),
    ("10. Aterramento e SPDA", "Conexões de aterramento sem corrosão, ruptura ou afrouxamento", True),
    ("10. Aterramento e SPDA", "Integração e afastamentos do SPDA avaliados conforme projeto", True),
    ("10. Aterramento e SPDA", "Medição de continuidade e/ou resistência registrada quando aplicável", False),
    # 11. Medição e monitoramento — 4 (58)
    ("11. Medição e monitoramento", "Medidor, TCs e sentidos de corrente coerentes com o sistema", True),
    ("11. Medição e monitoramento", "Datalogger, gateway, antena e alimentação operacionais", True),
    ("11. Medição e monitoramento", "Portal recebe dados atuais de todos os inversores/dispositivos", False),
    ("11. Medição e monitoramento", "Alarmes, usuários, notificações e fuso horário conferidos", False),
    # 12. Ensaios elétricos — 5 (63)
    ("12. Ensaios elétricos", "Tensão de circuito aberto por string registrada e comparada", False),
    ("12. Ensaios elétricos", "Corrente por string/MPPT registrada e comparada", False),
    ("12. Ensaios elétricos", "Resistência de isolamento medida quando tecnicamente aplicável", False),
    ("12. Ensaios elétricos", "Tensões, correntes e frequência CA registradas por fase", False),
    ("12. Ensaios elétricos", "Termografia executada em conexões e componentes sob carga", True),
    # 13. Desempenho e operação — 4 (67)
    ("13. Desempenho e operação", "Potência instantânea e curva diária compatíveis com as condições", False),
    ("13. Desempenho e operação", "MPPTs e strings equivalentes sem desequilíbrio relevante", False),
    ("13. Desempenho e operação", "Geração do período comparada com histórico e expectativa", False),
    ("13. Desempenho e operação", "Disponibilidade, perdas e eventos relevantes documentados", False),
    # 14. Limpeza e encerramento — 4 (71)
    ("14. Limpeza e encerramento", "Necessidade e método de limpeza dos módulos avaliados", True),
    ("14. Limpeza e encerramento", "Resíduos, peças retiradas e materiais recolhidos do local", True),
    ("14. Limpeza e encerramento", "Sistema restabelecido, alarmes encerrados e geração confirmada", False),
    ("14. Limpeza e encerramento", "Cliente informado sobre achados, riscos, pendências e retorno", False),
]


assert len(PREVENTIVE_71_CHECKLIST) == 71

