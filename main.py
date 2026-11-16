import json, os, socket, threading
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.network.urlrequest import UrlRequest
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform, escape_markup

VERSAO = "1.4"   # suba este número a cada nova versão (e o "version" do buildozer.spec)

BK, BK2 = (.07, .07, .07, 1), (.15, .15, .15, 1)
Y, BR, TX = (1, .78, .18, 1), (.55, .29, .08, 1), (.96, .94, .9, 1)
MUT = (.66, .6, .53, 1)
GREEN, RED, AMBER = (.18, .5, .27, 1), (.7, .2, .18, 1), (.95, .66, .1, 1)
FORMAS = ["Dinheiro", "Débito", "Crédito", "Pix"]
ICONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
FONTE_ICONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icones.ttf")
if os.path.exists(FONTE_ICONES):
    LabelBase.register(name="icones", fn_regular=FONTE_ICONES)  # Material Design Icons
ICONES = {"voltar": "\U000F004D", "ok": "\U000F012C", "impresso": "\U000F1146", "naoimpresso": "\U000F042C",
          "imprimir": "\U000F042A", "conta": "\U000F0449", "mais": "\U000F0415", "menos": "\U000F0374",
          "enviar": "\U000F048A", "dinheiro": "\U000F0114", "credito": "\U000F0FEF", "debito": "\U000F019B",
          "pix": "\U000F0432", "apagar": "\U000F0B5C", "mesas": "\U000F05BC", "engrenagem": "\U000F0493",
          "sair": "\U000F0343", "buscar": "\U000F0349", "atualizar": "\U000F0450"}
ICONE_FORMA = {"Dinheiro": "dinheiro", "Débito": "debito", "Crédito": "credito", "Pix": "pix"}


def ic(nome):
    return f"[font=icones]{ICONES[nome]}[/font]"
OK, BAD, GR, DK = (.25, .56, .37, 1), (.75, .22, .17, 1), (.25, .25, .25, 1), (0, 0, 0, 1)


def vtuple(s):
    try:
        return tuple(int(x) for x in str(s).split("."))
    except ValueError:
        return (0,)


def abrir_url(url):
    """Abre o link no navegador do celular (baixa o APK novo)."""
    try:
        from jnius import autoclass
        Intent, Uri = autoclass("android.content.Intent"), autoclass("android.net.Uri")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        act.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    except Exception:
        import webbrowser
        webbrowser.open(url)


def tempo(seg):
    m = max(int(seg // 60), 0)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}min"


def money(v):
    return "R$ " + f"{v:.2f}".replace(".", ",")


def total(itens):
    return sum(i["preco"] * i["qtd"] for i in itens)


DESC_PORTA = 5001


def _ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        s.close()


def descobrir_servidor(destinos=None, porta_desc=DESC_PORTA, timeout=1.2, tentativas=3):
    """Procura o caixa na rede: manda 'DONATA?' em broadcast e espera a resposta."""
    if destinos is None:
        destinos = ["255.255.255.255"]
        ip = _ip_local()
        if ip.count(".") == 3:
            destinos.append(ip.rsplit(".", 1)[0] + ".255")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    try:
        for _ in range(tentativas):
            for d in destinos:
                try:
                    s.sendto(b"DONATA?", (d, porta_desc))
                except OSError:
                    pass
            try:
                dados, end = s.recvfrom(64)
                if dados.startswith(b"DONATA:"):
                    return f"{end[0]}:{dados[7:].decode().strip()}"
            except socket.timeout:
                pass
    finally:
        s.close()
    return None


def varrer_rede(prefixo, porta=5000, timeout=0.4):
    """Plano B: testa 1..254 da faixa do Wi-Fi em paralelo, procurando o servidor."""
    import urllib.request
    achou = []

    def tenta(i):
        ip = f"{prefixo}.{i}"
        try:
            with urllib.request.urlopen(f"http://{ip}:{porta}/api/usuarios", timeout=timeout) as r:
                if b"nomes" in r.read(300):
                    achou.append(f"{ip}:{porta}")
        except Exception:
            pass
    ths = [threading.Thread(target=tenta, args=(i,), daemon=True) for i in range(1, 255)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout + 1)
    return achou[0] if achou else None


class RB(Button):
    """Botão com cantos arredondados."""
    def __init__(self, bg=(1, 1, 1, 1), **kw):
        super().__init__(background_normal="", background_down="", background_color=(0, 0, 0, 0), **kw)
        self._bg = bg
        with self.canvas.before:
            self._cor = Color(*bg)
            self._ret = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(pos=self._atualiza, size=self._atualiza, state=self._cor_estado, disabled=self._cor_estado)

    def _atualiza(self, *a):
        self._ret.pos, self._ret.size = self.pos, self.size

    def _cor_estado(self, *a):
        r, g, b, _ = self._bg
        if self.disabled:
            self._cor.rgba = (r, g, b, .35)
        elif self.state == "down":
            self._cor.rgba = (r * .75, g * .75, b * .75, 1)
        else:
            self._cor.rgba = self._bg


def btn(t, cb, bg=Y, fg=DK, icone=None, **k):
    if icone:
        t = ic(icone) + ("  " + escape_markup(t) if t else "")
        k["markup"] = True
    b = RB(bg=bg, text=t, color=fg, bold=True, **k)
    b.bind(on_release=lambda *_: cb())
    return b


def left(t, **k):
    k.setdefault("color", TX)
    l = Label(text=t, halign="left", valign="middle", **k)
    l.bind(size=lambda w, v: setattr(w, "text_size", v))
    return l


def wlabel(t, **k):
    k.setdefault("color", TX)
    l = Label(text=t, halign="left", valign="middle", size_hint_y=None, **k)
    l.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
           texture_size=lambda w, v: setattr(w, "height", max(v[1] + dp(10), dp(36))))
    return l


def titulo(t):
    return wlabel(t.upper(), bold=True, color=Y)


def lista():
    g = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=dp(8))
    g.bind(minimum_height=g.setter("height"))
    return g


