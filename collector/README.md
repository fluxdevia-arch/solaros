# SolarOS Collector · PHB85K-MT

Programa local, somente leitura, para coletar as 16 strings do inversor PHB85K-MT por RS485/Modbus RTU e gravar a telemetria no Supabase usado pelo SolarOS.

## O que já funciona

- valida o perfil de 4 MPPTs e 16 strings;
- abre a porta RS485 por meio de um conversor USB–RS485;
- lê apenas Input Registers ou Holding Registers, sem comandos de escrita;
- decodifica `uint16`, `int16`, `uint32`, `int32` e `float32`;
- calcula a potência da string quando o mapa fornecer corrente e tensão;
- grava amostras e alarmes no Supabase;
- mantém uma fila SQLite local se a internet ficar indisponível;
- oferece simulação sem inversor e teste sem gravar dados.

## Instalação

Instale Python 3.11 ou superior no computador que ficará na usina. Na pasta do projeto, execute:

```powershell
python -m venv .venv-coletor
.\.venv-coletor\Scripts\python.exe -m pip install -r collector\requirements.txt
```

No Linux/Raspberry Pi, troque o executável por `.venv-coletor/bin/python`.

## Configuração

1. No SolarOS, abra **Análise de equipamentos → Fontes de API**.
2. Cadastre `PHB PHB85K-MT · RS485/Modbus RTU`.
3. Em **Instalar coletor PHB**, baixe a configuração vinculada à usina.
4. No JSON, substitua a porta serial e preencha `baudrate`, `parity`, `stop_bits`, endereços e escalas usando exclusivamente o mapa oficial da PHB.
5. Defina `SOLAROS_DATABASE_URL` somente como variável de ambiente no computador coletor. Não grave essa senha no JSON.

Teste sem inversor e sem Supabase:

```powershell
.\.venv-coletor\Scripts\python.exe -m collector.solaros_collector --config .\phb85k-mt-048-coletor.json --simulate --dry-run --once
```

Teste uma leitura real sem gravar:

```powershell
.\.venv-coletor\Scripts\python.exe -m collector.solaros_collector --config .\phb85k-mt-048-coletor.json --dry-run --once
```

Inicie a coleta contínua:

```powershell
.\.venv-coletor\Scripts\python.exe -m collector.solaros_collector --config .\phb85k-mt-048-coletor.json
```

## Pendência de comissionamento

O manual público do PHB85K-MT confirma RS485/Modbus RTU, mas não publica a tabela de registradores, escalas, baud rate, paridade e stop bits. O programa recusa a leitura real enquanto esses campos estiverem vazios. Solicite à PHB o **mapa oficial de registradores Modbus RTU do PHB85K-MT**.
