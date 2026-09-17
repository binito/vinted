# Vigia da Vinted — o que funciona

**14 de Setembro de 2026.** Tudo o que está aqui foi corrido e medido hoje. Os blocos de comando
foram testados exactamente como estão escritos.

---

## 1. A API do catálogo

```
https://api.vinted.XX/svc-catalogue/items
```

### Cabeçalhos obrigatórios

```
X-Anon-Id:   <vem no CABEÇALHO da resposta da homepage, não num cookie>
X-Next-App:  marketplace-web
```

Sem eles, `401`.

### Obter o `X-Anon-Id`

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
JAR=/tmp/.vinted.jar

ANON=$(curl -s -D - -o /dev/null -A "$UA" -c "$JAR" https://www.vinted.pt/ \
       | grep -i '^x-anon-id:' | cut -d: -f2- | tr -d ' \r')
```

### O pedido

```bash
curl -s -A "$UA" -b "$JAR" \
  -H 'Accept: application/json' \
  -H 'X-Next-App: marketplace-web' \
  -H "X-Anon-Id: $ANON" \
  -H 'Referer: https://www.vinted.pt/' \
  -H 'Origin: https://www.vinted.pt' \
  'https://api.vinted.pt/svc-catalogue/items?search_text=optiplex&per_page=60&order=newest_first'
```

**HTTP 200, 60 artigos.** Basta `curl` simples — não é preciso biblioteca de impersonação.

### O que cada artigo traz

| Campo | |
|---|---|
| `id` | número do anúncio; o URL é `https://www.vinted.pt/items/<id>` |
| `title` | título completo |
| `price.amount` | preço pedido |
| **`total_item_price.amount`** | **preço com a taxa de protecção** — é o que o comprador paga |
| `service_fee` | a taxa, à parte |
| `favourite_count` | quantos gostos |
| `photo`, `photos`, `promoted`, `item_box` | |

### Parâmetros úteis

| | |
|---|---|
| `search_text` | o termo de pesquisa |
| `per_page` | **pedir 60**: se filtrares preço e título do teu lado, pedir poucos perde artigos bons |
| `order=newest_first` | os mais recentes primeiro |
| `attribute_ids[catalog]` | filtro por categoria — ver a nota abaixo |

⚠️ **O filtro por categoria fica em aberto.** O parâmetro é `attribute_ids[catalog]`, mas ainda
não descobri o número certo: os artigos na resposta não trazem campo de categoria, e
`svc-catalogue/catalogs`, `/catalog-tree` e `/filters` respondem `NOT_FOUND`. Se descobrires o
número, diz — é o filtro mais limpo que há, e poupa metade das exclusões por título.

---

## 2. O HTML do catálogo, como rede de segurança

A página pública continua a servir tudo o que é preciso, e é bom ter os dois caminhos: se a API
mudar, o aviso degrada — perde-se o preço com taxa — em vez de desaparecer.

```
https://www.vinted.pt/catalog?search_text=<termo>&order=newest_first
```

Cada artigo é uma ligação com o texto todo no atributo `title`:

```python
ARTIGO = re.compile(r'href="(/items/(\d+)-[^"]+)"[^>]*title="([^"]+)"')
```

O `title` traz nome, preço, marca, tamanho e estado. O nome acaba no primeiro atributo:

```python
nome = re.split(r",\s*(?:Marca|Tamanho|Estado|Brand|Size|Condition):", texto)[0]
```

Medido: **7,2 MB de página, 96 artigos**, com `curl` simples.

⚠️ **Diz no log qual dos dois caminhos foi usado.** Se cair para o HTML sem ninguém saber,
perde-se o preço com taxa em silêncio e um dia alguém pergunta porque é que os avisos mudaram
de forma.

---

## 3. Ler o preço sem partir os números

A Vinted escreve `45.00 €` — **ponto decimal**. Tratá-lo como separador de milhares faz `4500`,
nenhum artigo passa o tecto, e o log diz `0 artigos` como se o catálogo estivesse vazio: a
leitura funciona, o número é que está errado, e nada aponta o erro.

A regra que resolve os dois formatos sem adivinhar a região — **o separador decimal é o último
símbolo que aparecer; tudo antes são milhares**:

```python
up, uv = v.rfind("."), v.rfind(",")
if up >= 0 and uv >= 0:                       # 1.234,50  ou  1,234.50
    v = v.replace("," if up > uv else ".", "").replace(",", ".")
elif uv >= 0:                                 # 45,5 é decimal; 1,234 são milhares
    v = v.replace(",", "." if len(v) - uv - 1 <= 2 else "")
```

Provado contra `45.00`, `1.234,50`, `1,234.50`, `45,5`, `1.234`, `7` e entradas inválidas.

---

## 4. O filtro do título

### As exclusões de peças

O tecto de preço **não corta peças** — são baratas, e é isso que as faz passar por um filtro que
só olha ao máximo. Sem lista de exclusões entram cabos a 12 € e caddies a 25 €.

