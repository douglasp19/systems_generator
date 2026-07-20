# Gerador de Sistemas Offline

Motor genérico para montar sistemas de controle (estoque, cadastros, etc.)
a partir de um arquivo de configuração (YAML), sem escrever código novo
para cada cliente.

> **Sobre o "offline"**: a gestão do negócio (cadastros, estoque, vendas,
> relatórios, backup) é toda local -- o cliente não depende de internet
> pra abrir o sistema e trabalhar no dia a dia. Isso não significa que o
> sistema nunca fala com a internet: quando a própria tarefa exige (ex:
> emitir uma nota fiscal, que por lei precisa ser autorizada pela SEFAZ
> em tempo real), o sistema chama a API necessária. O ponto central é
> que a pessoa consegue **gerir o negócio dela localmente**, e a
> dependência de internet fica restrita só às tarefas que realmente
> precisam disso.

## Como funciona

Você **não** cria uma tela ou tabela por cliente. Você descreve as tabelas
e campos em um arquivo `.yaml`, e o motor:

1. Cria/atualiza o banco SQLite automaticamente
2. Gera as telas de lista e formulário sozinho
3. Já vem com login, permissões, auditoria, exportação e backup prontos

## Estrutura do projeto

```
sistema_generator/
├── main.py                  # ponto de entrada
├── schema_exemplo.yaml      # AQUI é onde você configura o sistema do cliente
├── engine/                  # o motor (não mexe por cliente)
│   ├── schema_loader.py     # lê o YAML
│   ├── db.py                # cria tabelas e faz CRUD genérico
│   ├── auth.py               # login e usuários
│   ├── audit.py              # log de auditoria
│   ├── export.py             # exportar CSV/Excel
│   └── backup.py             # backup do banco
├── ui/
│   └── app.py                # interface Flet, gerada a partir do schema
├── data/                     # onde fica o arquivo .db do cliente
├── exports/                  # arquivos exportados
└── backups/                  # backups automáticos
```

## Criando um sistema novo para um cliente

1. Escolha um ponto de partida e copie para `schema_clientex.yaml`:
   - `schema_estoque.yaml` — só estoque (produtos, fornecedores, movimentações)
   - `schema_clientes.yaml` — cadastro de clientes + histórico de interações (CRM simples)
   - `schema_os.yaml` — ordens de serviço (clientes, equipamentos, status, valor)
   - `schema_exemplo.yaml` — estoque + vendas + NF-e (distribuidor B2B)
   - `schema_loja_eletronicos.yaml` — estoque + vendas + NFC-e (venda de balcão)
2. Edite o nome do sistema e o caminho do banco:
   ```yaml
   sistema:
     nome: "Estoque - Padaria do João"
     banco: "data/padaria_joao.db"
   ```
3. Defina as tabelas e campos (veja tipos suportados abaixo)
4. Rode:
   ```bash
   python main.py schema_clientex.yaml
   ```

Pronto — sistema funcionando, sem escrever nenhuma linha de código de tela.

## Tipos de campo suportados

| Tipo         | Uso                                  | Vira no SQLite |
|--------------|---------------------------------------|----------------|
| `texto`      | nomes, categorias, campos curtos      | TEXT           |
| `texto_longo`| observações, descrições               | TEXT           |
| `inteiro`    | quantidade, estoque mínimo            | INTEGER        |
| `decimal`    | preços, valores monetários            | REAL           |
| `booleano`   | ativo/inativo, sim/não                | INTEGER (0/1)  |
| `data`       | datas (formato AAAA-MM-DD)            | TEXT           |
| `referencia` | liga a um registro de outra tabela    | INTEGER (FK)   |

Cada campo aceita: `label` (texto exibido na tela), `obrigatorio` (true/false),
`buscavel` (se aparece na busca da lista), `default` (valor padrão) e
`largura` (largura em pixels da coluna na tela de lista -- opcional, veja
"Colunas ajustáveis e filtro de colunas" mais abaixo).

### Relacionamento entre tabelas (`referencia`)

Para ligar uma tabela a outra (ex: uma venda aponta pra um produto),
use o tipo `referencia`:

```yaml
- nome: produto_id
  label: "Produto"
  tipo: referencia
  tabela_ref: produtos       # nome da tabela referenciada
  campo_exibicao: nome       # qual campo dela mostrar no dropdown/lista
  obrigatorio: true
```

Isso vira automaticamente um dropdown no formulário e mostra o nome
(não o número do id) na tela de lista e no cupom impresso.

> A tabela referenciada (`tabela_ref`) precisa estar definida **antes**
> dela no YAML, para a chave estrangeira ser criada corretamente.

### Layout em abas no formulário

Se o formulário de uma tabela tem muitos campos, agrupe-os em abas:

