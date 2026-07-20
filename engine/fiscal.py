"""
Emissão de nota fiscal (NF-e / NFC-e).

IMPORTANTE: emissão de nota fiscal NÃO é uma operação offline. A nota
precisa ser autorizada pela SEFAZ em tempo real, e isso exige (a)
certificado digital ICP-Brasil e (b) internet no momento da emissão.
Por isso este módulo não implementa a integração direta com a SEFAZ
(é um projeto de compliance por si só). Em vez disso, ele fala com um
GATEWAY FISCAL -- um serviço terceirizado (Focus NFe, PlugNotas,
eNotas, Nuvem Fiscal, TecnoSpeed etc.) que cuida da assinatura digital,
homologação, contingência e protocolo com a SEFAZ, e devolve pra você
só o XML/PDF (DANFE) prontos via uma API REST simples.

Dois modelos são suportados:

- NF-e (`tipo: nfe`): a nota que acompanha a mercadoria e gera o DANFE
  impresso. SEMPRE precisa de destinatário identificado (CNPJ/CPF
  completo) e de uma lista de itens. Caso de venda para outra empresa,
  produto despachado, etc.
- NFC-e (`tipo: nfce`): nota de consumidor emitida no balcão/PDV --
  gera o DANFCE, um documento diferente do DANFE. Pensada justamente
  pra venda direta ao consumidor final: o destinatário é OPCIONAL (o
  cliente pode pedir CPF na nota ou não). Também usa lista de itens,
  igual à NF-e -- a diferença real é só a obrigatoriedade do
  destinatário. Caso de loja física vendendo no balcão (ex: loja de
  eletrônicos, mercado, farmácia).

O TOKEN de acesso ao gateway NUNCA fica no YAML nem no código -- ele
vem de uma variável de ambiente (configurada em 'api_token_env' no
YAML), para não vazar credencial em nenhum arquivo versionado.
"""
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from .schema_loader import FiscalGlobalConfig, Schema, Tabela, encontrar_campo_fk_para
from . import db


class ErroFiscal(Exception):
    pass


@dataclass
class ResultadoEmissao:
    sucesso: bool
    mensagem: str
    protocolo: Optional[str] = None
    numero_nota: Optional[str] = None
    url_danfe: Optional[str] = None
    simulado: bool = False


# ---------------------------------------------------------------------------
# Montagem do payload
# ---------------------------------------------------------------------------

def _resolver_destinatario(conn: sqlite3.Connection, schema: Schema, tabela: Tabela, registro: dict):
    """Busca os dados do cliente vinculado à venda, se houver campo
    configurado. Retorna None se não houver (válido para NFC-e de
    balcão, onde o cliente pode não ser identificado)."""
    fc = tabela.fiscal
    if not fc.campo_destinatario:
        return None

    campo_dest = tabela.campo(fc.campo_destinatario)
    if not campo_dest or campo_dest.tipo != "referencia":
        raise ErroFiscal(
            f"'campo_destinatario' ({fc.campo_destinatario}) precisa ser um "
            f"campo do tipo 'referencia' na tabela '{tabela.nome}'."
        )
    valor_ref = registro.get(campo_dest.nome)
    if valor_ref is None:
        return None  # venda sem cliente vinculado (ok pra NFC-e)

    tabela_cliente = schema.tabela(campo_dest.tabela_ref)
    return db.obter(conn, tabela_cliente, valor_ref)


def _resolver_itens(conn: sqlite3.Connection, schema: Schema, tabela: Tabela, registro: dict) -> tuple[list, float]:
    """Busca as linhas de item vinculadas ao registro (ex: os produtos
    de uma venda) e soma o valor total. Se a tabela não tiver uma
    'tabela_itens' configurada, usa o modo simples de um item único a
    partir de 'campo_valor'/'campo_descricao' (útil pra notas avulsas
    sem lista de produtos, como um serviço)."""
    fc = tabela.fiscal

    if fc.tabela_itens:
        tabela_itens = schema.tabela(fc.tabela_itens)
        if not tabela_itens:
            raise ErroFiscal(f"Tabela de itens '{fc.tabela_itens}' não existe no schema.")

        campo_fk = encontrar_campo_fk_para(tabela_itens, tabela.nome)
        if not campo_fk:
            raise ErroFiscal(
                f"Não encontrei, na tabela '{fc.tabela_itens}', nenhum campo do tipo "
                f"'referencia' apontando de volta para '{tabela.nome}'."
            )

        registros_itens = db.listar_vinculados(conn, tabela_itens, campo_fk.nome, registro.get("id"))
        if not registros_itens:
            raise ErroFiscal(
                f"Esta venda não tem nenhum item lançado em '{fc.tabela_itens}'. "
                f"Toda nota fiscal precisa de ao menos um item."
            )

        itens, valor_total = [], 0.0
        for item in registros_itens:
            item_exibicao = db.registro_para_exibicao(conn, tabela_itens, item)
            valor_item = item_exibicao.get("valor_total") or item_exibicao.get("valor_unitario") or 0
            try:
                valor_total += float(valor_item)
            except (TypeError, ValueError):
                pass
            itens.append(item_exibicao)
        return itens, round(valor_total, 2)

    # Sem tabela de itens configurada -> modo simples (1 item só)
    if not fc.campo_valor:
        raise ErroFiscal(
            f"Tabela '{tabela.nome}' não tem 'tabela_itens' nem 'campo_valor' "
            f"configurados no YAML -- não tenho como saber o valor/itens da nota."
        )
    valor = registro.get(fc.campo_valor)
    if valor is None:
        raise ErroFiscal(f"Campo de valor ('{fc.campo_valor}') não encontrado ou vazio no registro.")
    descricao = registro.get(fc.campo_descricao) if fc.campo_descricao else "Item"
    return [{"descricao": descricao, "valor_total": valor}], float(valor)


