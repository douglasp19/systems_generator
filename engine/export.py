"""
Exportação genérica de dados de qualquer tabela para CSV ou Excel.
"""
import csv
import os
from openpyxl import Workbook
from openpyxl.styles import Font

from .schema_loader import Tabela


def exportar_csv(tabela: Tabela, registros: list[dict], caminho_saida: str):
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)
    cabecalho = ["id"] + [c.nome for c in tabela.campos]

    with open(caminho_saida, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cabecalho)
        writer.writeheader()
        for r in registros:
            writer.writerow({k: r.get(k, "") for k in cabecalho})


def exportar_excel(tabela: Tabela, registros: list[dict], caminho_saida: str):
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = tabela.label[:31]  # limite do Excel para nome de aba

    cabecalho = ["id"] + [c.label for c in tabela.campos]
    ws.append(cabecalho)
    for cel in ws[1]:
        cel.font = Font(bold=True)

    chaves = ["id"] + [c.nome for c in tabela.campos]
    for r in registros:
        ws.append([r.get(k, "") for k in chaves])

    # Autoajuste simples de largura de coluna
    for coluna in ws.columns:
        largura = max((len(str(c.value)) for c in coluna if c.value is not None), default=10)
        ws.column_dimensions[coluna[0].column_letter].width = min(largura + 2, 40)

    wb.save(caminho_saida)
