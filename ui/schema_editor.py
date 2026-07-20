"""
Editor visual de schema. Tela dentro do próprio gerador para montar
tabelas e campos através de formulários e botões (adicionar, editar,
remover, reordenar), em vez de editar o arquivo .yaml na mão.

Trabalha diretamente sobre o dicionário "bruto" carregado do YAML (não
sobre os dataclasses de engine/schema_loader.py), para que seções que o
editor ainda não sabe montar visualmente (ex: configuração de
impressora, fiscal por tabela) sejam preservadas ao salvar.
"""
import os
import subprocess
import sys

import flet as ft
import yaml

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
