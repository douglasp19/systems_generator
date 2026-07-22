"""
Motor de banco de dados. Responsável por:
- Criar as tabelas do SQLite a partir do schema
- Migrar automaticamente (adicionar colunas novas se o schema mudar)
- Operações genéricas de CRUD que funcionam para QUALQUER tabela do schema
"""
import sqlite3
import os
from typing import Any, Optional

from .schema_loader import Schema, Tabela


def conectar(banco_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(banco_path) or ".", exist_ok=True)
    conn = sqlite3.connect(banco_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _colunas_existentes(conn: sqlite3.Connection, tabela: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({tabela})")
    return {row["name"] for row in cur.fetchall()}


def _criar_tabela_sistema(conn: sqlite3.Connection):
    """Tabelas internas do motor: usuários, permissões por aba e log de auditoria."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            papel TEXT NOT NULL DEFAULT 'usuario',
            ativo INTEGER NOT NULL DEFAULT 1,
            permissoes_configuradas INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # migração: bancos criados antes do controle de permissões por aba
    if "permissoes_configuradas" not in _colunas_existentes(conn, "_usuarios"):
        conn.execute("ALTER TABLE _usuarios ADD COLUMN permissoes_configuradas INTEGER NOT NULL DEFAULT 0")

    # Quais abas (tabelas do schema, ou "_auditoria"/"_backup") um usuário
    # de papel 'usuario' pode ver. Enquanto 'permissoes_configuradas' for
    # 0 na tabela _usuarios, o usuário vê tudo (comportamento padrão até
    # o admin decidir restringir algo). Admins sempre veem tudo.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _usuario_permissoes (
            usuario_id INTEGER NOT NULL,
            aba TEXT NOT NULL,
            PRIMARY KEY (usuario_id, aba),
            FOREIGN KEY (usuario_id) REFERENCES _usuarios(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tabela TEXT NOT NULL,
            registro_id INTEGER,
            acao TEXT NOT NULL,
            usuario TEXT,
            detalhes TEXT,
            criado_em TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # Colunas que o usuário escolheu esconder na tela de lista de uma
    # tabela (filtro de colunas). Ausência de linhas = todas visíveis.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _colunas_ocultas (
            usuario_id INTEGER NOT NULL,
            tabela TEXT NOT NULL,
            campo TEXT NOT NULL,
            PRIMARY KEY (usuario_id, tabela, campo),
            FOREIGN KEY (usuario_id) REFERENCES _usuarios(id)
        )
    """)
    # Largura de coluna customizada pelo usuário na tela de lista.
    # Ausência de linha para um campo = usa a largura do schema ou o
    # cálculo automático.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _colunas_largura (
            usuario_id INTEGER NOT NULL,
            tabela TEXT NOT NULL,
            campo TEXT NOT NULL,
            largura REAL NOT NULL,
            PRIMARY KEY (usuario_id, tabela, campo),
            FOREIGN KEY (usuario_id) REFERENCES _usuarios(id)
        )
    """)
    # Notas fiscais que falharam por problema de comunicação com o
    # gateway (ex: sem internet no momento da venda) -- ficam aqui até
    # serem reenviadas com sucesso (retry automático no login, ou manual
    # na tela "Notas Pendentes").
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _fiscal_pendente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tabela TEXT NOT NULL,
            registro_id INTEGER NOT NULL,
            tentativas INTEGER NOT NULL DEFAULT 1,
            ultimo_erro TEXT,
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            atualizado_em TEXT,
            resolvido INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Configurações de impressora e fiscal ajustáveis pelo admin em tempo
    # de execução (tela "Configurações"), sobrepondo o que está no YAML
    # sem precisar editar o arquivo nem reiniciar com outro schema.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)
    # Preferências genéricas por usuário (ex: pasta de backup, tema, etc.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _preferencias (
            usuario_id INTEGER NOT NULL,
            chave TEXT NOT NULL,
            valor TEXT,
            PRIMARY KEY (usuario_id, chave),
            FOREIGN KEY (usuario_id) REFERENCES _usuarios(id)
        )
    """)
    conn.commit()


def garantir_schema(conn: sqlite3.Connection, schema: Schema):
    """Cria todas as tabelas do schema se não existirem, e adiciona
    colunas novas automaticamente se o YAML foi alterado depois."""
    _criar_tabela_sistema(conn)

    for tabela in schema.tabelas:
        existentes = _colunas_existentes(conn, tabela.nome)

        if not existentes:
            # Tabela não existe -> cria do zero
            colunas_sql = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
            chaves_estrangeiras = []
            for c in tabela.campos:
                colunas_sql.append(f'"{c.nome}" {c.tipo_sqlite}')
                if c.tipo == "referencia":
                    chaves_estrangeiras.append(
                        f'FOREIGN KEY ("{c.nome}") REFERENCES "{c.tabela_ref}"(id)'
                    )
            colunas_sql.append("criado_em TEXT DEFAULT (datetime('now', 'localtime'))")
            colunas_sql.append("atualizado_em TEXT")
            colunas_sql.extend(chaves_estrangeiras)
            sql = f'CREATE TABLE "{tabela.nome}" ({", ".join(colunas_sql)})'
            conn.execute(sql)
        else:
            # Tabela existe -> adiciona colunas que faltam (migração simples)
            for c in tabela.campos:
                if c.nome not in existentes:
                    conn.execute(
                        f'ALTER TABLE "{tabela.nome}" ADD COLUMN "{c.nome}" {c.tipo_sqlite}'
                    )
    conn.commit()


