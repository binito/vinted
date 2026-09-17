import time
import json
import os
import re
import sys
import html
import argparse
from curl_cffi import requests
import vinted_db

# Forçar unbuffered output no stdout
sys.stdout.reconfigure(line_buffering=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONF_FILE = os.path.join(BASE_DIR, "vigiar-vinted.conf")
SEEN_FILE = os.path.join(BASE_DIR, "seen_items.json")
LOG_FILE = os.path.join(BASE_DIR, "vinted_monitor.log")
JAR_FILE = os.path.join(BASE_DIR, ".vinted_cookies.jar")
REPORT_STATE_FILE = os.path.join(BASE_DIR, ".daily_report_state.json")
CONFIG_VIEW_URL = "http://192.168.1.176:8765/"

def registar(mensagem):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass

def load_seen_items():
    """
    Retorna um dicionário {item_id_str: float(ultimo_preco)}
    Garante suporte e migração retrocompatível se o ficheiro antigo for uma lista/set.
    """
    # MariaDB é a fonte principal; o JSON antigo é apenas migrado/fallback.
    try:
        state = vinted_db.load_seen_items()
        if state:
            return state
    except Exception as e:
        registar(f"[!] MariaDB indisponível ao ler estado: {e}")

    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    state = {str(k): float(v) for k, v in data.items()}
                    try:
                        vinted_db.save_seen_items(state)
                        registar(f"[*] Estado legado migrado para MariaDB: {len(state)} anúncios.")
                    except Exception as e:
                        registar(f"[!] Não foi possível migrar estado para MariaDB: {e}")
                    return state
                elif isinstance(data, list):
                    return {str(k): 999999.0 for k in data}
        except Exception as e:
            registar(f"[!] Erro ao carregar {SEEN_FILE}: {e}")
    return {}

def save_seen_items(seen_dict):
    try:
        vinted_db.save_seen_items(seen_dict)
        return
    except Exception as e:
        registar(f"[!] MariaDB indisponível ao guardar estado; a usar JSON: {e}")
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen_dict, f, indent=2)
    except Exception as e:
        registar(f"[!] Erro ao guardar {SEEN_FILE}: {e}")

