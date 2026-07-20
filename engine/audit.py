"""
Log de auditoria: registra quem fez o quê e quando.
"""
import sqlite3


def registrar(conn: sqlite3.Connection, tabela: str, registro_id, acao: str,
              usuario: str, detalhes: str = ""):
    conn.execute(
        "INSERT INTO _auditoria (tabela, registro_id, acao, usuario, detalhes) "
        "VALUES (?, ?, ?, ?, ?)",
        (tabela, registro_id, acao, usuario, detalhes),
    )
    conn.commit()


def listar(conn: sqlite3.Connection, limite: int = 200) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM _auditoria ORDER BY id DESC LIMIT ?", (limite,)
    )
    return [dict(row) for row in cur.fetchall()]