def _montar_payload(conn: sqlite3.Connection, schema: Schema, tabela: Tabela, registro: dict) -> dict:
    """Monta o payload da nota (NF-e ou NFC-e). O formato exato varia
    entre gateways -- ajuste os nomes de campo deste dicionário conforme
    a documentação do provedor escolhido antes de ir pra produção."""
    fc = tabela.fiscal

    destinatario = _resolver_destinatario(conn, schema, tabela, registro)
    if fc.tipo == "nfe" and not destinatario:
        raise ErroFiscal(
            "NF-e exige um destinatário identificado (CNPJ/CPF completo). "
            "Se esta é uma venda de balcão sem cliente identificado, use "
            "tipo: nfce em vez de nfe -- o destinatário é opcional nela."
        )

    itens, valor_total = _resolver_itens(conn, schema, tabela, registro)

    return {
        "modelo": fc.tipo,
        "ambiente": schema.fiscal.ambiente,
        "cnpj_emitente": schema.fiscal.cnpj_emitente,
        "destinatario": destinatario,  # pode ser None numa NFC-e de balcão
        "itens": itens,
        "valor_total": valor_total,
        "referencia_interna": f"{tabela.nome}:{registro.get('id')}",
    }


# ---------------------------------------------------------------------------
# Emissão
# ---------------------------------------------------------------------------

def emitir(conn: sqlite3.Connection, schema: Schema, tabela: Tabela, registro: dict) -> ResultadoEmissao:
    """Emite a nota fiscal para um registro (ex: uma venda), delegando
    para o gateway fiscal configurado. Se não houver credencial/URL
    configurada, roda em MODO SIMULAÇÃO (não emite nada de verdade --
    só valida os campos e mostra o payload que seria enviado). Isso
    permite testar o fluxo do sistema sem ter conta em nenhum provedor."""

    if not tabela.fiscal.ativo:
        raise ErroFiscal(f"A tabela '{tabela.nome}' não tem emissão fiscal habilitada no YAML.")
    if not schema.fiscal.ativo:
        raise ErroFiscal("Emissão fiscal desabilitada no YAML (sistema.fiscal.ativo: true).")

    if tabela.fiscal.tipo not in ("nfe", "nfce"):
        raise ErroFiscal(f"Tipo fiscal desconhecido: '{tabela.fiscal.tipo}' (use 'nfe' ou 'nfce').")

    payload = _montar_payload(conn, schema, tabela, registro)

    # Prioridade: token digitado na tela de Configurações (guardado no
    # banco do sistema) -- se não houver, cai pra variável de ambiente
    # (jeito antigo, ainda útil pra quem prefere configurar assim).
    token = schema.fiscal.api_token or (
        os.environ.get(schema.fiscal.api_token_env, "") if schema.fiscal.api_token_env else ""
    )

    # Sem token configurado -> modo simulação (não envia nada pela rede)
    if not token or not schema.fiscal.api_url:
        return ResultadoEmissao(
            sucesso=True,
            simulado=True,
            mensagem=(
                "MODO SIMULAÇÃO (sem token/API configurados). Nenhuma nota real foi emitida. "
                f"Payload que seria enviado ao provedor '{schema.fiscal.provedor}': {payload}"
            ),
        )

    return _emitir_via_gateway(schema.fiscal, token, payload)


