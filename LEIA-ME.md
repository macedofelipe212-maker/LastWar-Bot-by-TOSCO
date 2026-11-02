# TOSCO // BOT Last War: Survival Game

Bot para **Last War: Survival** escrito do zero em Python, com interface em português no estilo HUD.
Roda no **jogo oficial de PC** ou em **emulador Android** (BlueStacks, MuMu, LDPlayer… via ADB, em segundo plano).

O TOSCO **só olha a tela e toca**, como uma pessoa: não lê a memória do jogo, não mexe na rede e não altera
nenhum arquivo do jogo.

![Painel do TOSCO](imagens/painel.png)

---

## O que ele faz

| Grupo | Módulos |
|---|---|
| **Foco do bot** (roda sem parar, escolha um em 🎯) | **Escavações & Ovos** — escavações, drone, ovos, festas, fogos e presentes da aliança · **Zumbis Dourados & Rally** — caça, inicia e entra em mobilizações com um orçamento de energia · **Auto-Entrar em Rallies** — cada esquadrão com sua faixa de nível e posição na mobilização, listas de jogadores |
| **Tarefas extras** (entram entre as rodadas) | Tarefas Diárias (loja, passes, trem, VIP, correio, energia grátis, baús) · Recursos (e buff do Ministro) · Hospital, Treino & Pesquisa · Heróis (só recrutamento grátis) · Aliança (ajuda, presentes, tecnologia, Estrela) · Missões Secretas (envio por raridade, Mega, aliados, Tesouro) · Caminhões · Coleta no Mapa · Arena · Corrida Armamentista · Guarda do Marechal · Primeira-Dama |
| **Ferramentas** | Relatórios R4/R5 agendados (Excel, Texto, CSV) · **Scanner de mapa** com X/Y real e botão **IR** · Clique automático · Rotinas · **Estúdio visual (IA)** · **Estúdio de imagens** · 🩺 Teste de calibração · 📦 Pacote de diagnóstico |
| **Configuração** | Escudo automático · Agenda (com horário aleatório e Evento Zumbis Dourados) · Controle pelo celular (Telegram) · Pausa quando você mexe no PC · Registro de tudo |

Cada módulo tem dias da semana e horário próprios.

![Escavações & Ovos](imagens/escavacao.png)

![Auto-Entrar em Rallies](imagens/mobilizacoes.png)

---

## Como ele enxerga o jogo

Para cada botão, o TOSCO tenta nesta ordem: **imagem sua → IA → texto na tela (OCR)**.

- **IA de reconhecimento** — um modelo incluído reconhece sozinho **295 tipos de botões e ícones** do jogo
  (Base/Mundo, chat, escavações, cronômetro, presente, alerta de rally, esquadrões, Marchar, X de fechar…), em
  qualquer resolução e idioma. Você **não precisa capturar nada** para começar.
- **Números e cronômetros** — lidos pelo **RapidOCR** (~11 ms por cronômetro). O OCR do Windows não lê a fonte
  dos cronômetros do jogo; o Tesseract fica como reserva.
- **Botões com texto** (Confirmar, Reivindicar Tudo, Participar, Marchar…) — achados pelo texto, com as palavras
  **exatas que o jogo usa em português**, e salvos como imagem para ficar mais rápido.
- **Qualquer tamanho de janela** — a interface do jogo cresce pela **altura** da janela; o TOSCO escala as
  imagens do mesmo jeito, então funciona em janela larga ou estreita.

### Estúdio visual (IA)

Mostra, com **miniatura e nome em português**, cada uma das coisas que a IA reconhece, agrupadas por assunto
(Tesouro, Bate-papo, Comuns, Esquadrões, Recuperação, Aliança, Presente da Sorte, Arena, Posto Secreto…).

- **⟳ O QUE A IA VÊ AGORA** tira um print do jogo e marca em cada cartão o que foi visto:
  verde = reconhecido e usado · laranja = visto, mas fraco demais (ignorado).
- A **barrinha** de cada cartão é a confiança: para a esquerda se o bot **não acha** aquilo na tela; para a
  direita se ele **clica no lugar errado**. **Redefinir** volta ao padrão.
- **Clique na foto** para ampliá-la ao lado de como aquilo está **no seu jogo agora**, e trocar a foto de
  exemplo pelo recorte do seu jogo — o recorte também vira a imagem do Estúdio de imagens.

- **👁 Ver o que a IA vê** (barra de cima) liga uma janelinha que se atualiza a cada segundo com o que a IA
  está reconhecendo — com o bot rodando, é o mesmo print que ele acabou de olhar.

