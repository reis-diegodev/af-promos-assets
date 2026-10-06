# Carrossel de ofertas

Gera o carrossel "o que saiu no grupo" (capa, um slide por produto e CTA) a partir de uma
foto e dos prints do grupo, e agenda no Instagram e no TikTok pelo Buffer.

As imagens são servidas por este próprio repositório (que precisa ser **público**), por
URLs presas ao commit: `raw.githubusercontent.com/<repo>/<sha>/posts/.../slide-1.jpg`.
Como o endereço inclui o hash do commit, ele não muda nem quebra depois, e o Buffer
consegue buscar a imagem na hora de publicar.

## Estrutura

```
assets/          fonte manuscrita e setas
template/        carrossel.html.j2 (o layout; não faz contas)
scripts/         carrossel.py (valida, renderiza, agenda)
posts/<pasta>/   post.json, foto, prints e out/ com os slides
config.json      repo do GitHub, ids dos canais no Buffer e textos fixos
skill/SKILL.md   o passo a passo que o Claude segue no Projeto
```

As pastas `posts/2026-09-*` são de antes deste pipeline: só têm os slides prontos, sem
`post.json`, e o script não as usa.

## Configuração, uma vez

1. Crie o repositório **público** no GitHub e envie estes arquivos.
2. No ambiente do Projeto: libere `api.buffer.com` e `raw.githubusercontent.com`, e defina
   `BUFFER_API_KEY` como variável de ambiente.
3. Rode `python scripts/carrossel.py canais` e copie os ids do Instagram e do TikTok para o
   `config.json`. Preencha também `github_repo` (usuario/repo).

Dependências: `pip install -r requirements.txt` e `playwright install chromium`.

## Um post

```bash
python scripts/carrossel.py renderizar posts/2026-10-05-exemplo   # gera out/slide-*.jpg e out/previa.jpg
# revisar a prévia: os números batem com os prints?
git add posts/2026-10-05-exemplo && git commit -m "post 2026-10-05" && git push
python scripts/carrossel.py agendar posts/2026-10-05-exemplo --dry-run
python scripts/carrossel.py agendar posts/2026-10-05-exemplo
git commit -am "agendado 2026-10-05" && git push
```

## Proteções

| Situação | O que o script faz |
|---|---|
| Preço do grupo não é menor que o preço cheio | recusa |
| Legenda ou textos com tempo cravado ("hoje", "ontem", datas, dias da semana) ou disponibilidade ("ainda dá tempo") | recusa (lista em `termos_proibidos` no config.json) |
| post.json mudou depois da renderização | recusa agendar até renderizar de novo |
| Slides fora do commit, alterados ou sem push | recusa agendar |
| URL pública não responde com imagem | recusa agendar |
| Canal já agendado | pula (`--forcar canal` para reagendar) |
| `#` escrito à mão na legenda de um post novo | recusa (hashtags vêm do config.json) |
| Produto sem marca reconhecida para hashtag | avisa na renderização |
| Mais hashtags que o limite do canal | avisa e corta as de marca |
| Texto saindo do slide ou sobreposto | avisa na renderização |

O gancho e as linhas de preço da legenda são calculados no código a partir dos preços:
desconto de 50% ou mais vira "saiu pela metade.", de 40% a 49% vira "saiu quase pela
metade." e abaixo disso vira "saiu R$ X mais barato.".

## post.json

Para um post novo, copie `modelo-post.json` (o post de `posts/2026-10-02-nike-fila/` é anterior
aos marcadores `{cta}` e de hashtags e não serve mais de modelo). Preços: `preco_cheio` é o "de" e `preco_grupo` é o
"por" da mensagem do grupo, exatamente como aparecem no print. Campos de layout (px num slide de 1080x1440):

- `gancho`: canto superior esquerdo do bloco do gancho na capa.
- `capa.etiqueta` e `final.etiqueta`: `x`, `y` e `alinhar` (`esquerda` usa x como borda
  esquerda; `direita` usa x como borda direita).
- `capa.seta` e `final.seta`: `img` (`zigue`, `curva-esquerda`, `curva-baixo`), `x`, `y`,
  `largura` e, opcional, `rot` em graus.
- `recorte`: `cx` e `cy` (centro do produto na foto, de 0 a 1) e `zoom` (1,6 a 1,9 costuma
  enquadrar uma peça). O script converte e nunca deixa borda vazia.
- `legenda`: só a prosa, com `{gancho}`, `{precos}` e `{cta}`, que o script substitui, e
  opcionalmente `{hashtags}` para escolher onde as hashtags entram (sem o marcador, elas vão
  no fim). Nunca escreva `#` à mão.

## Publicação com música

A API do Buffer não envia áudio. Por isso `publicacao` no `config.json` define o modo de
cada rede:

- `notification` (TikTok): no horário, o app do Buffer avisa no celular; você toca
  no aviso, o post abre no app da rede, você escolhe um som em alta e publica.
- `automatic` (Instagram): o Buffer publica sozinho, sem música. Logo depois, edite o post no
  Instagram e adicione o som; a edição mantém curtidas, comentários e alcance.

Para o aviso chegar, o app do Buffer precisa estar instalado, logado e com notificações
ativas. O `post.json` registra o modo usado em cada canal.

## Depois de agendar: merge do PR

Cada chat do Projeto grava num branch próprio. Depois de agendar, abra o PR e faça o merge
com **Create a merge commit**. Nunca use Squash nem Rebase: os links das imagens enviados ao
Buffer apontam para o commit original, e esses modos o tiram do histórico.

## Chamado para o grupo (CTA)

`cta_legenda` no `config.json` traz a frase de cada rede, inserida no lugar de `{cta}`. Hoje o
Instagram aponta para o link na bio e o TikTok aponta para o Instagram, porque conta pessoal
só libera link na bio a partir de 1.000 seguidores. Quando o TikTok liberar o link, troque só
a frase do TikTok. O slide final diz "link no perfil", que vale para as duas redes. Legenda nova
sem `{cta}` ou com "link na bio" escrito à mão é recusada.

## Hashtags

Montadas pelo script para cada canal a partir do bloco `hashtags` do `config.json`:

- `fixas.<canal>`: as do perfil, sempre presentes e sempre primeiro.
- `por_marca`: marca → hashtag. O script procura a marca no nome do produto (ou no campo
  opcional `marca` do produto) e acrescenta a hashtag dela.
- `limite.<canal>`: máximo por post. Se passar, as de marca excedentes ficam de fora.

O Instagram e o TikTok recebem a mesma prosa com hashtags diferentes. O manifesto guarda a
legenda final de cada canal.
