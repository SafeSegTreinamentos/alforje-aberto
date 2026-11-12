"""Alforje Aberto — publicador automático.

Pega o próximo post da fila (posts/fila/*.json), busca fotos livres no
Wikimedia Commons, monta o carrossel 1080x1350 e publica no Instagram
pela API oficial da Meta.

Variáveis de ambiente:
  IG_USER_TOKEN  token de usuário (Facebook Login) com instagram_content_publish
  DRY_RUN=1      só monta as imagens, não publica
"""
import html
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
FILA = ROOT / "posts" / "fila"
PUBLICADOS = ROOT / "posts" / "publicados"
MEDIA = ROOT / "media"
FONTS = ROOT / "fonts"
REPO_RAW = "https://raw.githubusercontent.com/SafeSegTreinamentos/alforje-aberto/main"
GRAPH = "https://graph.facebook.com/v27.0"
UA = {"User-Agent": "AlforjeAbertoBot/1.0 (https://github.com/SafeSegTreinamentos/alforje-aberto)"}

W, H = 1080, 1350
ASFALTO = (28, 26, 23)
COURO = (139, 90, 51)
AMBAR = (232, 163, 61)
CREME = (242, 230, 208)

# ---------------------------------------------------------------- fontes
def garantir_fontes():
    for n in ("Oswald-Bold.ttf", "Oswald-Medium.ttf", "Inter-Regular.ttf"):
        if not (FONTS / n).exists():
            sys.exit(f"Fonte ausente: fonts/{n}")


def fonte(nome, tamanho, peso=None):
    if nome.startswith("Oswald"):
        arq = "Oswald-Bold.ttf" if (peso or 500) >= 650 else "Oswald-Medium.ttf"
    else:
        arq = "Inter-Regular.ttf"
    return ImageFont.truetype(str(FONTS / arq), tamanho)


# ---------------------------------------------------------------- fotos
def limpar_html(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


BLOQUEIO = ("moto guzzi", "guzzi", "studio", "museum", "museo", "exhibition", "salon", "eicma", "map", "karte", "mapa", "logo", "1900", "1910", "1920", "1930", "1940", "1950")


def colorido(img):
    """Métrica de colorfulness (Hasler & Süsstrunk)."""
    import statistics
    pequeno = img.resize((80, 80))
    rg, yb = [], []
    for r, g, b in pequeno.getdata():
        rg.append(r - g)
        yb.append(0.5 * (r + g) - b)
    sd = (statistics.pstdev(rg) ** 2 + statistics.pstdev(yb) ** 2) ** 0.5
    mu = (statistics.mean(rg) ** 2 + statistics.mean(yb) ** 2) ** 0.5
    return sd + 0.3 * mu


def buscar_foto(termo, usadas):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{termo} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 15,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600,
    }
    r = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers=UA, timeout=60)
    r.raise_for_status()
    paginas = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in paginas:
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 1200 or p["title"] in usadas:
            continue
        meta = info.get("extmetadata", {})
        autor = limpar_html(meta.get("Artist", {}).get("value", "")) or "autor desconhecido"
        licenca = limpar_html(meta.get("LicenseShortName", {}).get("value", "")) or "licença livre"
        titulo_arq = p["title"].lower()
        if any(b in titulo_arq for b in BLOQUEIO):
            continue
        img = requests.get(info.get("thumburl") or info["url"], headers=UA, timeout=120)
        img.raise_for_status()
        foto = Image.open(BytesIO(img.content)).convert("RGB")
        if colorido(foto) < 18:  # descarta preto e branco / sépia / foto antiga
            continue
        usadas.add(p["title"])
        return foto, f"{autor[:60]} ({licenca})"
    return None, None