```yaml
abas:
  - nome: "Dados gerais"
    campos: [nome, categoria, ativo]
  - nome: "Preços e estoque"
    campos: [quantidade, preco_custo, preco_venda]
```

Se você não definir `abas`, todos os campos aparecem numa coluna só
(comportamento padrão).

## Impressora térmica (cupom não fiscal)

Configure a impressora uma vez, globalmente, em `sistema.impressora`:

```yaml
sistema:
  impressora:
    ativo: true
    conexao: usb          # usb | rede | serial | arquivo
    vendor_id: "0x04b8"   # para conexao: usb (descubra com `lsusb` no Linux)
    product_id: "0x0202"
    ip: "192.168.0.50"    # para conexao: rede
    porta: 9100
    colunas: 42            # 32 (bobina 58mm) ou 42-48 (80mm)
```

Use `conexao: arquivo` para testar o layout do cupom sem ter a
impressora em mãos — ele grava um arquivo em `cupons_teste/` em vez de
imprimir de verdade.

Depois, habilite o cupom em qualquer tabela:

```yaml
impressao:
  ativo: true
  titulo: "Recibo de Venda"
  campos: [produto_id, quantidade_vendida, valor_total, forma_pagamento]
  rodape: "Obrigado pela preferência!"
```

Um botão de impressora aparece na lista dessa tabela.

Funciona com a maioria das térmicas do mercado (Epson, Elgin, Bematech,
Tanca...) via protocolo ESC/POS, usando a biblioteca `python-escpos`.

### Impressão automática ao salvar

Por padrão o cupom só sai quando alguém clica no botão de impressora na
lista. Se o cliente preferir que o cupom saia sozinho assim que a venda é
cadastrada (sem precisar desse clique extra), ative:

```yaml
impressao:
  ativo: true
  titulo: "Recibo de Venda"
  campos: [produto_id, quantidade_vendida, valor_total, forma_pagamento]
  rodape: "Obrigado pela preferência!"
  auto_imprimir: true
```

Só imprime sozinho ao **criar** um registro novo (não reimprime quando
o registro é editado depois) -- o botão manual continua disponível para
reimprimir uma segunda via quando precisar.

## Nota fiscal (NF-e / NFC-e) — qual escolher?

**Importante:** emitir nota fiscal não é uma operação local. A nota
precisa ser autorizada pela SEFAZ em tempo real, o que exige (1)
certificado digital ICP-Brasil e (2) internet no momento da emissão.
Por isso este módulo **não implementa a comunicação direta com a
SEFAZ** (é um projeto de compliance à parte, com bastante
responsabilidade legal) — ele se conecta a um **gateway fiscal**
terceirizado (Focus NFe, PlugNotas, eNotas, Nuvem Fiscal, TecnoSpeed...)
que cuida da assinatura, homologação e protocolo com o fisco, te
devolvendo o XML e o documento auxiliar (DANFE ou DANFCE) prontos por
uma API simples.

| | NF-e (`tipo: nfe`) | NFC-e (`tipo: nfce`) |
|---|---|---|
| Documento auxiliar | **DANFE** | **DANFCE** (documento diferente) |
| Destinatário | **Sempre obrigatório** (CNPJ/CPF completo) | **Opcional** |
| Uso típico | Venda pra outra empresa, produto despachado (acompanha a mercadoria) | Venda de balcão direto ao consumidor final |
| Exemplo | Distribuidor/fabricante vendendo pra revendedor | Loja de eletrônicos, mercado, farmácia |

Se a venda é no balcão e a pessoa não precisa (ou não pede) CPF na
nota, é **NFC-e**, não NF-e — tentar emitir NF-e sem destinatário dá
erro de propósito, com uma mensagem sugerindo trocar pra NFC-e.

Dois exemplos prontos no projeto:
- `schema_exemplo.yaml` — modela NF-e (distribuidor com clientes
  cadastrados, destinatário obrigatório).
- `schema_loja_eletronicos.yaml` — modela NFC-e (venda de balcão,
  cliente só é vinculado se pedir CPF na nota).

### Configuração global (uma vez por sistema)

```yaml
sistema:
  fiscal:
    ativo: true
    provedor: "focus_nfe"
    ambiente: "homologacao"     # troque pra "producao" quando for pra valer
    api_url: "https://homologacao.focusnfe.com.br/v2"
    api_token_env: "FOCUS_NFE_TOKEN"   # nome da variável de ambiente com o token
    cnpj_emitente: "00.000.000/0001-00"
```

O token **nunca** vai no YAML — fica numa variável de ambiente (nesse
exemplo, `FOCUS_NFE_TOKEN`), pra não vazar credencial em arquivo
versionado.

