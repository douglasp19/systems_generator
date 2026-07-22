"""
Editor visual de schema. Tela dentro do próprio gerador para montar
tabelas e campos através de formulários e botões (adicionar, editar,
remover, reordenar), em vez de editar o arquivo .yaml na mão.

Trabalha diretamente sobre o dicionário "bruto" carregado do YAML (não
sobre os dataclasses de engine/schema_loader.py), para que seções que o
editor ainda não sabe montar visualmente (ex: configuração de
impressora, fiscal por tabela) sejam preservadas ao salvar.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys

import flet as ft
import yaml

# Raiz do projeto (onde ficam main.py e a pasta modulos/) -- calculada a
# partir deste arquivo pra funcionar independente da pasta de onde o
# editor foi iniciado.
PROJETO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Precisa bater com main.py: nome fixo que o schema escolhido leva
# dentro do executável, independente do nome real do arquivo .yaml.
# Sem isso, main.py (rodando já empacotado) não saberia qual arquivo
# procurar -- cada cliente pode nomear o schema como quiser.
NOME_SCHEMA_EMPACOTADO = "schema_embutido.yaml"


def _preparar_schema_para_empacotar(caminho_arquivo: str) -> str:
    """Copia o schema escolhido pra um nome fixo na raiz do projeto, pra
    ser embutido no executável com --add-data. Retorna o caminho da
    cópia (é isso que entra no --add-data, não o arquivo original)."""
    destino = os.path.join(PROJETO_DIR, NOME_SCHEMA_EMPACOTADO)
    shutil.copyfile(os.path.abspath(caminho_arquivo), destino)
    return destino

# Caminhos comuns de instalação do Inno Setup 6 no Windows, além do PATH.
_CAMINHOS_ISCC = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def _localizar_iscc() -> str | None:
    """Acha o compilador de linha de comando do Inno Setup (ISCC.exe),
    usado pra gerar o instalador. Retorna None se não estiver instalado."""
    encontrado = shutil.which("iscc")
    if encontrado:
        return encontrado
    for caminho in _CAMINHOS_ISCC:
        if os.path.isfile(caminho):
            return caminho
    return None


_TEMPLATE_ISS = """\
[Setup]
AppName={nome_sistema}
AppVersion=1.0.0
DefaultDirName={{autopf}}\\{nome_executavel}
DefaultGroupName={nome_sistema}
UninstallDisplayIcon={{app}}\\{nome_executavel}.exe
OutputDir={pasta_saida}
OutputBaseFilename={nome_executavel}_Instalador
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais"

