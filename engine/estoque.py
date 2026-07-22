"""
Baixa automática de estoque: quando um registro de uma tabela "de item"
(ex: item de venda) é criado, editado ou excluído, ajusta sozinho a
quantidade em estoque do produto referenciado -- sem precisar de nenhum
lançamento manual separado.

Padrão de uso: reverter() o efeito do registro antigo (edição/exclusão)
e/ou aplicar() o efeito do registro novo (criação/edição). Editar um
registro é sempre "reverter o antigo, aplicar o novo" -- isso cobre
tanto mudança de quantidade quanto mudança do produto selecionado, sem
precisar calcular diferenças manualmente.
"""
import sqlite3
from dataclasses import dataclass
from typing import Optional

from .schema_loader import Schema, Tabela
from . import db


@dataclass
class ResultadoBaixa:
    aplicada: bool
    estoque_negativo: bool = False
    mensagem: str = ""


def _rotulo_produto(tabela_estoque: Tabela, produto: dict) -> str:
    campos_buscaveis = tabela_estoque.campos_buscaveis
    if campos_buscaveis:
        return str(produto.get(campos_buscaveis[0].nome, f"#{produto.get('id')}"))
    return f"#{produto.get('id')}"


def _mover(conn: sqlite3.Connection, schema: Schema, tabela_itens: Tabela,
           registro: dict, sinal: int) -> ResultadoBaixa:
    cfg = tabela_itens.baixa_estoque
    if not cfg.ativo:
        return ResultadoBaixa(aplicada=False)

    produto_id = registro.get(cfg.campo_produto)
    quantidade = registro.get(cfg.campo_quantidade)
    if produto_id is None or quantidade is None:
        return ResultadoBaixa(aplicada=False)

    tabela_estoque = schema.tabela(cfg.tabela_estoque)
    if not tabela_estoque:
        return ResultadoBaixa(aplicada=False, mensagem=f"Tabela de estoque '{cfg.tabela_estoque}' não existe.")

    produto = db.obter(conn, tabela_estoque, produto_id)
    if not produto:
        return ResultadoBaixa(aplicada=False, mensagem="Produto não encontrado (pode ter sido excluído).")

    try:
        quantidade = float(quantidade)
    except (TypeError, ValueError):
        return ResultadoBaixa(aplicada=False)

    valor_atual = produto.get(cfg.campo_estoque) or 0
    novo_valor = valor_atual + (sinal * quantidade)

    conn.execute(
        f'UPDATE "{tabela_estoque.nome}" SET "{cfg.campo_estoque}" = ? WHERE id = ?',
        (novo_valor, produto_id),
    )
    conn.commit()

    negativo = novo_valor < 0
    return ResultadoBaixa(
        aplicada=True,
        estoque_negativo=negativo,
        mensagem=(
            f"Estoque de '{_rotulo_produto(tabela_estoque, produto)}' ficou "
            f"negativo ({novo_valor:g})."
        ) if negativo else "",
    )


def aplicar(conn: sqlite3.Connection, schema: Schema, tabela_itens: Tabela, registro: dict) -> ResultadoBaixa:
    """Desconta do estoque a quantidade deste registro (usado ao criar
    um item novo, ou ao aplicar o estado novo numa edição)."""
    return _mover(conn, schema, tabela_itens, registro, sinal=-1)


def reverter(conn: sqlite3.Connection, schema: Schema, tabela_itens: Tabela, registro: dict) -> ResultadoBaixa:
    """Devolve ao estoque a quantidade deste registro (usado ao excluir
    um item, ou antes de reaplicar numa edição)."""
    return _mover(conn, schema, tabela_itens, registro, sinal=+1)
