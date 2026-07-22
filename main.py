"""
Ponto de entrada. Para gerar um sistema novo para um cliente:
1. Copie schema_exemplo.yaml, renomeie e ajuste as tabelas/campos
   (ou use o editor visual: python main.py --editor).
2. Rode: python main.py caminho_do_schema.yaml
   (ou apenas "python main.py" para usar o schema_exemplo.yaml)
"""
import os
import sys
import tempfile

from engine.schema_loader import carregar_schema
from ui.app import rodar_app
from ui.schema_editor import rodar_editor

# Nome do schema dentro do executável empacotado -- precisa bater com o
# que ui/schema_editor.py usa em "Gerar executável"/"Gerar instalador"
# (eles copiam o .yaml escolhido pra esse nome fixo antes de empacotar).
NOME_SCHEMA_EMPACOTADO = "schema_embutido.yaml"


def _pasta_dados_do_executavel() -> str:
    """Onde procurar arquivos empacotados (como o schema) quando rodando
    como .exe gerado pelo PyInstaller.

    Um .exe com duplo clique NÃO roda com a pasta atual apontando pra
    onde os dados de --add-data foram extraídos -- por isso usar um
    caminho relativo simples (ex: "schema_exemplo.yaml") quebra com
    FileNotFoundError fora do modo desenvolvimento. sys._MEIPASS aponta
    pro lugar certo nos dois modos de empacotamento (arquivo único ou
    pasta)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.getcwd()


def _preparar_pasta_de_dados_gravavel():
    """Quando instalado (ex: em Program Files pelo instalador), a pasta
    do próprio executável não é gravável por um usuário comum do Windows
    -- e todo o motor grava dados (banco, backups, exports, cupons de
    teste, logo) em caminhos relativos como "data/sistema.db". Sem isso,
    o sistema quebra com PermissionError ao tentar criar essas pastas.

    A solução é trocar a pasta de trabalho do processo pra uma pasta
    gravável específica desse sistema (%LOCALAPPDATA%), antes de
    qualquer coisa gravar em disco -- assim o restante do código (que
    já usa caminhos relativos em toda parte) passa a gravar lá sem
    precisar de nenhuma outra mudança."""
    if not getattr(sys, "frozen", False):
        return  # modo desenvolvimento: mantém a pasta atual de sempre

    nome_pasta = os.path.splitext(os.path.basename(sys.executable))[0]
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    pasta_dados = os.path.join(base, nome_pasta)
    os.makedirs(pasta_dados, exist_ok=True)
    os.chdir(pasta_dados)


if __name__ == "__main__":
    _preparar_pasta_de_dados_gravavel()

    argumentos = sys.argv[1:]

    if argumentos and argumentos[0] == "--editor":
        caminho_inicial = argumentos[1] if len(argumentos) > 1 else None
        rodar_editor(caminho_inicial)
    else:
        if argumentos:
            caminho_schema = argumentos[0]
        else:
            caminho_schema = os.path.join(_pasta_dados_do_executavel(), NOME_SCHEMA_EMPACOTADO)
            if not os.path.exists(caminho_schema):
                caminho_schema = "schema_exemplo.yaml"  # modo desenvolvimento, sem empacotar

        schema = carregar_schema(caminho_schema)
        rodar_app(schema)
