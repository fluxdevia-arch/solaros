from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


LOGGER = logging.getLogger("solaros.collector")
SUPPORTED_DATA_TYPES = {"uint16", "int16", "uint32", "int32", "float32"}


class CollectorError(RuntimeError):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError(f"Não foi possível ler a configuração: {exc}") from exc
    if not isinstance(config, dict):
        raise CollectorError("A configuração precisa ser um objeto JSON.")
    return config


def validate_config(config: dict[str, Any], *, require_registers: bool = True) -> None:
    if config.get("collector_mode") != "read_only":
        raise CollectorError("O coletor aceita somente collector_mode=read_only.")
    if config.get("transport") != "modbus_rtu":
        raise CollectorError("O PHB85K-MT deve usar transport=modbus_rtu.")
    integration_id = config.get("integration_id")
    if not isinstance(integration_id, int) or integration_id <= 0:
        raise CollectorError("Baixe no SolarOS a configuração vinculada à usina.")
    address = config.get("modbus_address")
    if not isinstance(address, int) or not 1 <= address <= 247:
        raise CollectorError("O endereço Modbus precisa ficar entre 1 e 247.")
    strings = config.get("registers", {}).get("strings", [])
    if len(strings) != 16:
        raise CollectorError("O perfil PHB85K-MT deve conter as 16 strings.")
    if not require_registers:
        return
    for item in strings:
        for measurement in ("current_a", "voltage_v"):
            spec = item.get(measurement)
            if not isinstance(spec, dict) or spec.get("address") is None or spec.get("scale") is None:
                raise CollectorError(
                    "O mapa oficial PHB ainda não foi preenchido: "
                    f"{item.get('string_name', '?')}.{measurement}."
                )
            if spec.get("data_type") not in SUPPORTED_DATA_TYPES:
                raise CollectorError(f"Tipo de registrador inválido em {item.get('string_name', '?')}.")


def decode_registers(
    registers: list[int],
    *,
    data_type: str,
    scale: float,
    word_order: str = "big",
) -> float:
    if data_type not in SUPPORTED_DATA_TYPES:
        raise CollectorError(f"Tipo de dado não suportado: {data_type}.")
    expected = 1 if data_type.endswith("16") else 2
    if len(registers) != expected:
        raise CollectorError(f"{data_type} requer {expected} registrador(es).")
    words = list(registers if word_order == "big" else reversed(registers))
    raw = b"".join(int(word).to_bytes(2, "big", signed=False) for word in words)
    formats = {
        "uint16": ">H",
        "int16": ">h",
        "uint32": ">I",
        "int32": ">i",
        "float32": ">f",
    }
    return float(struct.unpack(formats[data_type], raw)[0]) * float(scale)


class ModbusReader:
    """Read-only Modbus RTU adapter. No write method is intentionally exposed."""

    def __init__(self, config: dict[str, Any]):
        try:
            from pymodbus.client import ModbusSerialClient
        except ImportError as exc:
            raise CollectorError(
                "PyModbus não está instalado. Execute: pip install -r collector/requirements.txt"
            ) from exc
        self.device_id = int(config["modbus_address"])
        self.client = ModbusSerialClient(
            port=str(config["serial_port"]),
            baudrate=int(config["baudrate"]),
            parity=str(config["parity"]),
            stopbits=float(config["stop_bits"]),
            bytesize=int(config.get("byte_size", 8)),
            timeout=float(config.get("timeout_seconds", 3)),
        )

    def __enter__(self) -> "ModbusReader":
        if not self.client.connect():
            raise CollectorError("Não foi possível abrir a porta RS485 configurada.")
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def read(self, spec: dict[str, Any]) -> float:
        data_type = str(spec["data_type"])
        count = 1 if data_type.endswith("16") else 2
        method = (
            self.client.read_holding_registers
            if spec.get("table", "input") == "holding"
            else self.client.read_input_registers
        )
        kwargs = {"address": int(spec["address"]), "count": count}
        try:
            response = method(**kwargs, device_id=self.device_id)
        except TypeError:
            response = method(**kwargs, slave=self.device_id)
        if response.isError():
            raise CollectorError(f"Falha ao ler o registrador {spec['address']}: {response}")
        return decode_registers(
            list(response.registers),
            data_type=data_type,
            scale=float(spec["scale"]),
            word_order=str(spec.get("word_order", "big")),
        )


