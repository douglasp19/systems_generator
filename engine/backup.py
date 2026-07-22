"""
Backup do banco SQLite. Como o banco é um arquivo único, o backup
é simplesmente uma cópia com timestamp no nome.
"""
import shutil
import os
from datetime import datetime


def fazer_backup(banco_path: str, pasta_backup: str = None) -> str:
    """
    Cria backup do banco SQLite.
    
    Args:
        banco_path: Caminho completo do banco de dados atual
        pasta_backup: Pasta onde salvar o backup (opcional). 
                      Se None, usa pasta padrão "backups"
    
    Returns:
        Caminho completo do arquivo de backup criado
    """
    if pasta_backup is None:
        pasta_backup = "backups"
    
    os.makedirs(pasta_backup, exist_ok=True)
    nome_banco = os.path.basename(banco_path)
    nome_sem_ext = os.path.splitext(nome_banco)[0]
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destino = os.path.join(pasta_backup, f"{nome_sem_ext}_{timestamp}.db")

    shutil.copy2(banco_path, destino)
    return destino


def listar_backups(pasta_backup: str = None) -> list[str]:
    """
    Lista todos os backups disponíveis na pasta especificada.
    
    Args:
        pasta_backup: Pasta onde procurar backups (opcional).
                      Se None, usa pasta padrão "backups"
    
    Returns:
        Lista de nomes de arquivos de backup, ordenados do mais recente para o mais antigo
    """
    if pasta_backup is None:
        pasta_backup = "backups"
    
    if not os.path.isdir(pasta_backup):
        return []
    arquivos = [f for f in os.listdir(pasta_backup) if f.endswith(".db")]
    arquivos.sort(reverse=True)
    return arquivos


def limpar_backups_antigos(pasta_backup: str = None, manter: int = 10):
    """Mantém apenas os N backups mais recentes, apaga o resto."""
    if pasta_backup is None:
        pasta_backup = "backups"
    
    arquivos = listar_backups(pasta_backup)
    for antigo in arquivos[manter:]:
        os.remove(os.path.join(pasta_backup, antigo))


def restaurar_backup(banco_path: str, backup_path: str) -> bool:
    """
    Restaura o banco de dados a partir de um backup.
    
    Args:
        banco_path: Caminho do banco de dados atual (será substituído)
        backup_path: Caminho completo do arquivo de backup a ser restaurado
    
    Returns:
        True se a restauração foi bem-sucedida, False caso contrário
    """
    if not os.path.exists(backup_path):
        return False
    
    # Cria backup automático do estado atual antes de restaurar
    try:
        fazer_backup(banco_path)
    except Exception:
        pass  # Continua mesmo se falhar ao criar backup preventivo
    
    # Copia o backup sobre o banco atual
    shutil.copy2(backup_path, banco_path)
    return True
