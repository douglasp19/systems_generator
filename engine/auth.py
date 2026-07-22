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


def criar_usuario(conn: sqlite3.Connection, usuario: str, senha: str, papel: str = "usuario") -> Optional[int]:
    """Cria um usuário novo. Retorna o id criado, ou None se o nome já existe."""
    salt = _gerar_salt()
    senha_hash = f"{salt}${_hash_senha(senha, salt)}"
    try:
        cur = conn.execute(
            "INSERT INTO _usuarios (usuario, senha_hash, papel) VALUES (?, ?, ?)",
            (usuario, senha_hash, papel),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # usuário já existe


def atualizar_usuario(conn: sqlite3.Connection, usuario_id: int, usuario: str, papel: str,
                       ativo: bool, nova_senha: Optional[str] = None) -> bool:
    """Atualiza nome, papel e status de um usuário existente. Se
    'nova_senha' for informada (não vazia), também troca a senha.
    Retorna False se o novo nome já pertence a outro usuário."""
    try:
        if nova_senha:
            salt = _gerar_salt()
            senha_hash = f"{salt}${_hash_senha(nova_senha, salt)}"
            conn.execute(
                "UPDATE _usuarios SET usuario = ?, papel = ?, ativo = ?, senha_hash = ? WHERE id = ?",
                (usuario, papel, int(ativo), senha_hash, usuario_id),
            )
        else:
            conn.execute(
                "UPDATE _usuarios SET usuario = ?, papel = ?, ativo = ? WHERE id = ?",
                (usuario, papel, int(ativo), usuario_id),
            )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


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


# ---------------------------------------------------------------------------
# Permissões por aba (quais telas um usuário de papel 'usuario' pode ver)
# ---------------------------------------------------------------------------

def permissoes_configuradas(conn: sqlite3.Connection, usuario_id: int) -> bool:
    """Indica se o admin já definiu explicitamente as abas visíveis desse
    usuário. Enquanto False, o padrão é mostrar todas as abas -- assim
    usuários criados antes desse recurso (ou sem configuração ainda)
    continuam vendo o sistema inteiro."""
    cur = conn.execute("SELECT permissoes_configuradas FROM _usuarios WHERE id = ?", (usuario_id,))
    row = cur.fetchone()
    return bool(row["permissoes_configuradas"]) if row else False


def permissoes_usuario(conn: sqlite3.Connection, usuario_id: int) -> set[str]:
    """Retorna o conjunto de abas liberadas para o usuário: nomes de
    tabelas do schema, e/ou "_auditoria"/"_backup" para essas telas fixas."""
    cur = conn.execute("SELECT aba FROM _usuario_permissoes WHERE usuario_id = ?", (usuario_id,))
    return {row["aba"] for row in cur.fetchall()}


def definir_permissoes(conn: sqlite3.Connection, usuario_id: int, abas: list[str]):
    """Define quais abas o usuário pode ver, substituindo qualquer
    configuração anterior. Ignorado para administradores (sempre veem
    tudo, independente do que esteja gravado aqui)."""
    conn.execute("DELETE FROM _usuario_permissoes WHERE usuario_id = ?", (usuario_id,))
    conn.executemany(
        "INSERT INTO _usuario_permissoes (usuario_id, aba) VALUES (?, ?)",
        [(usuario_id, aba) for aba in abas],
    )
    conn.execute("UPDATE _usuarios SET permissoes_configuradas = 1 WHERE id = ?", (usuario_id,))
    conn.commit()
