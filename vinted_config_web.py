#!/usr/bin/env python3
"""Painel local para consultar e administrar os alvos do monitor Vinted."""

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from vinted_monitor import ler_alvos, adicionar_alvo, atualizar_preco_alvo, remover_alvo


def page_html(message="", is_error=False):
    ok, targets_or_error = ler_alvos()
    if not ok and "não contém nenhum alvo ativo" not in str(targets_or_error):
        return f"<h1>Erro de configuração</h1><p>{escape(str(targets_or_error))}</p>"
    targets_or_error = [] if not ok else targets_or_error

    cards = []
    for term, ceiling, _rule in targets_or_error:
        safe_term = escape(term, quote=True)
        cards.append(f"""
        <article class="target-card">
          <div class="target-top"><div><span class="eyebrow">PESQUISA ATIVA</span><h2>{safe_term}</h2></div><span class="pulse" title="Monitorização ativa"></span></div>
          <form method="post" action="/price" class="price-form">
            <input type="hidden" name="term" value="{safe_term}">
            <label for="price-{len(cards)}">Preço máximo</label>
            <div class="price-control"><span>€</span><input id="price-{len(cards)}" name="price" type="number" min="1" step="1" value="{ceiling:.0f}" required><button type="submit">Atualizar</button></div>
          </form>
          <form method="post" action="/remove" onsubmit="return confirm('Parar a busca por {safe_term}?')">
            <input type="hidden" name="term" value="{safe_term}">
            <button class="remove" type="submit">⌫&nbsp; Eliminar busca</button>
          </form>
        </article>""")

    notice = ""
    if message:
        css_class = "error" if is_error else "success"
        notice = f'<p class="{css_class}">{escape(message)}</p>'
    return f"""<!doctype html>
<html lang="pt-PT"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#090b16"><title>Vinted Radar</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;color:#f7f8ff;background:#090b16;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}
body:before{{content:"";position:fixed;z-index:-1;inset:0;background:radial-gradient(circle at 85% -5%,#854dff55,transparent 32rem),radial-gradient(circle at 0 22%,#00e5b544,transparent 29rem)}}
.shell{{width:min(100%,48rem);margin:auto;padding:calc(2rem + env(safe-area-inset-top)) 1.1rem 3rem}} .hero{{padding:.5rem .2rem 2rem}}
.brand{{display:flex;align-items:center;gap:.65rem;color:#aeb8ff;font-size:.78rem;font-weight:800;letter-spacing:.16em}} .brand-mark{{display:grid;place-items:center;width:2rem;height:2rem;border-radius:.7rem;background:linear-gradient(135deg,#8b5cf6,#00d7b4);color:white;font-size:1rem;box-shadow:0 8px 24px #7c3aed55}}
h1{{font-size:clamp(2.15rem,9vw,3.5rem);letter-spacing:-.075em;line-height:.95;margin:1.25rem 0 .9rem}} h1 em{{font-style:normal;color:#55f2ca}} .subtitle{{margin:0;color:#a8afc7;max-width:34rem;font-size:1rem}}
.stat{{display:inline-flex;align-items:center;gap:.4rem;margin-top:1.25rem;padding:.45rem .7rem;border:1px solid #ffffff16;border-radius:99px;background:#ffffff0a;color:#d7dcf2;font-size:.82rem}} .stat b{{color:#55f2ca}}
.success,.error{{margin:0 0 1rem;padding:1rem 1.1rem;border-radius:1rem;font-weight:650}} .success{{background:#0acb8c20;border:1px solid #28e3ae55;color:#baffea}} .error{{background:#ff496620;border:1px solid #ff6b7c55;color:#ffd4da}}
.grid{{display:grid;gap:.85rem}} .target-card{{position:relative;overflow:hidden;padding:1.2rem;border:1px solid #ffffff14;border-radius:1.35rem;background:linear-gradient(135deg,#171a2cdd,#101220dd);box-shadow:0 15px 35px #0000002e}}
.target-card:before{{content:"";position:absolute;top:0;left:0;width:100%;height:2px;background:linear-gradient(90deg,#8b5cf6,#00d7b4);opacity:.8}} .target-top{{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}}
.eyebrow{{color:#8490b6;font-size:.64rem;letter-spacing:.13em;font-weight:800}} h2{{margin:.35rem 0 1.3rem;font-size:1.16rem;letter-spacing:-.025em;overflow-wrap:anywhere}} .pulse{{margin-top:.25rem;width:.7rem;height:.7rem;border-radius:50%;background:#4ff3c9;box-shadow:0 0 0 .3rem #4ff3c922,0 0 15px #4ff3c9}}
.add-card{{margin-bottom:1.1rem;padding:1.2rem;border:1px solid #55f2ca3d;border-radius:1.35rem;background:linear-gradient(135deg,#122a2ddd,#101220dd);box-shadow:0 15px 35px #0000002e}} .add-card h2{{margin-bottom:.35rem}} .add-card p{{margin:.1rem 0 1rem;color:#a8afc7;font-size:.82rem}} .add-grid{{display:grid;gap:.7rem}} label{{display:block;color:#aeb6cf;font-size:.76rem;font-weight:750;margin-bottom:.35rem}} input{{min-width:0;width:100%;border:1px solid #ffffff1c;border-radius:.7rem;outline:0;padding:.75rem .8rem;background:#07091399;color:white;font:600 .95rem Inter,system-ui}} .add-grid button{{margin-top:.2rem;width:100%}} .price-form label{{display:block;color:#aeb6cf;font-size:.76rem;font-weight:750;margin-bottom:.45rem}} .price-control{{display:flex;align-items:center;gap:.35rem;padding:.28rem .3rem .28rem .85rem;border:1px solid #ffffff1c;border-radius:.9rem;background:#07091399;color:#55f2ca;font-size:1.15rem;font-weight:800}} .price-control input{{border:0;border-radius:0;padding:.2rem 0;font:800 1.35rem/1 Inter,system-ui}} button{{border:0;border-radius:.68rem;padding:.72rem .86rem;background:linear-gradient(135deg,#7c4dff,#9a63ff);color:white;font:750 .82rem Inter,system-ui;cursor:pointer;box-shadow:0 6px 16px #6939df4a}} button:active{{transform:scale(.97)}} .remove{{margin-top:.8rem;padding:0;background:none;box-shadow:none;color:#ff99a6;font-size:.75rem}}
.footer{{margin:1.8rem .2rem 0;color:#727c9b;font-size:.76rem;text-align:center}} @media (min-width:600px){{.shell{{padding-left:1.5rem;padding-right:1.5rem}}.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style>
<main class="shell"><header class="hero"><div class="brand"><span class="brand-mark">⌁</span> VINTED + WALLAPOP RADAR</div><h1>As tuas buscas,<br><em>sob controlo.</em></h1><p class="subtitle">Adiciona pesquisas, ajusta limites ou termina uma monitorização. As mudanças entram em vigor até à próxima ronda.</p><span class="stat"><b>{len(targets_or_error)}</b> buscas em vigilância</span></header>{notice}<section class="add-card"><h2>Adicionar pesquisa</h2><p>A mesma pesquisa será procurada na Vinted e no Wallapop.</p><form method="post" action="/add" class="add-grid"><div><label for="new-term">Termo de pesquisa</label><input id="new-term" name="term" type="text" placeholder="dell optiplex 3070" required></div><div><label for="new-price">Preço máximo (€)</label><input id="new-price" name="price" type="number" min="1" step="1" placeholder="95" required></div><div><label for="new-rule">Regra do título</label><input id="new-rule" name="rule" type="text" placeholder="optiplex+3070-aio-ecra" required></div><button type="submit">＋ Adicionar pesquisa</button></form></section><section class="grid">{''.join(cards)}</section><p class="footer">Monitor Vinted + Wallapop · atualização automática a cada 2 minutos</p></main></html>"""


class ConfigHandler(BaseHTTPRequestHandler):
    def send_page(self, message="", is_error=False):
        body = page_html(message, is_error).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        self.send_page()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = parse_qs(self.rfile.read(length).decode("utf-8"))
        term = data.get("term", [""])[0].strip()
        if self.path == "/add":
            try:
                price = float(data.get("price", [""])[0])
            except ValueError:
                self.send_page("Indique um preço positivo.", True)
                return
            rule = data.get("rule", [""])[0].strip()
            ok, message = adicionar_alvo(term, price, rule)
        elif self.path == "/price":
            try:
                price = float(data.get("price", [""])[0])
                if price <= 0:
                    raise ValueError
            except ValueError:
                self.send_page("Indique um preço positivo.", True)
                return
            ok, message = atualizar_preco_alvo(term, price)
        elif self.path == "/remove":
            ok, message = remover_alvo(term)
        else:
            self.send_error(404)
            return
        self.send_page(message, not ok)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8765), ConfigHandler).serve_forever()