def collect_snapshot(
    config: dict[str, Any],
    read_register: Callable[[dict[str, Any]], float],
    *,
    sample_at: str | None = None,
) -> dict[str, Any]:
    timestamp = sample_at or datetime.now().astimezone().isoformat(timespec="seconds")
    samples: list[dict[str, Any]] = []
    for item in config["registers"]["strings"]:
        current = read_register(item["current_a"])
        voltage = read_register(item["voltage_v"])
        power_spec = item.get("power_kw")
        power = read_register(power_spec) if power_spec else current * voltage / 1000
        samples.append(
            {
                "sample_at": timestamp,
                "inverter_name": str(config.get("device_name") or config["model"]),
                "mppt": str(item["mppt"]),
                "string_name": str(item["string_name"]),
                "current_a": round(current, 4),
                "voltage_v": round(voltage, 3),
                "power_kw": round(power, 5),
                "source": "PHB Modbus RTU",
            }
        )
    alarms: list[dict[str, Any]] = []
    for index, item in enumerate(config["registers"].get("alarms", [])):
        value = read_register(item["register"])
        if value == float(item.get("active_when", 1)):
            alarms.append(
                {
                    "external_id": f"{item.get('code', index)}-{timestamp[:16]}",
                    "occurred_at": timestamp,
                    "code": str(item.get("code") or index),
                    "severity": str(item.get("severity") or "Atenção"),
                    "title": str(item.get("title") or "Alarme PHB"),
                    "message": str(item.get("message") or ""),
                    "status": "Aberto",
                }
            )
    return {
        "integration_id": int(config["integration_id"]),
        "samples": samples,
        "alarms": alarms,
    }


