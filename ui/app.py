"""
Interface gráfica (Flet). Todas as telas de tabela (lista + formulário)
são geradas dinamicamente a partir do schema -- não existe uma tela
"produtos.py" ou "fornecedores.py" escrita à mão. Se você adicionar uma
tabela nova no YAML, a tela aparece sozinha aqui.
"""
import os
import flet as ft

from engine.schema_loader import Schema, Tabela, Campo
from engine import db, auth, audit, export, backup, printer, fiscal, preferencias, estoque, configuracoes


def _texto_largura(valor) -> str:
    """Formata uma largura numérica (ou None) para exibir num TextField."""
    if valor is None:
        return ""
    return str(int(valor)) if float(valor).is_integer() else str(valor)


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
                if self.schema.fiscal.ativo:
                    self._tentar_reenviar_pendentes_silencioso()
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
    def _abas_visiveis(self):
        """Filtra as abas do sistema conforme as permissões do usuário
        logado. Admin sempre vê tudo. Usuário comum só vê o que o admin
        marcou explicitamente ao criar/editar a conta -- enquanto isso não
        for configurado, vê tudo (comportamento padrão)."""
        fiscal_ativo = self.schema.fiscal.ativo

        if self.usuario_logado["papel"] == "admin":
            return list(self.schema.tabelas), True, True, fiscal_ativo

        if not auth.permissoes_configuradas(self.conn, self.usuario_logado["id"]):
            return list(self.schema.tabelas), True, True, fiscal_ativo

        permitidas = auth.permissoes_usuario(self.conn, self.usuario_logado["id"])
        tabelas_visiveis = [t for t in self.schema.tabelas if t.nome in permitidas]
        mostrar_fiscal_pendente = fiscal_ativo and "_fiscal_pendente" in permitidas
        return tabelas_visiveis, "_auditoria" in permitidas, "_backup" in permitidas, mostrar_fiscal_pendente

    def _mostrar_app_principal(self):
        self.page.controls.clear()

        tabelas_visiveis, mostrar_auditoria, mostrar_backup, mostrar_fiscal_pendente = self._abas_visiveis()

        destinos = []
        for t in tabelas_visiveis:
            destinos.append(
                ft.NavigationRailDestination(
                    icon=getattr(ft.Icons, t.icone.upper(), ft.Icons.TABLE_ROWS),
                    label=t.label,
                )
            )
        if mostrar_auditoria:
            destinos.append(ft.NavigationRailDestination(icon=ft.Icons.HISTORY, label="Auditoria"))
        if mostrar_fiscal_pendente:
            destinos.append(ft.NavigationRailDestination(icon=ft.Icons.RECEIPT_LONG, label="Notas Pendentes"))
        if self.usuario_logado["papel"] == "admin":
            destinos.append(ft.NavigationRailDestination(icon=ft.Icons.PEOPLE, label="Usuários"))
            destinos.append(ft.NavigationRailDestination(icon=ft.Icons.SETTINGS, label="Configurações"))
        if mostrar_backup:
            destinos.append(ft.NavigationRailDestination(icon=ft.Icons.SAVE, label="Backup"))

        self.area_conteudo = ft.Container(expand=True, padding=20)

        def trocar_tela(e):
            idx = e.control.selected_index
            if idx < len(tabelas_visiveis):
                self._tela_tabela(tabelas_visiveis[idx])
                return
            idx -= len(tabelas_visiveis)

            if mostrar_auditoria:
                if idx == 0:
                    self._tela_auditoria()
                    return
                idx -= 1

            if mostrar_fiscal_pendente:
                if idx == 0:
                    self._tela_fiscal_pendente()
                    return
                idx -= 1

            if self.usuario_logado["papel"] == "admin":
                if idx == 0:
                    self._tela_usuarios()
                    return
                idx -= 1
                if idx == 0:
                    self._tela_configuracoes()
                    return
                idx -= 1

            if mostrar_backup and idx == 0:
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
            ],
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

        if destinos:
            if tabelas_visiveis:
                self._tela_tabela(tabelas_visiveis[0])
            elif mostrar_auditoria:
                self._tela_auditoria()
            elif mostrar_fiscal_pendente:
                self._tela_fiscal_pendente()
            elif self.usuario_logado["papel"] == "admin":
                self._tela_usuarios()
            elif mostrar_backup:
                self._tela_backup()
        else:
            self.area_conteudo.content = ft.Text(
                "Nenhuma aba liberada para este usuário. Fale com o administrador.",
                color=ft.Colors.GREY_600,
            )
        self.page.update()

    # ------------------------------------------------------------------
    # TELA GENÉRICA DE TABELA (lista + busca + ações)
    # ------------------------------------------------------------------
    def _tela_tabela(self, tabela: Tabela):
        campos_ocultos = preferencias.colunas_ocultas(self.conn, self.usuario_logado["id"], tabela.nome)
        campos_visiveis = [c for c in tabela.campos if c.nome not in campos_ocultos]
        larguras_custom = preferencias.larguras_colunas(self.conn, self.usuario_logado["id"], tabela.nome)

        campo_busca = ft.TextField(
            label="Buscar", prefix_icon=ft.Icons.SEARCH, width=300, dense=True
        )
        tabela_dados = ft.DataTable(
            columns=self._colunas_datatable(campos_visiveis, larguras_custom), rows=[],
            column_spacing=16, horizontal_margin=10,
        )
        banner_estoque = ft.Container(visible=False)

        def recarregar(e=None):
            registros = db.listar(self.conn, tabela, busca=campo_busca.value or "")
            tabela_dados.rows = [
                self._linha_datatable(tabela, r, campos_visiveis, larguras_custom) for r in registros
            ]
            self._atualizar_banner_estoque(tabela, banner_estoque)
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
                ft.OutlinedButton("Colunas", icon=ft.Icons.VIEW_COLUMN,
                                  on_click=lambda e: self._abrir_dialogo_colunas(tabela)),
                ft.OutlinedButton("Exportar CSV", icon=ft.Icons.DOWNLOAD, on_click=exportar_csv_click),
                ft.OutlinedButton("Exportar Excel", icon=ft.Icons.DOWNLOAD, on_click=exportar_excel_click),
                ft.ElevatedButton(
                    f"Novo {tabela.label[:-1] if tabela.label.endswith('s') else tabela.label}",
                    icon=ft.Icons.ADD,
                    on_click=lambda e: self._abrir_formulario(tabela, recarregar),
                ),
            ],
        )

        self.area_conteudo.content = ft.Column(
            [
                ft.Text(tabela.label, size=20, weight=ft.FontWeight.BOLD),
                banner_estoque,
                barra_acoes,
                self._tabela_rolavel(tabela_dados),
            ],
            expand=True,
        )
        # guardamos referências para reaproveitar no formulário (editar/excluir)
        self._tabela_dados_atual = tabela_dados
        self._recarregar_atual = recarregar
        recarregar()
        self.page.update()

    def _abrir_dialogo_colunas(self, tabela: Tabela):
        """Diálogo com um checkbox + campo de largura por coluna, para
        escolher o que aparece e o quão larga cada coluna fica na tela de
        lista dessa tabela (preferência por usuário)."""
        ocultos_atuais = preferencias.colunas_ocultas(self.conn, self.usuario_logado["id"], tabela.nome)
        larguras_atuais = preferencias.larguras_colunas(self.conn, self.usuario_logado["id"], tabela.nome)

        checkboxes: dict[str, ft.Checkbox] = {
            c.nome: ft.Checkbox(label=c.label, value=c.nome not in ocultos_atuais)
            for c in tabela.campos
        }
        campos_largura: dict[str, ft.TextField] = {
            c.nome: ft.TextField(
                value=_texto_largura(larguras_atuais.get(c.nome, c.largura)),
                width=90, dense=True, suffix="px",
                hint_text=str(int(self._largura_campo(c))),
            )
            for c in tabela.campos
        }

        def marcar_todas(valor: bool):
            for cb in checkboxes.values():
                cb.value = valor
            self.page.update()

        mensagem_erro = ft.Text("", color=ft.Colors.RED, size=12)

        def salvar(e):
            ocultos = [nome for nome, cb in checkboxes.items() if not cb.value]

            larguras: dict[str, float] = {}
            for nome, campo_txt in campos_largura.items():
                texto = campo_txt.value.strip()
                if not texto:
                    continue
                try:
                    larguras[nome] = float(texto)
                except ValueError:
                    mensagem_erro.value = f"Largura inválida em '{nome}'."
                    self.page.update()
                    return

            preferencias.definir_colunas_ocultas(self.conn, self.usuario_logado["id"], tabela.nome, ocultos)
            preferencias.definir_larguras_colunas(self.conn, self.usuario_logado["id"], tabela.nome, larguras)
            self.page.pop_dialog()
            self._tela_tabela(tabela)

        linhas_campos = [
            ft.Row(
                [checkboxes[c.nome], ft.Container(expand=True), campos_largura[c.nome]],
                scroll=ft.ScrollMode.AUTO,
            )
            for c in tabela.campos
        ]

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Colunas visíveis"),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.TextButton("Marcar todas", on_click=lambda e: marcar_todas(True)),
                                ft.TextButton("Desmarcar todas", on_click=lambda e: marcar_todas(False)),
                            ]
                        ),
                        ft.Text(
                            "Deixe a largura em branco para calcular automaticamente.",
                            size=11, color=ft.Colors.GREY_600,
                        ),
                        ft.Divider(),
                        ft.Column(linhas_campos, spacing=4, scroll=ft.ScrollMode.AUTO),
                        mensagem_erro,
                    ],
                    tight=True,
                ),
                width=360, height=min(150 + 46 * len(checkboxes), 480),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton("Aplicar", on_click=salvar),
            ],
        )
        self.page.show_dialog(dialogo)

    def _tabela_rolavel(self, tabela_dados: ft.DataTable) -> ft.Container:
        """Envolve um DataTable com rolagem vertical, para a lista de
        registros não estourar a altura disponível da tela. Também torna
        todo o texto da tabela selecionável/copiável via SelectionArea.

        Nota: tentar somar rolagem horizontal aqui (Row com scroll dentro
        do Column com scroll) quebra o layout nesta versão do Flet -- a
        janela inteira passa a "vazar" para a largura do conteúdo. Por
        isso as colunas usam largura moderada (_largura_texto/_largura_campo)
        e o usuário pode ocultar colunas (botão "Colunas") em vez de
        depender de rolagem nos dois eixos.

        Nota 2: usar `ft.Text(selectable=True)` campo a campo (em vez de
        um único SelectionArea envolvendo tudo) causa um bug visual nesta
        versão do Flet -- células aparecem "selecionadas" sozinhas, sem
        nenhum clique. SelectionArea usa um único controlador de seleção
        pra toda a subárvore e não tem esse problema."""
        return ft.Container(
            content=ft.SelectionArea(
                content=ft.Column([tabela_dados], scroll=ft.ScrollMode.AUTO)
            ),
            expand=True,
        )

    def _atualizar_banner_estoque(self, tabela: Tabela, banner: ft.Container):
        if not tabela.alerta_estoque.ativo:
            banner.visible = False
            return

        abaixo_do_minimo = db.listar_abaixo_do_minimo(self.conn, tabela)
        if not abaixo_do_minimo:
            banner.visible = False
            return

        campo_qtd = tabela.alerta_estoque.campo_quantidade
        campo_min = tabela.alerta_estoque.campo_minimo
        # usa o primeiro campo buscável (normalmente "nome") como rótulo do item
        campos_buscaveis = tabela.campos_buscaveis
        campo_rotulo = campos_buscaveis[0].nome if campos_buscaveis else tabela.campos[0].nome

        itens = ", ".join(
            f"{r.get(campo_rotulo, '#' + str(r['id']))} ({r.get(campo_qtd)}/{r.get(campo_min)})"
            for r in abaixo_do_minimo
        )

        banner.visible = True
        banner.content = ft.Row(
            [
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.ORANGE_800),
                ft.Text(f"Estoque baixo: {itens}", color=ft.Colors.ORANGE_800, size=13, expand=True),
            ]
        )
        banner.bgcolor = ft.Colors.ORANGE_50
        banner.padding = 10
        banner.border_radius = 6

    def _largura_texto(self, texto: str) -> float:
        """Calcula uma largura mínima para a coluna com base no tamanho do
        rótulo. Sem isso, o DataTable dimensiona a coluna pelo conteúdo das
        células (que pode ser vazio/curto) e o texto do cabeçalho, quando
        mais longo, invade a coluna vizinha. O rótulo quebra em duas linhas
        quando não cabe na largura calculada."""
        return max(70.0, min(130.0, len(texto) * 7 + 20))

    def _largura_campo(self, campo: Campo, overrides: dict[str, float] | None = None) -> float:
        """Largura da coluna desse campo na lista. Prioridade: ajuste do
        usuário (diálogo 'Colunas') > 'largura' do schema/YAML > cálculo
        automático a partir do tamanho do rótulo."""
        if overrides and campo.nome in overrides:
            return float(overrides[campo.nome])
        if campo.largura:
            return float(campo.largura)
        return self._largura_texto(campo.label)

    def _colunas_datatable(self, campos: list[Campo], larguras: dict[str, float] | None = None) -> list[ft.DataColumn]:
        colunas = [
            ft.DataColumn(ft.Container(ft.Text("ID", weight=ft.FontWeight.BOLD), width=50))
        ]
        for c in campos:
            colunas.append(
                ft.DataColumn(
                    ft.Container(
                        ft.Text(c.label, weight=ft.FontWeight.BOLD),
                        width=self._largura_campo(c, larguras),
                    )
                )
            )
        colunas.append(ft.DataColumn(ft.Container(ft.Text("Ações", weight=ft.FontWeight.BOLD), width=100)))
        return colunas

    def _linha_datatable(self, tabela: Tabela, registro: dict, campos: list[Campo],
                          larguras: dict[str, float] | None = None) -> ft.DataRow:
        # Resolve os campos de referência (ex: produto_id -> "Parafuso 6mm")
        # para exibir o rótulo em vez do número do id.
        registro_exibicao = db.registro_para_exibicao(self.conn, tabela, registro)

        valor_qtd = registro.get(tabela.alerta_estoque.campo_quantidade) if tabela.alerta_estoque.ativo else None
        valor_min = registro.get(tabela.alerta_estoque.campo_minimo) if tabela.alerta_estoque.ativo else None
        abaixo_do_minimo = valor_qtd is not None and valor_min is not None and valor_qtd < valor_min

        celulas = [ft.DataCell(ft.Container(ft.Text(str(registro["id"])), width=50))]
        for c in campos:
            valor = registro_exibicao.get(c.nome)
            destaque = abaixo_do_minimo and c.nome == tabela.alerta_estoque.campo_quantidade
            celulas.append(
                ft.DataCell(
                    ft.Container(
                        ft.Text(
                            self._formatar_valor(c, valor),
                            color=ft.Colors.RED if destaque else None,
                            weight=ft.FontWeight.BOLD if destaque else None,
                        ),
                        width=self._largura_campo(c, larguras),
                    )
                )
            )

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
        except fiscal.ErroFiscal as e:
            self._notificar(f"Erro ao emitir nota: {e}")
            return

        if resultado.sucesso:
            audit.registrar(
                self.conn, tabela.nome, registro.get("id"),
                "emitir_nota_simulada" if resultado.simulado else "emitir_nota",
                self.usuario_logado["usuario"], resultado.mensagem[:200],
            )
            self._mostrar_resultado_fiscal(resultado)
        else:
            # falha de comunicação com o gateway (provavelmente sem internet
            # no momento da venda) -- guarda como pendente em vez de perder
            # a emissão; será reenviada automaticamente no próximo login.
            fiscal.enfileirar_pendente(self.conn, tabela.nome, registro.get("id"), resultado.mensagem)
            audit.registrar(
                self.conn, tabela.nome, registro.get("id"), "nota_pendente",
                self.usuario_logado["usuario"], resultado.mensagem[:200],
            )
            self._notificar(
                "Sem conexão com o gateway fiscal. A nota ficou pendente e será "
                "reenviada automaticamente (veja em \"Notas Pendentes\")."
            )

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
            # Nota: SelectionArea aqui reintroduz o bug de seleção espontânea
            # (provavelmente por causa da animação de abertura do
            # AlertDialog) -- funciona bem na lista, mas não em diálogos.
            content=ft.Container(content=ft.Column(conteudo, tight=True), width=420),
            actions=[ft.TextButton("Fechar", on_click=lambda e: self.page.pop_dialog())],
        )
        self.page.show_dialog(dialogo)

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

            aviso_estoque = ""

            if editando:
                if tabela.baixa_estoque.ativo:
                    # edição = devolve o efeito do registro antigo e aplica
                    # o do novo, cobrindo tanto troca de quantidade quanto
                    # troca do produto selecionado sem calcular diferença
                    estoque.reverter(self.conn, self.schema, tabela, registro)
                    resultado_estoque = estoque.aplicar(self.conn, self.schema, tabela, dados)
                    if resultado_estoque.estoque_negativo:
                        aviso_estoque = f" Atenção: {resultado_estoque.mensagem}"
                db.atualizar(self.conn, tabela, registro["id"], dados)
                audit.registrar(self.conn, tabela.nome, registro["id"], "editar",
                                 self.usuario_logado["usuario"])
            else:
                novo_id = db.inserir(self.conn, tabela, dados)
                audit.registrar(self.conn, tabela.nome, novo_id, "criar",
                                 self.usuario_logado["usuario"])
                if tabela.baixa_estoque.ativo:
                    resultado_estoque = estoque.aplicar(self.conn, self.schema, tabela, dados)
                    if resultado_estoque.estoque_negativo:
                        aviso_estoque = f" Atenção: {resultado_estoque.mensagem}"
                if tabela.impressao.ativo and tabela.impressao.auto_imprimir:
                    registro_novo = db.obter(self.conn, tabela, novo_id)
                    registro_exibicao = db.registro_para_exibicao(self.conn, tabela, registro_novo)
                    self._imprimir_cupom(tabela, registro_exibicao)

            self.page.pop_dialog()
            recarregar()
            self._notificar("Salvo com sucesso." + aviso_estoque)

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
                    ft.Row(botoes_aba, spacing=4, scroll=ft.ScrollMode.AUTO),
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
                ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton("Salvar", on_click=salvar),
            ],
        )
        self.page.show_dialog(dialogo)

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
            if tabela.baixa_estoque.ativo:
                estoque.reverter(self.conn, self.schema, tabela, registro)
            db.excluir(self.conn, tabela, registro["id"])
            audit.registrar(self.conn, tabela.nome, registro["id"], "excluir",
                             self.usuario_logado["usuario"])
            self.page.pop_dialog()
            self._recarregar_atual()
            self._notificar("Registro excluído.")

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar exclusão"),
            content=ft.Text(f"Tem certeza que deseja excluir o registro #{registro['id']}?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton("Excluir", icon=ft.Icons.DELETE, on_click=excluir,
                                   color=ft.Colors.WHITE, bgcolor=ft.Colors.RED),
            ],
        )
        self.page.show_dialog(dialogo)

    # ------------------------------------------------------------------
    # AUDITORIA
    # ------------------------------------------------------------------
    def _tela_auditoria(self):
        registros = audit.listar(self.conn)
        rotulos = ["ID", "Data/Hora", "Usuário", "Tabela", "Ação", "Registro"]
        larguras = [self._largura_texto(r) for r in rotulos]

        def celula(idx: int, texto: str) -> ft.DataCell:
            return ft.DataCell(ft.Container(ft.Text(texto), width=larguras[idx]))

        linhas = [
            ft.DataRow(cells=[
                celula(0, str(r["id"])),
                celula(1, r["criado_em"]),
                celula(2, r["usuario"] or ""),
                celula(3, r["tabela"]),
                celula(4, r["acao"]),
                celula(5, str(r["registro_id"]) if r["registro_id"] else "-"),
            ])
            for r in registros
        ]
        tabela_dados = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Container(ft.Text(rotulo, weight=ft.FontWeight.BOLD), width=largura))
                for rotulo, largura in zip(rotulos, larguras)
            ],
            rows=linhas,
            column_spacing=16, horizontal_margin=10,
        )
        self.area_conteudo.content = ft.Column(
            [ft.Text("Auditoria", size=20, weight=ft.FontWeight.BOLD),
             self._tabela_rolavel(tabela_dados)],
            expand=True,
        )
        self.page.update()

    # ------------------------------------------------------------------
    # USUÁRIOS (apenas admin)
    # ------------------------------------------------------------------
    def _abas_fixas(self) -> list[tuple[str, str]]:
        """Nomes das abas fixas (não são tabelas do schema) que também
        podem ser liberadas/restringidas por usuário. "Notas Pendentes"
        só aparece aqui quando a emissão fiscal está ativa no schema."""
        abas = [("_auditoria", "Auditoria"), ("_backup", "Backup")]
        if self.schema.fiscal.ativo:
            abas.append(("_fiscal_pendente", "Notas Pendentes"))
        return abas

    def _tela_usuarios(self):
        usuarios = auth.listar_usuarios(self.conn)
        rotulos = ["ID", "Usuário", "Papel", "Status"]
        larguras = [self._largura_texto(r) for r in rotulos]

        def linha_usuario(u: dict) -> ft.DataRow:
            return ft.DataRow(cells=[
                ft.DataCell(ft.Container(ft.Text(str(u["id"])), width=larguras[0])),
                ft.DataCell(ft.Container(ft.Text(u["usuario"]), width=larguras[1])),
                ft.DataCell(ft.Container(ft.Text(u["papel"]), width=larguras[2])),
                ft.DataCell(ft.Container(ft.Text("Ativo" if u["ativo"] else "Inativo"), width=larguras[3])),
                ft.DataCell(
                    ft.IconButton(
                        ft.Icons.EDIT, icon_size=18, tooltip="Editar",
                        on_click=lambda e, usr=u: self._abrir_dialogo_usuario(usr),
                    )
                ),
            ])

        tabela_dados = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Container(ft.Text(rotulo, weight=ft.FontWeight.BOLD), width=largura))
                for rotulo, largura in zip(rotulos, larguras)
            ] + [ft.DataColumn(ft.Container(ft.Text("Ações", weight=ft.FontWeight.BOLD), width=100))],
            rows=[linha_usuario(u) for u in usuarios],
            column_spacing=16, horizontal_margin=10,
        )

        self.area_conteudo.content = ft.Column(
            [
                ft.Text("Usuários", size=20, weight=ft.FontWeight.BOLD),
                ft.ElevatedButton(
                    "Novo usuário", icon=ft.Icons.PERSON_ADD,
                    on_click=lambda e: self._abrir_dialogo_usuario(None),
                ),
                ft.Divider(),
                self._tabela_rolavel(tabela_dados),
            ],
            expand=True,
        )
        self.page.update()

    def _abrir_dialogo_usuario(self, usuario_existente: dict | None):
        editando = usuario_existente is not None

        campo_usuario = ft.TextField(
            label="Usuário", value=usuario_existente["usuario"] if editando else "", width=250,
        )
        campo_senha = ft.TextField(
            label="Nova senha" if editando else "Senha",
            hint_text="Deixe em branco para manter a atual" if editando else None,
            width=250, password=True, can_reveal_password=True,
        )
        campo_papel = ft.Dropdown(
            label="Papel", width=180,
            options=[ft.dropdown.Option("usuario"), ft.dropdown.Option("admin")],
            value=usuario_existente["papel"] if editando else "usuario",
        )
        campo_ativo = ft.Switch(label="Ativo", value=bool(usuario_existente["ativo"]) if editando else True)

        ja_configurado = editando and auth.permissoes_configuradas(self.conn, usuario_existente["id"])
        permissoes_atuais = auth.permissoes_usuario(self.conn, usuario_existente["id"]) if ja_configurado else set()

        checkboxes_abas: dict[str, ft.Checkbox] = {}
        for t in self.schema.tabelas:
            marcado = (t.nome in permissoes_atuais) if ja_configurado else True
            checkboxes_abas[t.nome] = ft.Checkbox(label=t.label, value=marcado)
        for chave, rotulo in self._abas_fixas():
            marcado = (chave in permissoes_atuais) if ja_configurado else True
            checkboxes_abas[chave] = ft.Checkbox(label=rotulo, value=marcado)

        aviso_permissoes = ft.Text(
            "Abas visíveis para este usuário (ignorado para administradores):",
            size=12, weight=ft.FontWeight.BOLD,
        )
        coluna_permissoes = ft.Column(
            [aviso_permissoes] + list(checkboxes_abas.values()),
            spacing=4, scroll=ft.ScrollMode.AUTO,
        )

        def atualizar_visibilidade_permissoes(e=None):
            coluna_permissoes.visible = campo_papel.value != "admin"
            self.page.update()

        campo_papel.on_select = atualizar_visibilidade_permissoes
        atualizar_visibilidade_permissoes()

        mensagem_erro = ft.Text("", color=ft.Colors.RED, size=12)

        def salvar(e):
            nome = (campo_usuario.value or "").strip()
            if not nome:
                mensagem_erro.value = "Informe o nome de usuário."
                self.page.update()
                return
            if not editando and not campo_senha.value:
                mensagem_erro.value = "Informe uma senha."
                self.page.update()
                return

            if editando:
                ok = auth.atualizar_usuario(
                    self.conn, usuario_existente["id"], nome, campo_papel.value,
                    campo_ativo.value, nova_senha=campo_senha.value or None,
                )
                usuario_id = usuario_existente["id"] if ok else None
            else:
                usuario_id = auth.criar_usuario(self.conn, nome, campo_senha.value, campo_papel.value)
                ok = usuario_id is not None

            if not ok:
                mensagem_erro.value = "Já existe um usuário com esse nome."
                self.page.update()
                return

            abas_marcadas = [chave for chave, cb in checkboxes_abas.items() if cb.value]
            auth.definir_permissoes(self.conn, usuario_id, abas_marcadas)

            audit.registrar(
                self.conn, "_usuarios", usuario_id,
                "editar_usuario" if editando else "criar_usuario",
                self.usuario_logado["usuario"],
            )

            self.page.pop_dialog()
            self._tela_usuarios()
            self._notificar("Usuário salvo com sucesso.")

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar usuário" if editando else "Novo usuário"),
            content=ft.Container(
                content=ft.Column(
                    [
                        campo_usuario, campo_senha,
                        ft.Row([campo_papel, campo_ativo], scroll=ft.ScrollMode.AUTO),
                        ft.Divider(),
                        coluna_permissoes,
                        mensagem_erro,
                    ],
                    tight=True, spacing=10, scroll=ft.ScrollMode.AUTO,
                ),
                width=420, height=460,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton("Salvar", on_click=salvar),
            ],
        )
        self.page.show_dialog(dialogo)

    # ------------------------------------------------------------------
    # NOTAS FISCAIS PENDENTES (fila de retry)
    # ------------------------------------------------------------------
    def _tentar_reenviar_pendentes_silencioso(self):
        """Chamado depois do login: tenta reemitir sozinho as notas que
        ficaram pendentes por falha de conexão. Silencioso quando não há
        nada pendente; avisa só quando alguma foi resolvida ou continua
        pendente."""
        pendentes = fiscal.listar_pendentes(self.conn)
        if not pendentes:
            return

        resolvidas = 0
        for p in pendentes:
            resultado = fiscal.reprocessar_pendente(self.conn, self.schema, p)
            if resultado.sucesso:
                resolvidas += 1
                audit.registrar(self.conn, p["tabela"], p["registro_id"], "emitir_nota",
                                 self.usuario_logado["usuario"], "reenviada automaticamente no login")

        if resolvidas:
            self._notificar(f"{resolvidas} nota(s) fiscal(is) pendente(s) foram reenviadas com sucesso.")
        else:
            self._notificar(
                f"Ainda há {len(pendentes)} nota(s) fiscal(is) pendente(s) "
                f"(veja em \"Notas Pendentes\")."
            )

    def _tela_fiscal_pendente(self):
        pendentes = fiscal.listar_pendentes(self.conn)

        def tentar_uma(pendente: dict):
            resultado = fiscal.reprocessar_pendente(self.conn, self.schema, pendente)
            if resultado.sucesso:
                audit.registrar(self.conn, pendente["tabela"], pendente["registro_id"], "emitir_nota",
                                 self.usuario_logado["usuario"], "reenviada manualmente")
                self._notificar(f"Nota #{pendente['registro_id']} ({pendente['tabela']}) emitida com sucesso.")
            else:
                self._notificar(f"Ainda sem sucesso: {resultado.mensagem}")
            self._tela_fiscal_pendente()

        def tentar_todas(e):
            total = len(fiscal.listar_pendentes(self.conn))
            resolvidas = 0
            for p in fiscal.listar_pendentes(self.conn):
                resultado = fiscal.reprocessar_pendente(self.conn, self.schema, p)
                if resultado.sucesso:
                    resolvidas += 1
                    audit.registrar(self.conn, p["tabela"], p["registro_id"], "emitir_nota",
                                     self.usuario_logado["usuario"], "reenviada manualmente (lote)")
            self._notificar(f"{resolvidas} de {total} nota(s) pendente(s) emitida(s) com sucesso.")
            self._tela_fiscal_pendente()

        rotulos = ["ID", "Tabela", "Registro", "Tentativas", "Criada em", "Último erro"]
        larguras = [self._largura_texto(r) for r in rotulos]
        larguras[5] = 160  # último erro precisa de mais espaço (mas sem estourar a janela)

        linhas = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Container(ft.Text(str(p["id"])), width=larguras[0])),
                ft.DataCell(ft.Container(ft.Text(p["tabela"]), width=larguras[1])),
                ft.DataCell(ft.Container(ft.Text(str(p["registro_id"])), width=larguras[2])),
                ft.DataCell(ft.Container(ft.Text(str(p["tentativas"])), width=larguras[3])),
                ft.DataCell(ft.Container(ft.Text(p["criado_em"]), width=larguras[4])),
                ft.DataCell(
                    ft.Container(
                        ft.Text((p["ultimo_erro"] or "")[:60], size=12, tooltip=p["ultimo_erro"]),
                        width=larguras[5],
                    )
                ),
                ft.DataCell(
                    ft.IconButton(ft.Icons.REFRESH, icon_size=18, tooltip="Tentar novamente",
                                  on_click=lambda e, p=p: tentar_uma(p))
                ),
            ])
            for p in pendentes
        ]

        tabela_dados = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Container(ft.Text(rotulo, weight=ft.FontWeight.BOLD), width=largura))
                for rotulo, largura in zip(rotulos, larguras)
            ] + [ft.DataColumn(ft.Container(ft.Text("Ações", weight=ft.FontWeight.BOLD), width=80))],
            rows=linhas,
            column_spacing=16, horizontal_margin=10,
        )

        self.area_conteudo.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Notas Fiscais Pendentes", size=20, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.ElevatedButton("Tentar todas agora", icon=ft.Icons.REFRESH, on_click=tentar_todas),
                    ]
                ),
                ft.Text(
                    "Notas que não puderam ser emitidas por falha de comunicação com o "
                    "gateway fiscal (ex: sem internet no momento da venda). São reenviadas "
                    "automaticamente a cada login, ou manualmente aqui."
                    if pendentes else "Nenhuma nota pendente no momento.",
                    size=12, color=ft.Colors.GREY_600,
                ),
                self._tabela_rolavel(tabela_dados),
            ],
            expand=True,
        )
        self.page.update()

    # ------------------------------------------------------------------
    # CONFIGURAÇÕES (impressora e fiscal -- só admin)
    # ------------------------------------------------------------------
    def _tela_configuracoes(self):
        imp = self.schema.impressora
        fis = self.schema.fiscal

        campo_imp_ativo = ft.Switch(label="Ativo", value=imp.ativo)
        campo_imp_conexao = ft.Dropdown(
            label="Tipo de conexão", width=180, dense=True, value=imp.conexao,
            options=[ft.dropdown.Option(v) for v in ("usb", "rede", "serial", "arquivo")],
        )
        campo_imp_colunas = ft.TextField(label="Colunas do papel", value=str(imp.colunas), width=140, dense=True)
        campo_imp_vendor = ft.TextField(label="Vendor ID (USB)", value=imp.vendor_id, width=180, dense=True)
        campo_imp_product = ft.TextField(label="Product ID (USB)", value=imp.product_id, width=180, dense=True)
        campo_imp_ip = ft.TextField(label="IP (rede)", value=imp.ip, width=180, dense=True)
        campo_imp_porta = ft.TextField(label="Porta (rede)", value=str(imp.porta), width=120, dense=True)
        campo_imp_serial = ft.TextField(label="Dispositivo serial", value=imp.dispositivo_serial, width=220, dense=True)

        mensagem_imp = ft.Text("", color=ft.Colors.RED, size=12)

        def salvar_impressora(e):
            try:
                porta = int(campo_imp_porta.value or 0)
                colunas = int(campo_imp_colunas.value or 42)
            except ValueError:
                mensagem_imp.value = "Porta e colunas precisam ser números."
                self.page.update()
                return

            valores = {
                "ativo": campo_imp_ativo.value,
                "conexao": campo_imp_conexao.value,
                "vendor_id": campo_imp_vendor.value,
                "product_id": campo_imp_product.value,
                "ip": campo_imp_ip.value,
                "porta": porta,
                "dispositivo_serial": campo_imp_serial.value,
                "colunas": colunas,
            }
            configuracoes.salvar(self.conn, "impressora", valores)
            for chave, valor in valores.items():
                setattr(self.schema.impressora, chave, valor)
            audit.registrar(self.conn, "_configuracoes", None, "editar_impressora",
                             self.usuario_logado["usuario"])
            mensagem_imp.value = ""
            self._notificar("Configuração de impressora salva.")

        campo_fis_ativo = ft.Switch(label="Ativo", value=fis.ativo)
        campo_fis_provedor = ft.TextField(label="Provedor", value=fis.provedor, width=200, dense=True)
        campo_fis_ambiente = ft.Dropdown(
            label="Ambiente", width=180, dense=True, value=fis.ambiente,
            options=[ft.dropdown.Option("homologacao"), ft.dropdown.Option("producao")],
        )
        campo_fis_url = ft.TextField(label="URL da API do gateway", value=fis.api_url, width=340, dense=True)
        campo_fis_token = ft.TextField(
            label="Token de acesso", value=fis.api_token, width=340, dense=True,
            password=True, can_reveal_password=True,
            hint_text=(
                f"Em branco = usa a variável de ambiente '{fis.api_token_env}'"
                if fis.api_token_env else "Token fornecido pelo gateway fiscal contratado"
            ),
        )
        campo_fis_cnpj = ft.TextField(label="CNPJ do emitente", value=fis.cnpj_emitente, width=220, dense=True)

        def salvar_fiscal(e):
            valores = {
                "ativo": campo_fis_ativo.value,
                "provedor": campo_fis_provedor.value,
                "ambiente": campo_fis_ambiente.value,
                "api_url": campo_fis_url.value,
                "api_token": campo_fis_token.value,
                "cnpj_emitente": campo_fis_cnpj.value,
            }
            configuracoes.salvar(self.conn, "fiscal", valores)
            for chave, valor in valores.items():
                setattr(self.schema.fiscal, chave, valor)
            audit.registrar(self.conn, "_configuracoes", None, "editar_fiscal",
                             self.usuario_logado["usuario"])
            self._notificar("Configuração fiscal salva.")

        # --- Cupom de impressão, por tabela -----------------------------
        opcoes_tabela_cupom = [(t.nome, t.label) for t in self.schema.tabelas]
        container_cupom = ft.Container()

        def montar_secao_cupom(nome_tabela: str) -> ft.Control:
            tabela_cupom = self.schema.tabela(nome_tabela)
            imp = tabela_cupom.impressao

            sw_ativo = ft.Switch(label="Ativo", value=imp.ativo)
            campo_titulo = ft.TextField(label="Título do cupom", value=imp.titulo, width=280, dense=True)
            campo_rodape = ft.TextField(label="Rodapé", value=imp.rodape, width=280, dense=True)
            sw_auto = ft.Switch(
                label="Imprimir automaticamente ao salvar um registro novo",
                value=imp.auto_imprimir,
            )
            campos_selecionados = set(imp.campos)
            checkboxes_cupom = {
                c.nome: ft.Checkbox(label=c.label, value=c.nome in campos_selecionados)
                for c in tabela_cupom.campos
            }

            def salvar_cupom(e):
                valores = {
                    "ativo": sw_ativo.value,
                    "titulo": campo_titulo.value,
                    "campos": [nome for nome, cb in checkboxes_cupom.items() if cb.value],
                    "rodape": campo_rodape.value,
                    "auto_imprimir": sw_auto.value,
                }
                configuracoes.salvar(self.conn, configuracoes.chave_cupom(tabela_cupom.nome), valores)
                for chave, valor in valores.items():
                    setattr(tabela_cupom.impressao, chave, valor)
                audit.registrar(self.conn, "_configuracoes", None, "editar_cupom",
                                 self.usuario_logado["usuario"], tabela_cupom.nome)
                self._notificar(f"Cupom de '{tabela_cupom.label}' salvo.")

            return ft.Column(
                [
                    sw_ativo,
                    campo_titulo,
                    ft.Text("Campos que entram no cupom:", size=12),
                    (
                        ft.Column(list(checkboxes_cupom.values()), spacing=2)
                        if checkboxes_cupom
                        else ft.Text("Nenhum campo nesta tabela.", size=11, color=ft.Colors.GREY_600)
                    ),
                    campo_rodape,
                    sw_auto,
                    ft.ElevatedButton("Salvar cupom", icon=ft.Icons.SAVE, on_click=salvar_cupom),
                ],
                spacing=8,
            )

        campo_tabela_cupom = ft.Dropdown(
            label="Tabela", width=220, dense=True,
            value=opcoes_tabela_cupom[0][0] if opcoes_tabela_cupom else None,
            options=[ft.dropdown.Option(key=n, text=l) for n, l in opcoes_tabela_cupom],
        )

        def trocar_tabela_cupom(e=None):
            if campo_tabela_cupom.value:
                container_cupom.content = montar_secao_cupom(campo_tabela_cupom.value)
                self.page.update()

        campo_tabela_cupom.on_select = trocar_tabela_cupom
        if opcoes_tabela_cupom:
            container_cupom.content = montar_secao_cupom(opcoes_tabela_cupom[0][0])

        self.area_conteudo.content = ft.Column(
            [
                ft.Text("Configurações", size=20, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Essas configurações ficam salvas neste sistema (não no arquivo "
                    "schema.yaml) e valem a partir de agora, sem precisar reiniciar.",
                    size=12, color=ft.Colors.GREY_600,
                ),
                ft.Divider(),
                ft.Text("Impressora térmica", weight=ft.FontWeight.BOLD),
                campo_imp_ativo,
                ft.Row([campo_imp_conexao, campo_imp_colunas], scroll=ft.ScrollMode.AUTO),
                ft.Row([campo_imp_vendor, campo_imp_product], scroll=ft.ScrollMode.AUTO),
                ft.Row([campo_imp_ip, campo_imp_porta], scroll=ft.ScrollMode.AUTO),
                campo_imp_serial,
                mensagem_imp,
                ft.ElevatedButton("Salvar impressora", icon=ft.Icons.SAVE, on_click=salvar_impressora),
                ft.Divider(),
                ft.Text("Nota fiscal (gateway)", weight=ft.FontWeight.BOLD),
                campo_fis_ativo,
                ft.Row([campo_fis_provedor, campo_fis_ambiente], scroll=ft.ScrollMode.AUTO),
                campo_fis_url,
                campo_fis_token,
                campo_fis_cnpj,
                ft.ElevatedButton("Salvar fiscal", icon=ft.Icons.SAVE, on_click=salvar_fiscal),
                ft.Divider(),
                ft.Text("Cupom de impressão (por tabela)", weight=ft.FontWeight.BOLD),
                ft.Text(
                    "A nota fiscal (NF-e/NFC-e) segue o padrão exigido pela SEFAZ e não "
                    "é editável aqui -- isso é só o cupom não fiscal impresso na térmica.",
                    size=11, color=ft.Colors.GREY_600,
                ),
                campo_tabela_cupom,
                container_cupom,
            ],
            spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
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
        self.page.show_dialog(ft.SnackBar(ft.Text(mensagem)))


def rodar_app(schema: Schema):
    conn = db.conectar(schema.banco_path)
    db.garantir_schema(conn, schema)
    configuracoes.aplicar_no_schema(conn, schema)

    def main(page: ft.Page):
        SistemaApp(page, schema, conn)

    ft.app(target=main)
