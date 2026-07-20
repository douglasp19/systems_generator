"""
Interface gráfica (Flet). Todas as telas de tabela (lista + formulário)
são geradas dinamicamente a partir do schema -- não existe uma tela
"produtos.py" ou "fornecedores.py" escrita à mão. Se você adicionar uma
tabela nova no YAML, a tela aparece sozinha aqui.
"""
import os
import flet as ft

from engine.schema_loader import Schema, Tabela, Campo
from engine import db, auth, audit, export, backup, printer, fiscal


class SistemaApp:
    def __init__(self, page: ft.Page, schema: Schema, conn):
        self.page = page
        self.schema = schema
        self.conn = conn
        self.usuario_logado: dict | None = None

        self.page.title = schema.nome_sistema
        self.page.window.width = 1100
        self.page.window.height = 720
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)

        self._mostrar_login()

    # ------------------------------------------------------------------
    # LOGIN
    # ------------------------------------------------------------------
    def _mostrar_login(self):
        self.page.controls.clear()

        # Se ainda não existe nenhum usuário, cria o admin padrão
        primeiro_acesso = not auth.existe_algum_usuario(self.conn)
        if primeiro_acesso:
            auth.criar_usuario(self.conn, "admin", "admin", papel="admin")

        campo_usuario = ft.TextField(label="Usuário", width=300, autofocus=True)
        campo_senha = ft.TextField(label="Senha", width=300, password=True, can_reveal_password=True)
        texto_erro = ft.Text("", color=ft.Colors.RED)

        aviso = ft.Text(
            "Primeiro acesso: usuário 'admin', senha 'admin' (altere depois em Usuários).",
            size=12, color=ft.Colors.GREY_600, visible=primeiro_acesso,
        )

        def fazer_login(e):
            usr = auth.autenticar(self.conn, campo_usuario.value or "", campo_senha.value or "")
            if usr:
                self.usuario_logado = usr
                audit.registrar(self.conn, "_login", None, "login", usr["usuario"])
                self._mostrar_app_principal()
            else:
                texto_erro.value = "Usuário ou senha inválidos."
                self.page.update()

        campo_senha.on_submit = fazer_login

        self.page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.LOCK_OUTLINE, size=48, color=ft.Colors.INDIGO),
                        ft.Text(self.schema.nome_sistema, size=22, weight=ft.FontWeight.BOLD),
                        ft.Container(height=10),
                        campo_usuario,
                        campo_senha,
                        texto_erro,
                        ft.ElevatedButton("Entrar", on_click=fazer_login, width=300),
                        aviso,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
                alignment=ft.Alignment.CENTER,
                expand=True,
            )
        )
        self.page.update()

    # ------------------------------------------------------------------
    # APP PRINCIPAL (após login)
    # ------------------------------------------------------------------
    def _mostrar_app_principal(self):
        self.page.controls.clear()

        destinos = []
        for t in self.schema.tabelas:
            destinos.append(
                ft.NavigationRailDestination(
                    icon=getattr(ft.Icons, t.icone.upper(), ft.Icons.TABLE_ROWS),
                    label=t.label,
                )
            )
        destinos.append(ft.NavigationRailDestination(icon=ft.Icons.HISTORY, label="Auditoria"))
        if self.usuario_logado["papel"] == "admin":
            destinos.append(ft.NavigationRailDestination(icon=ft.Icons.PEOPLE, label="Usuários"))
        destinos.append(ft.NavigationRailDestination(icon=ft.Icons.SAVE, label="Backup"))

        self.area_conteudo = ft.Container(expand=True, padding=20)

        def trocar_tela(e):
            idx = e.control.selected_index
            if idx < len(self.schema.tabelas):
                self._tela_tabela(self.schema.tabelas[idx])
            elif idx == len(self.schema.tabelas):
                self._tela_auditoria()
            elif self.usuario_logado["papel"] == "admin" and idx == len(self.schema.tabelas) + 1:
                self._tela_usuarios()
            else:
                self._tela_backup()

        rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=90,
            min_extended_width=180,
            destinations=destinos,
            on_change=trocar_tela,
        )

        cabecalho = ft.Row(
            [
                ft.Text(self.schema.nome_sistema, size=18, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.Text(f"Usuário: {self.usuario_logado['usuario']} ({self.usuario_logado['papel']})", size=12),
                ft.IconButton(ft.Icons.LOGOUT, tooltip="Sair", on_click=lambda e: self._mostrar_login()),
            ]
        )

        self.page.add(
            ft.Column(
                [
                    cabecalho,
                    ft.Divider(height=1),
                    ft.Row([rail, ft.VerticalDivider(width=1), self.area_conteudo], expand=True),
                ],
                expand=True,
            )
        )

        if self.schema.tabelas:
            self._tela_tabela(self.schema.tabelas[0])
        self.page.update()

    # ------------------------------------------------------------------
    # TELA GENÉRICA DE TABELA (lista + busca + ações)
    # ------------------------------------------------------------------
    def _tela_tabela(self, tabela: Tabela):
        campo_busca = ft.TextField(
            label="Buscar", prefix_icon=ft.Icons.SEARCH, width=300, dense=True
        )
        tabela_dados = ft.DataTable(columns=self._colunas_datatable(tabela), rows=[])

        def recarregar(e=None):
            registros = db.listar(self.conn, tabela, busca=campo_busca.value or "")
            tabela_dados.rows = [self._linha_datatable(tabela, r) for r in registros]
            self.page.update()

        campo_busca.on_change = recarregar

        def exportar_csv_click(e):
            registros = db.listar(self.conn, tabela, busca=campo_busca.value or "")
            caminho = f"exports/{tabela.nome}.csv"
            export.exportar_csv(tabela, registros, caminho)
            self._notificar(f"Exportado para {caminho}")

        def exportar_excel_click(e):
            registros = db.listar(self.conn, tabela, busca=campo_busca.value or "")
            caminho = f"exports/{tabela.nome}.xlsx"
            export.exportar_excel(tabela, registros, caminho)
            self._notificar(f"Exportado para {caminho}")

        barra_acoes = ft.Row(
            [
                campo_busca,
                ft.Container(expand=True),
                ft.OutlinedButton("Exportar CSV", icon=ft.Icons.DOWNLOAD, on_click=exportar_csv_click),
                ft.OutlinedButton("Exportar Excel", icon=ft.Icons.DOWNLOAD, on_click=exportar_excel_click),
                ft.ElevatedButton(
                    f"Novo {tabela.label[:-1] if tabela.label.endswith('s') else tabela.label}",
                    icon=ft.Icons.ADD,
                    on_click=lambda e: self._abrir_formulario(tabela, recarregar),
                ),
            ]
        )

        self.area_conteudo.content = ft.Column(
            [
                ft.Text(tabela.label, size=20, weight=ft.FontWeight.BOLD),
                barra_acoes,
                ft.Container(content=ft.Column([tabela_dados], scroll=ft.ScrollMode.AUTO), expand=True),
            ],
            expand=True,
        )
        # guardamos referências para reaproveitar no formulário (editar/excluir)
        self._tabela_dados_atual = tabela_dados
        self._recarregar_atual = recarregar
        recarregar()
        self.page.update()

    def _colunas_datatable(self, tabela: Tabela) -> list[ft.DataColumn]:
        colunas = [ft.DataColumn(ft.Text("ID"))]
        for c in tabela.campos:
            colunas.append(ft.DataColumn(ft.Text(c.label)))
        colunas.append(ft.DataColumn(ft.Text("Ações")))
        return colunas

    def _linha_datatable(self, tabela: Tabela, registro: dict) -> ft.DataRow:
        # Resolve os campos de referência (ex: produto_id -> "Parafuso 6mm")
        # para exibir o rótulo em vez do número do id.
        registro_exibicao = db.registro_para_exibicao(self.conn, tabela, registro)

        celulas = [ft.DataCell(ft.Text(str(registro["id"])))]
        for c in tabela.campos:
            valor = registro_exibicao.get(c.nome)
            celulas.append(ft.DataCell(ft.Text(self._formatar_valor(c, valor))))

        botoes_acao = [
            ft.IconButton(
                ft.Icons.EDIT, icon_size=18,
                tooltip="Editar",
                on_click=lambda e, r=registro: self._abrir_formulario(
                    tabela, self._recarregar_atual, registro=r
                ),
            ),
            ft.IconButton(
                ft.Icons.DELETE_OUTLINE, icon_size=18, icon_color=ft.Colors.RED,
                tooltip="Excluir",
                on_click=lambda e, r=registro: self._confirmar_exclusao(tabela, r),
            ),
        ]

        if tabela.impressao.ativo:
            botoes_acao.append(
                ft.IconButton(
                    ft.Icons.PRINT, icon_size=18, icon_color=ft.Colors.BLUE_GREY,
                    tooltip="Imprimir cupom",
                    on_click=lambda e, r=registro_exibicao: self._imprimir_cupom(tabela, r),
                )
            )

        if tabela.fiscal.ativo:
            botoes_acao.append(
                ft.IconButton(
                    ft.Icons.RECEIPT_LONG, icon_size=18, icon_color=ft.Colors.GREEN_800,
                    tooltip="Emitir nota fiscal",
                    on_click=lambda e, r=registro: self._emitir_nota_fiscal(tabela, r),
                )
            )

        celulas.append(ft.DataCell(ft.Row(botoes_acao, spacing=0)))
        return ft.DataRow(cells=celulas)

    def _formatar_valor(self, campo: Campo, valor) -> str:
        if valor is None:
            return ""
        if campo.tipo == "booleano":
            return "Sim" if valor else "Não"
        if campo.tipo == "decimal":
            try:
                return f"{float(valor):.2f}"
            except (TypeError, ValueError):
                return str(valor)
        return str(valor)

    # ------------------------------------------------------------------
    # IMPRESSÃO DE CUPOM E EMISSÃO DE NOTA FISCAL
    # ------------------------------------------------------------------
    def _imprimir_cupom(self, tabela: Tabela, registro_exibicao: dict):
        try:
            resultado = printer.imprimir_cupom(self.schema.impressora, tabela, registro_exibicao)
            audit.registrar(self.conn, tabela.nome, registro_exibicao.get("id"), "imprimir_cupom",
                             self.usuario_logado["usuario"])
            self._notificar(resultado)
        except printer.ErroImpressora as e:
            self._notificar(f"Erro ao imprimir: {e}")

    def _emitir_nota_fiscal(self, tabela: Tabela, registro: dict):
        try:
            resultado = fiscal.emitir(self.conn, self.schema, tabela, registro)
            audit.registrar(
                self.conn, tabela.nome, registro.get("id"),
                "emitir_nota_simulada" if resultado.simulado else "emitir_nota",
                self.usuario_logado["usuario"], resultado.mensagem[:200],
            )
            self._mostrar_resultado_fiscal(resultado)
        except fiscal.ErroFiscal as e:
            self._notificar(f"Erro ao emitir nota: {e}")

    def _mostrar_resultado_fiscal(self, resultado: "fiscal.ResultadoEmissao"):
        cor_titulo = ft.Colors.ORANGE if resultado.simulado else ft.Colors.GREEN
        titulo = "Modo simulação" if resultado.simulado else "Nota emitida"

        conteudo = [ft.Text(resultado.mensagem, size=13)]
        if resultado.numero_nota:
            conteudo.append(ft.Text(f"Número: {resultado.numero_nota}"))
        if resultado.protocolo:
            conteudo.append(ft.Text(f"Protocolo: {resultado.protocolo}"))
        if resultado.url_danfe:
            conteudo.append(ft.Text(f"DANFE: {resultado.url_danfe}"))

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text(titulo, color=cor_titulo, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=ft.Column(conteudo, tight=True), width=420),
            actions=[ft.TextButton("Fechar", on_click=lambda e: self.page.close(dialogo))],
        )
        self.page.open(dialogo)

    # ------------------------------------------------------------------
    # FORMULÁRIO GENÉRICO (criar/editar) - gerado a partir dos campos
    # ------------------------------------------------------------------
    def _abrir_formulario(self, tabela: Tabela, recarregar, registro: dict | None = None):
        editando = registro is not None
        controles_por_campo: dict[str, ft.Control] = {}

        for c in tabela.campos:
            valor_atual = registro.get(c.nome) if registro else c.default
            controles_por_campo[c.nome] = self._criar_input(c, valor_atual)

        mensagem_erro = ft.Text("", color=ft.Colors.RED, size=12)

        def salvar(e):
            dados = {}
            for c in tabela.campos:
                ctrl = controles_por_campo[c.nome]
                valor = self._extrair_valor(c, ctrl)

                if c.obrigatorio and (valor is None or valor == ""):
                    mensagem_erro.value = f"O campo '{c.label}' é obrigatório."
                    self.page.update()
                    return

                erro_validacao = c.validar(valor)
                if erro_validacao:
                    mensagem_erro.value = erro_validacao
                    self.page.update()
                    return

                dados[c.nome] = valor

            if editando:
                db.atualizar(self.conn, tabela, registro["id"], dados)
                audit.registrar(self.conn, tabela.nome, registro["id"], "editar",
                                 self.usuario_logado["usuario"])
            else:
                novo_id = db.inserir(self.conn, tabela, dados)
                audit.registrar(self.conn, tabela.nome, novo_id, "criar",
                                 self.usuario_logado["usuario"])

            self.page.close(dialogo)
            recarregar()
            self._notificar("Salvo com sucesso.")

        altura_conteudo = min(60 + 70 * len(tabela.campos), 500)

        if tabela.abas:
            # Layout em abas, implementado manualmente com botões + um
            # container que troca de conteúdo (mais simples e estável
            # entre versões do Flet do que o widget Tabs embutido).
            conteudo_da_aba = ft.Container(padding=ft.Padding.only(top=12))
            botoes_aba: list[ft.TextButton] = []

            def mostrar_aba(indice_aba):
                aba = tabela.abas[indice_aba]
                controles_da_aba = [
                    controles_por_campo[nome_campo]
                    for nome_campo in aba.campos
                    if nome_campo in controles_por_campo
                ]
                conteudo_da_aba.content = ft.Column(
                    controles_da_aba, tight=True, spacing=10, scroll=ft.ScrollMode.AUTO
                )
                for i, botao in enumerate(botoes_aba):
                    botao.style = ft.ButtonStyle(
                        color=ft.Colors.INDIGO if i == indice_aba else ft.Colors.GREY_600,
                    )
                self.page.update()

            for indice, aba in enumerate(tabela.abas):
                botoes_aba.append(
                    ft.TextButton(aba.nome, on_click=lambda e, i=indice: mostrar_aba(i))
                )

            mostrar_aba(0)  # abre a primeira aba por padrão

            conteudo_formulario = ft.Column(
                [
                    ft.Row(botoes_aba, spacing=4),
                    ft.Divider(height=1),
                    conteudo_da_aba,
                    mensagem_erro,
                ],
                tight=True,
            )
        else:
            # Sem abas definidas no YAML: todos os campos em uma coluna só.
            conteudo_formulario = ft.Column(
                [controles_por_campo[c.nome] for c in tabela.campos] + [mensagem_erro],
                tight=True, scroll=ft.ScrollMode.AUTO, spacing=10,
            )

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text(("Editar " if editando else "Novo ") + (tabela.label[:-1] if tabela.label.endswith("s") else tabela.label)),
            content=ft.Container(content=conteudo_formulario, width=440, height=altura_conteudo),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.close(dialogo)),
                ft.ElevatedButton("Salvar", on_click=salvar),
            ],
        )
        self.page.open(dialogo)

    def _criar_input(self, campo: Campo, valor_atual) -> ft.Control:
        if campo.tipo == "referencia":
            opcoes = db.opcoes_referencia(self.conn, campo)
            return ft.Dropdown(
                label=campo.label,
                value=str(valor_atual) if valor_atual is not None else None,
                options=[ft.dropdown.Option(key=str(id_), text=rotulo) for id_, rotulo in opcoes],
            )
        if campo.tipo == "booleano":
            return ft.Switch(label=campo.label, value=bool(valor_atual))
        if campo.tipo == "texto_longo":
            return ft.TextField(label=campo.label, value=str(valor_atual or ""), multiline=True, min_lines=3, max_lines=5)
        if campo.tipo in ("inteiro", "decimal"):
            return ft.TextField(
                label=campo.label,
                value="" if valor_atual is None else str(valor_atual),
                keyboard_type=ft.KeyboardType.NUMBER,
            )
        if campo.tipo == "data":
            return ft.TextField(
                label=campo.label + " (AAAA-MM-DD)",
                value=str(valor_atual or ""),
                hint_text="2026-07-18",
            )
        return ft.TextField(label=campo.label, value=str(valor_atual or ""))

    def _extrair_valor(self, campo: Campo, controle: ft.Control):
        if campo.tipo == "referencia":
            return int(controle.value) if controle.value else None
        if campo.tipo == "booleano":
            return 1 if controle.value else 0
        if campo.tipo == "inteiro":
            try:
                return int(controle.value) if controle.value != "" else None
            except ValueError:
                return None
        if campo.tipo == "decimal":
            try:
                return float(controle.value) if controle.value != "" else None
            except ValueError:
                return None
        return controle.value

    def _confirmar_exclusao(self, tabela: Tabela, registro: dict):
        def excluir(e):
            db.excluir(self.conn, tabela, registro["id"])
            audit.registrar(self.conn, tabela.nome, registro["id"], "excluir",
                             self.usuario_logado["usuario"])
            self.page.close(dialogo)
            self._recarregar_atual()
            self._notificar("Registro excluído.")

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar exclusão"),
            content=ft.Text(f"Tem certeza que deseja excluir o registro #{registro['id']}?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.close(dialogo)),
                ft.ElevatedButton("Excluir", icon=ft.Icons.DELETE, on_click=excluir,
                                   color=ft.Colors.WHITE, bgcolor=ft.Colors.RED),
            ],
        )
        self.page.open(dialogo)

    # ------------------------------------------------------------------
    # AUDITORIA
    # ------------------------------------------------------------------
    def _tela_auditoria(self):
        registros = audit.listar(self.conn)
        linhas = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(r["id"]))),
                ft.DataCell(ft.Text(r["criado_em"])),
                ft.DataCell(ft.Text(r["usuario"] or "")),
                ft.DataCell(ft.Text(r["tabela"])),
                ft.DataCell(ft.Text(r["acao"])),
                ft.DataCell(ft.Text(str(r["registro_id"]) if r["registro_id"] else "-")),
            ])
            for r in registros
        ]
        tabela_dados = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("ID")), ft.DataColumn(ft.Text("Data/Hora")),
                ft.DataColumn(ft.Text("Usuário")), ft.DataColumn(ft.Text("Tabela")),
                ft.DataColumn(ft.Text("Ação")), ft.DataColumn(ft.Text("Registro")),
            ],
            rows=linhas,
        )
        self.area_conteudo.content = ft.Column(
            [ft.Text("Auditoria", size=20, weight=ft.FontWeight.BOLD),
             ft.Container(content=ft.Column([tabela_dados], scroll=ft.ScrollMode.AUTO), expand=True)],
            expand=True,
        )
        self.page.update()

    # ------------------------------------------------------------------
    # USUÁRIOS (apenas admin)
    # ------------------------------------------------------------------
    def _tela_usuarios(self):
        usuarios = auth.listar_usuarios(self.conn)
        linhas = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(u["id"]))),
                ft.DataCell(ft.Text(u["usuario"])),
                ft.DataCell(ft.Text(u["papel"])),
                ft.DataCell(ft.Text("Ativo" if u["ativo"] else "Inativo")),
            ])
            for u in usuarios
        ]
        tabela_dados = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("ID")), ft.DataColumn(ft.Text("Usuário")),
                     ft.DataColumn(ft.Text("Papel")), ft.DataColumn(ft.Text("Status"))],
            rows=linhas,
        )

        campo_usuario = ft.TextField(label="Novo usuário", width=200)
        campo_senha = ft.TextField(label="Senha", width=200, password=True, can_reveal_password=True)
        campo_papel = ft.Dropdown(
            label="Papel", width=150,
            options=[ft.dropdown.Option("usuario"), ft.dropdown.Option("admin")],
            value="usuario",
        )

        def criar(e):
            if campo_usuario.value and campo_senha.value:
                auth.criar_usuario(self.conn, campo_usuario.value, campo_senha.value, campo_papel.value)
                self._tela_usuarios()

        self.area_conteudo.content = ft.Column(
            [
                ft.Text("Usuários", size=20, weight=ft.FontWeight.BOLD),
                ft.Row([campo_usuario, campo_senha, campo_papel,
                        ft.ElevatedButton("Adicionar", icon=ft.Icons.ADD, on_click=criar)]),
                ft.Divider(),
                ft.Container(content=ft.Column([tabela_dados], scroll=ft.ScrollMode.AUTO), expand=True),
            ],
            expand=True,
        )
        self.page.update()

    # ------------------------------------------------------------------
    # BACKUP
    # ------------------------------------------------------------------
    def _tela_backup(self):
        lista_backups = backup.listar_backups()

        def fazer_backup_click(e):
            destino = backup.fazer_backup(self.schema.banco_path)
            audit.registrar(self.conn, "_sistema", None, "backup", self.usuario_logado["usuario"], destino)
            self._notificar(f"Backup criado: {destino}")
            self._tela_backup()

        self.area_conteudo.content = ft.Column(
            [
                ft.Text("Backup do banco de dados", size=20, weight=ft.FontWeight.BOLD),
                ft.ElevatedButton("Fazer backup agora", icon=ft.Icons.SAVE, on_click=fazer_backup_click),
                ft.Divider(),
                ft.Text("Backups existentes:", weight=ft.FontWeight.BOLD),
                ft.Column([ft.Text(b) for b in lista_backups] or [ft.Text("Nenhum backup ainda.")]),
            ]
        )
        self.page.update()

    def _notificar(self, mensagem: str):
        self.page.open(ft.SnackBar(ft.Text(mensagem)))


def rodar_app(schema: Schema):
    conn = db.conectar(schema.banco_path)
    db.garantir_schema(conn, schema)

    def main(page: ft.Page):
        SistemaApp(page, schema, conn)

    ft.app(target=main)