```
-aio-ecra-ecrã-monitor-cabo-cable-câble-caddy-peca-peça-fonte-alimentation-chargeur-suporte-ventoinha-dissipador-tampa
```

⚠️ **Os acentos contam.** O filtro compara texto tal e qual: `cabo` não apanha `câbles`, e `peca`
não apanha `peça`. Por isso estão os dois.

### Exigir ou excluir, conforme o caso

Exigir o número do modelo (`Optiplex+3050`) corta muito ruído, **mas deixa escapar anúncios com
títulos pobres**. Um Dell OptiPlex Micro a 70 € passou-nos ao lado porque o título era só
*"Dell Optiplex - Windows 11 Pro"* — tem `optiplex`, não tem o número.

A saída foi ter os dois tipos de alvo: as pesquisas por modelo, e uma pesquisa larga que **exclui
em vez de exigir** — os modelos velhos e os formatos errados:

```
optiplex micro | 90 | Optiplex-780-380-390-790-990-3010-7010-9010-sff<exclusões de peças>
```

Provado contra nove títulos reais: passa o de título pobre, o 9020 e o 3020; chumba o AIO, o 780,
o 380, o 7010 SFF, uma bateria de portátil e um Lenovo ThinkCentre.

Custa avisos repetidos quando um artigo casa com dois alvos. Vale a pena: mais vale o aviso a
dobrar do que perder o negócio.

---

## 5. Três coisas que evitam ficar cego sem saber

### 5.1 Distinguir "não há nada" de "não consegui ler"

A mais importante de todas. Um vigia que devolve `0 artigos novos` quando na verdade não
conseguiu falar com o site **fica cego e parece que está a trabalhar**.

Se o pedido corre bem mas a resposta não tem a forma esperada, devolve-se **erro**, nunca lista
vazia:

```python
if "items" not in d:
    return False, "a resposta nao tem `items` -- a API mudou de forma"
```

```python
if not achados:
    return False, ("a pagina veio inteira (%d bytes) mas nenhum artigo casou o padrao -- "
                   "o HTML mudou?" % len(t))
```

### 5.2 Um guarda para respostas curtas

Uma página de erro ou um desafio anti-bot mede poucos KB; as reais medem MB.

```python
if len(t) < 200000:
    return False, "a pagina veio com %d bytes (as reais tem varios MB)" % len(t)
```

Foi este guarda que apanhou um `curl` sem `-L` a devolver 76 bytes de cabeçalho — um vigia que
sem ele ficava mudo para sempre.

### 5.3 Alguém tem de ler esse log

Os dois pontos acima não valem nada sozinhos. Uma verificação automática, uma vez por dia, que
acusa por **dois sinais** — porque cada um sozinho deixa passar o outro:

1. a última corrida **correu mas não leu nada**;
2. **não há corrida nenhuma** há demasiado tempo.

Seja um email diário, um segundo tópico do ntfy ou um `cron` que lê o log. É a peça que impede
que uma paragem dure semanas sem ninguém dar por ela.

---

## 6. Três correcções que te sugiro

### 6.1 Marcar o artigo como visto **depois** de olhar ao preço

```python
if item_id in seen_items:
    continue
seen_items.add(item_id)          # <-- isto acontece antes do filtro
...
if item['price'] <= tecto_preco and casa_filtro_titulo(...):
```

Um artigo acima do tecto fica registado como visto **para sempre**. Se amanhã baixar de preço
para dentro do tecto, **não há aviso** — já não é novo. E esperar que um anúncio desça é metade
do valor de um vigia de preços.

**Mínimo:** mover o `add` para depois da decisão.
**Melhor:** guardar `{id: preço}` em vez de só o id, e reavisar quando o preço descer — passas a
ter alertas de descida.

### 6.2 O ensaio não deve gravar estado

```python
save_seen_items(seen_items)
if args.once or args.ensaio:
    break
```

O `save` corre antes do `break`, por isso um `--ensaio` grava tudo o que viu: os artigos passam a
"vistos" sem nunca terem gerado aviso. E é precisamente quando se afinam regras que se ensaia
mais.

**Correcção:** `if not args.ensaio: save_seen_items(seen_items)`.

### 6.3 Estado por alvo, não partilhado

Com um `seen_items` único, alvos que se sobrepõem (`3080`, `3085`, `3090` apanham muitas vezes o
mesmo anúncio) roubam-se uns aos outros: o primeiro a ver consome-o para todos. Um ficheiro de
estado por termo evita isso.

### 6.4 Se mantiveres o daemon, põe-no num serviço

Com `@reboot ... &`, se o processo morrer — excepção não apanhada, OOM killer, um `kill`
distraído — não há quem o levante até ao próximo reinício da máquina, e nada o sinaliza. Um
serviço `systemd` com `Restart=always` resolve em cinco linhas e dá o `journalctl` por acréscimo.

---

Boa caçada.
