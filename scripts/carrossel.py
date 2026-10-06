#!/usr/bin/env python3
"""Carrossel "o que saiu no grupo": valida, renderiza e agenda no Buffer.

Uso:
    python scripts/carrossel.py validar     posts/2026-10-05-exemplo
    python scripts/carrossel.py renderizar  posts/2026-10-05-exemplo
    python scripts/carrossel.py agendar     posts/2026-10-05-exemplo [--dry-run] [--forcar CANAL] [--sem-verificar]
    python scripts/carrossel.py canais

Divisão de responsabilidades:
- O post.json traz os DADOS (produtos, preços, datas) e o LAYOUT (coordenadas
  decididas olhando a foto).
- Este script faz tudo que precisa ser determinístico: formatação de preço, cálculo
  do gancho, legenda com os preços, checagem de layout, URLs, agendamento e a
  proteção contra agendar duas vezes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ASSETS = RAIZ / "assets"
TEMPLATE = RAIZ / "template" / "carrossel.html.j2"
LARGURA, ALTURA, ALTURA_RECORTE = 1080, 1440, 640
SETAS = {p.stem for p in (ASSETS / "setas").glob("*.png")} - {"assinatura", "deslize"}
CANAIS_SUPORTADOS = {"instagram", "tiktok"}
# automatic: o Buffer publica sozinho. notification: o Buffer avisa no celular e você publica
# pelo app da rede, o que permite escolher a música (a API não envia áudio).
MODOS_PUBLICACAO = ("automatic", "notification")


def modo_publicacao(config: dict, canal: str) -> str:
    return config.get("publicacao", {}).get(canal, "automatic")
BUFFER_URL = os.environ.get("BUFFER_API_URL", "https://api.buffer.com")


# ---------------------------------------------------------------- utilidades

def falhar(msg: str) -> None:
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def ler_json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        falhar(f"Arquivo não encontrado: {caminho}")
    except json.JSONDecodeError as e:
        falhar(f"JSON inválido em {caminho}: {e}")


def gravar_json(caminho: Path, dados: dict) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fmt_preco(valor: float) -> str:
    """149.99 -> 'R$ 149,99'; 79 -> 'R$ 79'; 1299.9 -> 'R$ 1.299,90'."""
    centavos = round(valor * 100)
    reais, cent = divmod(centavos, 100)
    inteiro = f"{reais:,}".replace(",", ".")
    return f"R$ {inteiro}" if cent == 0 else f"R$ {inteiro},{cent:02d}"


def hash_post(post: dict) -> str:
    """Hash do post sem o bloco de agendamento: detecta post.json editado depois da renderização."""
    limpo = {k: v for k, v in post.items() if k != "agendamento"}
    return hashlib.sha256(json.dumps(limpo, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True)


# ---------------------------------------------------------------- regras de conteúdo

def calcular_gancho(produtos: list[dict], item: str) -> dict:
    """O gancho vem da conta, nunca de texto livre: o post não promete o que os números não sustentam."""
    total_cheio = sum(p["preco_cheio"] for p in produtos)
    total_grupo = sum(p["preco_grupo"] for p in produtos)
    desconto = 1 - total_grupo / total_cheio
    sujeito = f"esse {item}" if len(produtos) > 1 else "esse achado"
    linha1 = f"{sujeito} de {fmt_preco(round(total_cheio))}"
    if desconto >= 0.5:
        linha2 = "saiu pela metade."
    elif desconto >= 0.4:
        linha2 = "saiu quase pela metade."
    else:
        linha2 = f"saiu {fmt_preco(math.floor(total_cheio - total_grupo))} mais barato."
    return {"linha1": linha1, "linha2": linha2, "desconto": desconto,
            "total_cheio": total_cheio, "total_grupo": total_grupo}


def marcas_do_produto(produto: dict, por_marca: dict) -> list[str]:
    """Marcas citadas no nome do produto (ou no campo opcional 'marca'), na ordem do config."""
    texto = f"{produto.get('nome', '')} {produto.get('marca', '')}"
    return [m for m in por_marca if re.search(rf"(?<!\w){re.escape(m)}(?!\w)", texto, re.IGNORECASE)]


def montar_hashtags(post: dict, config: dict, canal: str) -> tuple[list[str], list[str]]:
    """Fixas do perfil + as das marcas do post, sem repetir, até o limite do canal.
    As fixas vêm primeiro: identificam o perfil e nunca são cortadas pelo limite."""
    cfg = config.get("hashtags", {})
    por_marca = cfg.get("por_marca", {})
    limite = cfg.get("limite", {}).get(canal, 5)
    avisos, tags = [], list(cfg.get("fixas", {}).get(canal, []))
    for p in post["produtos"]:
        marcas = marcas_do_produto(p, por_marca)
        if not marcas:
            avisos.append(f"produto {p['id']}: nenhuma marca reconhecida no nome; "
                          "adicione a marca em hashtags.por_marca no config.json ou o campo 'marca' no produto")
        tags += [por_marca[m] for m in marcas]
    unicas = list(dict.fromkeys(t.lower() for t in tags))
    if len(unicas) > limite:
        avisos.append(f"{canal}: {len(unicas)} hashtags para um limite de {limite}; ficaram fora {' '.join(unicas[limite:])}")
    return unicas[:limite], avisos


def montar_textos(post: dict, gancho: dict, config: dict) -> dict:
    frase = f"{gancho['linha1']} {gancho['linha2']}"
    frase = frase[0].upper() + frase[1:]
    precos = "\n".join(
        f"• {p['nome'][0].upper() + p['nome'][1:]}: de {fmt_preco(p['preco_cheio'])} por {fmt_preco(p['preco_grupo'])}"
        for p in post["produtos"]
    )
    base = post["legenda"].replace("{gancho}", frase).replace("{precos}", precos)
    legendas, hashtags, avisos = {}, {}, []
    for canal in post["canais"]:
        tags, av = montar_hashtags(post, config, canal)
        avisos += [a for a in av if a not in avisos]
        linha = " ".join(tags)
        texto = base.replace("{cta}", config.get("cta_legenda", {}).get(canal, ""))
        if "{hashtags}" in texto:
            texto = texto.replace("{hashtags}", linha)
        else:
            texto = f"{texto.rstrip()}\n\n{linha}" if linha else texto
        legendas[canal] = re.sub(r"\n{3,}", "\n\n", texto).strip()
        hashtags[canal] = tags
    titulo = post.get("titulo_tiktok", "{gancho}").replace("{gancho}", frase)[:90]
    return {"legendas": legendas, "hashtags": hashtags, "titulo_tiktok": titulo, "avisos": avisos}


HASHTAG_VALIDA = re.compile(r"#[^\s#]+")


def checar_hashtags(post: dict, config: dict, para_agendar: bool) -> tuple[list[str], list[str]]:
    erros, avisos = [], []
    cfg = config.get("hashtags")
    if not cfg:
        avisos.append("config.json sem o bloco 'hashtags': os posts vão sair sem hashtags")
        return erros, avisos
    todas = [t for lista in cfg.get("fixas", {}).values() for t in lista] + list(cfg.get("por_marca", {}).values())
    for t in todas:
        if not HASHTAG_VALIDA.fullmatch(t):
            erros.append(f"config.json: hashtag inválida '{t}' (precisa começar com # e não ter espaço)")
    # o post já aprovado usa a legenda gravada no manifesto; a regra vale para conteúdo novo
    if not para_agendar and re.search(r"(?<![\w&])#\w", post.get("legenda", "")):
        erros.append("legenda: hashtags vêm do config.json; tire os # da legenda (use {hashtags} para escolher onde entram)")
    return erros, avisos


def checar_cta(post: dict, config: dict, para_agendar: bool) -> list[str]:
    """O CTA muda por rede (no TikTok sem link na bio, ele aponta para o Instagram):
    vem do config.json pelo marcador {cta}, nunca escrito à mão na legenda."""
    if para_agendar:  # post já aprovado: vale a legenda gravada no manifesto
        return []
    erros = []
    legenda = post.get("legenda", "")
    if "{cta}" not in legenda:
        erros.append("legenda: falta o marcador {cta}; o chamado para o grupo vem de cta_legenda no config.json")
    if re.search(r"link\s+(do\s+grupo\s+)?t[áa]\s+na\s+bio|link\s+na\s+bio", legenda, re.IGNORECASE):
        erros.append("legenda: tire o 'link na bio' escrito à mão; use {cta}, que muda por rede")
    for canal in post.get("canais", []):
        if not config.get("cta_legenda", {}).get(canal):
            erros.append(f"config.json: falta cta_legenda.{canal}")
    return erros


DATA_CRAVADA = re.compile(r"\b\d{1,2}/\d{1,2}\b|\bdia\s+\d{1,2}\b", re.IGNORECASE)


def checar_termos(post: dict, config: dict) -> list[str]:
    """O post pode sair dias depois da oferta: nenhum texto público pode cravar quando ela aconteceu
    nem afirmar que ainda está valendo. A lista de termos fica no config.json."""
    termos = config.get("termos_proibidos", [])
    padrao = re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in termos) + r")(?!\w)", re.IGNORECASE) if termos else None
    textos = {"legenda": post.get("legenda", ""), "titulo_tiktok": post.get("titulo_tiktok", "")}
    textos.update({f"config.texto.{k}": v for k, v in config.get("texto", {}).items()})
    textos.update({f"config.cta_legenda.{k}": v for k, v in config.get("cta_legenda", {}).items()})
    erros = []
    for onde, texto in textos.items():
        achados = (padrao.findall(texto) if padrao else []) + DATA_CRAVADA.findall(texto)
        if achados:
            erros.append(f"{onde}: referência de tempo ou disponibilidade ({', '.join(sorted(set(a.lower() for a in achados)))}). "
                         "O post pode sair depois da oferta; tire o termo")
    return erros


def recorte_px(rec: dict, foto_w: int, foto_h: int) -> dict:
    """Converte {cx, cy, zoom} (centro do produto na foto, 0-1) em background-size/position do topo do slide."""
    w = LARGURA * rec["zoom"]
    h = w * foto_h / foto_w
    x = LARGURA / 2 - rec["cx"] * w
    y = ALTURA_RECORTE / 2 - rec["cy"] * h
    x = min(0, max(LARGURA - w, x))          # nunca deixa borda vazia
    y = min(0, max(ALTURA_RECORTE - h, y))
    return {"w": round(w), "x": round(x), "y": round(y)}


# ---------------------------------------------------------------- validação

def validar(pasta: Path, config: dict, para_agendar: bool = False) -> tuple[dict, list[str], list[str]]:
    post = ler_json(pasta / "post.json")
    erros, avisos = [], []

    for campo in ("titulo", "foto", "agendar_em", "canais", "legenda", "gancho", "produtos"):
        if campo not in post:
            erros.append(f"post.json sem o campo '{campo}'")
    if erros:
        return post, erros, avisos

    if not (pasta / post["foto"]).is_file():
        erros.append(f"foto não encontrada: {post['foto']}")
    if "foto_gerada_por_ia" not in post:
        erros.append("informe 'foto_gerada_por_ia' (true/false): vai para a sinalização de IA no Instagram")

    produtos = post["produtos"]
    if not 1 <= len(produtos) <= 3:
        erros.append("o carrossel aceita de 1 a 3 produtos")
    ids = [p.get("id") for p in produtos]
    if len(set(ids)) != len(ids) or None in ids:
        erros.append("cada produto precisa de um 'id' único")

    def dentro(e: dict, onde: str) -> None:
        if not (0 <= e.get("x", -1) <= LARGURA and 0 <= e.get("y", -1) <= ALTURA):
            erros.append(f"{onde}: coordenada fora do slide 1080x1440")

    for p in produtos:
        pid = p.get("id", "?")
        for campo in ("nome", "preco_cheio", "preco_grupo", "print", "capa", "final", "recorte"):
            if campo not in p:
                erros.append(f"produto {pid}: falta '{campo}'")
        if any(c not in p for c in ("preco_cheio", "preco_grupo", "print", "capa", "final", "recorte")):
            continue
        if not all(isinstance(p[c], (int, float)) and p[c] > 0 for c in ("preco_cheio", "preco_grupo")):
            erros.append(f"produto {pid}: preços precisam ser números positivos")
        elif p["preco_grupo"] >= p["preco_cheio"]:
            erros.append(f"produto {pid}: preço do grupo não é menor que o preço cheio")
        elif 1 - p["preco_grupo"] / p["preco_cheio"] < 0.10:
            avisos.append(f"produto {pid}: desconto abaixo de 10%, fraco para o formato")
        if not (pasta / p["print"]).is_file():
            erros.append(f"produto {pid}: print não encontrado: {p['print']}")
        for bloco in ("capa", "final"):
            et = p[bloco].get("etiqueta", {})
            dentro(et, f"produto {pid} {bloco}.etiqueta")
            if et.get("alinhar") not in ("esquerda", "direita"):
                erros.append(f"produto {pid} {bloco}.etiqueta: 'alinhar' deve ser esquerda ou direita")
            seta = p[bloco].get("seta")
            if seta:
                dentro(seta, f"produto {pid} {bloco}.seta")
                if seta.get("img") not in SETAS:
                    erros.append(f"produto {pid} {bloco}.seta: img deve ser uma de {sorted(SETAS)}")
        r = p["recorte"]
        if not (0 <= r.get("cx", -1) <= 1 and 0 <= r.get("cy", -1) <= 1 and r.get("zoom", 0) >= 1):
            erros.append(f"produto {pid}: recorte precisa de cx e cy entre 0 e 1 e zoom >= 1")

    for canal in post["canais"]:
        modo = config.get("publicacao", {}).get(canal, "automatic")
        if modo not in MODOS_PUBLICACAO:
            erros.append(f"config.json: publicacao.{canal} deve ser {' ou '.join(MODOS_PUBLICACAO)}, não '{modo}'")
        if canal not in CANAIS_SUPORTADOS:
            erros.append(f"canal desconhecido: {canal}")
        elif para_agendar and not re.fullmatch(r"[0-9a-f]{24}", str(config["canais"].get(canal, ""))):
            avisos.append(f"config.json: o id do canal {canal} não parece um id do Buffer, rode 'canais'")

    erros.extend(checar_termos(post, config))
    e_tags, a_tags = checar_hashtags(post, config, para_agendar)
    erros.extend(e_tags)
    erros.extend(checar_cta(post, config, para_agendar))
    avisos.extend(a_tags)

    try:
        quando = datetime.fromisoformat(post["agendar_em"])
        if quando.tzinfo is None:
            erros.append("agendar_em precisa de fuso, ex.: 2026-10-05T19:00:00-03:00")
        elif quando <= datetime.now(timezone.utc):
            (erros if para_agendar else avisos).append(f"agendar_em já passou: {post['agendar_em']}")
    except ValueError:
        erros.append(f"agendar_em inválido: {post['agendar_em']}")

    return post, erros, avisos


def relatar(erros: list[str], avisos: list[str]) -> None:
    for a in avisos:
        print(f"  ! {a}")
    for e in erros:
        print(f"  ✗ {e}")
    if erros:
        falhar(f"{len(erros)} erro(s). Corrija o post.json e rode de novo.")


# ---------------------------------------------------------------- renderização

def renderizar(pasta: Path, config: dict) -> None:
    from jinja2 import Environment, FileSystemLoader
    from PIL import Image
    from playwright.sync_api import sync_playwright

    post, erros, avisos = validar(pasta, config)
    relatar(erros, avisos)

    with Image.open(pasta / post["foto"]) as im:
        foto_w, foto_h = im.size
    gancho = calcular_gancho(post["produtos"], post.get("item", config["texto"]["item"]))

    def seta(s):
        return None if not s else {**s, "url": (ASSETS / "setas" / f"{s['img']}.png").as_uri(),
                                   "largura": s.get("largura", 130), "rot": s.get("rot", 0)}

    produtos = [{
        "id": p["id"], "nome": p["nome"],
        "preco_cheio": fmt_preco(p["preco_cheio"]), "preco_grupo": fmt_preco(p["preco_grupo"]),
        "print": (pasta / p["print"]).resolve().as_uri(),
        "capa": {"etiqueta": p["capa"]["etiqueta"], "seta": seta(p["capa"].get("seta"))},
        "final": {"etiqueta": p["final"]["etiqueta"], "seta": seta(p["final"].get("seta"))},
        "recorte": recorte_px(p["recorte"], foto_w, foto_h),
    } for p in post["produtos"]]

    env = Environment(loader=FileSystemLoader(TEMPLATE.parent), autoescape=True)
    html = env.get_template(TEMPLATE.name).render(
        titulo=post["titulo"], assets=ASSETS.as_uri(), foto=(pasta / post["foto"]).resolve().as_uri(),
        gancho={**post["gancho"], **gancho}, produtos=produtos, texto=config["texto"],
    )

    saida = pasta / "out"
    saida.mkdir(exist_ok=True)
    for antigo in saida.glob("slide-*.jpg"):
        antigo.unlink()
    pagina = saida / "carrossel.html"
    pagina.write_text(html, encoding="utf-8")

    slides, problemas = [], []
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        aba = navegador.new_page(viewport={"width": LARGURA, "height": ALTURA})
        aba.goto(pagina.as_uri())
        aba.evaluate("document.fonts.ready")
        aba.wait_for_function("[...document.images].every(i => i.complete && i.naturalWidth > 0)", timeout=15000)
        problemas = aba.evaluate(CHECAGEM_LAYOUT)
        for i, secao in enumerate(aba.query_selector_all("section"), start=1):
            destino = saida / f"slide-{i}.jpg"
            secao.screenshot(path=str(destino), type="jpeg", quality=92)
            slides.append(destino)
        navegador.close()

    # prévia em grade, para revisar de uma vez
    miniaturas = [Image.open(s).resize((360, 480)) for s in slides]
    colunas = min(len(miniaturas), 4)
    linhas = math.ceil(len(miniaturas) / colunas)
    grade = Image.new("RGB", (colunas * 360 + (colunas - 1) * 12, linhas * 480 + (linhas - 1) * 12), (20, 20, 20))
    for i, m in enumerate(miniaturas):
        grade.paste(m, ((i % colunas) * 372, (i // colunas) * 492))
    grade.save(saida / "previa.jpg", quality=88)

    textos = montar_textos(post, gancho, config)
    gravar_json(saida / "manifesto.json", {
        "post_hash": hash_post(post),
        "slides": [str(s.relative_to(RAIZ)) for s in slides],
        "legendas": textos["legendas"],
        "titulo_tiktok": textos["titulo_tiktok"],
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })

    print(f"\n✓ {len(slides)} slides em {saida.relative_to(RAIZ)}/")
    print(f"  gancho: {gancho['linha1']} / {gancho['linha2']} (desconto real {gancho['desconto']:.0%})")
    if problemas:
        print("\n  Layout para revisar:")
        for p in problemas:
            print(f"  ! {p}")
    else:
        print("  layout: nenhum texto fora do slide ou sobreposto")
    for a in textos["avisos"]:
        print(f"  ! {a}")
    for canal, legenda in textos["legendas"].items():
        print(f"\n--- legenda {canal} ---\n{legenda}")
    print("---------------")


CHECAGEM_LAYOUT = """
() => {
  const out = [];
  document.querySelectorAll('section').forEach((sec, i) => {
    const s = sec.getBoundingClientRect();
    const itens = [...sec.querySelectorAll('[data-check]')].map(el => {
      const r = el.getBoundingClientRect();
      return {nome: el.dataset.check, l: r.left - s.left, t: r.top - s.top, r: r.right - s.left, b: r.bottom - s.top};
    });
    const n = i + 1;
    for (const a of itens) {
      if (a.l < 0 || a.t < 0 || a.r > s.width || a.b > s.height)
        out.push(`slide ${n}: '${a.nome}' sai do slide`);
    }
    for (let x = 0; x < itens.length; x++) for (let y = x + 1; y < itens.length; y++) {
      const a = itens[x], b = itens[y];
      if (a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b)
        out.push(`slide ${n}: '${a.nome}' encosta em '${b.nome}'`);
    }
  });
  return out;
}
"""


# ---------------------------------------------------------------- Buffer

def buffer(query: str, variaveis: dict | None = None) -> dict:
    chave = os.environ.get("BUFFER_API_KEY")
    if not chave:
        falhar("BUFFER_API_KEY não está definida no ambiente.")
    corpo = json.dumps({"query": query, "variables": variaveis or {}}).encode()
    req = urllib.request.Request(BUFFER_URL, data=corpo, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {chave}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resposta = json.loads(r.read())
    except urllib.error.HTTPError as e:
        falhar(f"Buffer respondeu HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
    except urllib.error.URLError as e:
        falhar(f"Não consegui falar com {BUFFER_URL}: {e.reason}. O domínio está liberado no ambiente?")
    if resposta.get("errors"):
        falhar("Buffer retornou erro: " + "; ".join(e.get("message", str(e)) for e in resposta["errors"]))
    return resposta["data"]


def listar_canais() -> None:
    orgs = buffer("query { account { organizations { id name } } }")["account"]["organizations"]
    for org in orgs:
        print(f"\nOrganização: {org['name']} ({org['id']})")
        canais = buffer("query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id name service } }",
                        {"o": org["id"]})["channels"]
        for c in canais:
            print(f"  {c['service']:<12} {c['name']:<30} {c['id']}")
    print("\nCopie os ids de Instagram e TikTok para o config.json.")


MUTACAO = """
mutation Criar($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}
"""


def repo_github(config: dict, avisos: list[str], estrito: bool) -> str:
    repo = os.environ.get("GITHUB_REPO") or config.get("github_repo", "")
    if "/" not in repo or "SEU_" in repo:
        url = git("remote", "get-url", "origin").stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url) or re.search(r"/git/([^/]+/[^/.]+)", url)
        if m:
            return m.group(1)
        if estrito:
            falhar("Defina 'github_repo' no config.json (ex.: usuario/repo).")
        avisos.append("github_repo não definido no config.json")
        return "SEU_USUARIO/SEU_REPO"
    return repo


def checar_git(slides: list[str], avisos: list[str], estrito: bool) -> str:
    """Os slides precisam estar no commit atual E no GitHub, senão a URL pública não existe."""
    problemas = []
    sha = git("rev-parse", "HEAD").stdout.strip()
    if not sha:
        falhar("Esta pasta não é um repositório git com commits.")
    for s in slides:
        if git("cat-file", "-e", f"{sha}:{s}").returncode != 0:
            problemas.append(f"{s} não está no commit {sha[:7]}: faça commit dos slides")
        elif git("status", "--porcelain", "--", s).stdout.strip():
            problemas.append(f"{s} mudou depois do commit: faça commit de novo")
    # clones rasos/de um branch só não conhecem todos os branches remotos: aceita também
    # o commit ser a ponta de algum branch no GitHub
    no_github = bool(git("branch", "-r", "--contains", sha).stdout.strip()) or \
        sha in git("ls-remote", "--heads", "origin").stdout.split()
    if not no_github:
        problemas.append(f"o commit {sha[:7]} ainda não foi enviado ao GitHub: faça git push")
    if problemas:
        if estrito:
            for p in problemas:
                print(f"  ✗ {p}")
            falhar("Slides ainda não estão publicados no GitHub.")
        avisos.extend(problemas)
    return sha


def checar_urls(urls: list[str]) -> None:
    for u in urls:
        try:
            req = urllib.request.Request(u, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                tipo = r.headers.get("Content-Type", "")
                if not tipo.startswith("image/"):
                    falhar(f"{u} não devolve imagem (Content-Type: {tipo}).")
        except urllib.error.HTTPError as e:
            falhar(f"{u} devolveu HTTP {e.code}. O repositório é público e o push foi feito?")
        except urllib.error.URLError as e:
            falhar(f"Não consegui abrir {u} ({e.reason}). Libere raw.githubusercontent.com "
                   "no ambiente ou rode com --sem-verificar depois de abrir uma URL no navegador.")
    print(f"  ✓ {len(urls)} URLs públicas respondendo com imagem")


def agendar(pasta: Path, config: dict, dry_run: bool, forcar: list[str], sem_verificar: bool) -> None:
    post, erros, avisos = validar(pasta, config, para_agendar=True)
    manifesto_path = pasta / "out" / "manifesto.json"
    if not manifesto_path.is_file():
        erros.append("rode 'renderizar' antes de agendar")
    else:
        manifesto = ler_json(manifesto_path)
        if manifesto["post_hash"] != hash_post(post):
            erros.append("o post.json mudou depois da renderização: renderize e revise de novo")
    if erros and dry_run:
        print("  (dry-run: os erros abaixo bloqueariam o agendamento real)")
        for e in erros:
            print(f"  ✗ {e}")
        if not manifesto_path.is_file():
            sys.exit(1)
        erros = []
    relatar(erros, avisos)
    ja_mostrados = len(avisos)

    slides = manifesto["slides"]
    sha = checar_git(slides, avisos, estrito=not dry_run)
    repo = repo_github(config, avisos, estrito=not dry_run)
    urls = [f"https://raw.githubusercontent.com/{repo}/{sha}/{s}" for s in slides]
    if not dry_run and not sem_verificar:
        checar_urls(urls)

    quando = datetime.fromisoformat(post["agendar_em"]).astimezone(timezone.utc)
    due_at = quando.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    feito = post.setdefault("agendamento", {}).setdefault("posts", {})

    for canal in post["canais"]:
        if canal in feito and canal not in forcar:
            print(f"  = {canal}: já agendado ({feito[canal]['id']}). Use --forcar {canal} para agendar de novo.")
            continue
        entrada = {
            # manifestos antigos tinham uma legenda só, igual para todos os canais
            "text": manifesto.get("legendas", {}).get(canal) or manifesto["legenda"],
            "channelId": config["canais"][canal],
            "schedulingType": modo_publicacao(config, canal),
            "mode": "customScheduled",
            "dueAt": due_at,
            "aiAssisted": True,
            "assets": [{"image": {"url": u}} for u in urls],
        }
        if canal == "instagram":
            entrada["metadata"] = {"instagram": {"type": "post", "shouldShareToFeed": True,
                                                 "isAiGenerated": bool(post["foto_gerada_por_ia"])}}
        elif canal == "tiktok":
            entrada["metadata"] = {"tiktok": {"title": manifesto["titulo_tiktok"]}}

        if dry_run:
            print(f"\n--- {canal} (dry-run, nada foi enviado) ---")
            print(json.dumps(entrada, ensure_ascii=False, indent=2))
            continue

        r = buffer(MUTACAO, {"input": entrada})["createPost"]
        if r["__typename"] != "PostActionSuccess":
            gravar_json(pasta / "post.json", post)
            falhar(f"{canal}: Buffer recusou ({r.get('message', r['__typename'])}). "
                   "Canais já agendados ficaram registrados no post.json.")
        modo = entrada["schedulingType"]
        feito[canal] = {"id": r["post"]["id"], "dueAt": r["post"]["dueAt"], "publicacao": modo}
        post["agendamento"].update({"commit": sha, "urls": urls})
        gravar_json(pasta / "post.json", post)  # grava a cada canal: um erro no seguinte não perde o anterior
        como = "aviso no celular para publicar com música" if modo == "notification" else "publicação automática"
        print(f"  ✓ {canal}: agendado para {post['agendar_em']}, {como} (id {r['post']['id']})")

    for a in avisos[ja_mostrados:]:
        print(f"  ! {a}")
    if not dry_run:
        print("\n✓ Pronto. Faça commit do post.json para registrar o agendamento.")


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)
    for nome in ("validar", "renderizar", "agendar"):
        p = sub.add_parser(nome)
        p.add_argument("pasta", type=Path)
        if nome == "agendar":
            p.add_argument("--dry-run", action="store_true", help="mostra o que seria enviado, sem enviar")
            p.add_argument("--forcar", nargs="*", default=[], metavar="CANAL", help="reagenda canais já agendados")
            p.add_argument("--sem-verificar", action="store_true", help="pula o teste das URLs públicas")
    sub.add_parser("canais", help="lista os canais da conta no Buffer")
    args = ap.parse_args()

    config = ler_json(RAIZ / "config.json")
    if args.comando == "canais":
        return listar_canais()

    pasta = args.pasta if args.pasta.is_absolute() else (Path.cwd() / args.pasta)
    pasta = pasta.resolve()
    if args.comando == "validar":
        _, erros, avisos = validar(pasta, config)
        relatar(erros, avisos)
        print("✓ post.json válido")
    elif args.comando == "renderizar":
        renderizar(pasta, config)
    else:
        agendar(pasta, config, args.dry_run, args.forcar, args.sem_verificar)


if __name__ == "__main__":
    main()