![Estúdio visual (IA)](imagens/estudio-visual.png)

### Scanner de mapa

Varre uma área em volta da sua cidade (ou de um X/Y escolhido): pula uma vez pela lupa do jogo, mede a escala e
varre **arrastando** o mapa, gravando o **X/Y real** de missões secretas, caminhões, chefes e recursos. O **IR**
leva direto até o item. A lista é acumulativa (some o que não é visto há horas). Pode também **compartilhar e
coletar** as tarefas secretas do mapa com os critérios que você escolher.

![Scanner de mapa](imagens/radar.png)

### Estúdio de imagens

Para as suas próprias imagens, em 4 passos: **1** capturar o jogo, salvar o print ou abrir uma imagem ·
**2** recortar arrastando o mouse ou pelos números (X, Y, largura, altura) · **3** salvar, como variante ou
importando imagens prontas · **4** testar na imagem. Os nomes que a IA já conhece aparecem com a miniatura do
jogo e o botão **◉ IA** abre o mesmo item no Estúdio visual. **F8** captura direto do jogo com o mouse em cima.

![Estúdio de imagens](imagens/estudio-imagens.png)

---

## Proteção da sua conta

- **Nunca toca perto de compra**: antes de cada toque ele lê a área em volta e bloqueia "Comprar", preços
  (R$, $, €), "Finalizar agora", "Acelerar instantaneamente com Diamantes", "Usar N diamantes",
  "Teleportar" e "Excluir tudo".
- **Pausa quando você mexe no PC** — o mouse é o mesmo; ele solta o controle e volta depois de 20 s parado.
- **Tempo máximo por tarefa** — se uma tarefa trava, ele interrompe e volta à tela principal.
- **Reconhece telas** (carregando, manutenção, conexão perdida, conta aberta no celular, sair do jogo…) e espera
  em vez de tocar; conta aberta no celular → reconecta depois de 10 min.
- **Recuperação** — volta à tela principal sozinho; se travar várias vezes seguidas, reinicia o jogo.
- Ignora a faixa do chat da tela principal (tocar ali abria o chat por engano).

---

## Começo rápido

1. Baixe ou compile o `TOSCO.exe` e deixe ao lado dele a pasta `data` (com `data\modelos` e `data\miniaturas`).
2. Abra o jogo. No TOSCO, em **Configurações**, confira a janela do jogo (padrão `Last War-Survival Game`).
   Para emulador, escolha *Emulador Android (ADB)* e clique em *detectar*.
3. Ligue os módulos que quiser e clique em **INICIAR**.

Atalhos: Iniciar `Alt+S` · Pausar `Alt+P` · Retomar `Alt+R` · Parar `Alt+Q` · Clique automático `Alt+C` ·
Captura rápida `F8`.

![Configurações](imagens/configuracoes.png)

### Telegram (controle pelo celular)

No Telegram, fale com `@BotFather` → `/newbot` → copie o token para **Controle pelo celular**. Mande "oi" para o
seu bot e clique em *descobrir meu chat ID*. Comandos: `/status` `/print` `/iniciar` `/parar` `/pausar`
`/retomar` `/log` `/modulos` `/ligar <id>` `/desligar <id>` `/agora <id>` `/clicker`.
Com o aviso de escavações ligado, ele manda o **print da recompensa** de cada escavação.

---

## Rodar pelo código-fonte

Precisa de **Windows 10/11** e **Python 3.12**.

```bash
python -m pip install --user -r requirements.txt
```

```bash
python main.py
```

Para gerar o executável, rode `build.bat`: ele instala as dependências, baixa os modelos do RapidOCR e cria
`dist\TOSCO.exe` (um arquivo só).

O Tesseract é opcional (reserva para números): `winget install UB-Mannheim.TesseractOCR`.

### Pastas

| Pasta | O que tem |
|---|---|
| `tosco/core` | motor, agendador, visão (imagens, IA, OCR), reconhecimento de telas, proteção dos toques |
| `tosco/tasks` | os módulos (escavação, rally, diárias…) |
| `tosco/ui` | a interface (painel, estúdios, páginas dos módulos) |
| `data/modelos` | modelo da IA (`lw_preciso.onnx` e `lw_rapido.onnx`) |
| `data/miniaturas` | fotos de exemplo do Estúdio visual |
| `data/templates` | imagens capturadas por você |

As configurações, o token do Telegram, os logs e os relatórios ficam em `data` no seu PC e **não** vão para o
repositório.

---

Automação pode violar os termos de uso do jogo; use por sua conta e risco.
