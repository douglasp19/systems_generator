"""
Carrega o schema.yaml e transforma em objetos Python fáceis de usar
pelo resto do motor (banco de dados e interface).
"""
from dataclasses import dataclass, field
from typing import Any, Optional
import yaml

# Tipos de campo suportados e o tipo SQLite correspondente
TIPOS_SQLITE = {
    "texto": "TEXT",
    "texto_longo": "TEXT",
    "inteiro": "INTEGER",
    "decimal": "REAL",
    "booleano": "INTEGER",  # 0 ou 1
    "data": "TEXT",         # armazenado como ISO 8601 (YYYY-MM-DD)
    "referencia": "INTEGER",  # chave estrangeira para outra tabela
}


@dataclass
class Campo:
    nome: str
    label: str
    tipo: str
    obrigatorio: bool = False
    buscavel: bool = False
    default: Any = None
    # usados apenas quando tipo == "referencia"
    tabela_ref: Optional[str] = None
    campo_exibicao: Optional[str] = None
    # validações customizadas -- só têm efeito em campos numéricos
    # (inteiro/decimal). Ex: "quantidade não pode ser negativa" -> minimo: 0
    minimo: Optional[float] = None
    maximo: Optional[float] = None
    # validações customizadas para texto -- expressão regular opcional
    # (ex: validar formato de e-mail ou CPF/CNPJ)
    regex: Optional[str] = None
    regex_mensagem: Optional[str] = None
    # largura da coluna (em pixels) na tela de lista. Se não informado, o
    # motor calcula uma largura automática a partir do tamanho do rótulo.
    largura: Optional[float] = None

    def __post_init__(self):
        if self.tipo not in TIPOS_SQLITE:
            raise ValueError(
                f"Tipo de campo desconhecido: '{self.tipo}'. "
                f"Tipos válidos: {list(TIPOS_SQLITE.keys())}"
            )
        if self.tipo == "referencia" and not (self.tabela_ref and self.campo_exibicao):
            raise ValueError(
                f"Campo '{self.nome}' é do tipo 'referencia' mas não define "
                f"'tabela_ref' e 'campo_exibicao' no YAML."
            )

    @property
    def tipo_sqlite(self) -> str:
        return TIPOS_SQLITE[self.tipo]

    def validar(self, valor: Any) -> Optional[str]:
        """Aplica as validações customizadas do campo (minimo/maximo/regex)
        sobre um valor já convertido para o tipo Python correspondente.
        Retorna a mensagem de erro, ou None se o valor é válido."""
        if valor is None or valor == "":
            return None

        if self.tipo in ("inteiro", "decimal"):
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                return None
            if self.minimo is not None and numero < self.minimo:
                return f"'{self.label}' não pode ser menor que {self.minimo:g}."
            if self.maximo is not None and numero > self.maximo:
                return f"'{self.label}' não pode ser maior que {self.maximo:g}."

        if self.regex and self.tipo in ("texto", "texto_longo"):
            import re
            if not re.fullmatch(self.regex, str(valor)):
                return self.regex_mensagem or f"'{self.label}' está em um formato inválido."

        return None


@dataclass
class Aba:
    nome: str
    campos: list[str] = field(default_factory=list)


@dataclass
class ImpressaoConfig:
    """Configuração de impressão de cupom/recibo térmico para uma tabela."""
    ativo: bool = False
    titulo: str = ""
    campos: list[str] = field(default_factory=list)  # quais campos entram no cupom
    rodape: str = ""
    # Se true, imprime o cupom sozinho assim que um registro NOVO é salvo
    # (não reimprime ao editar) -- sem precisar clicar no botão de impressora.
    auto_imprimir: bool = False