def simulated_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    simulated = dict(config)
    simulated["registers"] = dict(config["registers"])
    simulated["registers"]["strings"] = []
    values: dict[int, float] = {}
    address = 1000
    for index in range(16):
        current = 8.1 + ((index % 4) - 1.5) * 0.04
        voltage = 560 + (index // 4) * 2
        values[address] = current
        values[address + 1] = voltage
        simulated["registers"]["strings"].append(
            {
                "string_name": f"S{index + 1}",
                "mppt": f"MPPT {(index // 4) + 1}",
                "current_a": {"address": address},
                "voltage_v": {"address": address + 1},
            }
        )
        address += 2
    simulated["registers"]["alarms"] = []
    return collect_snapshot(simulated, lambda spec: values[int(spec["address"])])


class OfflineQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS pending_payloads (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   payload TEXT NOT NULL,
                   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def add(self, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO pending_payloads (payload) VALUES (?)",
            (json.dumps(payload, ensure_ascii=False),),
        )
        self.connection.commit()

    def pending(self) -> list[tuple[int, dict[str, Any]]]:
        rows = self.connection.execute("SELECT id, payload FROM pending_payloads ORDER BY id").fetchall()
        return [(int(row[0]), json.loads(row[1])) for row in rows]

    def remove(self, row_id: int) -> None:
        self.connection.execute("DELETE FROM pending_payloads WHERE id=?", (int(row_id),))
        self.connection.commit()


@dataclass
class DatabasePublisher:
    database_url: str

    def publish(self, payload: dict[str, Any]) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise CollectorError(
                "Psycopg não está instalado. Execute: pip install -r collector/requirements.txt"
            ) from exc
        integration_id = int(payload["integration_id"])
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO equipment_string_samples
                       (integration_id, sample_at, inverter_name, mppt, string_name,
                        current_a, voltage_v, power_kw, source)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT(integration_id, sample_at, inverter_name, mppt, string_name)
                       DO UPDATE SET current_a=excluded.current_a,
                                     voltage_v=excluded.voltage_v,
                                     power_kw=excluded.power_kw,
                                     source=excluded.source""",
                    [
                        (
                            integration_id,
                            row["sample_at"],
                            row["inverter_name"],
                            row["mppt"],
                            row["string_name"],
                            row["current_a"],
                            row["voltage_v"],
                            row["power_kw"],
                            row["source"],
                        )
                        for row in payload["samples"]
                    ],
                )
                cursor.executemany(
                    """INSERT INTO equipment_alarms
                       (integration_id, external_id, occurred_at, code, severity, title, message, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT(integration_id, external_id)
                       DO UPDATE SET occurred_at=excluded.occurred_at,
                                     severity=excluded.severity,
                                     title=excluded.title,
                                     message=excluded.message,
                                     status=excluded.status""",
                    [
                        (
                            integration_id,
                            row["external_id"],
                            row["occurred_at"],
                            row["code"],
                            row["severity"],
                            row["title"],
                            row["message"],
                            row["status"],
                        )
                        for row in payload["alarms"]
                    ],
                )
                cursor.execute(
                    """UPDATE equipment_integrations
                       SET status='Conectada', last_sync_at=%s,
                           last_sync_status='Sucesso', last_error=NULL
                       WHERE id=%s""",
                    (datetime.now().astimezone().isoformat(timespec="seconds"), integration_id),
                )


def publish_with_queue(
    payload: dict[str, Any],
    publisher: DatabasePublisher,
    queue: OfflineQueue,
) -> None:
    for row_id, pending_payload in queue.pending():
        publisher.publish(pending_payload)
        queue.remove(row_id)
    try:
        publisher.publish(payload)
    except Exception:
        queue.add(payload)
        raise


def _database_url(config: dict[str, Any]) -> str:
    variable = str(config.get("database_url_env") or "SOLAROS_DATABASE_URL")
    value = os.environ.get(variable, "").strip()
    if not value:
        raise CollectorError(f"Defina a variável de ambiente {variable} com a conexão do Supabase.")
    return value


def run_once(config: dict[str, Any], *, simulate: bool, dry_run: bool) -> dict[str, Any]:
    validate_config(config, require_registers=not simulate)
    if simulate:
        payload = simulated_snapshot(config)
    else:
        with ModbusReader(config) as reader:
            payload = collect_snapshot(config, reader.read)
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    queue = OfflineQueue(config.get("offline_queue") or "solaros-collector-queue.db")
    try:
        publish_with_queue(payload, DatabasePublisher(_database_url(config)), queue)
    finally:
        queue.close()
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coletor RS485/Modbus RTU do SolarOS")
    parser.add_argument("--config", required=True, help="Arquivo JSON baixado no SolarOS")
    parser.add_argument("--once", action="store_true", help="Executa uma coleta e encerra")
    parser.add_argument("--simulate", action="store_true", help="Gera 16 strings sem acessar a porta serial")
    parser.add_argument("--dry-run", action="store_true", help="Exibe os dados sem gravar no Supabase")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(args.config)
        while True:
            try:
                payload = run_once(config, simulate=args.simulate, dry_run=args.dry_run)
                LOGGER.info("Coleta concluída: %s strings, %s alarmes", len(payload["samples"]), len(payload["alarms"]))
            except Exception as exc:
                LOGGER.error("Coleta não concluída: %s", exc)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(max(int(config.get("poll_interval_seconds", 60)), 10))
    except (CollectorError, KeyboardInterrupt) as exc:
        if isinstance(exc, CollectorError):
            LOGGER.error("%s", exc)
            return 1
        LOGGER.info("Coletor encerrado.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