def cobrir(img):
    escala = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * escala) + 1, int(img.height * escala) + 1), Image.LANCZOS)
    x = (img.width - W) // 2
    y = (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


# ---------------------------------------------------------------- desenho
def quebrar(draw, texto, f, largura):
    linhas = []
    for par in texto.split("\n"):
        palavras, atual = par.split(), ""
        for p in palavras:
            teste = (atual + " " + p).strip()
            if draw.textlength(teste, font=f) <= largura:
                atual = teste
            else:
                if atual:
                    linhas.append(atual)
                atual = p
        linhas.append(atual)
    return linhas


def degrade(img, inicio=0.38):
    camada = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    y0 = int(H * inicio)
    for y in range(y0, H):
        a = int(235 * ((y - y0) / (H - y0)) ** 0.9)
        d.line([(0, y), (W, y)], fill=ASFALTO + (a,))
    topo = 170
    for y in range(topo):
        a = int(120 * (1 - y / topo))
        d.line([(0, y), (W, y)], fill=ASFALTO + (a,))
    return Image.alpha_composite(img.convert("RGBA"), camada)


def cabecalho(d, n, total):
    f = fonte("Oswald.ttf", 30, 600)
    t = f"{n}/{total}"
    xt = W - 60 - d.textlength(t, font=f)
    for dx, dy in ((2, 2), (0, 2), (2, 0), (-1, 1)):
        d.text((60 + dx, 52 + dy), "ALFORJE ABERTO", font=f, fill=(0, 0, 0))
        d.text((xt + dx, 52 + dy), t, font=f, fill=(0, 0, 0))
    d.text((60, 52), "ALFORJE ABERTO", font=f, fill=AMBAR)
    d.text((xt, 52), t, font=f, fill=CREME)


def slide_foto(foto, titulo, texto, n, total, capa=False, local=None):
    img = degrade(cobrir(foto), 0.30 if capa else 0.42)
    d = ImageDraw.Draw(img)
    cabecalho(d, n, total)
    ft = fonte("Oswald.ttf", 112 if capa else 76, 700)
    fx = fonte("Inter.ttf", 38 if capa else 36, 450)
    largura = W - 120
    l_tit = quebrar(d, titulo.upper(), ft, largura)
    l_txt = quebrar(d, texto, fx, largura) if texto else []
    alt_tit = len(l_tit) * int(ft.size * 1.08)
    alt_txt = len(l_txt) * int(fx.size * 1.42)
    y = H - 90 - alt_txt - (30 if l_txt else 0) - alt_tit - (70 if local else 0)
    if local:
        fl = fonte("Oswald.ttf", 36, 500)
        d.rectangle([60, y + 8, 66, y + 46], fill=AMBAR)
        d.text((84, y + 2), local.upper(), font=fl, fill=AMBAR)
        y += 70
    for l in l_tit:
        d.text((60, y), l, font=ft, fill=CREME)
        y += int(ft.size * 1.08)
    y += 30
    for l in l_txt:
        d.text((60, y), l, font=fx, fill=(235, 228, 214))
        y += int(fx.size * 1.42)
    return img.convert("RGB")


def slide_final(titulo, texto, n, total):
    img = Image.new("RGB", (W, H), ASFALTO)
    d = ImageDraw.Draw(img)
    cabecalho(d, n, total)
    logo = ROOT / "assets" / "logo.jpg"
    if logo.exists():
        lg = Image.open(logo).convert("RGB").resize((520, 520), Image.LANCZOS)
        mask = Image.new("L", lg.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, 519, 519], fill=255)
        img.paste(lg, ((W - 520) // 2, 120), mask)
        return _texto_final(img, d, titulo, texto)
    # alforje estilizado
    cx, cy = W // 2, 430
    d.ellipse([cx - 46, cy - 250, cx + 46, cy - 158], fill=AMBAR)
    d.polygon([(cx - 140, cy - 40), (cx + 140, cy - 40), (cx + 120, cy - 120), (cx - 120, cy - 120)], fill=(110, 69, 39))
    d.polygon([(cx - 84, cy - 30), (cx + 84, cy - 30), (cx + 8, cy - 140), (cx - 8, cy - 140)], fill=(58, 54, 50))
    for yy in range(cy - 125, cy - 35, 22):
        d.line([(cx, yy), (cx, yy + 11)], fill=AMBAR, width=5)
    d.rounded_rectangle([cx - 150, cy - 50, cx + 150, cy + 130], radius=36, fill=COURO, outline=(74, 45, 23), width=7)
    for bx in (cx - 82, cx + 56):
        d.rectangle([bx, cy - 50, bx + 26, cy + 90], fill=(92, 58, 31))
        d.rounded_rectangle([bx - 6, cy + 20, bx + 32, cy + 52], radius=4, outline=AMBAR, width=6)
    return _texto_final(img, d, titulo, texto)


def _texto_final(img, d, titulo, texto):
    ft = fonte("Oswald.ttf", 78, 700)
    fx = fonte("Inter.ttf", 38, 450)
    y = 700
    for l in quebrar(d, titulo.upper(), ft, W - 160):
        d.text(((W - d.textlength(l, font=ft)) / 2, y), l, font=ft, fill=CREME)
        y += int(ft.size * 1.1)
    y += 30
    for l in quebrar(d, texto, fx, W - 200):
        d.text(((W - d.textlength(l, font=fx)) / 2, y), l, font=fx, fill=(220, 210, 192))
        y += int(fx.size * 1.45)
    fs = fonte("Oswald.ttf", 34, 500)
    rod = "SIGA @ALFORJEABERTO  ·  DESTINOS DE MOTO"
    d.text(((W - d.textlength(rod, font=fs)) / 2, H - 120), rod, font=fs, fill=AMBAR)
    return img


# ---------------------------------------------------------------- git
def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def commit_push(msg):
    git("add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    git("commit", "-m", msg)
    git("push")


# ---------------------------------------------------------------- instagram
def api(metodo, caminho, **params):
    r = requests.request(metodo, f"{GRAPH}/{caminho}", params=params, timeout=120)
    dados = r.json()
    if "error" in dados:
        erro = dados["error"]
        if erro.get("code") == 190:
            sys.exit("TOKEN VENCIDO OU INVÁLIDO: gere um novo token no Graph API Explorer e atualize o segredo IG_USER_TOKEN.")
        raise RuntimeError(f"Erro da API: {erro}")
    return dados


def conta_instagram(token_usuario):
    dados = api("GET", "me/accounts", fields="name,access_token,instagram_business_account{id,username}", access_token=token_usuario)
    for pag in dados.get("data", []):
        ig = pag.get("instagram_business_account")
        if ig:
            print(f"Página: {pag['name']} -> @{ig.get('username')}")
            return ig["id"], pag["access_token"]
    sys.exit("Nenhuma Página com Instagram profissional ligado foi encontrada para este token.")


def esperar(container, token):
    for _ in range(30):
        st = api("GET", container, fields="status_code", access_token=token).get("status_code")
        if st == "FINISHED":
            return
        if st == "ERROR":
            raise RuntimeError(f"Container {container} falhou")
        time.sleep(5)
    raise RuntimeError("Tempo esgotado esperando o Instagram processar a mídia")


def publicar(urls, legenda, token_usuario):
    ig_id, token = conta_instagram(token_usuario)
    filhos = []
    for u in urls:
        c = api("POST", f"{ig_id}/media", image_url=u, is_carousel_item="true", access_token=token)["id"]
        esperar(c, token)
        filhos.append(c)
    car = api("POST", f"{ig_id}/media", media_type="CAROUSEL", children=",".join(filhos), caption=legenda, access_token=token)["id"]
    esperar(car, token)
    pub = api("POST", f"{ig_id}/media_publish", creation_id=car, access_token=token)
    print("Publicado! ID:", pub["id"])
    return pub["id"]


# ---------------------------------------------------------------- principal
def main():
    dry = os.environ.get("DRY_RUN") == "1"
    hoje = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 3600))
    if not dry and os.environ.get("FORCAR") != "1":
        for f in PUBLICADOS.glob("*.json"):
            pub = json.loads(f.read_text(encoding="utf-8")).get("publicado_em", "")
            if pub:
                t = time.mktime(time.strptime(pub, "%Y-%m-%d %H:%M UTC")) - time.timezone - 3 * 3600
                if time.strftime("%Y-%m-%d", time.gmtime(t)) == hoje:
                    print("Já saiu post hoje. Nada a fazer.")
                    return
    arquivos = sorted(FILA.glob("*.json"))
    if not arquivos:
        sys.exit("Fila vazia: nenhum post para publicar.")
    arq = arquivos[0]
    post = json.loads(arq.read_text(encoding="utf-8"))
    print("Post:", post["titulo"])

    garantir_fontes()
    pasta = MEDIA / post["id"]
    pasta.mkdir(parents=True, exist_ok=True)
    usadas, creditos, foto_capa = set(), [], None
    slides = post["slides"]
    total = len(slides) + 1
    for i, s in enumerate(slides, 1):
        foto, cred = None, None
        # capa e slides ímpares: tenta primeiro uma foto com moto no lugar
        if i == 1 or s.get("moto"):
            for termo in (f"{s['foto']} motorcycle", f"{post['titulo']} motorcycle", f"{post['titulo']} motorcyclist"):
                foto, cred = buscar_foto(termo, usadas)
                if foto is not None:
                    break
        if foto is None:
            foto, cred = buscar_foto(s["foto"], usadas)
        if foto is None:
            foto, cred = buscar_foto(post["titulo"], usadas)
        if foto is None and post.get("local"):
            foto, cred = buscar_foto(post["titulo"] + " " + post["local"].split(",")[0], usadas)
        if foto is None and foto_capa:
            foto, cred = foto_capa, None
        if foto is None:
            sys.exit(f"Nenhuma foto encontrada para: {s['foto']}")
        foto_capa = foto_capa or foto
        if cred and cred not in creditos:
            creditos.append(cred)
        img = slide_foto(foto, s["titulo"], s.get("texto", ""), i, total, capa=(i == 1), local=post.get("local") if i == 1 else None)
        img.save(pasta / f"{i:02d}.jpg", "JPEG", quality=90)
    fim = post["fechamento"]
    slide_final(fim["titulo"], fim["texto"], total, total).save(pasta / f"{total:02d}.jpg", "JPEG", quality=90)

    legenda = post["legenda"].strip()
    if creditos:
        legenda += "\n\n📸 Fotos: " + "; ".join(creditos) + " — via Wikimedia Commons"
    legenda += "\n\n🤖 Post criado por IA\n\n" + post["hashtags"].strip()
    (pasta / "legenda.txt").write_text(legenda, encoding="utf-8")

    if dry:
        print("DRY_RUN: imagens geradas em", pasta)
        commit_push(f"Prévia: {post['titulo']}")
        return

    commit_push(f"Mídia: {post['titulo']}")
    time.sleep(20)
    urls = [f"{REPO_RAW}/media/{post['id']}/{i:02d}.jpg" for i in range(1, total + 1)]
    media_id = publicar(urls, legenda, os.environ["IG_USER_TOKEN"])

    PUBLICADOS.mkdir(parents=True, exist_ok=True)
    post["publicado_em"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    post["media_id"] = media_id
    (PUBLICADOS / arq.name).write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    arq.unlink()
    commit_push(f"Publicado: {post['titulo']}")


if __name__ == "__main__":
    main()