# ---------------------------------------------------------------------------
# CRUD genérico
# ---------------------------------------------------------------------------

def listar(conn: sqlite3.Connection, tabela: Tabela, busca: str = "",
           ordenar_por: str = "id", ordem: str = "DESC") -> list[dict]:
    sql = f'SELECT * FROM "{tabela.nome}"'
    params: list[Any] = []

    if busca and tabela.campos_buscaveis:
        condicoes = " OR ".join(f'"{c.nome}" LIKE ?' for c in tabela.campos_buscaveis)
        sql += f" WHERE {condicoes}"
        params.extend([f"%{busca}%"] * len(tabela.campos_buscaveis))

    sql += f' ORDER BY "{ordenar_por}" {ordem}'
    cur = conn.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def obter(conn: sqlite3.Connection, tabela: Tabela, registro_id: int) -> Optional[dict]:
    cur = conn.execute(f'SELECT * FROM "{tabela.nome}" WHERE id = ?', (registro_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def inserir(conn: sqlite3.Connection, tabela: Tabela, dados: dict) -> int:
    campos = [c.nome for c in tabela.campos if c.nome in dados]
    placeholders = ", ".join(["?"] * len(campos))
    colunas = ", ".join(f'"{c}"' for c in campos)
    valores = [dados[c] for c in campos]

    sql = f'INSERT INTO "{tabela.nome}" ({colunas}) VALUES ({placeholders})'
    cur = conn.execute(sql, valores)
    conn.commit()
    return cur.lastrowid


def atualizar(conn: sqlite3.Connection, tabela: Tabela, registro_id: int, dados: dict):
    campos = [c.nome for c in tabela.campos if c.nome in dados]
    set_clause = ", ".join(f'"{c}" = ?' for c in campos)
    valores = [dados[c] for c in campos]
    valores.append(registro_id)

    sql = (
        f'UPDATE "{tabela.nome}" SET {set_clause}, '
        f'atualizado_em = datetime(\'now\', \'localtime\') WHERE id = ?'
    )
    conn.execute(sql, valores)
    conn.commit()


def excluir(conn: sqlite3.Connection, tabela: Tabela, registro_id: int):
    conn.execute(f'DELETE FROM "{tabela.nome}" WHERE id = ?', (registro_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Suporte a campos de referência (chave estrangeira / dropdown)
# ---------------------------------------------------------------------------

def opcoes_referencia(conn: sqlite3.Connection, campo) -> list[tuple[int, str]]:
    """Retorna [(id, rótulo_exibido), ...] da tabela referenciada por um
    campo do tipo 'referencia', para popular um dropdown."""
    sql = f'SELECT id, "{campo.campo_exibicao}" as rotulo FROM "{campo.tabela_ref}" ORDER BY rotulo'
    cur = conn.execute(sql)
    return [(row["id"], row["rotulo"]) for row in cur.fetchall()]


def rotulo_referencia(conn: sqlite3.Connection, campo, valor_id) -> str:
    """Dado o id salvo num campo de referência, busca o rótulo pra exibir
    na lista (em vez de mostrar só o número do id)."""
    if valor_id is None:
        return ""
    sql = f'SELECT "{campo.campo_exibicao}" as rotulo FROM "{campo.tabela_ref}" WHERE id = ?'
    cur = conn.execute(sql, (valor_id,))
    row = cur.fetchone()
    return row["rotulo"] if row else f"[registro #{valor_id} não encontrado]"


def registro_para_exibicao(conn: sqlite3.Connection, tabela: Tabela, registro: dict) -> dict:
    """Retorna uma cópia do registro onde os campos do tipo 'referencia'
    aparecem como o rótulo (ex: nome do produto) em vez do id cru.
    Usado tanto na tela de lista quanto na impressão do cupom."""
    resultado = dict(registro)
    for campo in tabela.campos_referencia:
        resultado[campo.nome] = rotulo_referencia(conn, campo, registro.get(campo.nome))
    return resultado


def listar_abaixo_do_minimo(conn: sqlite3.Connection, tabela: Tabela) -> list[dict]:
    """Retorna os registros cujo campo de quantidade está abaixo do campo
    de estoque mínimo, conforme configurado em 'alerta_estoque' no YAML.
    Usado para exibir o aviso de estoque baixo na tela de lista."""
    if not tabela.alerta_estoque.ativo:
        return []
    campo_qtd = tabela.alerta_estoque.campo_quantidade
    campo_min = tabela.alerta_estoque.campo_minimo
    sql = (
        f'SELECT * FROM "{tabela.nome}" '
        f'WHERE "{campo_qtd}" < "{campo_min}" ORDER BY "{campo_qtd}" ASC'
    )
    cur = conn.execute(sql)
    return [dict(row) for row in cur.fetchall()]


def listar_vinculados(conn: sqlite3.Connection, tabela_filha: Tabela,
                       campo_fk_nome: str, valor_pai) -> list[dict]:
    """Busca todos os registros da 'tabela_filha' que apontam para um
    registro pai, através do campo de referência. Usado, por exemplo,
    para buscar as linhas de item de uma venda ao montar a nota fiscal."""
    sql = f'SELECT * FROM "{tabela_filha.nome}" WHERE "{campo_fk_nome}" = ?'
    cur = conn.execute(sql, (valor_pai,))
    return [dict(row) for row in cur.fetchall()]