[Files]
Source: "{pasta_build}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{nome_sistema}"; Filename: "{{app}}\\{nome_executavel}.exe"
Name: "{{group}}\\Desinstalar {nome_sistema}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\{nome_sistema}"; Filename: "{{app}}\\{nome_executavel}.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{nome_executavel}.exe"; Description: "Abrir {nome_sistema} agora"; Flags: nowait postinstall skipifsilent
"""

TIPOS_CAMPO = [
    ("texto", "Texto curto"),
    ("texto_longo", "Texto longo"),
    ("inteiro", "Número inteiro"),
    ("decimal", "Número decimal"),
    ("booleano", "Sim/Não"),
    ("data", "Data"),
    ("referencia", "Referência a outra tabela"),
]

ICONES_SUGERIDOS = [
    "table_rows", "inventory_2", "local_shipping", "person", "point_of_sale",
    "list_alt", "build", "medical_services", "restaurant", "receipt_long",
]

# Pasta com os módulos prontos (blocos de tabelas reutilizáveis, ex:
# "Pacientes", "Anamnese") -- fica na raiz do projeto, ao lado de main.py.
MODULOS_DIR = os.path.join(PROJETO_DIR, "modulos")


def _listar_modulos() -> list[dict]:
    """Lê todo .yaml da pasta modulos/ e retorna os metadados + tabelas
    de cada um. Módulos com erro de leitura são ignorados silenciosamente
    (não travam o editor por causa de um arquivo malformado)."""
    modulos = []
    if not os.path.isdir(MODULOS_DIR):
        return modulos
    for nome_arquivo in sorted(os.listdir(MODULOS_DIR)):
        if not nome_arquivo.endswith((".yaml", ".yml")):
            continue
        caminho = os.path.join(MODULOS_DIR, nome_arquivo)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                bruto = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            continue
        meta = bruto.get("modulo", {})
        modulos.append({
            "arquivo": nome_arquivo,
            "nome": meta.get("nome", nome_arquivo),
            "descricao": meta.get("descricao", ""),
            "depende_de": meta.get("depende_de", []) or [],
            "tabelas": bruto.get("tabelas", []) or [],
        })
    return modulos


def _cast_default(tipo: str, texto: str):
    if texto is None or texto == "":
        return None
    if tipo == "inteiro":
        try:
            return int(texto)
        except ValueError:
            return texto
    if tipo == "decimal":
        try:
            return float(texto)
        except ValueError:
            return texto
    if tipo == "booleano":
        return texto.strip().lower() in ("1", "true", "sim", "verdadeiro")
    return texto


def _texto_default(valor) -> str:
    return "" if valor is None else str(valor)


class SchemaEditorApp:
    def __init__(self, page: ft.Page, caminho_inicial: str | None = None):
        self.page = page
        self.page.title = "Editor Visual de Schema"
        self.page.window.width = 1200
        self.page.window.height = 800
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)

        self.caminho_arquivo = caminho_inicial
        self.bruto: dict = {}
        self.tabela_selecionada_idx: int | None = None

        if caminho_inicial and os.path.exists(caminho_inicial):
            self._carregar_arquivo(caminho_inicial)
        else:
            self.bruto = {
                "sistema": {"nome": "Novo Sistema", "banco": "data/sistema.db"},
                "tabelas": [],
            }

        self._montar_layout()

    # ------------------------------------------------------------------
    # ARQUIVO (abrir / salvar)
    # ------------------------------------------------------------------
    def _carregar_arquivo(self, caminho: str):
        with open(caminho, "r", encoding="utf-8") as f:
            self.bruto = yaml.safe_load(f) or {}
        self.bruto.setdefault("sistema", {})
        self.bruto.setdefault("tabelas", [])
        self.caminho_arquivo = caminho

    def _abrir_click(self, e):
        caminho = self.campo_caminho.value.strip()
        if not caminho:
            self._notificar("Informe o caminho de um arquivo .yaml para abrir.")
            return
        if not os.path.exists(caminho):
            self._notificar(f"Arquivo não encontrado: {caminho}")
            return
        self._carregar_arquivo(caminho)
        self.tabela_selecionada_idx = None
        self._montar_layout()
        self._notificar(f"Schema carregado de {caminho}")

    def _salvar_click(self, e):
        caminho = self.campo_caminho.value.strip() or self.caminho_arquivo
        if not caminho:
            self._notificar("Informe o caminho onde salvar o arquivo .yaml.")
            return
        if not caminho.endswith((".yaml", ".yml")):
            caminho += ".yaml"
        os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            yaml.dump(self.bruto, f, allow_unicode=True, sort_keys=False)
        self.caminho_arquivo = caminho
        self.campo_caminho.value = caminho
        self.page.update()
        self._notificar(f"Schema salvo em {caminho}")

    def _rodar_sistema_click(self, e):
        if not self.caminho_arquivo:
            self._notificar("Salve o schema antes de rodar o sistema.")
            return
        subprocess.Popen([sys.executable, "main.py", self.caminho_arquivo])
        self._notificar(f"Abrindo sistema com {self.caminho_arquivo}...")

    def _gerar_executavel_click(self, e):
        if not self.caminho_arquivo:
            self._notificar("Salve o schema antes de gerar o executável.")
            return

        nome_sistema = self.bruto.get("sistema", {}).get("nome", "Sistema")
        nome_executavel = re.sub(r"[^A-Za-z0-9_]+", "_", nome_sistema).strip("_") or "Sistema"

        caminho_schema = _preparar_schema_para_empacotar(self.caminho_arquivo)
        comando = [
            "flet", "pack", "main.py",
            "--name", nome_executavel,
            "--add-data", f"{caminho_schema}:.",
            # 'appdirs' é usado pelo python-escpos (impressora térmica) mas o
            # PyInstaller não detecta essa dependência sozinho -- sem isso o
            # executável gerado quebra com "ImportError: The 'appdirs'
            # package is required" ao abrir.
            "--hidden-import", "appdirs",
        ]

        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        try:
            subprocess.Popen(comando, cwd=PROJETO_DIR, creationflags=flags)
        except FileNotFoundError:
            self._notificar(
                "Comando 'flet' não encontrado. Rode 'pip install flet[all] pyinstaller' "
                "no ambiente Python usado por este projeto."
            )
            return

        self._notificar(
            f"Gerando executável '{nome_executavel}' numa janela de terminal separada "
            f"-- acompanhe o progresso ali. Quando terminar, ele fica em "
            f"'{os.path.join(PROJETO_DIR, 'dist')}'. Isso pode levar alguns minutos."
        )

    async def _gerar_instalador_click(self, e):
        if not self.caminho_arquivo:
            self._notificar("Salve o schema antes de gerar o instalador.")
            return

        caminho_iscc = _localizar_iscc()
        if not caminho_iscc:
            self._notificar(
                "Inno Setup não encontrado. Instale (grátis) em jrsoftware.org/isdl.php "
                "e tente de novo -- o instalador padrão já deixa o ISCC.exe pronto pra uso."
            )
            return

        nome_sistema = self.bruto.get("sistema", {}).get("nome", "Sistema")
        nome_executavel = re.sub(r"[^A-Za-z0-9_]+", "_", nome_sistema).strip("_") or "Sistema"
        caminho_schema = _preparar_schema_para_empacotar(self.caminho_arquivo)

        pasta_build = os.path.join(PROJETO_DIR, "dist", nome_executavel)
        pasta_saida = os.path.join(PROJETO_DIR, "dist", "instalador")

        # 1) empacota em modo "pasta" (onedir) -- o Inno Setup precisa dos
        # arquivos soltos numa pasta pra copiar, diferente do modo "arquivo
        # único" usado pelo botão "Gerar executável".
        comando_build = [
            "flet", "pack", "main.py",
            "--name", nome_executavel,
            "--onedir",
            "--add-data", f"{caminho_schema}:.",
            "--hidden-import", "appdirs",
        ]

        self._notificar(f"Gerando '{nome_executavel}'... isso pode levar alguns minutos.")
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        try:
            resultado_build = await asyncio.to_thread(
                subprocess.run, comando_build, cwd=PROJETO_DIR, creationflags=flags,
            )
        except FileNotFoundError:
            self._notificar(
                "Comando 'flet' não encontrado. Rode 'pip install flet[all] pyinstaller' "
                "no ambiente Python usado por este projeto."
            )
            return
        finally:
            # o build (bem ou mal sucedido) já terminou de ler o arquivo
            # a essa altura -- diferente do botão "Gerar executável", que
            # não espera o processo terminar e por isso não pode limpar.
            if os.path.exists(caminho_schema):
                os.remove(caminho_schema)

        if resultado_build.returncode != 0:
            self._notificar(
                f"Falha ao gerar '{nome_executavel}' (veja a janela de terminal que abriu) "
                f"-- instalador não foi criado."
            )
            return

        # 2) gera o script do Inno Setup pra essa pasta e compila o instalador
        os.makedirs(pasta_saida, exist_ok=True)
        conteudo_iss = _TEMPLATE_ISS.format(
            nome_sistema=nome_sistema,
            nome_executavel=nome_executavel,
            pasta_build=pasta_build,
            pasta_saida=pasta_saida,
        )
        caminho_iss = os.path.join(PROJETO_DIR, "dist", f"{nome_executavel}.iss")
        with open(caminho_iss, "w", encoding="utf-8") as f:
            f.write(conteudo_iss)

        self._notificar("Compilando o instalador com o Inno Setup...")
        resultado_iscc = await asyncio.to_thread(
            subprocess.run, [caminho_iscc, caminho_iss], cwd=PROJETO_DIR, creationflags=flags,
        )

        if resultado_iscc.returncode != 0:
            self._notificar(
                "Falha ao compilar o instalador (veja a janela de terminal que abriu)."
            )
            return

        self._notificar(f"Instalador pronto em '{pasta_saida}'.")

    # ------------------------------------------------------------------
    # LAYOUT GERAL
    # ------------------------------------------------------------------
    def _montar_layout(self):
        self.page.controls.clear()

        self.campo_caminho = ft.TextField(
            label="Arquivo do schema (.yaml)",
            value=self.caminho_arquivo or "",
            width=380, dense=True,
        )

        barra_arquivo = ft.Row(
            [
                self.campo_caminho,
                ft.OutlinedButton("Abrir", icon=ft.Icons.FOLDER_OPEN, on_click=self._abrir_click),
                ft.ElevatedButton("Salvar", icon=ft.Icons.SAVE, on_click=self._salvar_click),
                ft.OutlinedButton("Rodar sistema", icon=ft.Icons.PLAY_ARROW, on_click=self._rodar_sistema_click),
                ft.OutlinedButton("Gerar executável", icon=ft.Icons.INVENTORY_2,
                                  on_click=self._gerar_executavel_click),
                ft.OutlinedButton("Gerar instalador", icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                                  on_click=self._gerar_instalador_click),
            ],
            scroll=ft.ScrollMode.AUTO,
        )

        sistema = self.bruto.setdefault("sistema", {})
        self.campo_nome_sistema = ft.TextField(
            label="Nome do sistema", value=sistema.get("nome", ""), width=280, dense=True,
            on_change=lambda e: sistema.__setitem__("nome", e.control.value),
        )
        self.campo_banco = ft.TextField(
            label="Arquivo do banco (.db)", value=sistema.get("banco", "data/sistema.db"),
            width=280, dense=True,
            on_change=lambda e: sistema.__setitem__("banco", e.control.value),
        )

        painel_sistema = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Sistema", weight=ft.FontWeight.BOLD),
                    self.campo_nome_sistema,
                    self.campo_banco,
                ],
                spacing=8,
            ),
            padding=ft.Padding.only(bottom=12),
        )

        self.lista_tabelas = ft.Column(spacing=4)
        self._renderizar_lista_tabelas()

        painel_tabelas = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Tabelas", weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            ft.IconButton(ft.Icons.LIBRARY_ADD, icon_color=ft.Colors.INDIGO,
                                          tooltip="Importar módulo pronto", on_click=self._abrir_dialogo_modulos),
                            ft.IconButton(ft.Icons.ADD_CIRCLE, icon_color=ft.Colors.INDIGO,
                                          tooltip="Nova tabela", on_click=self._nova_tabela),
                        ]
                    ),
                    self.lista_tabelas,
                ],
                spacing=4, scroll=ft.ScrollMode.AUTO,
            ),
            width=280,
        )

        coluna_esquerda = ft.Column([painel_sistema, ft.Divider(), painel_tabelas], width=300)

        self.painel_detalhe = ft.Container(expand=True, padding=ft.Padding.only(left=16))
        self._renderizar_detalhe_tabela()

        self.page.add(
            ft.Column(
                [
                    ft.Text("Editor Visual de Schema", size=20, weight=ft.FontWeight.BOLD),
                    barra_arquivo,
                    ft.Divider(),
                    ft.Row([coluna_esquerda, ft.VerticalDivider(width=1), self.painel_detalhe], expand=True),
                ],
                expand=True,
            )
        )
        self.page.update()

    # ------------------------------------------------------------------
    # LISTA DE TABELAS (esquerda)
    # ------------------------------------------------------------------
    def _renderizar_lista_tabelas(self):
        self.lista_tabelas.controls.clear()
        tabelas = self.bruto.get("tabelas", [])

        if not tabelas:
            self.lista_tabelas.controls.append(ft.Text("Nenhuma tabela ainda.", size=12, color=ft.Colors.GREY_600))

        for idx, t in enumerate(tabelas):
            selecionada = idx == self.tabela_selecionada_idx
            self.lista_tabelas.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(t.get("label") or t.get("nome") or "(sem nome)", expand=True,
                                     weight=ft.FontWeight.BOLD if selecionada else ft.FontWeight.NORMAL),
                            ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=16,
                                          on_click=lambda e, i=idx: self._mover_tabela(i, -1)),
                            ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=16,
                                          on_click=lambda e, i=idx: self._mover_tabela(i, 1)),
                            ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=ft.Colors.RED,
                                          on_click=lambda e, i=idx: self._remover_tabela(i)),
                        ],
                        spacing=0,
                    ),
                    bgcolor=ft.Colors.INDIGO_50 if selecionada else None,
                    padding=6, border_radius=6,
                    on_click=lambda e, i=idx: self._selecionar_tabela(i),
                )
            )

    def _selecionar_tabela(self, idx: int):
        self.tabela_selecionada_idx = idx
        self._renderizar_lista_tabelas()
        self._renderizar_detalhe_tabela()
        self.page.update()

    def _nova_tabela(self, e):
        self.bruto.setdefault("tabelas", []).append(
            {"nome": "nova_tabela", "label": "Nova Tabela", "icone": "table_rows", "campos": []}
        )
        self.tabela_selecionada_idx = len(self.bruto["tabelas"]) - 1
        self._renderizar_lista_tabelas()
        self._renderizar_detalhe_tabela()
        self.page.update()

    # ------------------------------------------------------------------
    # MÓDULOS PRONTOS (blocos de tabelas reutilizáveis)
    # ------------------------------------------------------------------
    def _abrir_dialogo_modulos(self, e=None):
        modulos = _listar_modulos()
        if not modulos:
            self._notificar(f"Nenhum módulo encontrado em '{MODULOS_DIR}'.")
            return

        def importar(modulo: dict, e=None):
            nomes_atuais = {t.get("nome") for t in self.bruto.get("tabelas", [])}
            adicionadas, ignoradas = [], []
            for tabela_mod in modulo["tabelas"]:
                nome = tabela_mod.get("nome")
                if nome in nomes_atuais:
                    ignoradas.append(nome)
                    continue
                self.bruto.setdefault("tabelas", []).append(dict(tabela_mod))
                nomes_atuais.add(nome)
                adicionadas.append(nome)

            faltando = [dep for dep in modulo.get("depende_de", []) if dep not in nomes_atuais]

            self.page.pop_dialog()
            self._renderizar_lista_tabelas()
            self._renderizar_detalhe_tabela()
            self.page.update()

            partes = [f"Módulo '{modulo['nome']}' importado."]
            if adicionadas:
                partes.append(f"Tabelas adicionadas: {', '.join(adicionadas)}.")
            if ignoradas:
                partes.append(f"Já existiam (não duplicadas): {', '.join(ignoradas)}.")
            if faltando:
                partes.append(
                    f"Atenção: este módulo espera uma tabela chamada '{', '.join(faltando)}' "
                    f"-- confira as referências antes de rodar o sistema."
                )
            self._notificar(" ".join(partes))

        linhas_modulos = []
        for modulo in modulos:
            rotulos_tabelas = ", ".join(
                t.get("label", t.get("nome", "")) for t in modulo["tabelas"]
            )
            linhas_modulos.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(modulo["nome"], weight=ft.FontWeight.BOLD),
                            ft.Text(modulo["descricao"], size=11, color=ft.Colors.GREY_600),
                            ft.Text(f"Tabelas: {rotulos_tabelas}", size=11),
                            (
                                ft.Text(
                                    f"Depende de: {', '.join(modulo['depende_de'])}",
                                    size=11, color=ft.Colors.ORANGE_800,
                                )
                                if modulo["depende_de"] else ft.Container(height=0)
                            ),
                            ft.ElevatedButton(
                                "Importar", icon=ft.Icons.ADD,
                                on_click=lambda e, m=modulo: importar(m),
                            ),
                        ],
                        spacing=4,
                    ),
                    padding=10, border_radius=6, bgcolor=ft.Colors.GREY_100,
                )
            )

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Importar módulo pronto"),
            content=ft.Container(
                content=ft.Column(linhas_modulos, spacing=8, scroll=ft.ScrollMode.AUTO),
                width=420, height=460,
            ),
            actions=[ft.TextButton("Fechar", on_click=lambda e: self.page.pop_dialog())],
        )
        self.page.show_dialog(dialogo)

    def _mover_tabela(self, idx: int, direcao: int):
        tabelas = self.bruto["tabelas"]
        novo_idx = idx + direcao
        if 0 <= novo_idx < len(tabelas):
            tabelas[idx], tabelas[novo_idx] = tabelas[novo_idx], tabelas[idx]
            if self.tabela_selecionada_idx == idx:
                self.tabela_selecionada_idx = novo_idx
            elif self.tabela_selecionada_idx == novo_idx:
                self.tabela_selecionada_idx = idx
            self._renderizar_lista_tabelas()
            self._renderizar_detalhe_tabela()
            self.page.update()

    def _remover_tabela(self, idx: int):
        def confirmar(e):
            del self.bruto["tabelas"][idx]
            if self.tabela_selecionada_idx == idx:
                self.tabela_selecionada_idx = None
            elif self.tabela_selecionada_idx is not None and self.tabela_selecionada_idx > idx:
                self.tabela_selecionada_idx -= 1
            self.page.pop_dialog()
            self._renderizar_lista_tabelas()
            self._renderizar_detalhe_tabela()
            self.page.update()

        nome = self.bruto["tabelas"][idx].get("label", "esta tabela")
        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Remover tabela"),
            content=ft.Text(f"Remover '{nome}'? Os campos configurados serão perdidos."),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton("Remover", color=ft.Colors.WHITE, bgcolor=ft.Colors.RED, on_click=confirmar),
            ],
        )
        self.page.show_dialog(dialogo)

    # ------------------------------------------------------------------
    # DETALHE DA TABELA SELECIONADA (direita)
    # ------------------------------------------------------------------
    def _renderizar_detalhe_tabela(self):
        if self.tabela_selecionada_idx is None:
            self.painel_detalhe.content = ft.Column(
                [ft.Text("Selecione uma tabela à esquerda, ou crie uma nova.", color=ft.Colors.GREY_600)]
            )
            return

        tabela = self.bruto["tabelas"][self.tabela_selecionada_idx]

        campo_nome = ft.TextField(
            label="Nome interno (sem espaços)", value=tabela.get("nome", ""), width=250, dense=True,
            on_change=lambda e: (tabela.__setitem__("nome", e.control.value.strip()), self._renderizar_lista_tabelas(), self.page.update()),
        )
        campo_label = ft.TextField(
            label="Rótulo exibido", value=tabela.get("label", ""), width=250, dense=True,
            on_change=lambda e: (tabela.__setitem__("label", e.control.value), self._renderizar_lista_tabelas(), self.page.update()),
        )
        campo_icone = ft.Dropdown(
            label="Ícone", value=tabela.get("icone", "table_rows"), width=220, dense=True,
            options=[ft.dropdown.Option(i) for i in ICONES_SUGERIDOS],
            on_select=lambda e: tabela.__setitem__("icone", e.control.value),
        )

        lista_campos = ft.Column(spacing=4)
        campos = tabela.setdefault("campos", [])
        if not campos:
            lista_campos.controls.append(ft.Text("Nenhum campo ainda.", size=12, color=ft.Colors.GREY_600))
        for idx, c in enumerate(campos):
            lista_campos.controls.append(self._linha_campo(tabela, idx, c))

        lista_abas = ft.Column(spacing=4)
        abas = tabela.setdefault("abas", [])
        for idx, a in enumerate(abas):
            lista_abas.controls.append(self._linha_aba(tabela, idx, a))

        self.painel_detalhe.content = ft.Column(
            [
                ft.Row([campo_nome, campo_label, campo_icone], scroll=ft.ScrollMode.AUTO),
                ft.Divider(),
                ft.Row(
                    [
                        ft.Text("Campos", weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.ElevatedButton("Novo campo", icon=ft.Icons.ADD,
                                          on_click=lambda e, t=tabela: self._abrir_dialogo_campo(t)),
                    ],
                ),
                lista_campos,
                ft.Divider(),
                ft.Row(
                    [
                        ft.Text("Abas do formulário (opcional)", weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.OutlinedButton("Nova aba", icon=ft.Icons.ADD,
                                          on_click=lambda e, t=tabela: self._nova_aba(t)),
                    ],
                ),
                ft.Text(
                    "Se nenhuma aba for definida, todos os campos aparecem em uma coluna só.",
                    size=11, color=ft.Colors.GREY_600,
                ),
                lista_abas,
                ft.Divider(),
                self._secao_alerta_estoque(tabela),
                ft.Divider(),
                self._secao_baixa_estoque(tabela),
                ft.Divider(),
                self._secao_impressao(tabela),
            ],
            spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
        )

    def _linha_campo(self, tabela: dict, idx: int, campo: dict) -> ft.Control:
        detalhes = campo.get("tipo", "texto")
        if campo.get("obrigatorio"):
            detalhes += " · obrigatório"
        if campo.get("tipo") == "referencia":
            detalhes += f" · ref: {campo.get('tabela_ref', '?')}"
        if campo.get("minimo") is not None or campo.get("maximo") is not None:
            detalhes += f" · min={campo.get('minimo', '-')} max={campo.get('maximo', '-')}"
        if campo.get("largura") is not None:
            detalhes += f" · largura={campo.get('largura')}px"

        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(campo.get("label") or campo.get("nome") or "(sem nome)", weight=ft.FontWeight.BOLD),
                            ft.Text(detalhes, size=11, color=ft.Colors.GREY_600),
                        ],
                        spacing=0, expand=True,
                    ),
                    ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=16,
                                  on_click=lambda e, t=tabela, i=idx: self._mover_campo(t, i, -1)),
                    ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=16,
                                  on_click=lambda e, t=tabela, i=idx: self._mover_campo(t, i, 1)),
                    ft.IconButton(ft.Icons.EDIT, icon_size=16,
                                  on_click=lambda e, t=tabela, i=idx, c=campo: self._abrir_dialogo_campo(t, c, i)),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=ft.Colors.RED,
                                  on_click=lambda e, t=tabela, i=idx: self._remover_campo(t, i)),
                ],
            ),
            padding=8, border_radius=6, bgcolor=ft.Colors.GREY_100,
        )

    def _mover_campo(self, tabela: dict, idx: int, direcao: int):
        campos = tabela["campos"]
        novo_idx = idx + direcao
        if 0 <= novo_idx < len(campos):
            campos[idx], campos[novo_idx] = campos[novo_idx], campos[idx]
            self._renderizar_detalhe_tabela()
            self.page.update()

    def _remover_campo(self, tabela: dict, idx: int):
        del tabela["campos"][idx]
        self._renderizar_detalhe_tabela()
        self.page.update()

    # ------------------------------------------------------------------
    # ABAS
    # ------------------------------------------------------------------
    def _linha_aba(self, tabela: dict, idx: int, aba: dict) -> ft.Control:
        campo_nome_aba = ft.TextField(
            label="Nome da aba", value=aba.get("nome", ""), dense=True, width=200,
            on_change=lambda e: aba.__setitem__("nome", e.control.value),
        )
        nomes_campos_disponiveis = [c.get("nome", "") for c in tabela.get("campos", [])]
        campo_campos_aba = ft.TextField(
            label="Campos (separados por vírgula)",
            value=", ".join(aba.get("campos", [])),
            dense=True, width=320,
            hint_text=", ".join(nomes_campos_disponiveis) or "nome_do_campo, outro_campo",
            on_change=lambda e: aba.__setitem__(
                "campos", [c.strip() for c in e.control.value.split(",") if c.strip()]
            ),
        )
        return ft.Row(
            [
                campo_nome_aba, campo_campos_aba,
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=ft.Colors.RED,
                              on_click=lambda e, t=tabela, i=idx: self._remover_aba(t, i)),
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def _nova_aba(self, tabela: dict):
        tabela.setdefault("abas", []).append({"nome": "Nova aba", "campos": []})
        self._renderizar_detalhe_tabela()
        self.page.update()

    def _remover_aba(self, tabela: dict, idx: int):
        del tabela["abas"][idx]
        self._renderizar_detalhe_tabela()
        self.page.update()

    # ------------------------------------------------------------------
    # ALERTA DE ESTOQUE MÍNIMO
    # ------------------------------------------------------------------
    def _secao_alerta_estoque(self, tabela: dict) -> ft.Control:
        config = tabela.get("alerta_estoque") or {}
        campos_numericos = [
            c.get("nome", "") for c in tabela.get("campos", [])
            if c.get("tipo") in ("inteiro", "decimal")
        ]

        if len(campos_numericos) < 2:
            return ft.Column(
                [
                    ft.Text("Alerta de estoque mínimo", weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Adicione pelo menos dois campos numéricos (inteiro/decimal) "
                        "nesta tabela para habilitar -- um de quantidade e um de mínimo.",
                        size=11, color=ft.Colors.GREY_600,
                    ),
                ],
                spacing=6,
            )

        switch_ativo = ft.Switch(label="Ativo", value=bool(config.get("ativo", False)))
        campo_qtd = ft.Dropdown(
            label="Campo de quantidade", width=220, dense=True,
            value=config.get("campo_quantidade") if config.get("campo_quantidade") in campos_numericos else None,
            options=[ft.dropdown.Option(n) for n in campos_numericos],
        )
        campo_min = ft.Dropdown(
            label="Campo de estoque mínimo", width=220, dense=True,
            value=config.get("campo_minimo") if config.get("campo_minimo") in campos_numericos else None,
            options=[ft.dropdown.Option(n) for n in campos_numericos],
        )
        linha_campos = ft.Row([campo_qtd, campo_min], scroll=ft.ScrollMode.AUTO)
        linha_campos.visible = switch_ativo.value

        def salvar(e=None):
            linha_campos.visible = switch_ativo.value
            if switch_ativo.value and campo_qtd.value and campo_min.value:
                tabela["alerta_estoque"] = {
                    "ativo": True,
                    "campo_quantidade": campo_qtd.value,
                    "campo_minimo": campo_min.value,
                }
            elif not switch_ativo.value:
                tabela.pop("alerta_estoque", None)
            self.page.update()

        switch_ativo.on_change = salvar
        campo_qtd.on_select = salvar
        campo_min.on_select = salvar

        return ft.Column(
            [
                ft.Text("Alerta de estoque mínimo", weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Mostra um aviso na tela de lista quando a quantidade ficar "
                    "abaixo do mínimo configurado.",
                    size=11, color=ft.Colors.GREY_600,
                ),
                switch_ativo,
                linha_campos,
            ],
            spacing=6,
        )

    # ------------------------------------------------------------------
    # IMPRESSÃO DE CUPOM
    # ------------------------------------------------------------------
    def _secao_impressao(self, tabela: dict) -> ft.Control:
        config = tabela.get("impressao") or {}
        nomes_campos = [c.get("nome", "") for c in tabela.get("campos", [])]
        campos_selecionados = set(config.get("campos", []))

        switch_ativo = ft.Switch(label="Ativo", value=bool(config.get("ativo", False)))
        campo_titulo = ft.TextField(label="Título do cupom", value=config.get("titulo", ""), width=250, dense=True)
        campo_rodape = ft.TextField(label="Rodapé", value=config.get("rodape", ""), width=250, dense=True)
        switch_auto = ft.Switch(
            label="Imprimir automaticamente ao salvar um registro novo",
            value=bool(config.get("auto_imprimir", False)),
        )
        checkboxes_campos = {
            nome: ft.Checkbox(label=nome, value=nome in campos_selecionados)
            for nome in nomes_campos
        }

        conteudo_extra = ft.Column(
            [
                campo_titulo,
                ft.Text("Campos que entram no cupom:", size=12),
                (
                    ft.Column(list(checkboxes_campos.values()), spacing=2)
                    if checkboxes_campos
                    else ft.Text("Nenhum campo nesta tabela.", size=11, color=ft.Colors.GREY_600)
                ),
                campo_rodape,
                switch_auto,
            ],
            spacing=8,
        )
        conteudo_extra.visible = switch_ativo.value

        def salvar(e=None):
            conteudo_extra.visible = switch_ativo.value
            if switch_ativo.value:
                tabela["impressao"] = {
                    "ativo": True,
                    "titulo": campo_titulo.value,
                    "campos": [nome for nome, cb in checkboxes_campos.items() if cb.value],
                    "rodape": campo_rodape.value,
                    "auto_imprimir": switch_auto.value,
                }
            else:
                tabela.pop("impressao", None)
            self.page.update()

        switch_ativo.on_change = salvar
        campo_titulo.on_change = salvar
        campo_rodape.on_change = salvar
        switch_auto.on_change = salvar
        for cb in checkboxes_campos.values():
            cb.on_change = salvar

        return ft.Column(
            [
                ft.Text("Impressão de cupom (impressora térmica)", weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Configure a impressora uma vez em sistema.impressora no YAML "
                    "(usb/rede/serial/arquivo) -- aqui você só liga o cupom desta tabela.",
                    size=11, color=ft.Colors.GREY_600,
                ),
                switch_ativo,
                conteudo_extra,
            ],
            spacing=6,
        )

    # ------------------------------------------------------------------
    # BAIXA AUTOMÁTICA DE ESTOQUE
    # ------------------------------------------------------------------
    def _campos_numericos_de(self, nome_tabela: str | None) -> list[str]:
        alvo = next((t for t in self.bruto.get("tabelas", []) if t.get("nome") == nome_tabela), None)
        if not alvo:
            return []
        return [c.get("nome", "") for c in alvo.get("campos", []) if c.get("tipo") in ("inteiro", "decimal")]

    def _secao_baixa_estoque(self, tabela: dict) -> ft.Control:
        config = tabela.get("baixa_estoque") or {}
        campos_referencia = [c.get("nome", "") for c in tabela.get("campos", []) if c.get("tipo") == "referencia"]
        campos_numericos_aqui = self._campos_numericos_de(tabela.get("nome"))
        outras_tabelas = [t.get("nome", "") for t in self.bruto.get("tabelas", []) if t is not tabela]

        if not campos_referencia or not campos_numericos_aqui or not outras_tabelas:
            return ft.Column(
                [
                    ft.Text("Baixa automática de estoque", weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Precisa de: um campo do tipo referência (pro produto), um campo "
                        "numérico nesta tabela (a quantidade) e outra tabela pra guardar "
                        "o estoque.",
                        size=11, color=ft.Colors.GREY_600,
                    ),
                ],
                spacing=6,
            )

        switch_ativo = ft.Switch(label="Ativo", value=bool(config.get("ativo", False)))
        campo_tabela_estoque = ft.Dropdown(
            label="Tabela de estoque", width=200, dense=True,
            value=config.get("tabela_estoque") if config.get("tabela_estoque") in outras_tabelas else None,
            options=[ft.dropdown.Option(n) for n in outras_tabelas],
        )
        campo_produto = ft.Dropdown(
            label="Campo do produto (referência)", width=230, dense=True,
            value=config.get("campo_produto") if config.get("campo_produto") in campos_referencia else None,
            options=[ft.dropdown.Option(n) for n in campos_referencia],
        )
        campo_quantidade = ft.Dropdown(
            label="Campo de quantidade (aqui)", width=200, dense=True,
            value=config.get("campo_quantidade") if config.get("campo_quantidade") in campos_numericos_aqui else None,
            options=[ft.dropdown.Option(n) for n in campos_numericos_aqui],
        )
        opcoes_estoque_iniciais = self._campos_numericos_de(campo_tabela_estoque.value)
        campo_estoque = ft.Dropdown(
            label="Campo de estoque (na tabela acima)", width=230, dense=True,
            value=config.get("campo_estoque") if config.get("campo_estoque") in opcoes_estoque_iniciais else None,
            options=[ft.dropdown.Option(n) for n in opcoes_estoque_iniciais],
        )

        linha1 = ft.Row([campo_tabela_estoque, campo_produto], scroll=ft.ScrollMode.AUTO)
        linha2 = ft.Row([campo_quantidade, campo_estoque], scroll=ft.ScrollMode.AUTO)
        linha1.visible = switch_ativo.value
        linha2.visible = switch_ativo.value

        def salvar(e=None):
            linha1.visible = switch_ativo.value
            linha2.visible = switch_ativo.value
            if switch_ativo.value and all([
                campo_tabela_estoque.value, campo_produto.value,
                campo_quantidade.value, campo_estoque.value,
            ]):
                tabela["baixa_estoque"] = {
                    "ativo": True,
                    "tabela_estoque": campo_tabela_estoque.value,
                    "campo_produto": campo_produto.value,
                    "campo_quantidade": campo_quantidade.value,
                    "campo_estoque": campo_estoque.value,
                }
            elif not switch_ativo.value:
                tabela.pop("baixa_estoque", None)
            self.page.update()

        def trocar_tabela_estoque(e=None):
            opcoes = self._campos_numericos_de(campo_tabela_estoque.value)
            campo_estoque.options = [ft.dropdown.Option(n) for n in opcoes]
            if campo_estoque.value not in opcoes:
                campo_estoque.value = None
            salvar()

        switch_ativo.on_change = salvar
        campo_tabela_estoque.on_select = trocar_tabela_estoque
        campo_produto.on_select = salvar
        campo_quantidade.on_select = salvar
        campo_estoque.on_select = salvar

        return ft.Column(
            [
                ft.Text("Baixa automática de estoque", weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Ao salvar um registro novo aqui, desconta a quantidade do estoque "
                    "do produto referenciado -- e devolve se o registro for editado ou "
                    "excluído depois.",
                    size=11, color=ft.Colors.GREY_600,
                ),
                switch_ativo,
                linha1,
                linha2,
            ],
            spacing=6,
        )

    # ------------------------------------------------------------------
    # DIÁLOGO DE CAMPO (criar/editar)
    # ------------------------------------------------------------------
    def _abrir_dialogo_campo(self, tabela: dict, campo: dict | None = None, idx: int | None = None):
        editando = campo is not None
        c = dict(campo) if campo else {"nome": "", "label": "", "tipo": "texto", "obrigatorio": False, "buscavel": False}

        outras_tabelas = [t.get("nome", "") for t in self.bruto.get("tabelas", []) if t is not tabela]

        campo_nome = ft.TextField(label="Nome interno (sem espaços)", value=c.get("nome", ""), width=250)
        campo_label = ft.TextField(label="Rótulo exibido", value=c.get("label", ""), width=250)
        campo_default = ft.TextField(label="Valor padrão (opcional)", value=_texto_default(c.get("default")), width=250)
        campo_obrigatorio = ft.Switch(label="Obrigatório", value=bool(c.get("obrigatorio", False)))
        campo_buscavel = ft.Switch(label="Aparece na busca", value=bool(c.get("buscavel", False)))

        campo_minimo = ft.TextField(label="Valor mínimo (opcional)", value=_texto_default(c.get("minimo")), width=180)
        campo_maximo = ft.TextField(label="Valor máximo (opcional)", value=_texto_default(c.get("maximo")), width=180)
        linha_min_max = ft.Row([campo_minimo, campo_maximo], scroll=ft.ScrollMode.AUTO)

        campo_largura = ft.TextField(
            label="Largura da coluna na lista, em px (opcional)",
            value=_texto_default(c.get("largura")), width=250,
            hint_text="deixe em branco para calcular automaticamente",
        )

        campo_tabela_ref = ft.Dropdown(
            label="Tabela referenciada", width=250,
            value=c.get("tabela_ref"),
            options=[ft.dropdown.Option(n) for n in outras_tabelas],
        )
        campo_exibicao_ref = ft.TextField(label="Campo a exibir (dessa tabela)", value=c.get("campo_exibicao", ""), width=250)
        linha_referencia = ft.Row([campo_tabela_ref, campo_exibicao_ref], scroll=ft.ScrollMode.AUTO)

        def atualizar_visibilidade(e=None):
            tipo = campo_tipo.value
            linha_min_max.visible = tipo in ("inteiro", "decimal")
            linha_referencia.visible = tipo == "referencia"
            campo_default.visible = tipo != "referencia"
            self.page.update()

        campo_tipo = ft.Dropdown(
            label="Tipo do campo", width=250, value=c.get("tipo", "texto"),
            options=[ft.dropdown.Option(key=v, text=lbl) for v, lbl in TIPOS_CAMPO],
            on_select=atualizar_visibilidade,
        )

        mensagem_erro = ft.Text("", color=ft.Colors.RED, size=12)

        def salvar(e):
            nome = campo_nome.value.strip()
            if not nome:
                mensagem_erro.value = "O nome interno do campo é obrigatório."
                self.page.update()
                return

            novo = {
                "nome": nome,
                "label": campo_label.value.strip() or nome,
                "tipo": campo_tipo.value,
                "obrigatorio": campo_obrigatorio.value,
                "buscavel": campo_buscavel.value,
            }

            default_valor = _cast_default(campo_tipo.value, campo_default.value.strip())
            if default_valor is not None:
                novo["default"] = default_valor

            if campo_tipo.value in ("inteiro", "decimal"):
                if campo_minimo.value.strip():
                    try:
                        novo["minimo"] = float(campo_minimo.value.strip())
                    except ValueError:
                        mensagem_erro.value = "Valor mínimo inválido."
                        self.page.update()
                        return
                if campo_maximo.value.strip():
                    try:
                        novo["maximo"] = float(campo_maximo.value.strip())
                    except ValueError:
                        mensagem_erro.value = "Valor máximo inválido."
                        self.page.update()
                        return

            if campo_largura.value.strip():
                try:
                    novo["largura"] = float(campo_largura.value.strip())
                except ValueError:
                    mensagem_erro.value = "Largura da coluna inválida."
                    self.page.update()
                    return

            if campo_tipo.value == "referencia":
                if not campo_tabela_ref.value or not campo_exibicao_ref.value.strip():
                    mensagem_erro.value = "Campos de referência precisam de tabela e campo a exibir."
                    self.page.update()
                    return
                novo["tabela_ref"] = campo_tabela_ref.value
                novo["campo_exibicao"] = campo_exibicao_ref.value.strip()

            if editando:
                tabela["campos"][idx] = novo
            else:
                tabela.setdefault("campos", []).append(novo)

            self.page.pop_dialog()
            self._renderizar_detalhe_tabela()
            self.page.update()

        atualizar_visibilidade()

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar campo" if editando else "Novo campo"),
            content=ft.Container(
                content=ft.Column(
                    [
                        campo_nome, campo_label, campo_tipo,
                        ft.Row([campo_obrigatorio, campo_buscavel], scroll=ft.ScrollMode.AUTO),
                        campo_default,
                        linha_min_max,
                        linha_referencia,
                        campo_largura,
                        mensagem_erro,
                    ],
                    tight=True, spacing=10, scroll=ft.ScrollMode.AUTO,
                ),
                width=440, height=470,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton("Salvar", on_click=salvar),
            ],
        )
        self.page.show_dialog(dialogo)

    def _notificar(self, mensagem: str):
        self.page.show_dialog(ft.SnackBar(ft.Text(mensagem)))


def rodar_editor(caminho_inicial: str | None = None):
    def main(page: ft.Page):
        SchemaEditorApp(page, caminho_inicial)

    ft.app(target=main)