@dataclass
class FiscalConfig:
    """Configuração de emissão de nota fiscal para uma tabela (ex: vendas).

    tipo 'nfe'  -> nota fiscal completa (modelo 55, a que acompanha a
                   mercadoria e gera o DANFE). Destinatário SEMPRE
                   obrigatório (CNPJ/CPF completo) -- é o caso de venda
                   pra outra empresa ou produto despachado.
    tipo 'nfce' -> nota de consumidor no balcão (modelo 65, gera o
                   DANFCE -- documento diferente do DANFE). Destinatário
                   OPCIONAL: dá pra emitir sem nenhum cliente
                   identificado. Caso de loja física vendendo direto ao
                   consumidor (ex: loja de eletrônicos, mercado).

    'campo_destinatario' e 'tabela_itens' servem pros dois tipos -- a
    única diferença de verdade é que a NF-e exige destinatário e a
    NFC-e não.
    """
    ativo: bool = False
    tipo: str = "nfe"  # nfe | nfce

    campo_destinatario: Optional[str] = None   # campo (tipo referencia) apontando pro cliente -- opcional na nfce
    tabela_itens: Optional[str] = None          # nome da tabela com as linhas de item da nota

    # --- fallback simples (sem tabela de itens) ------------------------
    # Só usado se 'tabela_itens' não for definida -- útil pra uma nota
    # avulsa de um item só (ex: um serviço), sem lista de produtos.
    campo_valor: Optional[str] = None       # campo que representa o valor total
    campo_descricao: Optional[str] = None   # campo usado como descrição do item/serviço


@dataclass
class AlertaEstoqueConfig:
    """Aviso na tela de lista quando a quantidade em estoque de um
    registro fica abaixo do mínimo configurado (ex: produtos).

    'campo_quantidade' e 'campo_minimo' são os nomes dos campos
    (inteiro/decimal) da própria tabela que guardam, respectivamente, a
    quantidade atual e o estoque mínimo desejado."""
    ativo: bool = False
    campo_quantidade: Optional[str] = None
    campo_minimo: Optional[str] = None


@dataclass
class BaixaEstoqueConfig:
    """Baixa automática de estoque: ao criar/editar/excluir um registro
    nesta tabela (ex: um item de venda), ajusta a quantidade em estoque
    do produto referenciado, sem precisar de nenhuma ação manual.

    'tabela_estoque' é a tabela que guarda o estoque (ex: produtos).
    'campo_produto' é o campo (tipo referencia) desta tabela que aponta
    pro produto. 'campo_quantidade' é o campo numérico desta tabela com
    a quantidade vendida/usada. 'campo_estoque' é o campo numérico, na
    tabela de estoque, que guarda a quantidade disponível."""
    ativo: bool = False
    tabela_estoque: Optional[str] = None
    campo_produto: Optional[str] = None
    campo_quantidade: Optional[str] = None
    campo_estoque: Optional[str] = None


def encontrar_campo_fk_para(tabela_filha: "Tabela", nome_tabela_pai: str) -> Optional[Campo]:
    """Dado uma tabela de itens (filha) e o nome da tabela pai (ex: 'vendas'),
    encontra automaticamente qual campo dela é a referência de volta pro pai.
    Assim não precisa configurar isso duas vezes no YAML -- já foi declarado
    quando o campo 'referencia' da tabela de itens foi criado."""
    for c in tabela_filha.campos:
        if c.tipo == "referencia" and c.tabela_ref == nome_tabela_pai:
            return c
    return None


@dataclass
class Tabela:
    nome: str
    label: str
    icone: str = "table_rows"
    campos: list[Campo] = field(default_factory=list)
    abas: list[Aba] = field(default_factory=list)
    impressao: ImpressaoConfig = field(default_factory=ImpressaoConfig)
    fiscal: FiscalConfig = field(default_factory=FiscalConfig)
    alerta_estoque: AlertaEstoqueConfig = field(default_factory=AlertaEstoqueConfig)
    baixa_estoque: BaixaEstoqueConfig = field(default_factory=BaixaEstoqueConfig)

    def campo(self, nome: str) -> Optional[Campo]:
        for c in self.campos:
            if c.nome == nome:
                return c
        return None

    @property
    def campos_buscaveis(self) -> list[Campo]:
        return [c for c in self.campos if c.buscavel]

    @property
    def campos_referencia(self) -> list[Campo]:
        return [c for c in self.campos if c.tipo == "referencia"]


