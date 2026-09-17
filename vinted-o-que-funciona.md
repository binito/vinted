# Vigia da Vinted — O Que Funciona & Estado do Sistema

**14–15 de Setembro de 2026.** Relatório de estado, funcionamento e regras operacionais do sistema de monitorização Vinted (`vinted_monitor.py`).

---

## 1. Métodos de Acesso & Leitura

O sistema opera com uma arquitetura de duas camadas para garantir resiliência e continuidade da monitorização:

### A. Método Primário: API Oficial do Catálogo (`/svc-catalogue/items`)
- **Endpoint:** `https://api.vinted.pt/svc-catalogue/items`
- **Cabeçalhos Obrigatórios:**
  - `X-Next-App: marketplace-web`
  - `X-Anon-Id: <extraído dinamicamente do cabeçalho de resposta da homepage>`
- **Comportamento:** Retorna até 60 artigos em formato JSON ordenados por `newest_first`.
- **Vantagem Principal:** Fornece o campo `total_item_price.amount` (preço do artigo + taxa de proteção ao comprador da Vinted).

### B. Método Secundário: Fallback para HTML do Catálogo (`/catalog`)
- **Endpoint:** `https://www.vinted.pt/catalog?search_text=<termo>&order=newest_first`
- **Ativação:** Acionado automaticamente se a API falhar ou devolver código HTTP diferente de 200.
- **Parsing:** Expressão regular para extração de URLs, IDs e títulos com atributos combinados.
- **Resiliência:** Validação de tamanho mínimo da resposta (>200 KB) para evitar falsos positivos por bloqueios ou captchas.

---

## 2. Parsing de Preços e Normalização Regional

Para evitar erros onde `45.00 €` é interpretado como `4500 €` devido à divergência de separadores decimais/milhares (, vs .):
- O separador decimal é sempre identificado como o **último símbolo (ponto ou vírgula)** presente na string.
- Os símbolos numéricos anteriores são limpos e o preço é convertido com precisão para `float`.

---

## 3. Lógica de Filtragem e Rastreio de Artigos (BD)

- **Filtro Avançado de Título:**
  - Suporta inclusões obrigatórias e exclusões (`+` e `-`), por exemplo: `optiplex+3070-aio-ecra-cabo-caddy`.
  - Tolerância de grafia (ex.: substituição interna `optiplex` / `optiflex`).
  - Suporte a acentuação e termos equivalentes em múltiplos idiomas (ex.: `peça`, `peca`, `câble`, `cabo`).

- **Ciclo de Vida do Rastreio de Preços (`seen_items.json`):**
  1. A marcação do artigo no dicionário de vistos **só ocorre após a avaliação completa dos critérios** de elegibilidade (teto de preço + filtro de título).
  2. Suporta **alertas de baixa de preço**: se um artigo visto anteriormente sofrer uma redução de valor e ficar abaixo do teto, um novo alerta de descida (`📉 BAIXA DE PREÇO`) é emitido.
  3. No modo `--ensaio`, o estado no disco não é modificado.

---

## 4. Integração de Notificações e Execução

- **Serviço de Alertas:** Integração direta com `ntfy` (`send_ntfy_notification`), incluindo cabeçalhos com hiperligação direta para o anúncio no Vinted.
- **Serviço de Sistema:** Configurado para execução persistente via `systemd` (`vinted-monitor.service`) com auto-restart ativado.

---

## 5. Resumo da Implementação no Código (`vinted_monitor.py`)

Todas as boas práticas e correções do documento de comparação foram integradas na versão v2.1 do `vinted_monitor.py`:
- [x] Atualização de estado diferida após verificação de regras.
- [x] Rastreio de histórico de preços por ID (`{id: ultimo_preco}`).
- [x] Proteção contra sobregravação de BD no modo `--ensaio`.
- [x] Distinção explícita no log entre API `/svc-catalogue` e Fallback HTML `/catalog`.
- [x] Verificação do tamanho da resposta HTML para mitigação de bloqueios silenciosos.
