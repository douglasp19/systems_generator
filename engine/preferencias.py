"""
Preferências de exibição por usuário: quais colunas aparecem e com que
largura, na tela de lista de cada tabela. Um usuário sem nenhuma
preferência salva vê todas as colunas nas larguras padrão (schema ou
cálculo automático) -- essas tabelas só guardam as EXCEÇÕES.
"""
import sqlite3


def colunas_ocultas(conn: sqlite3.Connection, usuario_id: int, tabela_nome: str) -> set[str]:
    cur = conn.execute(
        "SELECT campo FROM _colunas_ocultas WHERE usuario_id = ? AND tabela = ?",
        (usuario_id, tabela_nome),
    )
    return {row["campo"] for row in cur.fetchall()}


def definir_colunas_ocultas(conn: sqlite3.Connection, usuario_id: int, tabela_nome: str,
                             campos_ocultos: list[str]):
    """Substitui a lista de colunas ocultas do usuário para essa tabela."""
    conn.execute(
        "DELETE FROM _colunas_ocultas WHERE usuario_id = ? AND tabela = ?",
        (usuario_id, tabela_nome),
    )
    conn.executemany(
        "INSERT INTO _colunas_ocultas (usuario_id, tabela, campo) VALUES (?, ?, ?)",
        [(usuario_id, tabela_nome, campo) for campo in campos_ocultos],
    )
    conn.commit()


def larguras_colunas(conn: sqlite3.Connection, usuario_id: int, tabela_nome: str) -> dict[str, float]:
    """Larguras de coluna (em px) que o usuário ajustou manualmente para
    essa tabela, por nome de campo. Campos sem entrada aqui usam a
    largura do schema (campo.largura) ou o cálculo automático."""
    cur = conn.execute(
        "SELECT campo, largura FROM _colunas_largura WHERE usuario_id = ? AND tabela = ?",
        (usuario_id, tabela_nome),
    )
    return {row["campo"]: row["largura"] for row in cur.fetchall()}


def definir_larguras_colunas(conn: sqlite3.Connection, usuario_id: int, tabela_nome: str,
                              larguras: dict[str, float]):
    """Substitui as larguras customizadas do usuário para essa tabela.
    Campos ausentes de 'larguras' voltam a usar a largura padrão."""
    conn.execute(
        "DELETE FROM _colunas_largura WHERE usuario_id = ? AND tabela = ?",
        (usuario_id, tabela_nome),
    )
    conn.executemany(
        "INSERT INTO _colunas_largura (usuario_id, tabela, campo, largura) VALUES (?, ?, ?, ?)",
        [(usuario_id, tabela_nome, campo, largura) for campo, largura in larguras.items()],
    )
    conn.commit()


def obter_preferencia(conn: sqlite3.Connection, usuario_id: int, chave: str) -> str | None:
    """
    Obtém uma preferência genérica do usuário pelo nome da chave.
    
    Args:
        conn: Conexão com o banco de dados
        usuario_id: ID do usuário
        chave: Nome da preferência (ex: '_pasta_backup')
    
    Returns:
        Valor da preferência como string, ou None se não existir
    """
    cur = conn.execute(
        "SELECT valor FROM _preferencias WHERE usuario_id = ? AND chave = ?",
        (usuario_id, chave),
    )
    row = cur.fetchone()
    return row["valor"] if row else None


def salvar_preferencia(conn: sqlite3.Connection, usuario_id: int, chave: str, valor: str):
    """
    Salva ou atualiza uma preferência genérica do usuário.
    
    Args:
        conn: Conexão com o banco de dados
        usuario_id: ID do usuário
        chave: Nome da preferência (ex: '_pasta_backup')
        valor: Valor da preferência
    """
    conn.execute(
        """INSERT OR REPLACE INTO _preferencias (usuario_id, chave, valor) 
           VALUES (?, ?, ?)""",
        (usuario_id, chave, valor),
    )
    conn.commit()