### Modelando NF-e ou NFC-e no schema

Os dois tipos usam a mesma estrutura — tabelas + campo `referencia` —,
mudando só se o destinatário é obrigatório ou não:

1. **Tabela de clientes** (o destinatário) — uma tabela normal com
   nome, CNPJ/CPF, endereço. Na NFC-e ela é opcional: só é preenchida
   se o cliente pedir CPF na nota.
2. **Tabela de vendas** (o cabeçalho da nota) — com um campo do tipo
   `referencia` apontando pro cliente, e a configuração `fiscal`:
   ```yaml
   fiscal:
     ativo: true
     tipo: nfe                        # ou nfce
     campo_destinatario: cliente_id   # obrigatório na nfe; opcional na nfce
     tabela_itens: itens_venda        # nome da tabela com as linhas da nota
   ```
   Na NF-e, deixe o campo `cliente_id` com `obrigatorio: true` no
   formulário. Na NFC-e, deixe `obrigatorio: false` — a venda pode
   ficar sem cliente vinculado.
3. **Tabela de itens** (as linhas da nota, uma por produto vendido) —
   com um campo `referencia` apontando de volta pra venda:
   ```yaml
   - nome: venda_id
     tipo: referencia
     tabela_ref: vendas
     campo_exibicao: data_venda
   ```
   O motor descobre sozinho essa ligação na hora de montar a nota — não
   precisa configurar de novo lá no cabeçalho.

Os dois exemplos prontos do projeto (`schema_exemplo.yaml` para NF-e e
`schema_loja_eletronicos.yaml` para NFC-e) já vêm com essa estrutura —
é só copiar o padrão mais parecido com o caso do seu cliente.

**Sem token configurado, o sistema roda em modo simulação** — monta o
payload completo (destinatário + itens + valor total somado
automaticamente) e mostra o que seria enviado, sem emitir nada de
verdade. Isso permite testar o fluxo inteiro antes de contratar um
provedor.

### Fila de retry (se a internet cair na hora da venda)

Emitir a nota exige internet no momento -- se a conexão cair bem na hora
de fechar a venda, o sistema não perde a emissão: guarda a nota como
**pendente** e mostra um aviso (`Sem conexão com o gateway fiscal. A
nota ficou pendente...`) em vez de travar a venda.

- **Reenvio automático**: a cada login, o sistema tenta reemitir sozinho
  todas as notas pendentes. Se a internet já tiver voltado, elas saem
  sem precisar de nenhuma ação.
- **Tela "Notas Pendentes"**: aparece no menu (abaixo de Auditoria)
  sempre que `sistema.fiscal.ativo: true` no schema. Lista tentativas e
  último erro de cada pendência, com um botão para tentar novamente uma
  nota específica ou todas de uma vez.
- Assim como Auditoria e Backup, essa aba pode ser liberada ou
  escondida por usuário no cadastro de conta (veja a seção de
  permissões mais abaixo, em Usuários).

Isso cobre quedas de conexão -- erros de dados (ex: item faltando,
destinatário inválido) continuam aparecendo na hora, já que reenviar não
resolveria o problema.

### Antes de ir pra produção com um cliente

1. Escolha um gateway fiscal (compare preço, suporte e documentação).
2. Contrate um certificado digital e-CNPJ A1 para o CNPJ do cliente.
3. Peça ao contador do cliente os códigos fiscais (**NCM** de cada
   produto e **CFOP** de cada tipo de operação) — o schema de exemplo
   já reserva esses campos na tabela de itens, mas os valores corretos
   variam por ramo/produto e não dá pra generalizar.
4. Ajuste o payload em `engine/fiscal.py` conforme a documentação
   exata do provedor escolhido (o formato varia entre eles).
5. Teste tudo em ambiente de homologação antes de trocar pra produção.

## Adicionando um campo depois que o sistema já está em produção

Só editar o YAML e adicionar o campo na lista de `campos` da tabela.
Na próxima vez que o sistema abrir, a coluna nova é criada automaticamente
no banco **sem apagar os dados existentes** (migração automática).

## Primeiro acesso

Se não existir nenhum usuário cadastrado, o sistema cria automaticamente
`admin` / `admin` no primeiro uso. Oriente o cliente a trocar a senha
(ou criar um novo admin e desativar o padrão) na tela de Usuários.

## Rodando

```bash
pip install -r requirements.txt
python main.py
```

## Gerando um executável para o cliente (sem precisar instalar Python)

```bash
pip install pyinstaller
flet pack main.py --name SistemaCliente --add-data "schema_clientex.yaml:."
```

Isso gera um `.exe`/binário standalone que o cliente pode simplesmente
abrir com duplo clique.

## Editor visual de schema

