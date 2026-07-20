"""
Backup do banco SQLite. Como o banco é um arquivo único, o backup
é simplesmente uma cópia com timestamp no nome.
"""
import shutil
import os
from datetime import datetime


def fazer_backup(banco_path: str, pasta_backup: str = "backups") -> str:
    os.makedirs(pasta_backup, exist_ok=True)
    nome_banco = os.path.basename(banco_path)
    nome_sem_ext = os.path.splitext(nome_banco)[0]
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destino = os.path.join(pasta_backup, f"{nome_sem_ext}_{timestamp}.db")

    shutil.copy2(banco_path, destino)
    return destino


def listar_backups(pasta_backup: str = "backups") -> list[str]:
    if not os.path.isdir(pasta_backup):
        return []
    arquivos = [f for f in os.listdir(pasta_backup) if f.endswith(".db")]
    arquivos.sort(reverse=True)
    return arquivos


def limpar_backups_antigos(pasta_backup: str = "backups", manter: int = 10):
    """Mantém apenas os N backups mais recentes, apaga o resto."""
    arquivos = listar_backups(pasta_backup)
    for antigo in arquivos[manter:]:
        os.remove(os.path.join(pasta_backup, antigo))
