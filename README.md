# Vinted + Wallapop Radar

Monitor de anúncios Vinted e Wallapop para Raspberry Pi. Pesquisa alvos configuráveis nos dois mercados, filtra resultados, envia alertas para ntfy e disponibiliza um painel local para gerir preços e pesquisas pelo telemóvel.

## Funcionalidades

- Pesquisa periódica na API do catálogo Vinted, com fallback para HTML.
- Pesquisa adicional no endpoint JSON interno usado pelo site Wallapop.
- Filtros por preço final (inclui taxa Vinted), título e exclusões.
- Alertas ntfy para anúncios novos e baixas de preço, com link direto e botão para terminar a busca associada.
- Resumo diário das pesquisas ativas.
- Painel web móvel para adicionar pesquisas, editar o teto de preço ou eliminar buscas.
- Persistência em MariaDB para anúncios vistos, histórico de alertas e eventos de saúde.
- Serviço `systemd` com reinício automático.

Nota: o Wallapop não disponibiliza atualmente uma API pública/documentada. A integração usa o endpoint JSON público que o próprio site utiliza para a pesquisa; por isso, poderá precisar de manutenção se o Wallapop alterar esse endpoint. O estado dos anúncios Wallapop é guardado com o prefixo `wallapop:` para não colidir com IDs Vinted.

## Requisitos

- Linux / Raspberry Pi com Python 3.11+
- MariaDB acessível
- Uma instalação de [ntfy](https://ntfy.sh/) ou um tópico ntfy

## Configuração

As pesquisas ficam em `vigiar-vinted.conf`:

```ini
# <pesquisa> | <preço máximo em EUR> | <filtro de título>
dell optiplex 3070 | 95 | optiplex+3070-aio-monitor-cabo-pecas
```

No filtro, `+` exige uma palavra e `-` exclui uma palavra. Por exemplo, `optiplex+3070-aio` exige “optiplex” e “3070”, mas rejeita anúncios com “aio”.

As credenciais MariaDB não pertencem ao repositório. Crie `.env` com a referência segura às credenciais existentes:

```ini
VINTED_DB_CREDENTIALS_FILE=/caminho/seguro/para/.env
VINTED_DB_NAME=cafemartins
```

O ficheiro referenciado deve definir `DB_HOST`, `DB_USER` e `DB_PASS` (ou `DB_PASSWORD`).

## Instalação

```bash
python3 -m venv venv
venv/bin/pip install curl-cffi mysql-connector-python
```

Instale os serviços:

```bash
sudo install -m 644 vinted-monitor.service /etc/systemd/system/
sudo install -m 644 vinted-config-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vinted-monitor vinted-config-web
```

O serviço do monitor deve receber o tópico ntfy no `ExecStart` de `vinted-monitor.service`.

## Painel móvel

Por predefinição, o painel está em:

```text
http://192.168.1.176:8765/
```

Altere `CONFIG_VIEW_URL` em `vinted_monitor.py` se o IP do Raspberry mudar. O painel permite adicionar uma pesquisa (termo, preço máximo e regra de título), ajustar o teto ou eliminar uma busca; as alterações são lidas pelo monitor na ronda seguinte.

## Operação

```bash
# Executar uma ronda
venv/bin/python vinted_monitor.py --topic <topico> --once

# Simular sem enviar alertas nem alterar estado
venv/bin/python vinted_monitor.py --topic <topico> --ensaio

# Executar só com Vinted, caso seja necessário desativar a pesquisa Wallapop
venv/bin/python vinted_monitor.py --topic <topico> --once --sem-wallapop

# Enviar o resumo de alvos manualmente
venv/bin/python vinted_monitor.py --topic <topico> --relatorio

# Alterar um preço por terminal
venv/bin/python vinted_monitor.py --topic <topico> --set-price "dell optiplex 3070" 100

# Consultar serviços e logs
sudo systemctl status vinted-monitor vinted-config-web
journalctl -u vinted-monitor -f
```

## Testes

```bash
venv/bin/python -m unittest -v
```

## Dados gerados localmente

Não devem ser versionados: `.env`, `seen_items.json`, `.daily_report_state.json`, cookies, logs e `venv/`. Estes ficheiros já estão no `.gitignore`.
