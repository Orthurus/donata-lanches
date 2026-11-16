import json, os, sys, threading, secrets, socket, textwrap, subprocess
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import atualizador
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

NOME = "DONATA LANCHES"
PORT = 5000  # Usando a porta 5000 para evitar conflito com a 8000
DESC_PORT = 5001  # porta UDP da descoberta automática (o app acha o servidor sozinho)
NUM_MESAS = 20
FORMAS = ("Dinheiro", "Débito", "Crédito", "Pix")
COR_LIVRE, COR_CONSUMO, COR_CONTA = "#2e7d4f", "#b3261e", "#f5a623"
USUARIO_PAINEL = {"nome": "Caixa (painel)", "papel": "admin"}
AUTO_IMPRIMIR = True   # imprime na impressora do PC do caixa assim que o pedido é enviado
LARGURA = 32           # colunas do cupom
VERSAO_SERVIDOR = "1.4"                      # suba a cada nova versão (igual à tag do GitHub)
REPO_ATUALIZACAO = "Orthurus/donata-lanches"  # troque pelo seu repositório no GitHub

BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
RES = getattr(sys, "_MEIPASS", BASE)
ARQ = os.path.join(BASE, "dados.json")
LOCK = threading.RLock()
SESS = {}

class Erro(Exception):
    pass

PADRAO = {
    "usuarios": [
        {"nome": "Dono", "pin": "1234", "papel": "admin"},
        {"nome": "Caixa", "pin": "1111", "papel": "admin"},
        {"nome": "Garçom 1", "pin": "0000", "papel": "garcom"}
    ],
    "menu": {
        "X-Burger": {"preco": 22.0, "cat": "Lanches", "destino": "cozinha"},
        "X-Bacon": {"preco": 26.0, "cat": "Lanches", "destino": "cozinha"},
        "Batata Frita": {"preco": 18.0, "cat": "Porções", "destino": "cozinha"},
        "Cerveja Antarctica": {"preco": 12.0, "cat": "Bebidas", "destino": "bar"},
        "Refrigerante Lata": {"preco": 6.0, "cat": "Bebidas", "destino": "bar"}
    },
    "mesas": {}, "vendas": [], "tickets": [], "seq": 0,
}

def carregar():
    if os.path.exists(ARQ):
        try:
            with open(ARQ, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return json.loads(json.dumps(PADRAO))

DB = carregar()

def garantir_locais():
    """Locais de preparo/impressão que o próprio cliente cria e nomeia (Cozinha, Bar, Chapa...)."""
    if isinstance(DB.get("locais"), list) and DB["locais"]:
        return
    imp = DB.get("impressoras") or {}
    DB["locais"] = [{"nome": "Cozinha", "impressora": imp.get("cozinha", "")},
                    {"nome": "Bar", "impressora": imp.get("bar", "")},
                    {"nome": "Caixa", "impressora": imp.get("caixa", "")}]
    for v in DB.get("menu", {}).values():
        d = str(v.get("destino", "")).lower()
        v["destino"] = {"cozinha": "Cozinha", "bar": "Bar"}.get(d, v.get("destino") or "Cozinha")
    DB["impressoras"] = {"modo": imp.get("modo", "varias"), "unica": imp.get("unica", ""), "local_conta": "Caixa"}

garantir_locais()

def nomes_locais():
    return [l["nome"] for l in DB.get("locais", [])]

def destino_valido(x):
    nomes = nomes_locais()
    for n in nomes:
        if n.strip().lower() == str(x or "").strip().lower():
            return n
    return nomes[0] if nomes else "Cozinha"

def salvar():
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQ)

def agora():
    return datetime.now()

def nid():
    DB["seq"] += 1
    return DB["seq"]

def lista_mesas():
    """Mesas cadastradas (números ou nomes). Começa em 1..NUM_MESAS e é editada pelo painel."""
    return DB.setdefault("lista_mesas", [str(i) for i in range(1, NUM_MESAS + 1)])


def mesa_de(d):
    m = DB["mesas"].get(str(d.get("mesa")))
    if not m:
        raise Erro("Mesa não está aberta")
    return m

# ---------------- Impressão ----------------
def centro(t):
    return "\n".join(p.center(LARGURA) for p in (textwrap.wrap(t, LARGURA) or [""]))

def texto(t):
    L = ["=" * LARGURA, centro(NOME), centro(t["destino"].upper() + " - MESA " + str(t["mesa"])),
         centro(f"{t['hora']} - {t['por']}"), "-" * LARGURA]
    for n, q, c in t["itens"]:
        L.append(centro(f"{q}x {n}"))
        if c != "Geral":
            L.append(centro(f"({c})"))
    L.append("=" * LARGURA)
    return "\n".join(L) + "\n\n\n"

def auto_imprimir():
    return DB.get("imprimir_auto", AUTO_IMPRIMIR)

def impressora_de(dest):
    """Impressora de um local pelo nome. dest=None = local das contas. '' = padrão do Windows, '-' = não imprimir."""
    c = DB.get("impressoras") or {}
    if c.get("modo", "varias") == "uma":
        return c.get("unica", "")
    if dest is None:
        dest = c.get("local_conta", "")
    for l in DB.get("locais", []):
        if l["nome"].strip().lower() == str(dest).strip().lower():
            return l.get("impressora", "")
    return ""

def listar_impressoras():
    try:
        if sys.platform.startswith("win"):
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
                               capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        else:
            r = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=10)
        return [x.strip() for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        return []

def mandar_imprimir(caminho, dest):
    _imprimir_em(caminho, impressora_de(dest))

def _imprimir_em(caminho, nome):
    if nome == "-":
        raise Erro("impressão desligada para este local")
    if sys.platform.startswith("win"):
        ps = "Get-Content -Raw -Encoding UTF8 -LiteralPath '%s' | Out-Printer" % caminho.replace("'", "''")
        if nome:
            ps += " -Name '%s'" % nome.replace("'", "''")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           timeout=40, creationflags=0x08000000)
        if r.returncode != 0:
            raise Erro((r.stderr or "falha ao imprimir").strip()[:80])
    else:
        subprocess.run(["lpr"] + (["-P", nome] if nome else []) + [caminho], check=True, timeout=10)

