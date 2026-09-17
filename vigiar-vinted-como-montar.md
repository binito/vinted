# Vigiar preços na Vinted — como montar

Avisa-te quando aparece um artigo novo dentro do teu tecto de preço, ou quando um anúncio que
segues baixa de preço ou é vendido. Corre numa máquina Linux qualquer (um Raspberry Pi chega).

---

## ⚠️ Lê isto primeiro: o estado em 14/09/2026

**A API interna da Vinted deixou de responder a pedidos feitos por `curl`.** A homepage entregava
um cookie de sessão (`access_token_web`) e é com ele que a API do catálogo funcionava. Desde
14/09 entrega apenas três cookies que não servem para isso, e qualquer chamada a
`/api/v2/catalog/items` responde:

```
HTTP 404  {"code":104,"message":"Conteúdo não encontrado","message_code":"not_found"}
```

**Não é bloqueio de IP nem castigo por excesso de pedidos** — testei o mesmo pedido a sair por
outro IP, noutro país, e o resultado é idêntico. E quando a Vinted trava quem faz pedidos a mais,
devolve `403`, não `404`.

**O que isto significa para ti:**

| | Estado |
|---|---|
| Pesquisas por preço (artigos novos dentro de um tecto) | **parado** — depende da API |
| Preço de um anúncio que segues | **parado** — mesma razão |
| Saber que um anúncio foi **vendido** | **funciona** — lê-se na página normal |

Montar isto hoje dá-te o "vendido" a funcionar e o resto pronto para o dia em que a API voltar,
ou em que alguém descubra como obter o token. **Se preferires esperar, esperas.**

---

## O que precisas

