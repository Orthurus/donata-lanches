"""Auto-atualização via GitHub Releases (reutilizável: DoNata, A Tapioca...).

Uso:
    info = checar("usuario/repositorio", "1.0")   # None se já está atualizado
    baixar(info["exe"], destino)
    trocar_exe(info["exe"])                       # baixa, troca e reinicia o programa
"""
import json, os, subprocess, sys, tempfile, urllib.error, urllib.request

API = "https://api.github.com"


def vtuple(s):
    try:
        return tuple(int(x) for x in str(s).lstrip("vV").split("."))
    except ValueError:
        return (0,)


def _abrir(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "atualizador"}), timeout=timeout)


def checar(repo, versao_atual, api=API):
    """Devolve {'versao','exe','apk'} se existir versão mais nova no GitHub; senão None."""
    try:
        with _abrir(f"{api}/repos/{repo}/releases/latest") as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # ainda não existe nenhuma versão publicada
            return None
        raise
    versao = rel["tag_name"].lstrip("vV")
    if vtuple(versao) <= vtuple(versao_atual):
        return None
    arqs = {a["name"].rsplit(".", 1)[-1].lower(): a["browser_download_url"] for a in rel.get("assets", [])}
    return {"versao": versao, "exe": arqs.get("exe"), "apk": arqs.get("apk")}


def baixar(url, destino):
    tmp = destino + ".tmp"
    with _abrir(url, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
    os.replace(tmp, destino)


def gerar_bat(atual, novo):
    return (f'@echo off\nchcp 65001 >nul\nset n=0\n:t\nset /a n+=1\ntimeout /t 1 /nobreak >nul\n'
            f'move /y "{novo}" "{atual}" >nul 2>&1\nif errorlevel 1 if %n% lss 30 goto t\n'
            f'start "" "{atual}"\n(goto) 2>nul & del "%~f0"\n')


def trocar_exe(url):
    """Baixa o .exe novo e deixa um .bat trocar o arquivo e reabrir o programa."""
    atual, novo = sys.executable, sys.executable + ".novo"
    baixar(url, novo)
    bat = os.path.join(tempfile.gettempdir(), "atualizar_programa.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(gerar_bat(atual, novo))
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    subprocess.Popen(["cmd", "/c", bat], env=env, close_fds=True,
                     creationflags=0x08000000 | 0x00000008)  # sem janela, desacoplado