def imprimir(t):
    try:
        pasta = os.path.join(BASE, "tickets")
        os.makedirs(pasta, exist_ok=True)
        p = os.path.join(pasta, f"T{t['id']}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(texto(t))
        mandar_imprimir(p, t.get("destino") or destino_valido(None))
        t["impresso"] = True
        t.pop("erro", None)
    except Exception as ex:
        t["impresso"] = False
        t["erro"] = str(ex)[:80]

# ---------------- Rotas da API ----------------
def r_estado(u, d):
    hoje = agora().strftime("%d/%m/%Y")
    admin = u["papel"] == "admin"
    vh = [v for v in DB["vendas"] if v["data"] == hoje] if admin else []
    por = {}
    for v in vh:
        f = v.get("forma", "Não informado")
        por[f] = round(por.get(f, 0) + v["total"], 2)
    return {"usuario": u["nome"], "papel": u["papel"], "menu": DB["menu"], "mesas": DB["mesas"],
            "n": len(lista_mesas()), "lista": lista_mesas(), "tickets": DB["tickets"][-40:][::-1], "agora": time.time(),
            "faturamento": round(sum(v["total"] for v in vh), 2) if admin else None, "por_forma": por}

def r_abrir(u, d):
    k = str(d.get("mesa"))
    if k not in lista_mesas():
        raise Erro("Mesa inválida")
    DB["mesas"].setdefault(k, {"comandas": ["Geral"], "itens": [], "aberta": agora().strftime("%H:%M"),
                                                  "ts": time.time(), "conta": False})
    return {}

def r_comanda(u, d):
    m = mesa_de(d)
    n = str(d.get("nome", "")).strip()[:30]
    if not n:
        raise Erro("Informe o nome da comanda")
    if n not in m["comandas"]:
        m["comandas"].append(n)
    return {}

def r_add(u, d):
    m = mesa_de(d)
    p, c = d.get("produto"), d.get("comanda", "Geral")
    if p not in DB["menu"]:
        raise Erro("Produto inexistente")
    if c not in m["comandas"]:
        raise Erro("Comanda inexistente")
    for i in m["itens"]:
        if i["nome"] == p and i["comanda"] == c and not i["enviado"]:
            i["qtd"] += 1
            return {}
    m["itens"].append({"id": nid(), "nome": p, "preco": DB["menu"][p]["preco"], "qtd": 1,
                       "comanda": c, "enviado": False, "por": u["nome"]})
    return {}

def r_qtd(u, d):
    m = mesa_de(d)
    for i in m["itens"]:
        if i["id"] == d.get("id"):
            if i["enviado"] and u["papel"] != "admin":
                raise Erro("Item já enviado para preparo. Peça ao caixa para remover.")
            i["qtd"] += int(d.get("delta", 0))
            if i["qtd"] <= 0:
                m["itens"].remove(i)
            return {}
    raise Erro("Item não encontrado")

def r_enviar(u, d):
    m = mesa_de(d)
    novos = [i for i in m["itens"] if not i["enviado"]]
    if not novos:
        raise Erro("Nada novo para enviar")
    grupos = {}
    for i in novos:
        i["enviado"] = True
        dest = DB["menu"].get(i["nome"], {}).get("destino") or destino_valido(None)
        grupos.setdefault(dest, []).append([i["nome"], i["qtd"], i["comanda"]])
    for dest, its in grupos.items():
        t = {"id": nid(), "destino": dest, "mesa": d["mesa"], "hora": agora().strftime("%H:%M"),
             "por": u["nome"], "itens": its, "impresso": False}
        DB["tickets"].append(t)
        if auto_imprimir():
            imprimir(t)
    DB["tickets"] = DB["tickets"][-300:]
    return {"tickets": len(grupos)}

def r_pagar(u, d):
    m = mesa_de(d)
    c = d.get("comanda", "*")
    its = [i for i in m["itens"] if c == "*" or i["comanda"] == c]
    if not its:
        raise Erro("Comanda sem itens")
    forma = d.get("forma") if d.get("forma") in FORMAS else "Não informado"
    if any(not i["enviado"] for i in its):
        raise Erro("Há itens não enviados. Envie o pedido antes de pagar.")
    total = round(sum(i["preco"] * i["qtd"] for i in its), 2)
    n = agora()
    DB["vendas"].append({"data": n.strftime("%d/%m/%Y"), "hora": n.strftime("%H:%M:%S"), "mesa": d["mesa"],
                         "comanda": c, "total": total, "itens": [[i["nome"], i["qtd"]] for i in its], "por": u["nome"], "forma": forma})
    m["itens"] = [i for i in m["itens"] if i not in its]
    if c not in ("*", "Geral") and c in m["comandas"]:
        m["comandas"].remove(c)
    if not m["itens"]:
        del DB["mesas"][str(d["mesa"])]
    return {"total": total}

def r_fechar(u, d):
    if mesa_de(d)["itens"]:
        raise Erro("A mesa ainda tem itens")
    del DB["mesas"][str(d["mesa"])]
    return {}

def r_reimprimir(u, d):
    for t in DB["tickets"]:
        if t["id"] == d.get("id"):
            imprimir(t)
            return {}
    raise Erro("Pedido não encontrado")

def r_menu_set(u, d):
    n = str(d.get("nome", "")).strip()
    try:
        preco = float(str(d.get("preco", "")).replace(",", "."))
    except ValueError:
        raise Erro("Preço inválido")
    if not n or preco < 0:
        raise Erro("Dados inválidos")
    DB["menu"][n] = {"preco": preco, "cat": str(d.get("cat") or "Outros").strip(),
                     "destino": destino_valido(d.get("destino"))}
    return {}

def r_menu_del(u, d):
    DB["menu"].pop(d.get("nome"), None)
    return {}

def r_conta(u, d):
    m = mesa_de(d)
    m["conta"] = not m.get("conta", False)
    return {}


def r_mesa_add(u, d):
    nome = str(d.get("nome", "")).strip()[:20]
    if not nome:
        raise Erro("Digite o número ou o nome da mesa")
    if nome in lista_mesas():
        raise Erro(f"A mesa {nome} já existe")
    lista_mesas().append(nome)
    lista_mesas().sort(key=lambda x: (0, int(x), "") if x.isdigit() else (1, 0, x.lower()))
    return {}


def r_mesa_del(u, d):
    nome = str(d.get("nome", ""))
    if nome not in lista_mesas():
        raise Erro("Mesa não encontrada")
    m = DB["mesas"].get(nome)
    if m and m["itens"]:
        raise Erro("Essa mesa tem consumo em aberto. Receba antes de remover.")
    DB["mesas"].pop(nome, None)
    lista_mesas().remove(nome)
    return {}


ROTAS = {"mesa/adicionar": r_mesa_add, "mesa/remover": r_mesa_del, "mesa/conta": r_conta, "estado": r_estado, "mesa/abrir": r_abrir, "comanda/nova": r_comanda, "item/add": r_add,
         "item/qtd": r_qtd, "enviar": r_enviar, "pagar": r_pagar, "mesa/fechar": r_fechar,
         "ticket/imprimir": r_reimprimir, "menu/set": r_menu_set, "menu/del": r_menu_del}
SO_ADMIN = {"menu/set", "menu/del", "mesa/fechar", "mesa/adicionar", "mesa/remover"}

PAGINA_INSTALAR = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>DoNata Lanches</title>
<style>body{margin:0;background:#111;color:#f5f0e6;font:17px system-ui,sans-serif;text-align:center;padding:24px}
h1{color:#ffc62e;font:italic 800 32px Georgia,serif;margin:8px 0}
a.b{display:block;background:#ffc62e;color:#111;font-weight:800;padding:18px;border-radius:14px;text-decoration:none;margin:22px auto;max-width:360px;font-size:20px}
ol{text-align:left;max-width:360px;margin:auto;line-height:1.6;color:#d8cfc0}small{color:#a89a86}</style></head><body>
<h1>DoNata Lanches</h1><p>Aplicativo dos garçons</p>
<a class="b" href="/baixar-apk">Baixar o aplicativo</a>
<ol><li>Toque em <b>Baixar o aplicativo</b> e abra o arquivo quando terminar.</li>
<li>Se o Android pedir, permita <b>instalar apps desconhecidos</b> para este navegador.</li>
<li>Se aparecer um aviso de segurança (Play Protect), toque em <b>Mais detalhes</b> e depois em <b>Instalar mesmo assim</b>.</li>
<li>Abra o app: ele encontra o caixa sozinho no Wi-Fi.</li></ol>
<p><small>Aplicativo do próprio restaurante. Funciona dentro do Wi-Fi do caixa.</small></p></body></html>"""


def versao_app():
    """Versão do APK publicado: lida de versao.txt (ao lado do servidor)."""
    try:
        with open(os.path.join(BASE, "versao.txt"), encoding="utf-8") as f:
            return f.read().strip() or "1.0"
    except OSError:
        return "1.0"


class H(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def resp(self, code, body, tipo="application/json", extra=None):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", tipo if tipo.startswith("application/vnd") else tipo + "; charset=utf-8")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        # Rota para baixar o APK diretamente pelo navegador
        if self.path in ("/baixar-apk", "/download"):
            apk_path = os.path.join(BASE, "donata.apk")
            if os.path.exists(apk_path):
                with open(apk_path, "rb") as f:
                    self.resp(200, f.read(), "application/vnd.android.package-archive",
                              {"Content-Disposition": 'attachment; filename="donata.apk"'})
            else:
                self.resp(404, b"APK nao encontrado na pasta do servidor. Coloque o donata.apk la.", "text/plain")
            return

        if self.path.startswith("/api/"):
            return self.api({})
        try:
            with open(os.path.join(RES, "index.html"), "rb") as f:
                self.resp(200, f.read(), "text/html")
        except OSError:
            self.resp(200, PAGINA_INSTALAR.encode("utf-8"), "text/html")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            d = {}
        self.api(d)

    def api(self, d):
        rota = self.path[5:].split("?")[0]
        with LOCK:
            try:
                if rota == "versao":
                    return self.resp(200, {"versao": versao_app()})
                if rota == "usuarios":
                    return self.resp(200, {"nomes": [u["nome"] for u in DB["usuarios"]]})
                if rota == "login":
                    for u in DB["usuarios"]:
                        if u["nome"] == d.get("nome") and u["pin"] == str(d.get("pin")):
                            t = secrets.token_hex(16)
                            SESS[t] = u
                            return self.resp(200, {"token": t})
                    raise Erro("PIN incorreto")
                u = SESS.get(self.headers.get("X-Token"))
                if not u:
                    return self.resp(401, {"erro": "login"})
                if rota not in ROTAS:
                    raise Erro("Rota inválida")
                if rota in SO_ADMIN and u["papel"] != "admin":
                    raise Erro("Apenas o caixa/dono pode fazer isso")
                r = ROTAS[rota](u, d)
                salvar()
                self.resp(200, r)
            except Erro as e:
                self.resp(400, {"erro": str(e)})
            except Exception as e:
                self.resp(500, {"erro": "Erro interno: " + str(e)})

def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

# ---------------- GUI do Servidor (Tkinter) ----------------
def reais(v):
    return "R$ " + f"{v:.2f}".replace(".", ",")


def total_itens(its):
    return sum(i["preco"] * i["qtd"] for i in its)


def tempo_aberta(m):
    ts = m.get("ts")
    if not ts:
        return m.get("aberta", "")
    mins = max(int((time.time() - ts) // 60), 0)
    return f"{mins // 60}h{mins % 60:02d}" if mins >= 60 else f"{mins}min"


def texto_conta(num, m):
    L = ["=" * LARGURA, centro(NOME), centro(f"CONTA - MESA {num}"),
         centro(agora().strftime("%d/%m/%Y %H:%M")), "-" * LARGURA]
    varias = len(m["comandas"]) > 1
    for c in m["comandas"]:
        its = [i for i in m["itens"] if i["comanda"] == c]
        if not its:
            continue
        if varias:
            L.append(centro(f"[ {c} ]"))
        for i in its:
            L.append(centro(f"{i['qtd']}x {i['nome']}"))
            L.append(centro(reais(i["preco"] * i["qtd"])))
        if varias:
            L.append(centro(f"Subtotal {reais(total_itens(its))}"))
    L += ["-" * LARGURA, centro("TOTAL"), centro(reais(total_itens(m["itens"]))), "=" * LARGURA]
    return "\n".join(L) + "\n\n\n"


def imprimir_texto(conteudo, nome_arquivo, dest=None):
    pasta = os.path.join(BASE, "tickets")
    os.makedirs(pasta, exist_ok=True)
    p = os.path.join(pasta, nome_arquivo)
    with open(p, "w", encoding="utf-8") as f:
        f.write(conteudo)
    mandar_imprimir(p, dest)


class JanelaPedido:
    """Tela do caixa para lançar pedidos: em uma mesa (mesa=...) ou venda no balcão (mesa=None)."""
    def __init__(self, gui, mesa=None):
        self.gui, self.mesa = gui, mesa
        self.balcao = mesa is None
        self.carrinho = {}
        self.cat = "Todos"
        w = self.w = tk.Toplevel(gui.root)
        w.title("Venda no balcão" if self.balcao else f"Lançar pedido - Mesa {mesa}")
        w.configure(bg="#222222")
        w.geometry("1250x780")
        try:
            w.state("zoomed")
        except Exception:
            pass
        w.transient(gui.root)
        w.protocol("WM_DELETE_WINDOW", self.fechar)

        esq = tk.Frame(w, bg="#2b2b2b", width=430)
        esq.pack(side="left", fill="y", padx=(10, 5), pady=10)
        esq.pack_propagate(False)
        dir_ = tk.Frame(w, bg="#222222")
        dir_.pack(side="left", fill="both", expand=True, padx=(5, 10), pady=10)

        # ----- Lado esquerdo: o pedido -----
        titulo = "VENDA NO BALCÃO" if self.balcao else f"MESA {mesa}"
        tk.Label(esq, text=titulo, bg="#ffc107", fg="#000", font=("Helvetica", 20, "bold"), pady=8).pack(fill="x")
        cols = ("Item", "Qtd", "Valor")
        self.tree = ttk.Treeview(esq, columns=cols, show="headings", height=10)
        for c, wd in zip(cols, (210, 50, 110)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=wd, anchor="w" if c == "Item" else "center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        bq = tk.Frame(esq, bg="#2b2b2b")
        bq.pack(pady=2)
        for txt, cor, cmd in ((" + ", COR_LIVRE, lambda: self.mudar(1)), (" − ", COR_CONTA, lambda: self.mudar(-1)),
                              (" Remover ", COR_CONSUMO, self.remover)):
            tk.Button(bq, text=txt, bg=cor, fg="#fff" if cor != COR_CONTA else "#000",
                      font=("Helvetica", 15, "bold"), command=cmd).pack(side="left", padx=4)
        self.lbl_total = tk.Label(esq, text="Total: R$ 0,00", bg="#2b2b2b", fg="#ffc107", font=("Helvetica", 24, "bold"))
        self.lbl_total.pack(pady=8)

        if self.balcao:
            linha = tk.Frame(esq, bg="#2b2b2b")
            linha.pack(pady=4)
            tk.Label(linha, text="Pagamento:", bg="#2b2b2b", fg="#fff", font=("Helvetica", 14, "bold")).pack(side="left")
            self.cb_forma = ttk.Combobox(linha, values=list(FORMAS), width=10, state="readonly", font=("Helvetica", 14))
            self.cb_forma.set(FORMAS[0])
            self.cb_forma.pack(side="left", padx=6)
            tk.Button(esq, text=" RECEBER E FECHAR PEDIDO ", bg=COR_LIVRE, fg="#fff", font=("Helvetica", 16, "bold"),
                      command=self.fechar_balcao).pack(fill="x", padx=8, pady=(6, 10))
        else:
            with LOCK:
                m = DB["mesas"].get(str(mesa))
                coms = list(m["comandas"]) if m else ["Geral"]
            linha = tk.Frame(esq, bg="#2b2b2b")
            linha.pack(pady=4)
            tk.Label(linha, text="Comanda:", bg="#2b2b2b", fg="#fff", font=("Helvetica", 14, "bold")).pack(side="left")
            self.cb_com = ttk.Combobox(linha, values=coms, width=14, font=("Helvetica", 14))
            self.cb_com.set("Geral")
            self.cb_com.pack(side="left", padx=6)
            tk.Label(esq, text="(digite um nome para criar outra comanda)", bg="#2b2b2b", fg="#aaa",
                     font=("Helvetica", 10)).pack()
            tk.Button(esq, text=" LANÇAR E ENVIAR (preparo) ", bg=COR_LIVRE, fg="#fff", font=("Helvetica", 15, "bold"),
                      command=lambda: self.confirmar(True)).pack(fill="x", padx=8, pady=(8, 4))
            tk.Button(esq, text=" Só lançar (enviar depois) ", bg="#555", fg="#fff", font=("Helvetica", 13, "bold"),
                      command=lambda: self.confirmar(False)).pack(fill="x", padx=8, pady=(0, 10))
        tk.Button(esq, text=" Cancelar ", bg="#333", fg="#fff", font=("Helvetica", 12), command=self.fechar).pack(pady=(0, 10))

        # ----- Lado direito: cardápio -----
        bus = tk.Frame(dir_, bg="#222222")
        bus.pack(fill="x")
        tk.Label(bus, text="Buscar:", bg="#222222", fg="#fff", font=("Helvetica", 15, "bold")).pack(side="left")
        self.var_busca = tk.StringVar()
        self.var_busca.trace_add("write", lambda *a: self.desenhar_menu())
        self.ent = tk.Entry(bus, textvariable=self.var_busca, font=("Helvetica", 18), width=30)
        self.ent.pack(side="left", padx=8, ipady=4)
        self.fcats = tk.Frame(dir_, bg="#222222")
        self.fcats.pack(fill="x", pady=8)
        caixa = tk.Frame(dir_, bg="#222222")
        caixa.pack(fill="both", expand=True)
        self.cv = tk.Canvas(caixa, bg="#222222", highlightthickness=0)
        sb = ttk.Scrollbar(caixa, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.grade = tk.Frame(self.cv, bg="#222222")
        self.cv.create_window((0, 0), window=self.grade, anchor="nw")
        self.grade.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind_all("<MouseWheel>", lambda e: self.cv.yview_scroll(int(-e.delta / 120), "units"))
        self.desenhar_cats()
        self.desenhar_menu()
        self.desenhar_carrinho()
        self.ent.focus_set()

    def fechar(self):
        try:
            self.cv.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.w.destroy()

    def desenhar_cats(self):
        for x in self.fcats.winfo_children():
            x.destroy()
        with LOCK:
            cats = ["Todos"] + sorted({v.get("cat", "Outros") for v in DB["menu"].values()})
        for c in cats:
            ativo = c == self.cat
            tk.Button(self.fcats, text=f" {c} ", bg="#ffc107" if ativo else "#4a3728", fg="#000" if ativo else "#fff",
                      font=("Helvetica", 14, "bold"), command=lambda c=c: self.set_cat(c)).pack(side="left", padx=3)

    def set_cat(self, c):
        self.cat = c
        self.desenhar_cats()
        self.desenhar_menu()

    def desenhar_menu(self):
        for x in self.grade.winfo_children():
            x.destroy()
        busca = self.var_busca.get().strip().lower()
        with LOCK:
            itens = [(n, v) for n, v in DB["menu"].items()]
        itens = [(n, v) for n, v in itens if (self.cat == "Todos" or v.get("cat", "Outros") == self.cat)
                 and (not busca or busca in n.lower())]
        for idx, (n, v) in enumerate(itens):
            tk.Button(self.grade, text=f"{n}\n{reais(v['preco'])}", bg="#ffc107", fg="#000", activebackground="#ffd54f",
                      width=18, height=3, wraplength=190, font=("Helvetica", 14, "bold"),
                      command=lambda n=n: self.add(n)).grid(row=idx // 4, column=idx % 4, padx=5, pady=5)
        if not itens:
            tk.Label(self.grade, text="Nenhum item encontrado", bg="#222222", fg="#aaa", font=("Helvetica", 16)).pack(pady=20)

    def add(self, nome):
        self.carrinho[nome] = self.carrinho.get(nome, 0) + 1
        self.desenhar_carrinho(nome)

    def mudar(self, d):
        sel = self.tree.selection()
        if not sel:
            return
        n = sel[0]
        self.carrinho[n] = self.carrinho.get(n, 0) + d
        if self.carrinho[n] <= 0:
            del self.carrinho[n]
            self.desenhar_carrinho()
        else:
            self.desenhar_carrinho(n)

    def remover(self):
        sel = self.tree.selection()
        if sel:
            self.carrinho.pop(sel[0], None)
            self.desenhar_carrinho()

    def total(self):
        with LOCK:
            return sum(DB["menu"].get(n, {}).get("preco", 0) * q for n, q in self.carrinho.items())

    def desenhar_carrinho(self, selecionar=None):
        for r in self.tree.get_children():
            self.tree.delete(r)
        with LOCK:
            menu = DB["menu"]
            for n, q in self.carrinho.items():
                self.tree.insert("", "end", iid=n, values=(n, q, reais(menu.get(n, {}).get("preco", 0) * q)))
        if selecionar and selecionar in self.carrinho:
            self.tree.selection_set(selecionar)
        self.lbl_total.config(text=f"Total: {reais(self.total())}")

    def _lancar(self, k, com):
        """Coloca o carrinho na mesa k (já aberta) na comanda com."""
        if com not in DB["mesas"][k]["comandas"]:
            r_comanda(USUARIO_PAINEL, {"mesa": k, "nome": com})
        for nome, q in self.carrinho.items():
            for _ in range(q):
                r_add(USUARIO_PAINEL, {"mesa": k, "produto": nome, "comanda": com})

    def confirmar(self, enviar):
        if not self.carrinho:
            return messagebox.showinfo("Pedido", "Clique nos itens do cardápio para montar o pedido.", parent=self.w)
        try:
            with LOCK:
                k = str(self.mesa)
                if k not in DB["mesas"]:
                    r_abrir(USUARIO_PAINEL, {"mesa": k})
                self._lancar(k, self.cb_com.get().strip()[:30] or "Geral")
                if enviar:
                    r_enviar(USUARIO_PAINEL, {"mesa": k})
                salvar()
        except Exception as e:
            return messagebox.showerror("Atenção", str(e), parent=self.w)
        self.gui.redesenhar_mesas(True)
        self.fechar()

    def fechar_balcao(self):
        if not self.carrinho:
            return messagebox.showinfo("Pedido", "Clique nos itens do cardápio para montar o pedido.", parent=self.w)
        forma, total = self.cb_forma.get(), self.total()
        if not messagebox.askyesno("Receber", f"Receber {reais(total)} em {forma}?", parent=self.w):
            return
        k = None
        try:
            with LOCK:
                k = f"Balcão {nid()}"
                DB["mesas"][k] = {"comandas": ["Geral"], "itens": [], "aberta": agora().strftime("%H:%M"),
                                  "ts": time.time(), "conta": False}
                self._lancar(k, "Geral")
                r_enviar(USUARIO_PAINEL, {"mesa": k})
                r_pagar(USUARIO_PAINEL, {"mesa": k, "comanda": "*", "forma": forma})
                salvar()
        except Exception as e:
            with LOCK:
                if k:
                    DB["mesas"].pop(k, None)
            return messagebox.showerror("Atenção", str(e), parent=self.w)
        self.gui.carregar_vendas()
        self.gui.redesenhar_mesas(True)
        self.fechar()
        messagebox.showinfo("Venda registrada", f"Venda de {reais(total)} ({forma}) registrada.", parent=self.gui.root)


class ServidorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("DoNata Lanches - Painel do Servidor")
        self.root.geometry("1280x860")
        try:
            self.root.state("zoomed")  # abre ocupando a tela toda
        except Exception:
            pass
        self.root.configure(bg="#222222")

        # Estilos
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#222222", borderwidth=0)
        style.configure("TNotebook.Tab", background="#333333", foreground="#ffffff", padding=[26, 14], font=('Helvetica', 15, 'bold'))
        style.map("TNotebook.Tab", background=[("selected", "#ffc107")], foreground=[("selected", "#000000")])
        # Letras e botões maiores (mais fácil de ler e de clicar)
        root.option_add("*Font", ("Helvetica", 13))
        root.option_add("*Button.padX", 18)
        root.option_add("*Button.padY", 9)
        root.option_add("*TCombobox*Listbox.font", ("Helvetica", 13))
        style.configure(".", font=("Helvetica", 13))
        style.configure("Treeview", font=("Helvetica", 13), rowheight=38)
        style.configure("Treeview.Heading", font=("Helvetica", 13, "bold"), padding=6)
        style.configure("TCombobox", padding=6)

        # Topo com Endereço IP
        frame_top = tk.Frame(root, bg="#333333", pady=10)
        frame_top.pack(fill="x")

        ip = ip_local()
        tk.Label(frame_top, text="SERVIDOR ONLINE", fg="#28a745", bg="#333333", font=("Helvetica", 20, "bold")).pack()
        tk.Label(frame_top, text=f"Endereço nos celulares: http://{ip}:{PORT}", fg="#ffffff", bg="#333333", font=("Helvetica", 16, "bold")).pack(pady=2)
        tk.Label(frame_top, text=f"Link para baixar o APK: http://{ip}:{PORT}/baixar-apk", fg="#ffc107", bg="#333333", font=("Helvetica", 13)).pack()
        tk.Button(frame_top, text=f"Verificar atualização (versão {VERSAO_SERVIDOR})", bg="#ffc107", fg="#000",
                  font=("Helvetica", 13, "bold"), command=self.verificar_update).pack(pady=(6, 0))
        tk.Button(frame_top, text="📱  Instalar no celular (QR Code)", bg="#ffffff", fg="#000",
                  font=("Helvetica", 13, "bold"), command=self.mostrar_qr).pack(pady=(6, 0))

        # Abas
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Aba 1: Funcionários
        self.aba_users = tk.Frame(self.notebook, bg="#222222")
        self.notebook.add(self.aba_users, text=" Funcionários / Senhas ")
        self.setup_aba_users()

        # Aba 2: Cardápio
        self.aba_menu = tk.Frame(self.notebook, bg="#222222")
        self.notebook.add(self.aba_menu, text=" Cardápio / Preços ")
        self.setup_aba_menu()
        self.aba_imp = tk.Frame(self.notebook, bg="#222222")
        self.notebook.add(self.aba_imp, text=" ⚙ Impressoras ")
        self.setup_aba_impressoras()
        # Abas novas (ficam no começo): Mesas, Pedidos enviados e Vendas
        self.aba_mesas = tk.Frame(self.notebook, bg="#222222")
        self.notebook.insert(0, self.aba_mesas, text=" Mesas ")
        self.aba_pedidos = tk.Frame(self.notebook, bg="#222222")
        self.notebook.insert(1, self.aba_pedidos, text=" Pedidos enviados ")
        self.aba_vendas = tk.Frame(self.notebook, bg="#222222")
        self.notebook.insert(2, self.aba_vendas, text=" Vendas ")
        self.setup_aba_mesas()
        self.setup_aba_pedidos()
        self.setup_aba_vendas()
        self.notebook.select(0)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.carregar_vendas())
        self.root.after(2000, self.tick)
        self.root.after(3000, lambda: self.verificar_update(True))

    # --- ATUALIZAÇÃO AUTOMÁTICA DAS TELAS ---
    def tick(self):
        try:
            self.redesenhar_mesas()
            self.redesenhar_pedidos()
        except Exception:
            pass
        self.root.after(2000, self.tick)

    # --- ABA MESAS (mapa colorido) ---
    def setup_aba_mesas(self):
        self.sel_mesa, self._sig_mesas, self._linhas = None, None, {}
        topo = tk.Frame(self.aba_mesas, bg="#222222")
        topo.pack(fill="x", padx=10, pady=(10, 0))
        for txt, cor, fg in (("Livre", COR_LIVRE, "#fff"), ("Em consumo", COR_CONSUMO, "#fff"), ("Conta pedida", COR_CONTA, "#000")):
            tk.Label(topo, text=f"  {txt}  ", bg=cor, fg=fg, font=("Helvetica", 13, "bold")).pack(side="left", padx=4)
        tk.Button(topo, text=" 🛒 Venda no balcão ", bg="#ffc107", fg="#000", font=("Helvetica", 14, "bold"),
                  command=self.venda_balcao).pack(side="left", padx=(14, 4))
        tk.Button(topo, text=" ➕ Lançar pedido na mesa ", bg="#ffffff", fg="#000", font=("Helvetica", 14, "bold"),
                  command=self.lancar_itens).pack(side="left", padx=4)
        tk.Button(topo, text=" − Remover mesa ", bg="#b3261e", fg="#fff", font=("Helvetica", 14, "bold"),
                  command=self.remover_mesa).pack(side="right", padx=4)
        tk.Button(topo, text=" + Adicionar mesa ", bg=COR_LIVRE, fg="#fff", font=("Helvetica", 14, "bold"),
                  command=self.adicionar_mesa).pack(side="right", padx=4)
        self.grade_mesas = tk.Frame(self.aba_mesas, bg="#222222")
        self.grade_mesas.pack(fill="x", padx=10, pady=8)
        self.lbl_sel = tk.Label(self.aba_mesas, text="Clique em uma mesa", fg="#ffc107", bg="#222222", font=("Helvetica", 16, "bold"))
        self.lbl_sel.pack(anchor="w", padx=12)
        cols = ("Comanda", "Item", "Qtd", "Valor", "Status")
        self.tree_mesa = ttk.Treeview(self.aba_mesas, columns=cols, show="headings", height=6)
        for c, w in zip(cols, (140, 280, 60, 110, 100)):
            self.tree_mesa.heading(c, text=c)
            self.tree_mesa.column(c, width=w, anchor="center")
        self.tree_mesa.pack(fill="both", expand=True, padx=10, pady=5)
        barra = tk.Frame(self.aba_mesas, bg="#222222")
        barra.pack(pady=(0, 8))

        def bt(txt, cor, fg, cmd):
            tk.Button(barra, text=txt, bg=cor, fg=fg, font=("Helvetica", 13, "bold"), command=cmd).pack(side="left", padx=4)
        bt(" Pedir / tirar conta ", COR_CONTA, "#000", self.tg_conta)
        bt(" Imprimir conta ", "#ffc107", "#000", self.imprimir_conta)
        bt(" Enviar itens novos ", "#555", "#fff", self.enviar_novos)
        tk.Label(barra, text="  Forma:", fg="#fff", bg="#222222").pack(side="left")
        self.cb_forma = ttk.Combobox(barra, values=list(FORMAS), width=9, state="readonly")
        self.cb_forma.set(FORMAS[0])
        self.cb_forma.pack(side="left", padx=4)
        bt(" Receber comanda ", COR_LIVRE, "#fff", lambda: self.receber(False))
        bt(" Receber mesa toda ", COR_LIVRE, "#fff", lambda: self.receber(True))
        self.redesenhar_mesas(True)

    def adicionar_mesa(self):
        with LOCK:
            nums = [int(x) for x in lista_mesas() if x.isdigit()]
        sugestao = str(max(nums) + 1) if nums else "1"
        nome = simpledialog.askstring("Adicionar mesa", "Número ou nome da nova mesa:", initialvalue=sugestao, parent=self.root)
        if not nome:
            return
        try:
            with LOCK:
                r_mesa_add(USUARIO_PAINEL, {"nome": nome})
                salvar()
            self.sel_mesa = nome.strip()[:20]
        except Exception as e:
            messagebox.showerror("Atenção", str(e))
        self.redesenhar_mesas(True)

    def remover_mesa(self):
        n = self.sel_mesa
        if not n:
            return messagebox.showinfo("Remover mesa", "Clique primeiro na mesa que quer remover.")
        if not messagebox.askyesno("Remover mesa", f"Remover a mesa {n}?\n(Só é possível se ela estiver sem consumo.)"):
            return
        try:
            with LOCK:
                r_mesa_del(USUARIO_PAINEL, {"nome": n})
                salvar()
            self.sel_mesa = None
        except Exception as e:
            messagebox.showerror("Atenção", str(e))
        self.redesenhar_mesas(True)

    def selecionar_mesa(self, n):
        self.sel_mesa = n
        self.redesenhar_mesas(True)

    def redesenhar_mesas(self, forcar=False):
        with LOCK:
            mesas = json.loads(json.dumps(DB["mesas"]))
            lista = list(lista_mesas())
        sig = (json.dumps(mesas, sort_keys=True), int(time.time() // 60), self.sel_mesa, tuple(lista))
        if sig == self._sig_mesas and not forcar:
            return
        self._sig_mesas = sig
        for w in self.grade_mesas.winfo_children():
            w.destroy()
        for idx, n in enumerate(lista):
            m = mesas.get(str(n))
            if m:
                conta = m.get("conta")
                bg, fg = (COR_CONTA, "#000") if conta else (COR_CONSUMO, "#fff")
                txt = f"{n}{' · CONTA' if conta else ''}\n{tempo_aberta(m)} · {reais(total_itens(m['itens']))}"
            else:
                bg, fg, txt = COR_LIVRE, "#fff", f"{n}\nlivre"
            esc = self.sel_mesa == n
            b = tk.Button(self.grade_mesas, text=txt, bg=bg, fg=fg, activebackground=bg, width=17, height=4,
                          relief="solid" if esc else "flat", bd=4 if esc else 1, font=("Helvetica", 13, "bold"),
                          command=lambda n=n: self.selecionar_mesa(n))
            b.grid(row=idx // 6, column=idx % 6, padx=4, pady=4)
        sel = self.tree_mesa.selection()
        for r in self.tree_mesa.get_children():
            self.tree_mesa.delete(r)
        self._linhas = {}
        m = mesas.get(str(self.sel_mesa)) if self.sel_mesa else None
        if not m:
            self.lbl_sel.config(text="Clique em uma mesa" if not self.sel_mesa else f"Mesa {self.sel_mesa} - livre")
            return
        self.lbl_sel.config(text=f"Mesa {self.sel_mesa} - aberta há {tempo_aberta(m)} - total {reais(total_itens(m['itens']))}")
        for i in m["itens"]:
            iid = str(i["id"])
            self._linhas[iid] = i["comanda"]
            self.tree_mesa.insert("", "end", iid=iid, values=(i["comanda"], i["nome"], i["qtd"],
                                  reais(i["preco"] * i["qtd"]), "enviado" if i["enviado"] else "novo"))
        for r in sel:
            if r in self._linhas:
                self.tree_mesa.selection_set(r)

    def acao(self, fn):
        n = self.sel_mesa
        if not n:
            return messagebox.showinfo("Mesas", "Clique em uma mesa primeiro.")
        try:
            fn(n)
        except Exception as e:
            messagebox.showerror("Atenção", str(e))
        self.redesenhar_mesas(True)

    def tg_conta(self):
        def f(n):
            with LOCK:
                r_conta(USUARIO_PAINEL, {"mesa": n})
                salvar()
        self.acao(f)

    def enviar_novos(self):
        def f(n):
            with LOCK:
                r_enviar(USUARIO_PAINEL, {"mesa": n})
                salvar()
        self.acao(f)

    def imprimir_conta(self):
        def f(n):
            with LOCK:
                m = DB["mesas"].get(str(n))
                if not m or not m["itens"]:
                    raise Erro("Mesa sem itens para imprimir")
                txt = texto_conta(n, m)
                m["conta"] = True
                salvar()
            imprimir_texto(txt, f"Conta_mesa{n}_{agora().strftime('%H%M%S')}.txt")
        self.acao(f)

    def receber(self, tudo):
        sel = self.tree_mesa.selection()
        if not tudo and not sel:
            return messagebox.showinfo("Receber", "Clique em um item da comanda que será paga.")
        c = "*" if tudo else self._linhas.get(sel[0], "Geral")
        forma = self.cb_forma.get()

        def f(n):
            with LOCK:
                m = DB["mesas"].get(str(n))
                if not m:
                    raise Erro("Mesa não está aberta")
                total = total_itens([i for i in m["itens"] if c == "*" or i["comanda"] == c])
            if not messagebox.askyesno("Receber", f"Receber {reais(total)} em {forma}\n({'mesa toda' if tudo else 'comanda ' + c})?"):
                return
            with LOCK:
                r_pagar(USUARIO_PAINEL, {"mesa": n, "comanda": c, "forma": forma})
                salvar()
            self.carregar_vendas()
        self.acao(f)

    def lancar_itens(self):
        if not self.sel_mesa:
            return messagebox.showinfo("Lançar pedido", "Clique primeiro na mesa (a mesa livre também serve: ela será aberta).")
        JanelaPedido(self, self.sel_mesa)

    def venda_balcao(self):
        JanelaPedido(self, None)

    # --- ABA IMPRESSORAS / LOCAIS ---
    def setup_aba_impressoras(self):
        cfg = DB.get("impressoras") or {}
        f = self.aba_imp
        BG = "#222222"
        tk.Label(f, text="Locais e impressoras", fg="#ffc107", bg=BG, font=("Helvetica", 22, "bold")).pack(anchor="w", padx=20, pady=(14, 0))
        tk.Label(f, text="Crie os locais que o cliente tem (Cozinha, Bar, Chapa, Sobremesas...) e escolha a impressora de cada um.",
                 fg="#ddd", bg=BG, font=("Helvetica", 13)).pack(anchor="w", padx=20)
        self.var_modo = tk.StringVar(value=cfg.get("modo", "varias"))
        self.var_auto = tk.BooleanVar(value=auto_imprimir())
        box = tk.Frame(f, bg="#2b2b2b")
        box.pack(fill="x", padx=20, pady=10)
        for txt, val in (("Tenho UMA impressora só (tudo sai nela)", "uma"), ("Tenho mais de uma (uma para cada local)", "varias")):
            tk.Radiobutton(box, text=txt, value=val, variable=self.var_modo, command=self.atualiza_modo_imp, bg="#2b2b2b",
                           fg="#fff", selectcolor="#444", activebackground="#2b2b2b", activeforeground="#fff",
                           font=("Helvetica", 14, "bold")).pack(anchor="w", padx=12, pady=3)
        fu = tk.Frame(f, bg=BG)
        fu.pack(anchor="w", padx=20, pady=4)
        tk.Label(fu, text="Impressora única:", fg="#fff", bg=BG, font=("Helvetica", 14, "bold"), width=18, anchor="w").pack(side="left")
        self.cb_unica = ttk.Combobox(fu, width=40, state="readonly", font=("Helvetica", 13))
        self.cb_unica.pack(side="left", padx=6)
        tk.Button(fu, text=" Testar ", bg="#555", fg="#fff", font=("Helvetica", 12, "bold"),
                  command=lambda: self.testar_impressora(self.cb_unica, "Impressora única")).pack(side="left", padx=4)
        tk.Label(f, text="Locais (nome e impressora de cada um):", fg="#ffc107", bg=BG, font=("Helvetica", 15, "bold")).pack(anchor="w", padx=20, pady=(12, 2))
        self.f_locais = tk.Frame(f, bg=BG)
        self.f_locais.pack(anchor="w", padx=20)
        self.imp_achadas, self.rows = [], []
        for l in DB.get("locais", []):
            self.add_row(l["nome"], l.get("impressora", ""), l["nome"])
        tk.Button(f, text=" ➕ Adicionar local ", bg="#ffffff", fg="#000", font=("Helvetica", 14, "bold"),
                  command=lambda: self.add_row("", "", None)).pack(anchor="w", padx=20, pady=8)
        fc = tk.Frame(f, bg=BG)
        fc.pack(anchor="w", padx=20, pady=2)
        tk.Label(fc, text="Contas (caixa) saem em:", fg="#fff", bg=BG, font=("Helvetica", 14, "bold"), anchor="w").pack(side="left")
        self.cb_contas = ttk.Combobox(fc, width=22, state="readonly", font=("Helvetica", 13), postcommand=self.refresh_contas)
        self.cb_contas.pack(side="left", padx=8)
        self.cb_contas.set(cfg.get("local_conta", ""))
        tk.Checkbutton(f, text="Imprimir os pedidos automaticamente ao enviar", variable=self.var_auto,
                       bg=BG, fg="#fff", selectcolor="#444", activebackground=BG, activeforeground="#fff",
                       font=("Helvetica", 14)).pack(anchor="w", padx=20, pady=(10, 2))
        bar = tk.Frame(f, bg=BG)
        bar.pack(anchor="w", padx=20, pady=8)
        tk.Button(bar, text=" 🔄 Procurar impressoras ", bg="#ffffff", fg="#000", font=("Helvetica", 14, "bold"),
                  command=self.procurar_impressoras).pack(side="left", padx=(0, 8))
        tk.Button(bar, text=" 💾 Salvar ", bg=COR_LIVRE, fg="#fff", font=("Helvetica", 14, "bold"),
                  command=self.salvar_impressoras).pack(side="left")
        tk.Label(f, text="“Padrão do Windows” usa a impressora marcada como padrão. “(não imprimir)” = aquele local não imprime.",
                 fg="#aaa", bg=BG, font=("Helvetica", 12)).pack(anchor="w", padx=20)
        self.cb_unica["values"] = self._vals_imp(cfg.get("unica", ""))
        self.cb_unica.set(self._txt_imp(cfg.get("unica", "")))
        self.atualiza_modo_imp()
        self.root.after(500, self.procurar_impressoras)

    def _txt_imp(self, v):
        return "Padrão do Windows" if not v else "(não imprimir)" if v == "-" else v

    def _val_imp(self, t):
        return "" if t.startswith("Padrão do Windows") else "-" if t.startswith("(não imprimir") else t

    def _vals_imp(self, atual=""):
        vals = ["Padrão do Windows", "(não imprimir)"] + list(self.imp_achadas)
        t = self._txt_imp(atual)
        if t not in vals:
            vals.append(t)
        return vals

    def add_row(self, nome, imp, orig):
        fr = tk.Frame(self.f_locais, bg="#222222")
        fr.pack(anchor="w", pady=4)
        var = tk.StringVar(value=nome)
        ent = tk.Entry(fr, textvariable=var, width=16, font=("Helvetica", 15))
        ent.pack(side="left", padx=(0, 8), ipady=4)
        cb = ttk.Combobox(fr, width=36, state="readonly", font=("Helvetica", 13))
        cb["values"] = self._vals_imp(imp)
        cb.set(self._txt_imp(imp))
        cb.pack(side="left")
        row = {"orig": orig, "var": var, "cb": cb, "fr": fr}
        tk.Button(fr, text=" Testar ", bg="#555", fg="#fff", font=("Helvetica", 12, "bold"),
                  command=lambda: self.testar_impressora(cb, var.get().strip() or "Local")).pack(side="left", padx=6)
        tk.Button(fr, text=" ✕ ", bg=COR_CONSUMO, fg="#fff", font=("Helvetica", 12, "bold"),
                  command=lambda: self.remover_local(row)).pack(side="left")
        self.rows.append(row)
        if hasattr(self, "var_modo"):
            self.atualiza_modo_imp()
        if not nome:
            ent.focus_set()

    def remover_local(self, row):
        if len(self.rows) <= 1:
            return messagebox.showinfo("Locais", "É preciso ter pelo menos um local.")
        nome = row["var"].get().strip()
        if not messagebox.askyesno("Remover local", f"Remover o local \"{nome}\"?\nOs produtos dele passam para o primeiro local da lista."):
            return
        row["fr"].destroy()
        self.rows.remove(row)

    def refresh_contas(self):
        self.cb_contas["values"] = [r["var"].get().strip() for r in self.rows if r["var"].get().strip()]

    def procurar_impressoras(self):
        def tarefa():
            achadas = listar_impressoras()
            self.root.after(0, lambda: depois(achadas))

        def depois(achadas):
            self.imp_achadas = achadas
            for cb in [self.cb_unica] + [r["cb"] for r in self.rows]:
                atual = self._val_imp(cb.get())
                cb["values"] = self._vals_imp(atual)
                cb.set(self._txt_imp(atual))
        threading.Thread(target=tarefa, daemon=True).start()

    def atualiza_modo_imp(self):
        uma = self.var_modo.get() == "uma"
        self.cb_unica.config(state="readonly" if uma else "disabled")
        for r in self.rows:
            r["cb"].config(state="disabled" if uma else "readonly")

    def salvar_impressoras(self):
        novos, vistos = [], set()
        for r in self.rows:
            n = r["var"].get().strip()[:20]
            if not n:
                return messagebox.showerror("Atenção", "Todo local precisa de um nome.")
            if n.lower() in vistos:
                return messagebox.showerror("Atenção", f"O nome \"{n}\" está repetido.")
            vistos.add(n.lower())
            novos.append({"nome": n, "impressora": self._val_imp(r["cb"].get())})
        ren = {r["orig"].lower(): r["var"].get().strip()[:20] for r in self.rows if r["orig"]}
        nomes = [l["nome"] for l in novos]
        contas = self.cb_contas.get().strip()
        contas = ren.get(contas.lower(), contas)
        if contas.lower() not in vistos:
            contas = ""
        with LOCK:
            DB["locais"] = novos
            for v in DB["menu"].values():
                d = str(v.get("destino", ""))
                d = ren.get(d.lower(), d)
                v["destino"] = d if d.lower() in vistos else nomes[0]
            DB["impressoras"] = {"modo": self.var_modo.get(), "unica": self._val_imp(self.cb_unica.get()), "local_conta": contas}
            DB["imprimir_auto"] = bool(self.var_auto.get())
            salvar()
        for r in self.rows:
            r["orig"] = r["var"].get().strip()[:20]
        self.cb_contas.set(contas)
        try:
            self.cb_prod_dest["values"] = nomes
            if self.cb_prod_dest.get() not in nomes:
                self.cb_prod_dest.set(nomes[0])
            self.carregar_menu_tree()
        except Exception:
            pass
        messagebox.showinfo("Locais e impressoras", "Configuração salva!")

    def testar_impressora(self, cb, rotulo):
        try:
            nome = self._val_imp(cb.get())
            txt = "\n".join(["=" * LARGURA, centro(NOME), centro("TESTE DE IMPRESSAO"), centro(str(rotulo).upper()),
                             centro(agora().strftime("%d/%m/%Y %H:%M")), "=" * LARGURA]) + "\n\n\n"
            pasta = os.path.join(BASE, "tickets")
            os.makedirs(pasta, exist_ok=True)
            p = os.path.join(pasta, "teste_impressora.txt")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(txt)
            _imprimir_em(p, nome)
            messagebox.showinfo("Teste", "Teste enviado. Veja se saiu na impressora certa.")
        except Exception as e:
            messagebox.showerror("Não foi possível imprimir", str(e))

    # --- ABA PEDIDOS ENVIADOS ---
    def setup_aba_pedidos(self):
        self._sig_ped = None
        cols = ("Hora", "Destino", "Mesa", "Itens", "Impresso")
        self.tree_ped = ttk.Treeview(self.aba_pedidos, columns=cols, show="headings", height=14)
        for c, w in zip(cols, (70, 90, 60, 560, 90)):
            self.tree_ped.heading(c, text=c)
            self.tree_ped.column(c, width=w, anchor="center")
        self.tree_ped.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Button(self.aba_pedidos, text=" Reimprimir selecionado ", bg="#ffc107", fg="#000",
                  font=("Helvetica", 13, "bold"), command=self.reimprimir).pack(pady=(0, 10))
        self.redesenhar_pedidos()

    def redesenhar_pedidos(self):
        with LOCK:
            ts = json.loads(json.dumps(DB["tickets"][-60:][::-1]))
        sig = json.dumps(ts, sort_keys=True)
        if sig == self._sig_ped:
            return
        self._sig_ped = sig
        sel = self.tree_ped.selection()
        for r in self.tree_ped.get_children():
            self.tree_ped.delete(r)
        ids = set()
        for t in ts:
            ids.add(str(t["id"]))
            itens = ", ".join(f"{q}x {n}" + (f" ({c})" if c != "Geral" else "") for n, q, c in t["itens"])
            self.tree_ped.insert("", "end", iid=str(t["id"]),
                                 values=(t["hora"], t["destino"], t["mesa"], itens, "sim" if t["impresso"] else "NÃO"))
        for r in sel:
            if r in ids:
                self.tree_ped.selection_set(r)

    def reimprimir(self):
        sel = self.tree_ped.selection()
        if not sel:
            return messagebox.showinfo("Pedidos", "Clique em um pedido da lista.")
        try:
            with LOCK:
                r_reimprimir(USUARIO_PAINEL, {"id": int(sel[0])})
                salvar()
                ok = next((t["impresso"] for t in DB["tickets"] if t["id"] == int(sel[0])), False)
            if not ok:
                messagebox.showwarning("Impressão", "Não foi possível imprimir. Confira a impressora padrão do Windows.")
        except Exception as e:
            messagebox.showerror("Erro", str(e))
        self._sig_ped = None
        self.redesenhar_pedidos()

    # --- ABA VENDAS ---
    def setup_aba_vendas(self):
        topo = tk.Frame(self.aba_vendas, bg="#222222")
        topo.pack(fill="x", padx=10, pady=10)
        tk.Label(topo, text="Data (dd/mm/aaaa):", fg="#fff", bg="#222222").pack(side="left")
        self.ent_data = tk.Entry(topo, width=12)
        self.ent_data.insert(0, agora().strftime("%d/%m/%Y"))
        self.ent_data.pack(side="left", padx=6)
        tk.Button(topo, text=" Ver ", bg="#ffc107", fg="#000", font=("Helvetica", 13, "bold"), command=self.carregar_vendas).pack(side="left")
        tk.Button(topo, text=" Hoje ", bg="#555", fg="#fff", font=("Helvetica", 13, "bold"), command=self.vendas_hoje).pack(side="left", padx=6)
        self.lbl_total_vendas = tk.Label(self.aba_vendas, text="", fg="#ffc107", bg="#222222", font=("Helvetica", 20, "bold"))
        self.lbl_total_vendas.pack(anchor="w", padx=12)
        self.lbl_formas = tk.Label(self.aba_vendas, text="", fg="#fff", bg="#222222", justify="left", font=("Helvetica", 13))
        self.lbl_formas.pack(anchor="w", padx=12, pady=(0, 6))
        cols = ("Hora", "Mesa", "Comanda", "Forma", "Total")
        self.tree_vendas = ttk.Treeview(self.aba_vendas, columns=cols, show="headings", height=14)
        for c in cols:
            self.tree_vendas.heading(c, text=c)
            self.tree_vendas.column(c, width=150, anchor="center")
        self.tree_vendas.pack(fill="both", expand=True, padx=10, pady=10)
        self.carregar_vendas()

    def vendas_hoje(self):
        self.ent_data.delete(0, "end")
        self.ent_data.insert(0, agora().strftime("%d/%m/%Y"))
        self.carregar_vendas()

    def carregar_vendas(self):
        data = self.ent_data.get().strip()
        with LOCK:
            vs = [v for v in DB["vendas"] if v["data"] == data]
        for r in self.tree_vendas.get_children():
            self.tree_vendas.delete(r)
        por = {}
        for v in vs:
            f = v.get("forma", "Não informado")
            por[f] = por.get(f, 0) + v["total"]
            self.tree_vendas.insert("", "end", values=(v["hora"], v["mesa"], "mesa toda" if v["comanda"] == "*" else v["comanda"], f, reais(v["total"])))
        self.lbl_total_vendas.config(text=f"Total do dia {data}: {reais(sum(v['total'] for v in vs))}  ({len(vs)} recebimentos)")
        self.lbl_formas.config(text="   ".join(f"{f}: {reais(t)}" for f, t in por.items()) or "Nenhuma venda nesta data.")

    # --- QR CODE PARA INSTALAR O APP ---
    def mostrar_qr(self):
        url = f"http://{ip_local()}:{PORT}/"
        win = tk.Toplevel(self.root)
        win.title("Instalar no celular")
        win.configure(bg="#222222")
        tk.Label(win, text="Aponte a câmera do celular", fg="#ffc107", bg="#222222", font=("Helvetica", 15, "bold")).pack(padx=24, pady=(14, 4))
        try:
            import qrcode
            q = qrcode.QRCode(border=2, box_size=1)
            q.add_data(url)
            q.make(fit=True)
            m = q.get_matrix()
            px = max(4, 300 // len(m))
            cv = tk.Canvas(win, width=len(m) * px, height=len(m) * px, bg="white", highlightthickness=0)
            cv.pack(padx=24, pady=8)
            for y, linha in enumerate(m):
                for x, cheio in enumerate(linha):
                    if cheio:
                        cv.create_rectangle(x * px, y * px, (x + 1) * px, (y + 1) * px, fill="black", outline="black")
        except Exception:
            tk.Label(win, text="QR Code indisponível neste computador.\nUse o link abaixo.", fg="#fff", bg="#222222").pack(pady=8)
        tk.Label(win, text=url, fg="#ffffff", bg="#222222", font=("Helvetica", 16, "bold")).pack()

        def copiar():
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            messagebox.showinfo("Link copiado", "Link copiado! Cole no WhatsApp dos garçons.")
        tk.Button(win, text=" Copiar link ", bg="#ffc107", fg="#000", font=("Helvetica", 13, "bold"), command=copiar).pack(pady=12)

    # --- ATUALIZAÇÃO ---
    def verificar_update(self, silencioso=False):
        def tarefa():
            try:
                info = atualizador.checar(REPO_ATUALIZACAO, VERSAO_SERVIDOR)
            except Exception as e:
                if not silencioso:
                    self.root.after(0, lambda: messagebox.showerror("Atualização", f"Não foi possível verificar:\n{e}"))
                return
            self.root.after(0, lambda: self.pos_check(info, silencioso))
        threading.Thread(target=tarefa, daemon=True).start()

    def pos_check(self, info, silencioso):
        if not info:
            if not silencioso:
                messagebox.showinfo("Atualização", "Você já está na versão mais recente.")
            return
        if messagebox.askyesno("Atualização", f"Versão {info['versao']} disponível.\n"
                               "Atualizar agora? O servidor vai reiniciar."):
            threading.Thread(target=self.aplicar_update, args=(info,), daemon=True).start()

    def aplicar_update(self, info):
        try:
            if info.get("apk"):  # APK novo fica disponível para os celulares
                atualizador.baixar(info["apk"], os.path.join(BASE, "donata.apk"))
                with open(os.path.join(BASE, "versao.txt"), "w", encoding="utf-8") as f:
                    f.write(info["versao"])
            if getattr(sys, "frozen", False) and info.get("exe"):
                atualizador.trocar_exe(info["exe"])
                os._exit(0)
            self.root.after(0, lambda: messagebox.showinfo("Atualização", "APK dos celulares atualizado."))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Atualização", f"Falha ao atualizar:\n{e}"))

    # --- ABA USUÁRIOS ---
    def setup_aba_users(self):
        cols = ("Nome", "PIN", "Papel")
        self.tree_users = ttk.Treeview(self.aba_users, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree_users.heading(c, text=c)
            self.tree_users.column(c, width=150, anchor="center")
        self.tree_users.pack(fill="x", padx=10, pady=10)

        f_form = tk.Frame(self.aba_users, bg="#222222")
        f_form.pack(pady=5)

        tk.Label(f_form, text="Nome:", fg="#ffffff", bg="#222222").grid(row=0, column=0, padx=5)
        self.ent_user_nome = tk.Entry(f_form, width=15)
        self.ent_user_nome.grid(row=0, column=1, padx=5)

        tk.Label(f_form, text="PIN:", fg="#ffffff", bg="#222222").grid(row=0, column=2, padx=5)
        self.ent_user_pin = tk.Entry(f_form, width=10)
        self.ent_user_pin.grid(row=0, column=3, padx=5)

        tk.Label(f_form, text="Papel:", fg="#ffffff", bg="#222222").grid(row=0, column=4, padx=5)
        self.cb_user_papel = ttk.Combobox(f_form, values=["garcom", "admin"], width=10, state="readonly")
        self.cb_user_papel.set("garcom")
        self.cb_user_papel.grid(row=0, column=5, padx=5)

        f_btn = tk.Frame(self.aba_users, bg="#222222")
        f_btn.pack(pady=10)

        tk.Button(f_btn, text=" Salvar / Adicionar ", bg="#ffc107", fg="#000", font=("Helvetica", 13, "bold"), command=self.salvar_usuario).pack(side="left", padx=5)
        tk.Button(f_btn, text=" Excluir Selecionado ", bg="#dc3545", fg="#fff", font=("Helvetica", 13, "bold"), command=self.excluir_usuario).pack(side="left", padx=5)

        self.carregar_usuarios_tree()

    def carregar_usuarios_tree(self):
        for row in self.tree_users.get_children():
            self.tree_users.delete(row)
        for u in DB["usuarios"]:
            self.tree_users.insert("", "end", values=(u["nome"], u["pin"], u["papel"]))

    def salvar_usuario(self):
        nome = self.ent_user_nome.get().strip()
        pin = self.ent_user_pin.get().strip()
        papel = self.cb_user_papel.get()

        if not nome or not pin or not pin.isdigit():
            messagebox.showerror("Erro", "Nome inválido ou PIN não numérico!")
            return

        with LOCK:
            achou = False
            for u in DB["usuarios"]:
                if u["nome"].lower() == nome.lower():
                    u["pin"] = pin
                    u["papel"] = papel
                    achou = True
                    break
            if not achou:
                DB["usuarios"].append({"nome": nome, "pin": pin, "papel": papel})
            salvar()

        self.ent_user_nome.delete(0, "end")
        self.ent_user_pin.delete(0, "end")
        self.carregar_usuarios_tree()
        messagebox.showinfo("Sucesso", "Usuário salvo com sucesso!")

    def excluir_usuario(self):
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showwarning("Atenção", "Selecione um usuário para excluir!")
            return
        item = self.tree_users.item(sel[0])
        nome = item["values"][0]

        if len(DB["usuarios"]) <= 1:
            messagebox.showerror("Erro", "É necessário manter pelo menos 1 usuário cadastrado!")
            return

        with LOCK:
            DB["usuarios"] = [u for u in DB["usuarios"] if u["nome"] != nome]
            salvar()

        self.carregar_usuarios_tree()

    # --- ABA CARDÁPIO ---
    def setup_aba_menu(self):
        cols = ("Produto", "Preço (R$)", "Categoria", "Destino")
        self.tree_menu = ttk.Treeview(self.aba_menu, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree_menu.heading(c, text=c)
            self.tree_menu.column(c, width=230, anchor="center")
        self.tree_menu.pack(fill="x", padx=10, pady=10)

        f_form = tk.Frame(self.aba_menu, bg="#222222")
        f_form.pack(pady=5)

        tk.Label(f_form, text="Item:", fg="#ffffff", bg="#222222").grid(row=0, column=0, padx=2)
        self.ent_prod_nome = tk.Entry(f_form, width=15)
        self.ent_prod_nome.grid(row=0, column=1, padx=2)

        tk.Label(f_form, text="Preço:", fg="#ffffff", bg="#222222").grid(row=0, column=2, padx=2)
        self.ent_prod_preco = tk.Entry(f_form, width=8)
        self.ent_prod_preco.grid(row=0, column=3, padx=2)

        tk.Label(f_form, text="Categoria:", fg="#ffffff", bg="#222222").grid(row=0, column=4, padx=2)
        self.ent_prod_cat = tk.Entry(f_form, width=12)
        self.ent_prod_cat.insert(0, "Lanches")
        self.ent_prod_cat.grid(row=0, column=5, padx=2)

        tk.Label(f_form, text="Destino:", fg="#ffffff", bg="#222222").grid(row=0, column=6, padx=2)
        self.cb_prod_dest = ttk.Combobox(f_form, values=nomes_locais(), width=14, state="readonly")
        self.cb_prod_dest.set(nomes_locais()[0])
        self.cb_prod_dest.grid(row=0, column=7, padx=2)

        f_btn = tk.Frame(self.aba_menu, bg="#222222")
        f_btn.pack(pady=10)

        tk.Button(f_btn, text=" Salvar / Atualizar Item ", bg="#ffc107", fg="#000", font=("Helvetica", 13, "bold"), command=self.salvar_menu_item).pack(side="left", padx=5)
        tk.Button(f_btn, text=" Remover Item ", bg="#dc3545", fg="#fff", font=("Helvetica", 13, "bold"), command=self.excluir_menu_item).pack(side="left", padx=5)

        self.carregar_menu_tree()

    def carregar_menu_tree(self):
        for row in self.tree_menu.get_children():
            self.tree_menu.delete(row)
        for p, d in DB["menu"].items():
            self.tree_menu.insert("", "end", values=(p, f"{d['preco']:.2f}", d["cat"], d["destino"]))

    def salvar_menu_item(self):
        nome = self.ent_prod_nome.get().strip()
        try:
            preco = float(self.ent_prod_preco.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Erro", "Preço inválido!")
            return
        cat = self.ent_prod_cat.get().strip() or "Outros"
        dest = self.cb_prod_dest.get()

        if not nome or preco < 0:
            messagebox.showerror("Erro", "Nome ou Preço inválidos!")
            return

        with LOCK:
            DB["menu"][nome] = {"preco": preco, "cat": cat, "destino": dest}
            salvar()

        self.ent_prod_nome.delete(0, "end")
        self.ent_prod_preco.delete(0, "end")
        self.carregar_menu_tree()

    def excluir_menu_item(self):
        sel = self.tree_menu.selection()
        if not sel:
            messagebox.showwarning("Atenção", "Selecione um produto para excluir!")
            return
        item = self.tree_menu.item(sel[0])
        nome = item["values"][0]

        with LOCK:
            DB["menu"].pop(nome, None)
            salvar()

        self.carregar_menu_tree()

def iniciar_descoberta():
    """Responde 'DONATA?' (broadcast UDP) para o app achar o servidor sozinho no Wi-Fi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", DESC_PORT))
        while True:
            dados, end = s.recvfrom(64)
            if dados.strip() == b"DONATA?":
                s.sendto(f"DONATA:{PORT}".encode(), end)
    except Exception as e:
        print(f"Descoberta automática indisponível: {e}")


def iniciar_servidor_http():
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
        srv.serve_forever()
    except Exception as e:
        print(f"Erro ao iniciar servidor HTTP: {e}")

if __name__ == "__main__":
    # Inicia o servidor HTTP numa thread em segundo plano
    t = threading.Thread(target=iniciar_servidor_http, daemon=True)
    t.start()
    threading.Thread(target=iniciar_descoberta, daemon=True).start()

    # Inicia a Interface Gráfica Tkinter no fluxo principal
    root = tk.Tk()
    app = ServidorGUI(root)
    root.mainloop()