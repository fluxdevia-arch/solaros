from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes

from solar_crm.config import encryption_key


class SecretStorageError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _require_windows() -> None:
    if os.name != "nt":
        raise SecretStorageError("O armazenamento protegido de credenciais requer o Windows.")


def _fernet():
    key = encryption_key()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode("ascii"))
    except (ImportError, ValueError, UnicodeError) as exc:
        raise SecretStorageError(
            "SOLAROS_ENCRYPTION_KEY inválida. Gere uma chave Fernet conforme o guia de implantação."
        ) from exc


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def protect_secret(value: str) -> str:
    """Encrypt credentials with a cloud key or Windows DPAPI for local use."""
    if not value:
        return ""
    fernet = _fernet()
    if fernet is not None:
        token = fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"fernet:v1:{token}"
    _require_windows()
    raw = value.encode("utf-8")
    source, source_buffer = _input_blob(raw)
    encrypted = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "SolarOS monitoring credential",
        None,
        None,
        None,
        0x1,
        ctypes.byref(encrypted),
    ):
        raise SecretStorageError(f"Não foi possível proteger a credencial (erro {ctypes.get_last_error()}).")
    try:
        protected = ctypes.string_at(encrypted.pbData, encrypted.cbData)
        return f"dpapi:v1:{base64.b64encode(protected).decode('ascii')}"
    finally:
        ctypes.windll.kernel32.LocalFree(encrypted.pbData)
        del source_buffer


def unprotect_secret(value: str | None) -> str:
    """Decrypt current cloud values and legacy Windows DPAPI values."""
    if not value:
        return ""
    if value.startswith("fernet:v1:"):
        fernet = _fernet()
        if fernet is None:
            raise SecretStorageError("Defina SOLAROS_ENCRYPTION_KEY para abrir esta credencial.")
        try:
            return fernet.decrypt(value.removeprefix("fernet:v1:").encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise SecretStorageError("A credencial armazenada não pôde ser descriptografada.") from exc
    _require_windows()
    try:
        encoded = value.removeprefix("dpapi:v1:")
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise SecretStorageError("A credencial armazenada está corrompida.") from exc
    source, source_buffer = _input_blob(raw)
    decrypted = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(decrypted),
    ):
        raise SecretStorageError(f"Não foi possível abrir a credencial (erro {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(decrypted.pbData, decrypted.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(decrypted.pbData)
        del source_buffer