Para montar tabelas e campos sem editar o YAML na mão, rode o editor:

```bash
python main.py --editor                      # começa um schema em branco
python main.py --editor schema_clientex.yaml # abre um schema existente
```

A tela permite: criar/remover/reordenar tabelas, adicionar/editar/remover
campos (com todas as opções: tipo, obrigatório, buscável, valor padrão,
mínimo/máximo, referência a outra tabela) e configurar abas do
formulário. O botão "Salvar" grava o `.yaml` no caminho informado, e
"Rodar sistema" abre o sistema gerado numa janela separada para testar
na hora. Seções mais avançadas que o editor ainda não monta visualmente
(impressora, gateway fiscal) são preservadas como estão no arquivo ao
salvar — continue ajustando essas partes direto no YAML.

## Validações customizadas

Além de `obrigatorio`, campos numéricos (`inteiro`/`decimal`) aceitam
`minimo` e `maximo`, e campos de texto aceitam uma expressão regular:

```yaml
- nome: quantidade
  label: "Quantidade em estoque"
  tipo: inteiro
  minimo: 0        # não deixa salvar estoque negativo

- nome: email
  label: "E-mail"
  tipo: texto
  regex: '[^@\s]+@[^@\s]+\.[^@\s]+'
  regex_mensagem: "Informe um e-mail válido."
```

A validação roda ao salvar o formulário, antes de gravar no banco; se
falhar, a mensagem de erro aparece no próprio formulário.

## Alerta de estoque mínimo

Para qualquer tabela com um campo de quantidade e um de estoque mínimo,
ative o aviso automático na tela de lista:

```yaml
alerta_estoque:
  ativo: true
  campo_quantidade: quantidade
  campo_minimo: estoque_minimo
```

Com isso, sempre que algum registro tiver `quantidade < estoque_minimo`:
a tela de lista mostra um banner no topo listando os itens afetados
(com a quantidade atual e o mínimo configurado), e a célula de
quantidade daquele registro fica destacada em vermelho na tabela.

## Colunas ajustáveis e filtro de colunas

Tabelas com muitos campos podem não caber todas as colunas na largura da
janela. Três recursos ajudam nisso, dos mais permanentes aos mais rápidos:

**Largura padrão no schema** -- ajuste no YAML quando quiser que todo
mundo já abra com essa largura (ex: uma coluna de texto longo precisando
de mais espaço):

```yaml
- nome: descricao_problema
  label: "Descrição do problema"
  tipo: texto_longo
  largura: 220        # px -- se não informado, o motor calcula automaticamente
```

**Ajuste de largura pelo usuário na tela** -- o botão "Colunas" na tela de
lista abre um diálogo com um campo de largura (em px) ao lado de cada
coluna. Deixar em branco volta a usar a largura do schema/cálculo
automático. Cada usuário pode ajustar a visão do jeito que preferir, sem
mexer no YAML -- a escolha fica salva por usuário e por tabela e persiste
entre sessões. (Não é possível arrastar a borda da coluna com o mouse --
o `DataTable` do Flet não suporta isso nesta versão; o campo numérico no
diálogo é o jeito de ajustar.)

**Filtro de colunas** -- no mesmo diálogo "Colunas", um checkbox por campo
esconde as colunas que não interessam naquele momento (ex: numa tabela
com 10 campos, deixar visíveis só os 4 mais usados no dia a dia). Também
salvo por usuário e por tabela. Colunas ocultas continuam existindo
normalmente: exportação (CSV/Excel), impressão de cupom e emissão fiscal
usam todos os campos, independente do que está oculto só na tela.

> A tabela ainda não tem rolagem horizontal (tentativas de somar rolagem
> horizontal e vertical quebraram o layout nesta versão do Flet) -- por
> isso o filtro de colunas e o ajuste de largura são o jeito recomendado
> de lidar com tabelas muito largas, em vez de rolar a tela pros lados.

**Texto selecionável** -- os valores mostrados nas telas de lista (Produtos,
Auditoria, Usuários, Notas Pendentes) podem ser destacados com o mouse e
copiados, pra colar um telefone, e-mail ou protocolo em outro lugar sem
precisar abrir o formulário de edição.

> Não aparece no diálogo de resultado da emissão fiscal -- nessa versão
> do Flet, texto selecionável dentro de um `AlertDialog` reintroduz um
> bug de seleção espontânea (provavelmente ligado à animação de abertura
> do diálogo). Como a lista (que não tem essa animação) funciona bem,
> deixamos selecionável só ali.

## Próximos passos sugeridos

Todos os itens da lista original (editor visual, validações, alertas de
estoque, templates prontos, impressão automática, fila de retry fiscal)
já foram implementados. Ideias futuras ficam registradas aqui conforme
surgirem.