def _emitir_via_gateway(config_global: FiscalGlobalConfig, token: str, payload: dict) -> ResultadoEmissao:
    """Chamada real à API do gateway fiscal. Requer a lib 'requests'
    (pip install requests) e as credenciais reais do provedor escolhido.

    O endpoint e o formato exato do payload variam por provedor -- ajuste
    conforme a documentação oficial de quem você contratar (Focus NFe,
    PlugNotas, eNotas etc.) antes de ir para produção. O exemplo abaixo
    segue o padrão comum de Basic Auth com o token como usuário."""
    try:
        import requests
    except ImportError:
        raise ErroFiscal("Biblioteca 'requests' não instalada. Rode: pip install requests")

    endpoint = "nfe" if payload["modelo"] == "nfe" else "nfce"
    url = f"{config_global.api_url.rstrip('/')}/{endpoint}"

    try:
        resposta = requests.post(url, json=payload, auth=(token, ""), timeout=30)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.exceptions.RequestException as e:
        return ResultadoEmissao(sucesso=False, mensagem=f"Falha na comunicação com o gateway fiscal: {e}")
    except ValueError:
        return ResultadoEmissao(sucesso=False, mensagem="Resposta inválida do gateway fiscal (não é JSON).")

    return ResultadoEmissao(
        sucesso=True,
        mensagem="Nota emitida com sucesso.",
        protocolo=dados.get("protocolo"),
        numero_nota=dados.get("numero"),
        url_danfe=dados.get("caminho_danfe") or dados.get("url_danfe") or dados.get("caminho_pdf"),
    )


# ---------------------------------------------------------------------------
# Fila de retry -- notas que falharam por problema de comunicação (ex: sem
# internet no momento da venda) ficam pendentes e são reenviadas depois,
# em vez de simplesmente perder a emissão.
# ---------------------------------------------------------------------------

def enfileirar_pendente(conn: sqlite3.Connection, tabela_nome: str, registro_id, erro: str):
    """Registra (ou atualiza) uma nota pendente de reenvio. Se já existir
    uma pendência não resolvida pro mesmo registro, só soma a tentativa
    em vez de duplicar a linha."""
    cur = conn.execute(
        "SELECT id FROM _fiscal_pendente WHERE tabela = ? AND registro_id = ? AND resolvido = 0",
        (tabela_nome, registro_id),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE _fiscal_pendente SET tentativas = tentativas + 1, ultimo_erro = ?, "
            "atualizado_em = datetime('now', 'localtime') WHERE id = ?",
            (erro, row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO _fiscal_pendente (tabela, registro_id, ultimo_erro) VALUES (?, ?, ?)",
            (tabela_nome, registro_id, erro),
        )
    conn.commit()


def listar_pendentes(conn: sqlite3.Connection) -> list[dict]:
    """Notas ainda não resolvidas, da mais antiga para a mais nova."""
    cur = conn.execute(
        "SELECT * FROM _fiscal_pendente WHERE resolvido = 0 ORDER BY criado_em ASC"
    )
    return [dict(row) for row in cur.fetchall()]


def marcar_resolvido(conn: sqlite3.Connection, pendente_id: int):
    conn.execute(
        "UPDATE _fiscal_pendente SET resolvido = 1, atualizado_em = datetime('now', 'localtime') WHERE id = ?",
        (pendente_id,),
    )
    conn.commit()


def reprocessar_pendente(conn: sqlite3.Connection, schema: Schema, pendente: dict) -> ResultadoEmissao:
    """Tenta emitir de novo uma nota da fila de pendências. Marca como
    resolvida se der certo dessa vez; senão, atualiza tentativas/erro e
    mantém pendente. Nunca levanta ErroFiscal -- eventuais problemas
    (tabela ou registro que não existem mais, validação) viram um
    ResultadoEmissao com sucesso=False, pra não travar um reenvio em
    lote de várias pendências."""
    tabela = schema.tabela(pendente["tabela"])
    if not tabela:
        marcar_resolvido(conn, pendente["id"])
        return ResultadoEmissao(
            sucesso=False,
            mensagem=f"Tabela '{pendente['tabela']}' não existe mais no schema -- pendência descartada.",
        )

    registro = db.obter(conn, tabela, pendente["registro_id"])
    if not registro:
        marcar_resolvido(conn, pendente["id"])
        return ResultadoEmissao(
            sucesso=False,
            mensagem="O registro original foi excluído -- pendência descartada.",
        )

    try:
        resultado = emitir(conn, schema, tabela, registro)
    except ErroFiscal as e:
        resultado = ResultadoEmissao(sucesso=False, mensagem=str(e))

    if resultado.sucesso:
        marcar_resolvido(conn, pendente["id"])
    else:
        enfileirar_pendente(conn, pendente["tabela"], pendente["registro_id"], resultado.mensagem)

    return resultado
