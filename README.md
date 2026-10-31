# TOSCO // BOT Last War Ops

Bot para Last War: Survival escrito do zero, com interface HUD futurista.
Roda no jogo oficial de PC ou em emulador Android (ADB, em segundo plano).

## Começo rápido

1. Abra `TOSCO.exe` (ou `run.bat` se estiver usando o código-fonte).
2. **SISTEMA**: confira a janela do jogo (padrão `Last War-Survival Game`). Para emulador, escolha
   "Emulador Android (ADB)", clique em *detectar* e escolha o emulador.
3. **MÓDULOS**: ligue o que quiser. A barra IMAGENS mostra quantos elementos o TOSCO já reconhece.
4. **INICIAR** (Alt+S) · PAUSAR (Alt+P) · RETOMAR (Alt+R) · PARAR (Alt+Q) · Clicker (Alt+C) · Captura (F8).

## Como o TOSCO "enxerga" o jogo

Ordem de busca de cada botão: **sua imagem capturada → IA → texto (OCR)**.

- **IA de reconhecimento** (`data\modelos\lw_rapido.onnx` e `lw_preciso.onnx`, reconhece ~295 botões e ícones (Base/Mundo, chat, escavações, cronômetro, presente,
  rally, '+' de vaga, esquadrões, marchar, X de fechar…) em qualquer resolução e idioma, sem capturar nada.
  Liga/desliga e escolhe rápido/preciso em SISTEMA › Visão. Sem a pasta `modelos`, o TOSCO segue sem IA.
- **Cronômetros e números** (escavação, vigor, níveis): lidos pelo **Tesseract** (o OCR do Windows não lê a fonte
  do jogo). Instale uma vez: `winget install UB-Mannheim.TesseractOCR` — ou copie a pasta `Tesseract-OCR` para
  `TOSCO\tesseract\`. Sem ele, o TOSCO usa o OCR do Windows (pior nos números).
- **Botões com texto** (Confirmar, Mundo, Aliança, Coletar, Marchar…): acha **sozinho** lendo a tela com o
  OCR do Windows, em vários idiomas, e salva a imagem para ficar mais rápido (auto-aprendizado). ◐ no Estúdio.
- **Ícones sem texto** (bolha de comida, ícone de escavação no chat, chefes, ícones do mapa): precisam ser
  capturados **uma vez**. Jeito mais rápido: no ESTÚDIO escolha o nome, ponha o mouse em cima do ícone no
  jogo e aperte **F8**. Ou CAPTURAR JOGO e arrastar um retângulo. Use **+ VARIANTE** para outro idioma/tema.
- Qualquer resolução: as imagens são reescaladas para o tamanho atual da janela.

## Páginas

- **PAINEL**: radar de estado, contadores do dia, visão ao vivo do jogo, fila de módulos.
- **MÓDULOS**: Escavações & Ovos, Recursos, Aliança, Diárias (loja/trem/VIP/correio/baús), Esquadrão
  Secreto, Caminhões, Coleta no Mapa, Arena & 3v3, Auto-Entrar em Rallies (14 chefes), Zumbis Dourados &
  Rally (sobe de nível), Guarda do Marechal, Corrida Armamentista, Primeira-Dama/Cargos, Relatórios R4/R5
  (CSV/Excel), Scanner de Mapa, Escudo e 3 Rotinas personalizadas. Cada um com dias e horário próprios.
- **MAPA**: varre o servidor, lista o que achou com coordenadas, filtros, fixar ★, ocultar ✕, copiar e **IR**.
  Clique em CALIBRAR uma vez (ele mede a escala do mapa sozinho).
- **AGENDA**: liga/desliga o bot, abre/fecha o jogo ou roda um módulo no dia e hora escolhidos.
- **CLICKER**, **ESTÚDIO**, **SISTEMA** (OCR, comportamento humano, Telegram, idioma, tamanho, iniciar com o
  Windows), **REGISTRO**.

## Telegram (controle pelo celular)

No Telegram fale com @BotFather → /newbot → copie o token para SISTEMA. Mande "oi" ao seu bot e clique em
*descobrir meu chat ID*. Comandos: /status /print /iniciar /parar /pausar /retomar /log /modulos
/ligar <id> /desligar <id> /agora <id> /clicker.

## Gerar o .exe

`build.bat` → `dist\TOSCO.exe`. Os dados (configuração, imagens, logs, relatórios) ficam na pasta `data`
ao lado do executável.

Automação pode violar os termos de uso do jogo; use por sua conta e risco.
