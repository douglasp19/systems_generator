"""
Ponto de entrada. Para gerar um sistema novo para um cliente:
1. Copie schema_exemplo.yaml, renomeie e ajuste as tabelas/campos
   (ou use o editor visual: python main.py --editor).
2. Rode: python main.py caminho_do_schema.yaml
   (ou apenas "python main.py" para usar o schema_exemplo.yaml)
"""
import sys
from engine.schema_loader import carregar_schema
from ui.app import rodar_app
from ui.schema_editor import rodar_editor

if __name__ == "__main__":
    argumentos = sys.argv[1:]

    if argumentos and argumentos[0] == "--editor":
        caminho_inicial = argumentos[1] if len(argumentos) > 1 else None
        rodar_editor(caminho_inicial)
    else:
        caminho_schema = argumentos[0] if argumentos else "schema_exemplo.yaml"
        schema = carregar_schema(caminho_schema)
        rodar_app(schema)