- Linux com `python3` e `curl` (qualquer distribuição)
- um sítio para receber os avisos. O exemplo usa [ntfy](https://ntfy.sh) porque é grátis e a app
  é instantânea, mas serve Telegram, email, o que quiseres — é uma função só

---

## 1. O script

Grava em `/usr/local/bin/vigiar-vinted.py` e dá-lhe `chmod +x`.

```python
#!/usr/bin/env python3
"""Vigia a Vinted e avisa quando aparece algo dentro do teu tecto de preço."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120 Safari/537.36")
BASE = "https://www.vinted.pt"          # muda para o teu país: .es, .fr, .it...
JAR = "/tmp/.vinted-cookies.jar"
CONF = "/etc/vigiar-vinted.conf"
ESTADO_D = "/var/lib/vigiar-vinted"
LOG = "/var/log/vigiar-vinted.log"
NTFY = "https://ntfy.sh/o-teu-topico-secreto"   # <-- muda isto

ENSAIO = "--ensaio" in sys.argv


def registar(*a):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("%s %s\n" % (time.strftime("%F %T"), " ".join(str(x) for x in a)))


def correr(args, timeout=90):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or ""
    except (subprocess.TimeoutExpired, OSError) as e:
        # só o TIPO do erro: a mensagem de um timeout traz o comando inteiro,
        # e se lá houver uma password fica escrita no log
        return 1, "__ERRO__%s" % type(e).__name__


def casa(titulo, regra):
    """O título cumpre a regra? `A+B-C` = tem A e B, não tem C. Ignora maiúsculas.

    Uma regra vazia REPROVA tudo — uma regra mal escrita tem de reprovar, não
    deixar passar o catálogo inteiro. É a diferença entre um filtro e um buraco.
    """
    t = (titulo or "").lower()
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
    return all(o in t for o in obrigatorios) and not any(p in t for p in proibidos)


def ler_alvos():
    """(ok, alvos ou motivo). Ficheiro em falta ou vazio NÃO é 'não há nada a vigiar'."""
    if not os.path.exists(CONF):
        return False, "o %s não existe" % CONF
    alvos = []
    for n, linha in enumerate(open(CONF, encoding="utf-8"), 1):
        linha = linha.split("#", 1)[0].strip()
        if not linha:
            continue
        partes = [x.strip() for x in linha.split("|")]
        if len(partes) != 3:
            return False, "linha %d tem %d campos, esperava 3" % (n, len(partes))
        try:
            tecto = int(partes[1])
        except ValueError:
            return False, "linha %d: `%s` não é um número" % (n, partes[1])
        alvos.append((partes[0], tecto, partes[2]))
    if not alvos:
        return False, "o %s não tem nenhum alvo" % CONF
    return True, alvos


def sessao():
    """Apanha os cookies. Sem isto a API devolve HTML de erro."""
    rc, _ = correr(["curl", "-s", "-o", "/dev/null", "-m", "30", "-A", UA,
                    "-c", JAR, BASE + "/"])
    return rc == 0


def procurar(termo, tecto):
    """(ok, artigos ou motivo). ok=False quer dizer NÃO CONSEGUI, nunca 'não há nada'."""
    p = ("/api/v2/catalog/items?search_text=%s&price_to=%d&currency=EUR"
         "&order=newest_first&per_page=20"
         % (urllib.parse.quote(termo), tecto))
    rc, t = correr(["curl", "-s", "-m", "45", "-A", UA, "-b", JAR,
                    "-H", "Accept: application/json", BASE + p])
    if rc != 0:
        return False, "o curl falhou (%s)" % t.replace("__ERRO__", "")
    t = t.strip()
    if not t.startswith("{"):
        return False, "a API não devolveu JSON (%d bytes)" % len(t)
    try:
        d = json.loads(t)
    except ValueError:
        return False, "a API devolveu JSON inválido"
    if "items" not in d:
        # é aqui que se percebe que a API mudou, em vez de pensar que não há artigos
        return False, "a resposta não tem `items` -- a API mudou de forma"
    return True, d["items"]


def avisar(titulo, corpo):
    rc, _ = correr(["curl", "-s", "-o", "/dev/null", "-m", "20",
                    "-H", "Title: %s" % titulo, "-d", corpo, NTFY], timeout=40)
    return rc == 0


def main():
    os.makedirs(ESTADO_D, exist_ok=True)
    ok, alvos = ler_alvos()
    if not ok:
        registar("NÃO CONSEGUI: %s" % alvos)
        return 3
    if not sessao():
        registar("NÃO CONSEGUI: não abri sessão na Vinted")
        return 2

    falhas = novos = 0
    for termo, tecto, exigir in alvos:
        chave = re.sub(r"[^a-z0-9]+", "-", termo.lower()).strip("-")
        f_estado = os.path.join(ESTADO_D, "%s.json" % chave)
        ok, r = procurar(termo, tecto)
        if not ok:
            registar("[%s] NÃO CONSEGUI: %s" % (termo, r))
            falhas += 1
            continue

        vistos = set()
        primeira = not os.path.exists(f_estado)
        if not primeira:
            try:
                vistos = set(json.load(open(f_estado, encoding="utf-8")))
            except (ValueError, OSError):
                registar("[%s] o estado estava ilegível -- recomecei" % termo)
                primeira = True

        interessa = [x for x in r if casa(x.get("title") or "", exigir)]
        ids_agora = [str(x.get("id")) for x in interessa]

        if primeira:
            json.dump(ids_agora, open(f_estado, "w", encoding="utf-8"))
            registar("[%s] primeira leitura: %d de %d artigos passam o filtro (não aviso)"
                     % (termo, len(interessa), len(r)))
            continue

        for x in interessa:
            i = str(x.get("id"))
            if i in vistos:
                continue
            preco = (x.get("price") or {}).get("amount", "?")
            total = (x.get("total_item_price") or {}).get("amount")
            corpo = ("Entrou na pesquisa:\n%s\n%s €%s\n\n%s"
                     % ((x.get("title") or "(sem título)")[:90], preco,
                        (" (%s € com taxa)" % total) if total else "",
                        x.get("url") or (BASE + (x.get("path") or ""))))
            if ENSAIO:
                print("  (--ensaio) NÃO enviei:\n%s\n" % corpo)
            elif avisar("Vigia de preços", corpo):
                registar("[%s] AVISADO: %s | %s EUR" % (termo, i, preco))
                novos += 1
            else:
                registar("[%s] ERRO: artigo %s novo mas o aviso não saiu" % (termo, i))
                falhas += 1

        if not ENSAIO:
            json.dump(ids_agora + list(vistos)[:200], open(f_estado, "w", encoding="utf-8"))

    registar("corrida terminada: %d aviso(s), %d falha(s)" % (novos, falhas))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 2. O que vigiar

Grava em `/etc/vigiar-vinted.conf`. Uma linha por alvo:

```
# <termo de pesquisa> | <tecto em EUR> | <regra do título>

optiplex 3050 | 80  | Optiplex+3050-AIO
optiplex 3060 | 80  | Optiplex+3060-AIO
bicicleta btt | 150 | btt+29-crianca-infantil
```

**A regra do título é o que faz isto prestar.** Sem ela, uma pesquisa por `optiplex 3080` traz
Optiplex 780, Optiplex 380 e baterias de portátil — 19 em cada 20 resultados são lixo.

- `Optiplex+3050` → o título tem de ter **as duas** palavras
- `Optiplex+3050-AIO` → as duas, e **não** pode ter "AIO"

Não distingue maiúsculas. Um anúncio escrito em maiúsculas não escapa.

---

## 3. Pôr a correr

Primeiro à mão, para ver o que apanha sem enviar nada:

```bash
/usr/local/bin/vigiar-vinted.py --ensaio
```

Depois no cron — `/etc/cron.d/vigiar-vinted`:

```
7,37 * * * * root /usr/local/bin/vigiar-vinted.py >/dev/null 2>&1
```

Os minutos ímpares são de propósito: não bater à porta em cima da hora certa, como toda a gente.

---

## 4. Saber que um anúncio foi vendido (isto funciona hoje)

Não precisa da API. A página do anúncio traz a palavra `Vendido` no HTML quando a venda acontece:

```bash
curl -sL -A "$UA" https://www.vinted.pt/items/<id> | grep -c ">Vendido<"
```

Devolve `1` se foi vendido, `0` se continua à venda. Guardas o valor entre corridas e avisas
quando muda. **Dois cuidados**, os dois medidos:

- **`-L` não é opcional.** O endereço sem a parte do nome redirecciona, e sem seguir recebes 76
  bytes de cabeçalho em vez da página.
- **Verifica o tamanho.** Uma página real mede ~2 MB. Se vier com menos de 200 KB, é erro ou
  desafio anti-bot — trata isso como "não consegui ler", nunca como "não foi vendido".

---

## As cinco coisas que fazem a diferença

**1. Distingue "não há nada" de "não consegui ler".** É a mais importante de todas. Um vigia que
escreve "0 artigos novos" quando na verdade não conseguiu falar com o site fica cego e parece
estar a trabalhar. Foi exactamente por termos esta distinção escrita que percebemos em dois
minutos que a API tinha morrido, em vez de andar semanas a pensar que não havia bons negócios.

**2. Alguém tem de ler o log.** O ponto acima não serve de nada se ninguém olhar. Põe um alerta
que dispare quando a última corrida não leu nada, ou quando não há corrida nenhuma há horas.
Mesmo que seja um email diário.

**3. A primeira corrida não avisa.** Guarda o estado e cala-se. Sem isto, a estreia manda um
aviso por cada artigo que já existia.

**4. Filtra pelo título, não só pelo preço.** O tecto de preço corta pouco; o filtro do título
corta quase tudo o que é lixo. Aperta-o sempre que receberes um aviso inútil.

**5. Tem um `--ensaio`.** Mostra a mensagem e não a envia. Serve para testar sem mandar preços
falsos a ninguém — e isso já aconteceu aqui.

---

## Se quiseres o preço de volta quando a API estiver fechada

A única via que conhecemos é um browser sem interface (o
[sockpuppetbrowser](https://github.com/dgtlmoon/sockpuppetbrowser) ou o Playwright) a abrir a
página e a ler os preços depois do JavaScript correr. Custa cerca de 1,2 GB de imagem, uns 2 GB
de memória, e o Chrome tem uma fuga de memória conhecida — mede-se 38 MB a subir para 213 MB em
40 minutos de uso, por isso precisa de ser reiniciado a espaços. É bastante trabalho para vigiar
preços; vale a pena decidir isso com calma.
