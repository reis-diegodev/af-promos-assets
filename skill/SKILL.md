---
name: carrossel-ofertas
description: Monta, revisa e agenda no Buffer o carrossel "o que saiu no grupo" a partir de uma foto gerada por IA, dos prints do grupo e dos preços. Use quando o usuário mandar foto e prints de oferta para um novo post ou pedir para agendar um carrossel.
---

# Carrossel de ofertas

Tudo roda a partir do repositório do Projeto (`template/`, `assets/`, `scripts/carrossel.py`,
`posts/`). Leia o `README.md` do repo na primeira vez da sessão.

Divisão do trabalho: **você decide o layout olhando a foto e escreve a legenda; o script faz
as contas, o gancho, as linhas de preço, a checagem de layout e o agendamento.** Nunca
calcule preço ou desconto à mão.

## O que o usuário manda

- a foto (gerada por IA, com os produtos fiéis);
- um print do grupo para cada produto;
- de cada produto: nome e o "de ➜ por" da mensagem do grupo (`preco_cheio` e `preco_grupo`);
- data e hora de publicação.

Se faltar algo, pergunte só o que falta. Nunca estime nem complete um preço.

## Passo a passo

1. Atualize o repo (`git pull`). Crie `posts/AAAA-MM-DD-slug/` e salve nela a foto e os prints
   (`print-<id>.png`).
2. Olhe a foto e decida o layout (seção abaixo). Escreva o `post.json` no formato de
   `posts/2026-10-02-nike-fila/post.json`. Na legenda, escreva só a prosa e as hashtags e use
   `{gancho}` e `{precos}`: o script insere os números. Confira que os preços batem com o
   print de cada produto; se não baterem, pare e pergunte.
3. Rode `python scripts/carrossel.py renderizar posts/<pasta>`. Corrija todo aviso de
   layout e renderize de novo. Abra `out/previa.jpg` e confira o que o script não vê: a
   etiqueta está perto da peça certa, a seta aponta para a peça, o recorte mostra o produto
   inteiro e nada cobre rosto ou produto.
4. Mostre ao usuário a prévia, a legenda que o script imprimiu, a data e os canais. Pergunte
   se aprova.
5. **Só depois de um "aprovado" explícito:** `git add posts/<pasta>`, commit e push. Rode
   `agendar --dry-run`, confira, e depois `agendar`.
6. Faça commit e push do `post.json` atualizado (ele guarda os ids do Buffer). Responda com
   a data, os canais e os ids.

Se o usuário pedir uma mudança depois de aprovar, altere, renderize e peça aprovação de
novo. O script recusa agendar um `post.json` alterado depois da renderização.

## Como decidir o layout

O slide tem 1080x1440 px e a foto o cobre inteiro.

- **Gancho:** topo da capa, `x 60, y 48`, ocupa até cerca de `y 190`. Deixe essa faixa sem
  etiquetas. Se algo importante da foto estiver ali, desça o `y` do gancho.
- **Etiqueta da capa:** bloco de cerca de 360 x 150 px. Coloque sobre fundo (chão, parede,
  céu), do lado da peça com mais espaço livre, sem cobrir rosto nem produto. `alinhar:
  esquerda` usa `x` como borda esquerda; `direita` usa `x` como borda direita (1036 encosta
  na margem).
- **Seta:** `zigue` aponta para baixo e para a direita, `curva-esquerda` aponta para a
  esquerda, `curva-baixo` aponta para baixo e para a esquerda. `x, y` é o canto superior
  esquerdo da imagem; `largura` entre 120 e 150. A ponta termina perto da peça, sem
  cobri-la. Use `rot` (graus) para ajustar a direção.
- **Etiqueta do slide final:** mesma lógica, com cerca de 200 px de altura. A faixa abaixo
  de `y 1240` é do CTA.
- **Recorte do slide do produto:** `cx` e `cy` são o centro da peça na foto (proporção da
  largura e da altura, de 0 a 1). `zoom` entre 1,6 e 1,9 costuma fazer a peça ocupar uns 70%
  da largura na faixa de 640 px do topo. O produto tem que aparecer inteiro.
- **Ordem:** a ordem do array `produtos` é a ordem dos slides. De 1 a 3 produtos.

## Regras

- Nunca agende sem aprovação explícita do usuário nesta conversa.
- Nunca invente, arredonde nem "corrija" um preço; use exatamente o que o usuário informou.
- Nada de tempo cravado (hoje, ontem, amanhã, datas, dias da semana) nem de disponibilidade
  ("ainda dá tempo", "só até"): o post pode sair dias depois da oferta. O FOMO vem de "saiu
  por" e de não perder a próxima. O script recusa os termos de `termos_proibidos` no config.json.
- `foto_gerada_por_ia: true` quando a foto for de IA: vira a sinalização de IA no Instagram.
- Chaves só por variável de ambiente. Nunca peça a chave no chat nem grave em arquivo.
- Se o Buffer ou o GitHub recusarem algo, mostre a mensagem exata ao usuário em vez de
  tentar contornar.

## Comandos

```
python scripts/carrossel.py validar     posts/<pasta>
python scripts/carrossel.py renderizar  posts/<pasta>
python scripts/carrossel.py agendar     posts/<pasta> [--dry-run] [--forcar CANAL] [--sem-verificar]
python scripts/carrossel.py canais
```

Se faltar dependência: `pip install --break-system-packages -r requirements.txt` e
`playwright install chromium`.
