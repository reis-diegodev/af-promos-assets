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
| Texto saindo do slide ou sobreposto | avisa na renderização |

O gancho e as linhas de preço da legenda são calculados no código a partir dos preços:
desconto de 50% ou mais vira "saiu pela metade.", de 40% a 49% vira "saiu quase pela
metade." e abaixo disso vira "saiu R$ X mais barato.".

## post.json

Veja `posts/2026-10-02-nike-fila/post.json`. Preços: `preco_cheio` é o "de" e `preco_grupo` é o
"por" da mensagem do grupo, exatamente como aparecem no print. Campos de layout (px num slide de 1080x1440):

- `gancho`: canto superior esquerdo do bloco do gancho na capa.
- `capa.etiqueta` e `final.etiqueta`: `x`, `y` e `alinhar` (`esquerda` usa x como borda
  esquerda; `direita` usa x como borda direita).
- `capa.seta` e `final.seta`: `img` (`zigue`, `curva-esquerda`, `curva-baixo`), `x`, `y`,
  `largura` e, opcional, `rot` em graus.
- `recorte`: `cx` e `cy` (centro do produto na foto, de 0 a 1) e `zoom` (1,6 a 1,9 costuma
  enquadrar uma peça). O script converte e nunca deixa borda vazia.
- `legenda`: texto livre com `{gancho}` e `{precos}`, que o script substitui.