class DoNata(App):
    def build(self):
        Window.clearcolor = BK
        Window.softinput_mode = "below_target"
        if platform != "android":
            Window.size = (420, 800)  # janela de celular ao testar no PC
        self.cfg = JsonStore(os.path.join(self.user_data_dir, "cfg.json"))
        self.host = self.cfg.get("c")["host"] if self.cfg.exists("c") else ""
        self.token, self.S, self.raw = "", {}, ""
        self.V, self.M, self.C, self.users = "mesas", None, "Geral", []
        self.Q, self.CAT, self.busca = "", "Todos", None
        self.sel_user, self.pin, self.lbl_pin = (self.cfg.get("u")["nome"] if self.cfg.exists("u") else ""), "", None
        self.buscando = False
        self.root_box = BoxLayout(orientation="vertical")
        self.draw()
        if self.host:
            self.buscar_usuarios()
        else:
            self.procurar_servidor()
        Clock.schedule_interval(lambda dt: self.refresh(), 3)
        return self.root_box

    # ---------------- rede ----------------
    def call(self, rota, dados=None, ok=None, erro=None):
        def falha(req, res):
            if getattr(req, "resp_status", None) == 401:
                self.token = ""
                return self.draw()
            if erro and not isinstance(res, dict):  # sem conexão (não é resposta do servidor)
                return erro()
            msg = res.get("erro") if isinstance(res, dict) else None
            self.toast(msg or "Sem conexão com o servidor")

        def sucesso(req, res):
            if isinstance(res, (str, bytes)):
                res = json.loads(res)
            if ok:
                ok(res)

        UrlRequest(f"http://{self.host}/api/{rota}", on_success=sucesso, on_failure=falha, on_error=falha,
                   req_body=json.dumps(dados) if dados is not None else None,
                   req_headers={"X-Token": self.token, "Content-Type": "application/json"},
                   method="POST" if dados is not None else "GET", timeout=8)

    def act(self, rota, dados):
        self.call(rota, dados, ok=lambda r: self.refresh(True))

    def refresh(self, force=False):
        if not self.token:
            return

        def got(res):
            raw = json.dumps(res, sort_keys=True)
            if force or raw != self.raw:
                self.raw, self.S = raw, res
                if not force and self.M and self.busca is not None and self.busca.focus:
                    return  # não refaz a tela enquanto a pessoa digita na busca
                self.draw()
        self.call("estado", ok=got)

    # ---------------- popups ----------------
    def toast(self, msg):
        p = Popup(title="", separator_height=0, content=Label(text=msg), size_hint=(.8, .2))
        p.open()
        Clock.schedule_once(lambda dt: p.dismiss(), 1.8)

    def ask(self, msg, yes):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        box.add_widget(Label(text=msg))
        row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(48))
        p = Popup(title="Confirmar", content=box, size_hint=(.9, .4))
        row.add_widget(btn("Não", p.dismiss, GR, TX))
        row.add_widget(btn("Sim", lambda: (p.dismiss(), yes()), OK, TX))
        box.add_widget(row)
        p.open()

    def prompt(self, titulo_, ok):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        ti = TextInput(multiline=False, size_hint_y=None, height=dp(44))
        p = Popup(title=titulo_, content=box, size_hint=(.9, .35))
        box.add_widget(ti)
        box.add_widget(btn("OK", lambda: (p.dismiss(), ti.text.strip() and ok(ti.text.strip())), Y, DK, size_hint_y=None, height=dp(48)))
        p.open()

    # ---------------- telas ----------------
    def draw(self):
        r = self.root_box
        r.clear_widgets()
        if not self.token:
            return r.add_widget(self.v_login())
        h = BoxLayout(size_hint_y=None, height=dp(52), padding=dp(8), spacing=dp(8))
        h.add_widget(Label(text="DoNata Lanches", bold=True, color=Y, font_size=dp(20), halign="left"))
        h.add_widget(Label(text=self.S.get("usuario", ""), color=TX, size_hint_x=.4))
        h.add_widget(btn("Sair", self.sair, GR, TX, icone="sair", size_hint_x=.3))
        r.add_widget(h)
        body = self.v_pedidos() if self.V == "pedidos" else (self.v_mesa() if self.M else self.v_mesas())
        r.add_widget(body)
        nav = BoxLayout(size_hint_y=None, height=dp(50))
        for k, t in (("mesas", "Mesas"), ("pedidos", "Pedidos enviados")):
            nav.add_widget(btn(t, lambda k=k: self.tab(k), BR if self.V == k else BK2, Y if self.V == k else TX,
                               icone="mesas" if k == "mesas" else "imprimir"))
        r.add_widget(nav)

    def tab(self, k):
        self.V, self.M = k, None
        self.draw()

    def sair(self):
        self.token = ""
        self.draw()

    def v_login(self):
        b = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(8))
        topo = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(150))
        if os.path.exists(ICONE):
            topo.add_widget(Image(source=ICONE, size_hint_y=None, height=dp(96)))
        topo.add_widget(Label(text="DoNata Lanches", bold=True, color=Y, font_size=dp(24), size_hint_y=None, height=dp(36)))
        topo.add_widget(Label(text="desde 1997", color=MUT, font_size=dp(12), size_hint_y=None, height=dp(18)))
        b.add_widget(topo)
        self.lbl_pin = None
        if not self.users:
            b.add_widget(Label(text="Procurando o servidor no Wi-Fi…" if self.buscando else
                               "Servidor não encontrado.\nConfira se o caixa está ligado\ne se o celular está no mesmo Wi-Fi.",
                               color=TX, halign="center"))
            if not self.buscando:
                b.add_widget(btn("Procurar de novo", self.procurar_servidor, Y, DK, icone="atualizar",
                                 size_hint_y=None, height=dp(52)))
        else:
            rows = (len(self.users) + 1) // 2
            sv = ScrollView(size_hint_y=None, height=min(rows * dp(58), dp(176)))
            g = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
            g.bind(minimum_height=g.setter("height"))
            for n in self.users:
                on = n == self.sel_user
                g.add_widget(btn(n, lambda n=n: self.escolher_usuario(n), BR if on else BK2, Y if on else TX,
                                 size_hint_y=None, height=dp(50)))
            sv.add_widget(g)
            b.add_widget(sv)
            self.lbl_pin = Label(text=self.pin_txt(), color=Y, font_size=dp(28), size_hint_y=None, height=dp(48))
            b.add_widget(self.lbl_pin)
            teclado = GridLayout(cols=3, spacing=dp(8))
            for k in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "←", "0", "Entrar"]:
                if k == "Entrar":
                    teclado.add_widget(btn(k, self.entrar, OK, TX, icone="ok", font_size=dp(18)))
                else:
                    teclado.add_widget(btn("" if k == "←" else k, lambda k=k: self.tecla(k), GR, TX,
                                           icone="apagar" if k == "←" else None, font_size=dp(26)))
            b.add_widget(teclado)
        rodape = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        rodape.add_widget(btn("Servidor: " + (self.host or "não configurado"), self.config_servidor, BK2, MUT, icone="engrenagem", font_size=dp(13)))
        rodape.add_widget(Label(text=f"v{VERSAO}", color=MUT, size_hint_x=.2))
        b.add_widget(rodape)
        return b

    def pin_txt(self):
        return " ".join("•" * len(self.pin)) or "Digite o PIN"

    def tecla(self, k):
        self.pin = self.pin[:-1] if k == "←" else (self.pin + k)[:8]
        if self.lbl_pin is not None:
            self.lbl_pin.text = self.pin_txt()

    def escolher_usuario(self, nome):
        self.sel_user, self.pin = nome, ""
        self.cfg.put("u", nome=nome)
        self.draw()

    def set_host(self):
        self.host = self.t_host.text.strip().replace("http://", "").rstrip("/")
        if self.host and ":" not in self.host:
            self.host += ":5000"
        self.cfg.put("c", host=self.host)

    def config_servidor(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        box.add_widget(Label(text="Endereço do servidor (IP do caixa)", color=TX, size_hint_y=None, height=dp(24)))
        self.t_host = TextInput(text=self.host, hint_text="ex: 192.168.0.10", multiline=False, size_hint_y=None, height=dp(46))
        box.add_widget(self.t_host)
        p = Popup(title="Servidor", content=box, size_hint=(.92, .6))
        box.add_widget(btn("Conectar", lambda: (self.set_host(), p.dismiss(), self.buscar_usuarios()), Y, DK, size_hint_y=None, height=dp(48)))
        box.add_widget(btn("Verificar atualização", lambda: (self.set_host(), self.checar_update(True)), GR, TX, icone="atualizar",
                           size_hint_y=None, height=dp(44)))
        box.add_widget(btn("Fechar", p.dismiss, BK2, TX, size_hint_y=None, height=dp(44)))
        p.open()

    def checar_update(self, manual=False):
        if not self.host:
            return self.toast("Informe o IP do caixa primeiro") if manual else None

        def ok(r):
            if vtuple(r.get("versao", "0")) > vtuple(VERSAO):
                self.ask(f"Nova versão {r['versao']} disponível.\nBaixar e instalar agora?",
                         lambda: abrir_url(f"http://{self.host}/baixar-apk"))
            elif manual:
                self.toast("Você já está na versão mais recente")
        self.call("versao", ok=ok)

    def buscar_usuarios(self, tentar_achar=True):
        def ok(r):
            self.users = r["nomes"]
            if self.sel_user not in self.users:
                self.sel_user = self.users[0] if self.users else ""
            if not self.token:
                self.draw()

        def erro():
            if tentar_achar and not self.buscando:
                self.procurar_servidor()
            else:
                self.toast("Sem conexão com o servidor")
        self.call("usuarios", ok=ok, erro=erro)

    def procurar_servidor(self):
        """Acha o caixa sozinho no Wi-Fi (broadcast UDP; se falhar, varre a faixa de rede)."""
        if self.buscando:
            return
        self.buscando = True
        self.draw()

        def tarefa():
            achado = descobrir_servidor()
            if not achado:
                ip = _ip_local()
                if ip.count(".") == 3:
                    achado = varrer_rede(ip.rsplit(".", 1)[0])
            Clock.schedule_once(lambda dt: self.achou_servidor(achado), 0)
        threading.Thread(target=tarefa, daemon=True).start()

    def achou_servidor(self, host):
        self.buscando = False
        if host:
            self.host = host
            self.cfg.put("c", host=host)
            self.buscar_usuarios(False)
        else:
            self.draw()
            self.toast("Servidor não encontrado.\nConfira o Wi-Fi e se o caixa está ligado.")

    def entrar(self):
        if not self.sel_user or not self.pin:
            return self.toast("Escolha o usuário e digite o PIN")
        pin, self.pin = self.pin, ""
        if self.lbl_pin is not None:
            self.lbl_pin.text = self.pin_txt()

        def ok(r):
            self.token = r["token"]
            self.V, self.M = "mesas", None
            self.refresh(True)
            self.checar_update()
        self.call("login", {"nome": self.sel_user, "pin": pin}, ok=ok)

    def v_mesas(self):
        sv = ScrollView()
        g = GridLayout(cols=3, size_hint_y=None, spacing=dp(8), padding=dp(8), row_default_height=dp(96),
                       row_force_default=True)
        g.bind(minimum_height=g.setter("height"))
        for n in (self.S.get("lista") or [str(i) for i in range(1, self.S.get("n", 0) + 1)]):
            m = self.S["mesas"].get(str(n))
            if m:
                ts = m.get("ts")
                t = tempo(self.S.get("agora", 0) - ts) if ts else m.get("aberta", "")
                conta = m.get("conta")
                txt = f"{n}{'  CONTA' if conta else ''}\n{t} · {money(total(m['itens']))}"
                bg, fg = (AMBER, DK) if conta else (RED, TX)
            else:
                txt, bg, fg = f"{n}\nlivre", GREEN, TX
            g.add_widget(btn(txt, lambda n=n: self.abrir(n), bg, fg, font_size=dp(16)))
        sv.add_widget(g)
        return sv

    def abrir(self, n):
        def go():
            self.M, self.C = n, "Geral"
            self.act("mesa/abrir", {"mesa": n})
        if str(n) in self.S["mesas"]:
            self.M, self.C = n, "Geral"
            self.draw()
        else:
            self.ask(f"Abrir mesa {n}?", go)

    def v_mesa(self):
        m = self.S["mesas"].get(str(self.M))
        if not m:
            self.M = None
            return self.v_mesas()
        if self.C not in m["comandas"]:
            self.C = "Geral"
        its = [i for i in m["itens"] if i["comanda"] == self.C]
        pend = len([i for i in m["itens"] if not i["enviado"]])
        box = BoxLayout(orientation="vertical")
        top = BoxLayout(size_hint_y=None, height=dp(48), padding=dp(4), spacing=dp(6))
        top.add_widget(btn("", self.voltar, GR, TX, icone="voltar", font_size=dp(22), size_hint_x=.2))
        top.add_widget(btn("Conta", lambda: self.act("mesa/conta", {"mesa": self.M}),
                           AMBER if m.get("conta") else GR, DK if m.get("conta") else TX, icone="conta", size_hint_x=.3))
        top.add_widget(Label(text=f"Mesa {self.M}  ·  {money(total(m['itens']))}", bold=True, color=Y))
        box.add_widget(top)
        sc = ScrollView(size_hint_y=None, height=dp(48), do_scroll_y=False)
        row = BoxLayout(size_hint_x=None, spacing=dp(6), padding=dp(4))
        row.bind(minimum_width=row.setter("width"))
        for c in m["comandas"]:
            row.add_widget(btn(c, lambda c=c: self.set_com(c), BR if c == self.C else BK2, Y if c == self.C else TX,
                               size_hint_x=None, width=dp(110)))
        row.add_widget(btn("Comanda", self.nova_comanda, GR, TX, icone="mais", size_hint_x=None, width=dp(120)))
        sc.add_widget(row)
        box.add_widget(sc)
        sv = ScrollView()
        g = lista()
        g.add_widget(titulo("Itens · " + self.C))
        if not its:
            g.add_widget(wlabel("Nenhum item nesta comanda."))
        for i in its:
            r = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
            r.add_widget(left(f"{escape_markup(i['nome'])}{'  [color=#3F8F5F]' + ic('ok') + '[/color]' if i['enviado'] else ''}\n{money(i['preco'] * i['qtd'])}", markup=True))
            r.add_widget(btn("", lambda i=i: self.act("item/qtd", {"mesa": self.M, "id": i["id"], "delta": -1}), GR, TX, icone="menos", font_size=dp(22), size_hint_x=None, width=dp(48)))
            r.add_widget(Label(text=str(i["qtd"]), size_hint_x=None, width=dp(30), color=TX))
            r.add_widget(btn("", lambda i=i: self.act("item/qtd", {"mesa": self.M, "id": i["id"], "delta": 1}), GR, TX, icone="mais", font_size=dp(22), size_hint_x=None, width=dp(48)))
            g.add_widget(r)
        if not m["itens"]:
            g.add_widget(btn("Liberar mesa vazia", lambda: self.act("mesa/fechar", {"mesa": self.M}), BAD, TX, size_hint_y=None, height=dp(46)))
        g.add_widget(titulo("Cardápio"))
        self.busca = TextInput(text=self.Q, hint_text="Buscar produto…", multiline=False, size_hint_y=None, height=dp(44))
        self.busca.bind(text=self.on_busca)
        g.add_widget(self.busca)
        cats = ["Todos"] + sorted({p["cat"] for p in self.S["menu"].values()})
        if self.CAT not in cats:
            self.CAT = "Todos"
        tabs = ScrollView(size_hint_y=None, height=dp(46), do_scroll_y=False)
        trow = BoxLayout(size_hint_x=None, spacing=dp(6))
        trow.bind(minimum_width=trow.setter("width"))
        for c in cats:
            trow.add_widget(btn(c, lambda c=c: self.set_cat(c), BR if c == self.CAT else BK2,
                                Y if c == self.CAT else TX, size_hint_x=None, width=dp(110)))
        tabs.add_widget(trow)
        g.add_widget(tabs)
        self.grade = GridLayout(cols=2, size_hint_y=None, spacing=dp(6))
        self.grade.bind(minimum_height=self.grade.setter("height"))
        g.add_widget(self.grade)
        self.fill_menu()
        sv.add_widget(g)
        box.add_widget(sv)
        bar = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(6), padding=dp(4))
        e = btn(f"Enviar ({pend})", lambda: self.act("enviar", {"mesa": self.M}), OK, TX, icone="enviar")
        e.disabled = not pend
        bar.add_widget(e)
        bar.add_widget(btn("Pagar " + self.C[:8], lambda: self.pagar(self.C), icone="dinheiro"))
        bar.add_widget(btn("Mesa toda", lambda: self.pagar("*"), GR, TX))
        box.add_widget(bar)
        return box

    def fill_menu(self):
        self.grade.clear_widgets()
        q = self.Q.strip().lower()
        for n, p in self.S["menu"].items():
            if (self.CAT == "Todos" or p["cat"] == self.CAT) and q in n.lower():
                b = btn(f"{n}\n{money(p['preco'])}", lambda n=n: self.act("item/add", {"mesa": self.M, "comanda": self.C, "produto": n}),
                        BK2, TX, size_hint_y=None, height=dp(64))
                b.halign, b.valign = "center", "middle"
                b.bind(size=lambda w, v: setattr(w, "text_size", (v[0] - dp(8), v[1])))
                self.grade.add_widget(b)

    def on_busca(self, ti, text):
        self.Q = text
        self.fill_menu()

    def set_cat(self, c):
        self.CAT = c
        self.draw()

    def voltar(self):
        self.M = None
        self.draw()

    def set_com(self, c):
        self.C = c
        self.draw()

    def nova_comanda(self):
        def ok(nome):
            self.C = nome[:30]
            self.act("comanda/nova", {"mesa": self.M, "nome": nome})
        self.prompt("Nome da comanda (ex: João)", ok)

    def pagar(self, c):
        its = [i for i in self.S["mesas"][str(self.M)]["itens"] if c == "*" or i["comanda"] == c]
        txt = ("Fechar a mesa toda" if c == "*" else f"Pagar a comanda {c}") + f"\n{money(total(its))}\nForma de pagamento:"
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        box.add_widget(Label(text=txt))
        p = Popup(title="Pagamento", content=box, size_hint=(.92, .6))
        grade = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(130))
        for f in FORMAS:
            grade.add_widget(btn(f, lambda f=f: (p.dismiss(), self.act("pagar", {"mesa": self.M, "comanda": c, "forma": f})), OK, TX, icone=ICONE_FORMA.get(f)))
        box.add_widget(grade)
        box.add_widget(btn("Cancelar", p.dismiss, GR, TX, size_hint_y=None, height=dp(44)))
        p.open()

    def v_pedidos(self):
        sv = ScrollView()
        g = lista()
        if self.S.get("faturamento") is not None:
            g.add_widget(wlabel("Faturamento hoje: " + money(self.S["faturamento"]), bold=True, color=Y))
            for f, v in (self.S.get("por_forma") or {}).items():
                g.add_widget(wlabel(f"     {f}: {money(v)}"))
        for t in self.S.get("tickets", []):
            its = "\n".join(f"{q}x {n}" + (f" ({c})" if c != "Geral" else "") for n, q, c in t["itens"])
            g.add_widget(wlabel(f"{escape_markup(t['destino'].upper())} · Mesa {t['mesa']} · {t['hora']} · {escape_markup(t['por'])}\n{escape_markup(its)}\n"
                                + (f"[color=#3F8F5F]{ic('impresso')}[/color] impresso" if t["impresso"]
                                   else f"[color=#D9534F]{ic('naoimpresso')}[/color] não impresso"), markup=True))
            g.add_widget(btn("Imprimir", lambda t=t: self.act("ticket/imprimir", {"id": t["id"]}), BR, TX, icone="imprimir", size_hint_y=None, height=dp(42)))
        if not self.S.get("tickets"):
            g.add_widget(wlabel("Nenhum pedido enviado ainda."))
        sv.add_widget(g)
        return sv


if __name__ == "__main__":
    DoNata().run()