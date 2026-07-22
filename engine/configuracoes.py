"""
Configurações de impressora e fiscal ajustáveis pela conta admin em
tempo de execução (tela "Configurações"), sem precisar editar o YAML
nem reiniciar o sistema com outro schema.

Guardadas no próprio banco do sistema (chave-valor, um JSON por seção) e
sobrepõem o que está no schema.yaml quando presentes -- assim o YAML
continua funcionando como configuração inicial/padrão, mas o admin pode
ajustar depois sem depender de quem programou o sistema.

IMPORTANTE: diferente do YAML (que não deve ter segredos, pois costuma
ir pra controle de versão), aqui é seguro guardar o token do gateway
fiscal -- o banco .db é local e específico desse cliente, do mesmo jeito
que já guarda senhas (com hash) e dados de clientes.
"""
import json
import sqlite3

from .schema_loader import Schema


def obter(conn: sqlite3.Connection, chave: str) -> dict | None:
    cur = conn.execute("SELECT valor FROM _configuracoes WHERE chave = ?", (chave,))
    row = cur.fetchone()
    if not row or not row["valor"]:
        return None
    return json.loads(row["valor"])


def salvar(conn: sqlite3.Connection, chave: str, valores: dict):
    conn.execute(
        "INSERT INTO _configuracoes (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, json.dumps(valores)),
    )
    conn.commit()


def chave_cupom(tabela_nome: str) -> str:
    return f"impressao_{tabela_nome}"


def aplicar_no_schema(conn: sqlite3.Connection, schema: Schema):
    """Sobrepõe schema.impressora / schema.fiscal, e o cupom de cada
    tabela, com o que foi salvo na tela de Configurações, se houver.
    Chamado uma vez ao abrir o sistema, antes de qualquer tela ser
    exibida."""
    config_impressora = obter(conn, "impressora")
    if config_impressora:
        for chave, valor in config_impressora.items():
            if hasattr(schema.impressora, chave):
                setattr(schema.impressora, chave, valor)

    config_fiscal = obter(conn, "fiscal")
    if config_fiscal:
        for chave, valor in config_fiscal.items():
            if hasattr(schema.fiscal, chave):
                setattr(schema.fiscal, chave, valor)

    for tabela in schema.tabelas:
        config_cupom = obter(conn, chave_cupom(tabela.nome))
        if config_cupom:
            for chave, valor in config_cupom.items():
                if hasattr(tabela.impressao, chave):
                    setattr(tabela.impressao, chave, valor)

    config_aparencia = obter(conn, "aparencia")
    if config_aparencia:
        schema.logo_path = config_aparencia.get("logo_path", "")