def load_report_state():
    """Carrega o dia do último relatório diário enviado com sucesso."""
    try:
        with open(REPORT_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        registar(f"[!] Erro ao carregar estado do relatório diário: {e}")
        return {}

def save_report_state(state):
    try:
        with open(REPORT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        registar(f"[!] Erro ao guardar estado do relatório diário: {e}")

def hora_relatorio_valida(valor):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", valor):
        return False
    try:
        time.strptime(valor, "%H:%M")
        return True
    except ValueError:
        return False

def relatorio_em_falta(estado, hora_relatorio, agora=None):
    """Indica se o relatório deve ser enviado agora, no máximo uma vez por dia."""
    agora = agora or time.localtime()
    hoje = time.strftime("%Y-%m-%d", agora)
    hora_atual = time.strftime("%H:%M", agora)
    return hora_atual >= hora_relatorio and estado.get("last_daily_report") != hoje

def parse_price(val_str):
    """
    Normaliza strings de preço sem falhar por ponto/vírgula regional.
    O separador decimal é o último símbolo (, ou .) que surgir.
    """
    if isinstance(val_str, (int, float)):
        return float(val_str)
    
    v = str(val_str).strip()
    up, uv = v.rfind("."), v.rfind(",")
    if up >= 0 and uv >= 0:
        v = v.replace("," if up > uv else ".", "").replace(",", ".")
    elif uv >= 0:
        v = v.replace(",", "." if len(v) - uv - 1 <= 2 else "")
    
    # Remover símbolos não numéricos mantendo o ponto decimal
    v = re.sub(r"[^\d\.]", "", v)
    return float(v) if v else 0.0

def casa_filtro_titulo(titulo, regra):
    """
    Avalia se o título cumpre a regra no formato `palavra1+palavra2-proibida1`.
    Exemplo: 'optiplex+3070-aio-ecra'
    """
    t = html.unescape(titulo or "").lower()
    obrigatorios, proibidos = [], []
    for pedaco in re.split(r"(?=[+-])", regra.strip()):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        if pedaco.startswith("-"):
            proibidos.append(pedaco[1:].strip().lower())
        else:
            obrigatorios.append(pedaco.lstrip("+").strip().lower())

    obrigatorios = [x for x in obrigatorios if x]
    proibidos = [x for x in proibidos if x]

    if not obrigatorios:
        return False

    def check_ob(o):
        if o == "optiplex":
            return ("optiplex" in t) or ("optiflex" in t)
        return o in t

    passa_obrigatorios = all(check_ob(o) for o in obrigatorios)
    passa_proibidos = not any(p in t for p in proibidos)

    return passa_obrigatorios and passa_proibidos

def atualizar_preco_alvo(termo, novo_preco, config_path=CONF_FILE):
    """
    Atualiza o preço teto de um termo no ficheiro de configuração vigiar-vinted.conf.
    """
    if not os.path.exists(config_path):
        return False, f"Ficheiro de configuração não existe: {config_path}"

    linhas_novas = []
    atualizado = False
    termo_clean = termo.strip().lower()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for linha in f:
                linha_limpa = linha.split("#", 1)[0].strip()
                if linha_limpa:
                    partes = [x.strip() for x in linha_limpa.split("|")]
                    if len(partes) == 3 and partes[0].lower() == termo_clean:
                        # Substituir o preço mantendo os comentários se existissem na mesma linha
                        comentario = (" #" + linha.split("#", 1)[1].strip()) if "#" in linha else ""
                        nova_linha = f"{partes[0]} | {float(novo_preco):.0f} | {partes[2]} {comentario}\n".strip() + "\n"
                        linhas_novas.append(nova_linha)
                        atualizado = True
                        continue
                linhas_novas.append(linha)

        if atualizado:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(linhas_novas)
            return True, f"Preço de '{termo}' atualizado para {novo_preco:.0f}€."
        else:
            # Se o termo não existe, criar automaticamente com regra de exclusão padrão
            partes_termo = termo_clean.split()
            modelo = partes_termo[-1] if partes_termo else "3020"
            regra_defeito = f"optiplex+{modelo}-aio-ecra-monitor-cabo-cable-pecas-peca-caddy-fonte-alimentation-alimentatore-alimentador-chargeur-charger-carregador-part-parte-bateria-battery-placa-carte-board"
            nova_linha_alvo = f"\n{termo_clean} | {float(novo_preco):.0f} | {regra_defeito}\n"
            
            with open(config_path, "a", encoding="utf-8") as f:
                f.write(nova_linha_alvo)
            return True, f"Novo alvo '{termo_clean}' adicionado com sucesso (Tecto: {novo_preco:.0f}€)!"
    except Exception as e:
        return False, f"Erro ao atualizar/adicionar configuração: {e}"

def remover_alvo(termo, config_path=CONF_FILE):
    """
    Remove um termo do ficheiro de configuração vigiar-vinted.conf.
    """
    if not os.path.exists(config_path):
        return False, f"Ficheiro de configuração não existe: {config_path}"

    linhas_novas = []
    removido = False
    termo_clean = termo.strip().lower()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for linha in f:
                linha_limpa = linha.split("#", 1)[0].strip()
                if linha_limpa:
                    partes = [x.strip() for x in linha_limpa.split("|")]
                    if len(partes) == 3 and partes[0].lower() == termo_clean:
                        removido = True
                        continue
                linhas_novas.append(linha)

        if removido:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(linhas_novas)
            return True, f"Alvo '{termo}' removido com sucesso."
        else:
            return False, f"Alvo '{termo}' não encontrado."
    except Exception as e:
        return False, f"Erro ao remover alvo: {e}"

def ler_alvos(config_path=CONF_FILE):
    if not os.path.exists(config_path):
        return False, f"O ficheiro de configuração {config_path} não existe."

    alvos = []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for n, linha in enumerate(f, 1):
                linha = linha.split("#", 1)[0].strip()
                if not linha:
                    continue
                partes = [x.strip() for x in linha.split("|")]
                if len(partes) != 3:
                    return False, f"Linha {n} inválida: esperavam-se 3 campos separados por '|'."
                try:
                    tecto = float(partes[1])
                except ValueError:
                    return False, f"Linha {n}: preço máximo '{partes[1]}' inválido."

                alvos.append((partes[0], tecto, partes[2]))
    except Exception as e:
        return False, f"Erro ao ler configuração: {e}"

    if not alvos:
        return False, f"O ficheiro {config_path} não contém nenhum alvo ativo."

    return True, alvos

def enviar_relatorio_diario(ntfy_topic, ntfy_server="https://ntfy.sh"):
    """
    Envia um resumo diário dos alvos de pesquisa ativos e respetivos preços teto.
    """
    ok_conf, alvos_ou_erro = ler_alvos()
    if not ok_conf:
        registar(f"[!] Erro ao obter alvos para o relatório diário: {alvos_ou_erro}")
        return False

    alvos = alvos_ou_erro
    data_hoje = time.strftime("%d/%m/%Y")
    
    linhas_msg = [f"📊 Relatório Diário Vinted - {data_hoje}\n"]
    linhas_msg.append("Alvos ativos & Preços Máximos atuais:")
    for termo, tecto, _ in alvos:
        linhas_msg.append(f"• {termo.title()}: max {tecto:.0f}€")

    mensagem = "\n".join(linhas_msg)
    url = f"{ntfy_server.rstrip('/')}/{ntfy_topic}"
    
    # Criar botões de ação para os alvos principais (exemplo: aumentar/diminuir limite)
    actions = [
        f"view, Abrir configuracao, {CONFIG_VIEW_URL}",
    ]
    
    headers = {
        "Title": "Resumo Diario: Configuracao de Pesquisas Vinted",
        "Tags": "calendar,chart_with_upwards_trend,gear",
        "Actions": "; ".join(actions)
    }

    try:
        resp = requests.post(url, data=mensagem.encode("utf-8"), headers=headers, timeout=10)
        if resp.status_code == 200:
            registar(f"[+] Relatório diário enviado com sucesso para '{ntfy_topic}'!")
            return True
        else:
            registar(f"[!] Erro ao enviar relatório diário ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        registar(f"[!] Exceção ao enviar relatório diário: {e}")
        return False

def send_ntfy_notification(ntfy_topic, title, message, click_url, ntfy_server="https://ntfy.sh", termo=None):
    url = f"{ntfy_server.rstrip('/')}/{ntfy_topic}"
    headers = {
        "Title": "Alerta Vinted - Dell Optiplex",
        "Tags": "computer,desktop,euro",
    }
    if click_url:
        headers["Click"] = click_url

    # Permite terminar apenas o alvo que originou o alerta, depois de comprar o artigo.
    # O comando é processado pelo próprio daemon na ronda seguinte.
    if termo:
        headers["Actions"] = (
            f"http, Parar busca: {termo}, {url}, body=remover {termo}"
        )

    full_message = f"{title}\n\n{message}"
    try:
        resp = requests.post(url, data=full_message.encode("utf-8"), headers=headers, timeout=10)
        if resp.status_code == 200:
            registar(f"[+] Notificação ntfy enviada com sucesso para '{ntfy_topic}'!")
            return True
        else:
            registar(f"[!] Erro ao enviar notificação ntfy ({resp.status_code}): {resp.text}")
            vinted_db.record_health("ERROR", "ntfy", f"HTTP {resp.status_code} ao enviar alerta")
            return False
    except Exception as e:
        registar(f"[!] Exceção ao enviar notificação ntfy: {e}")
        try:
            vinted_db.record_health("ERROR", "ntfy", str(e))
        except Exception:
            pass
        return False

def enviar_confirmacao_comando(ntfy_topic, titulo, mensagem, tags, ntfy_server="https://ntfy.sh"):
    """Publica feedback visível e deixa no log o resultado do envio."""
    url = f"{ntfy_server.rstrip('/')}/{ntfy_topic}"
    headers = {"Title": titulo, "Tags": tags}
    try:
        resp = requests.post(url, data=mensagem.encode("utf-8"), headers=headers, timeout=10)
        if resp.status_code == 200:
            registar(f"[+] Confirmação ntfy enviada: {titulo}")
            return True
        registar(f"[!] Não foi possível enviar confirmação ntfy ({resp.status_code}): {resp.text}")
    except Exception as e:
        registar(f"[!] Exceção ao enviar confirmação ntfy: {e}")
    return False

def get_vinted_session_tokens(session):
    """
    Apanha os cookies da homepage e o cabeçalho X-Anon-Id para autorizar a API /svc-catalogue/items
    """
    try:
        r = session.get("https://www.vinted.pt/", timeout=15)
        anon_id = r.headers.get("X-Anon-Id") or r.headers.get("x-anon-id")
        return True, anon_id
    except Exception as e:
        return False, str(e)

def scrape_vinted_api(session, search_query, anon_id):
    """
    Método Primário: API oficial /svc-catalogue/items com X-Anon-Id
    Retorna (sucesso_bool, lista_itens_ou_mensagem_erro)
    """
    url = f"https://api.vinted.pt/svc-catalogue/items?search_text={requests.utils.quote(search_query)}&per_page=60&order=newest_first"
    headers = {
        "Accept": "application/json",
        "X-Next-App": "marketplace-web",
        "Referer": "https://www.vinted.pt/",
        "Origin": "https://www.vinted.pt",
    }
    if anon_id:
        headers["X-Anon-Id"] = anon_id

    try:
        resp = session.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return False, f"API respondeu com HTTP {resp.status_code}"

        data = resp.json()
        if "items" not in data:
            return False, "Estrutura JSON da API alterada (campo 'items' em falta)"

        items = []
        for item in data.get("items", []):
            item_id = str(item.get("id"))
            title = html.unescape(item.get("title") or "")
            
            # Preço do artigo (ou total com taxa se disponível)
            price_obj = item.get("price") or {}
            total_obj = item.get("total_item_price") or {}
            
            price_val = parse_price(price_obj.get("amount", 0))
            total_val = parse_price(total_obj.get("amount", price_val)) if total_obj else price_val
            
            item_url = item.get("url") or f"https://www.vinted.pt/items/{item_id}"
            if item_url.startswith("/"):
                item_url = "https://www.vinted.pt" + item_url

            items.append({
                'id': item_id,
                'title': title.strip(),
                'price': price_val,
                'total_price': total_val,
                'url': item_url
            })

        return True, items
    except Exception as e:
        return False, f"Exceção na API: {e}"

def scrape_vinted_html(session, search_query):
    """
    Método de Fallback (Rede de Segurança): Scraping do HTML /catalog caso a API falhar
    """
    url = f"https://www.vinted.pt/catalog?search_text={search_query.replace(' ', '+')}&order=newest_first"
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return False, f"HTTP Error {resp.status_code} no HTML"

        if len(resp.text) < 200000:
            return False, f"Página HTML curta ({len(resp.text)} bytes) - possível erro ou captcha"

        pattern = r'href="(/items/(\d+)-[^"]+)"[^>]*title="([^"]+)"'
        matches = re.findall(pattern, resp.text)

        if not matches:
            return False, "Nenhum padrão de artigo encontrado no HTML - estrutura alterada?"

        items = []
        for href, item_id, full_title_str in matches:
            full_url = "https://www.vinted.pt" + href
            prices = re.findall(r'([\d\.,]+)\s*€', full_title_str)
            if not prices:
                continue

            price_val = parse_price(prices[0])
            title = full_title_str.split(', Marca:')[0] if ', Marca:' in full_title_str else full_title_str
            title = html.unescape(title)

            items.append({
                'id': str(item_id),
                'title': title.strip(),
                'price': price_val,
                'total_price': price_val,
                'url': full_url
            })

        return True, items
    except Exception as e:
        return False, f"Exceção no HTML: {e}"

def processar_mensagens_ntfy(ntfy_topic, ntfy_server="https://ntfy.sh", since_time="10m"):
    """
    Consulta as mensagens recentes enviadas para o tópico do ntfy e processa comandos de ajuste de preço.
    Exemplo de mensagem enviada pelo utilizador no ntfy: 'dell optiplex 3020 30' ou 'dell optiplex 7010: 45'
    """
    url = f"{ntfy_server.rstrip('/')}/{ntfy_topic}/json?poll=1&since={since_time}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return

        linhas = resp.text.strip().split("\n")
        for linha in linhas:
            if not linha.strip():
                continue
            try:
                data = json.loads(linha)
                if data.get("event") == "message":
                    msg_id = data.get("id")
                    msg_text = data.get("message", "").strip()

                    # Ignorar mensagens enviadas pelo próprio sistema/bot
                    if not msg_text or "Relatorio" in msg_text or "Preco" in msg_text or "Anuncio" in msg_text or msg_text.startswith("📊") or msg_text.startswith("🚨") or msg_text.startswith("📉") or msg_text.startswith("✅") or msg_text.startswith("Alteracao"):
                        continue
                    
                    # Evitar reprocessar a mesma mensagem
                    if hasattr(processar_mensagens_ntfy, "processed_ids") and msg_id in processar_mensagens_ntfy.processed_ids:
                        continue
                    
                    if not hasattr(processar_mensagens_ntfy, "processed_ids"):
                        processar_mensagens_ntfy.processed_ids = set()
                    processar_mensagens_ntfy.processed_ids.add(msg_id)

                    # Tratar comando de remoção se o utilizador clicar ou enviar 'remover <termo>'
                    if msg_text.lower().startswith("remover ") or msg_text.lower().startswith("delete "):
                        termo_del = msg_text.split(" ", 1)[1].strip()
                        ok_del, msg_del = remover_alvo(termo_del)
                        registar(f"[NTFY COMMAND] {msg_del}")
                        enviar_confirmacao_comando(
                            ntfy_topic,
                            "Alvo removido" if ok_del else "Não foi possível remover o alvo",
                            f"❌ {msg_del}",
                            "wastebasket,x" if ok_del else "warning",
                            ntfy_server,
                        )
                        continue

                    # Tentar extrair termo e preco (ex: 'dell optiplex 3020 35' ou 'dell optiplex 3070 100')
                    match = re.search(r'^(.*?)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*€?$', msg_text, re.IGNORECASE)
                    if match:
                        termo_req = match.group(1).strip()
                        preco_req = parse_price(match.group(2))
                        if termo_req and preco_req > 0:
                            ok_upd, msg_upd = atualizar_preco_alvo(termo_req, preco_req)
                            registar(f"[NTFY COMMAND] {msg_upd}")
                            
                            texto_corpo = (
                                f"Alteração efetuada:\n\n"
                                f"• Alvo: {termo_req.title()}\n"
                                f"• Novo Tecto: {preco_req:.0f}EUR\n\n"
                                f"A busca será atualizada na ronda atual."
                            )
                            enviar_confirmacao_comando(
                                ntfy_topic,
                                "Preço atualizado" if ok_upd else "Não foi possível atualizar o preço",
                                texto_corpo if ok_upd else f"⚠️ {msg_upd}",
                                "white_check_mark,gear" if ok_upd else "warning",
                                ntfy_server,
                            )
            except Exception:
                pass
    except Exception as e:
        registar(f"[!] Erro ao consultar mensagens ntfy: {e}")

def main():
    parser = argparse.ArgumentParser(description="Vinted Monitor Avançado v2.1")
    parser.add_argument("--topic", type=str, required=True, help="Tópico do ntfy")
    parser.add_argument("--server", type=str, default="https://ntfy.sh", help="Servidor ntfy")
    parser.add_argument("--interval", type=int, default=120, help="Intervalo de verificação em segundos")
    parser.add_argument("--once", action="store_true", help="Executar apenas uma verificação e sair")
    parser.add_argument("--ensaio", action="store_true", help="Modo ensaio: mostra os alertas sem enviar ntfy e sem gravar estado")
    parser.add_argument("--relatorio", action="store_true", help="Envia o relatório diário de alvos e sai")
    parser.add_argument("--hora-relatorio", default="09:00", help="Hora local do resumo diário (HH:MM; predefinição: 09:00)")
    parser.add_argument("--sem-relatorio-diario", action="store_true", help="Desativa o resumo diário automático")
    parser.add_argument("--set-price", nargs=2, metavar=('TERMO', 'PRECO'), help="Atualiza o preço teto de um termo (ex: --set-price 'dell optiplex 3070' 95)")

    args = parser.parse_args()

    if not hora_relatorio_valida(args.hora_relatorio):
        parser.error("--hora-relatorio deve usar o formato HH:MM (por exemplo 09:00)")

    if args.set_price:
        termo_input, preco_input = args.set_price[0], float(args.set_price[1])
        ok_upd, msg_upd = atualizar_preco_alvo(termo_input, preco_input)
        registar(msg_upd)
        if ok_upd:
            sys.exit(0)
        else:
            sys.exit(1)

    if args.relatorio:
        enviar_relatorio_diario(args.topic, args.server)
        sys.exit(0)

    try:
        vinted_db.initialize()
        vinted_db.record_health("INFO", "monitor", "Monitor iniciado")
    except Exception as e:
        registar(f"[!] MariaDB indisponível; modo de compatibilidade JSON: {e}")
    seen_items = load_seen_items()
    report_state = load_report_state()
    primeira_execucao = (len(seen_items) == 0)

    registar(f"[*] Monitor Vinted v2.1 iniciado. Tópico ntfy: {args.topic} (Modo Ensaio: {args.ensaio})")

    session = requests.Session(impersonate="chrome120")

    while True:
        # 0. Verificar se o utilizador enviou comandos via ntfy
        processar_mensagens_ntfy(args.topic, args.server)

        # 0.1 Enviar, uma vez por dia, o resumo dos alvos ativos.
        if not args.sem_relatorio_diario and relatorio_em_falta(report_state, args.hora_relatorio):
            if enviar_relatorio_diario(args.topic, args.server):
                report_state["last_daily_report"] = time.strftime("%Y-%m-%d")
                save_report_state(report_state)

        # Recarregar alvos atualizados
        ok_conf, alvos_ou_erro = ler_alvos()
        if not ok_conf:
            registar(f"[CRÍTICO] Falha na configuração: {alvos_ou_erro}")
            sys.exit(1)

        alvos = alvos_ou_erro
        registar(f"\n[*] A iniciar verificação de {len(alvos)} alvos...")
        
        # Obter X-Anon-Id para a API
        ok_sess, anon_id = get_vinted_session_tokens(session)
        if not ok_sess:
            registar(f"[!] Aaviso: Não foi possível obter X-Anon-Id ({anon_id}). Tentará fallback.")

        for termo, tecto_preco, regra_filtro in alvos:
            # 1. Tentar API Primária
            via_usada = "API /svc-catalogue"
            ok_read, res_items = scrape_vinted_api(session, termo, anon_id)

            # 2. Fallback para HTML se a API falhar
            if not ok_read:
                registar(f"[!] [{termo}] API Falhou ({res_items}). A tentar Fallback HTML...")
                via_usada = "HTML /catalog"
                ok_read, res_items = scrape_vinted_html(session, termo)

            if not ok_read:
                registar(f"[CRÍTICO] [{termo}] FALHA TOTAL DE LEITURA (API e HTML falharam): {res_items}")
                try:
                    vinted_db.record_health("ERROR", "vinted", f"{termo}: {res_items}")
                except Exception:
                    pass
                continue

            items = res_items
            registar(f"[*] [{termo}] [{via_usada}] Lido com sucesso: {len(items)} anúncios recentes.")

            for item in items:
                item_id = item['id']
                # O teto representa o custo final para o comprador, incluindo taxa Vinted.
                preco_atual = item['total_price']
                ultimo_preco = seen_items.get(item_id)

                # Validar tecto de preço e regras do título
                if preco_atual <= tecto_preco and casa_filtro_titulo(item['title'], regra_filtro):
                    
                    is_novo = (ultimo_preco is None)
                    is_baixou_preco = (ultimo_preco is not None and preco_atual < ultimo_preco)

                    if (is_novo or is_baixou_preco) and not primeira_execucao:
                        if is_novo:
                            title_msg = f"🚨 Novo Anúncio Vinted: {item['title']}"
                            reason_str = f"Preço: {preco_atual:.2f}€ (Tecto: {tecto_preco:.2f}€)"
                        else:
                            title_msg = f"📉 BAIXA DE PREÇO Vinted: {item['title']}"
                            reason_str = f"Preço Baixou: {ultimo_preco:.2f}€ ➡️ {preco_atual:.2f}€ (Tecto: {tecto_preco:.2f}€)"

                        body_msg = f"{reason_str}\nVia: {via_usada}\nLink: {item['url']}"
                        registar(f"[MATCH] {title_msg} - {preco_atual}€")

                        if args.ensaio:
                            registar(f"  [MODO ENSAIO] Notificação omitida. Conteúdo:\n{body_msg}")
                        else:
                            send_ntfy_notification(
                                args.topic, title_msg, body_msg, item['url'], args.server, termo
                            )
                        try:
                            vinted_db.record_alert(item, termo, "new" if is_novo else "price_drop")
                        except Exception as e:
                            registar(f"[!] Não foi possível guardar histórico de alerta: {e}")

                    # Só anúncios elegíveis entram no estado; impede marcar ruído como visto.
                    seen_items[item_id] = preco_atual

        # Guardar estado apenas se NÃO FOR modo ensaio
        if not args.ensaio:
            save_seen_items(seen_items)
            if primeira_execucao:
                registar("[*] Primeira execução concluída. Base de dados inicial gravada em silêncio.")
                primeira_execucao = False
        else:
            registar("[*] [MODO ENSAIO] Estado de anúncios vistos NÃO foi alterado no disco.")

        if args.once or args.ensaio:
            registar("[*] Execução concluída (--once / --ensaio).")
            break

        registar(f"[*] A aguardar {args.interval} segundos até à próxima ronda...")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
