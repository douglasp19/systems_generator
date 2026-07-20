"""
Impressão em impressora térmica (cupom não fiscal / recibo / comanda).

Suporta conexão USB, rede (Ethernet/Wi-Fi) e serial via a biblioteca
python-escpos, que fala o protocolo ESC/POS usado pela grande maioria
das impressoras térmicas do mercado (Epson, Elgin, Bematech, Tanca etc.)

Também tem um modo "arquivo" que não precisa de impressora nenhuma --
grava o cupom em um arquivo .txt. Útil para testar o layout do cupom
sem ter o hardware em mãos, ou em ambientes de desenvolvimento.
"""
import os
from datetime import datetime

from .schema_loader import ImpressoraConfig, Tabela, ImpressaoConfig


class ErroImpressora(Exception):
    pass


def _obter_conexao(config: ImpressoraConfig):
    """Abre a conexão com a impressora de acordo com o tipo configurado
    no YAML. Import do escpos é feito aqui dentro (import tardio) para
    que o resto do sistema funcione mesmo em máquinas sem essa lib
    instalada, caso o cliente não use impressora térmica."""
    from escpos.printer import Usb, Network, Serial, File

    if config.conexao == "usb":
        if not (config.vendor_id and config.product_id):
            raise ErroImpressora(
                "Impressora USB configurada sem 'vendor_id'/'product_id' no YAML. "
                "Use o comando 'lsusb' (Linux) ou o Gerenciador de Dispositivos "
                "(Windows) para descobrir esses valores."
            )
        return Usb(int(config.vendor_id, 16), int(config.product_id, 16))

    if config.conexao == "rede":
        if not config.ip:
            raise ErroImpressora("Impressora de rede configurada sem 'ip' no YAML.")
        return Network(config.ip, port=config.porta)

    if config.conexao == "serial":
        if not config.dispositivo_serial:
            raise ErroImpressora("Impressora serial configurada sem 'dispositivo_serial' no YAML.")
        return Serial(devfile=config.dispositivo_serial)

    if config.conexao == "arquivo":
        os.makedirs("cupons_teste", exist_ok=True)
        nome = f"cupons_teste/cupom_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        return File(nome)

    raise ErroImpressora(f"Tipo de conexão de impressora desconhecido: '{config.conexao}'")


def imprimir_cupom(config_impressora: ImpressoraConfig, tabela: Tabela, registro: dict) -> str:
    """Imprime o cupom de um registro (ex: uma venda) de acordo com a
    configuração de 'impressao' definida na tabela do YAML.
    Retorna uma mensagem de status."""
    config_cupom: ImpressaoConfig = tabela.impressao

    if not config_cupom.ativo:
        raise ErroImpressora(f"A tabela '{tabela.nome}' não tem impressão de cupom habilitada no YAML.")
    if not config_impressora.ativo:
        raise ErroImpressora("Nenhuma impressora configurada no YAML (sistema.impressora.ativo: true).")

    largura = config_impressora.colunas

    impressora = _obter_conexao(config_impressora)
    try:
        impressora.set(align="center", bold=True, width=2, height=2)
        titulo = config_cupom.titulo or tabela.label
        impressora.text(titulo + "\n")
        impressora.set(align="center", bold=False, width=1, height=1)
        impressora.text(datetime.now().strftime("%d/%m/%Y %H:%M") + "\n")
        impressora.text("-" * largura + "\n")

        impressora.set(align="left")
        for nome_campo in config_cupom.campos:
            campo = tabela.campo(nome_campo)
            if not campo:
                continue
            valor = registro.get(nome_campo, "")
            linha = f"{campo.label}: {valor}"
            impressora.text(linha + "\n")

        impressora.text("-" * largura + "\n")
        if config_cupom.rodape:
            impressora.set(align="center")
            impressora.text(config_cupom.rodape + "\n")

        impressora.text("\n\n")
        impressora.cut()
    finally:
        impressora.close()

    if config_impressora.conexao == "arquivo":
        return "Cupom gerado em modo teste (pasta cupons_teste/, sem impressora física)."
    return "Cupom enviado para a impressora."