@dataclass
class ImpressoraConfig:
    """Configuração global da impressora térmica (ESC/POS)."""
    ativo: bool = False
    conexao: str = "usb"     # usb | rede | serial | arquivo (arquivo = modo teste, sem hardware)
    vendor_id: str = ""      # ex: "0x04b8" (para USB)
    product_id: str = ""     # ex: "0x0202" (para USB)
    ip: str = ""             # para conexão de rede
    porta: int = 9100
    dispositivo_serial: str = ""  # ex: "/dev/ttyUSB0"
    colunas: int = 42        # 32 (58mm) ou 42-48 (80mm), depende da impressora


@dataclass
class FiscalGlobalConfig:
    """Configuração global do gateway fiscal (provedor terceirizado que fala com a SEFAZ)."""
    ativo: bool = False
    provedor: str = ""            # ex: "focus_nfe", "plugnotas", "enotas"
    ambiente: str = "homologacao"  # homologacao | producao
    api_url: str = ""
    api_token_env: str = ""       # nome da variável de ambiente com o token (nunca no YAML!)
    cnpj_emitente: str = ""


@dataclass
class Schema:
    nome_sistema: str
    banco_path: str
    tabelas: list[Tabela] = field(default_factory=list)
    impressora: ImpressoraConfig = field(default_factory=ImpressoraConfig)
    fiscal: FiscalGlobalConfig = field(default_factory=FiscalGlobalConfig)

    def tabela(self, nome: str) -> Optional[Tabela]:
        for t in self.tabelas:
            if t.nome == nome:
                return t
        return None


def carregar_schema(caminho_yaml: str) -> Schema:
    with open(caminho_yaml, "r", encoding="utf-8") as f:
        bruto = yaml.safe_load(f)

    sistema = bruto.get("sistema", {})

    tabelas = []
    for t in bruto.get("tabelas", []):
        campos = [Campo(**c) for c in t.get("campos", [])]

        abas = [Aba(nome=a["nome"], campos=a.get("campos", [])) for a in t.get("abas", [])]

        impressao_bruta = t.get("impressao", {})
        impressao = ImpressaoConfig(**impressao_bruta) if impressao_bruta else ImpressaoConfig()

        fiscal_bruto = t.get("fiscal", {})
        fiscal_tabela = FiscalConfig(**fiscal_bruto) if fiscal_bruto else FiscalConfig()

        alerta_estoque_bruto = t.get("alerta_estoque", {})
        alerta_estoque = AlertaEstoqueConfig(**alerta_estoque_bruto) if alerta_estoque_bruto else AlertaEstoqueConfig()

        baixa_estoque_bruto = t.get("baixa_estoque", {})
        baixa_estoque = BaixaEstoqueConfig(**baixa_estoque_bruto) if baixa_estoque_bruto else BaixaEstoqueConfig()

        tabelas.append(
            Tabela(
                nome=t["nome"],
                label=t.get("label", t["nome"].title()),
                icone=t.get("icone", "table_rows"),
                campos=campos,
                abas=abas,
                impressao=impressao,
                fiscal=fiscal_tabela,
                alerta_estoque=alerta_estoque,
                baixa_estoque=baixa_estoque,
            )
        )

    impressora_bruta = sistema.get("impressora", {})
    impressora = ImpressoraConfig(**impressora_bruta) if impressora_bruta else ImpressoraConfig()

    fiscal_bruto = sistema.get("fiscal", {})
    fiscal_global = FiscalGlobalConfig(**fiscal_bruto) if fiscal_bruto else FiscalGlobalConfig()

    return Schema(
        nome_sistema=sistema.get("nome", "Sistema"),
        banco_path=sistema.get("banco", "data/sistema.db"),
        tabelas=tabelas,
        impressora=impressora,
        fiscal=fiscal_global,
    )
