"""
Autenticação simples: usuários e papéis (admin / usuario).
Senha é armazenada com hash (sha256 + salt), nunca em texto puro.
"""
import hashlib
import os
import sqlite3
from typing import Optional


def _hash_senha(senha: str, salt: str) -> str:
    return hashlib.sha256((salt + senha).encode("utf-8")).hexdigest()


def _gerar_salt() -> str:
    return os.urandom(8).hex()


def criar_usuario(conn: sqlite3.Connection, usuario: str, senha: str, papel: str = "usuario") -> bool:
    salt = _gerar_salt()
    senha_hash = f"{salt}${_hash_senha(senha, salt)}"
    try:
        conn.execute(
            "INSERT INTO _usuarios (usuario, senha_hash, papel) VALUES (?, ?, ?)",
            (usuario, senha_hash, papel),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # usuário já existe


def autenticar(conn: sqlite3.Connection, usuario: str, senha: str) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM _usuarios WHERE usuario = ? AND ativo = 1", (usuario,)
    )
    row = cur.fetchone()
    if not row:
        return None

    salt, hash_armazenado = row["senha_hash"].split("$")
    if _hash_senha(senha, salt) == hash_armazenado:
        return dict(row)
    return None


def existe_algum_usuario(conn: sqlite3.Connection) -> bool:
    cur = conn.execute("SELECT COUNT(*) as total FROM _usuarios")
    return cur.fetchone()["total"] > 0


def listar_usuarios(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT id, usuario, papel, ativo, criado_em FROM _usuarios")
    return [dict(row) for row in cur.fetchall()]


def desativar_usuario(conn: sqlite3.Connection, usuario_id: int):
    conn.execute("UPDATE _usuarios SET ativo = 0 WHERE id = ?", (usuario_id,))
    conn.commit()
