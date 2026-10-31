"""Alvos com texto: quando o template não existe (ou não bate), o TOSCO procura o botão pelo texto via OCR,
em qualquer um destes idiomas. Ao achar, recorta e salva o template sozinho (auto-aprendizado).

Para um idioma novo basta acrescentar a palavra na lista — maiúsculas e acentos não importam.
"""

TEXT_TARGETS = {
    # diálogos gerais
    "btn_confirm": ["Confirmar", "Confirm", "Confirmer", "Bestätigen", "Conferma", "Подтвердить", "Onayla",
                    "Konfirmasi", "Xác nhận", "OK"],
    "btn_exit_cancel": ["Cancelar", "Cancel", "Annuler", "Abbrechen", "Annulla", "Отмена", "İptal", "Batal", "Hủy"],
    "btn_reconnect": ["Reconectar", "Reconnect", "Reconnecter", "Verbinden", "Riconnetti", "Переподключиться",
                      "Yeniden Bağlan", "Sambung Ulang", "Kết nối lại", "Tentar novamente", "Retry", "Reintentar"],
    "dlg_exit_game": ["Sair do jogo", "Exit the game", "Quit game", "Salir del juego", "Quitter le jeu",
                      "Spiel beenden", "Uscire dal gioco", "Выйти из игры", "Oyundan çık", "Keluar dari game",
                      "Thoát trò chơi"],
    "dlg_connection_lost": ["Conexão perdida", "Rede desconectada", "Erro de Rede", "Servidor desconectado",
                            "Connection lost", "Network error", "Conexión perdida",
                            "Connexion perdue", "Verbindung verloren", "Connessione persa", "Соединение потеряно",
                            "Bağlantı koptu", "Koneksi terputus", "Mất kết nối", "Desconectado", "Disconnected"],
    # navegação
    "btn_to_world": ["Mundo", "World", "Monde", "Welt", "Mondo", "Мир", "Dünya", "Dunia", "Thế giới"],
    "btn_to_base": ["Base", "Cidade", "City", "Ciudad", "Ville", "Stadt", "Città", "Город", "Şehir", "Kota", "Thành"],
    "btn_alliance": ["Aliança", "Alliance", "Alianza", "Allianz", "Alleanza", "Альянс", "İttifak", "Aliansi", "Liên minh"],
    "tab_alliance_war": ["Guerra", "War", "Guerre", "Krieg", "Война", "Savaş", "Perang", "Chiến tranh"],
    "btn_search": ["Buscar", "Search", "Rechercher", "Suchen", "Cerca", "Поиск", "Ara", "Cari", "Tìm kiếm"],
    "btn_go": ["Ir", "Go", "Aller", "Los", "Vai", "Перейти", "Git", "Pergi", "Đi"],
    # combate
    "btn_march": ["Marchar", "March", "Marcher", "Marsch", "Marcia", "Марш", "Yürü", "Berangkat", "Hành quân",
                  "Implantar", "Deploy"],
    "btn_attack": ["Atacar", "Attack", "Attaquer", "Angreifen", "Attacca", "Атаковать", "Saldır", "Serang", "Tấn công"],
    "btn_rally": ["Mobilizar", "Mobilização", "Reunir", "Rally", "Ralliement", "Sammeln", "Raduno", "Сбор", "Toplan", "Kumpul", "Tập hợp"],
    "btn_heal": ["Curar", "Heal", "Soigner", "Heilen", "Cura", "Лечить", "İyileştir", "Sembuhkan", "Chữa trị"],
    "btn_gather": ["Coletar", "Gather", "Recolectar", "Récolter", "Sammeln", "Raccogli", "Собрать", "Topla",
                   "Kumpulkan", "Thu thập"],
    # coleta / recompensas
    "btn_claim": ["Reivindicar", "Resgatar", "Receber", "Claim", "Reclamar", "Réclamer", "Abholen", "Riscatta", "Получить", "Al",
                  "Klaim", "Nhận"],
    "btn_claim_all": ["Reivindicar Tudo", "Receber tudo", "Coletar tudo", "Claim all", "Reclamar todo", "Tout réclamer", "Alle abholen",
                      "Riscatta tutto", "Получить все", "Tümünü al", "Klaim semua", "Nhận tất cả"],
    "btn_collect": ["Coletar", "Collect", "Recoger", "Collecter", "Einsammeln", "Raccogli", "Собрать", "Topla",
                    "Kumpulkan", "Thu thập"],
    "btn_donate": ["Doar", "Donate", "Donar", "Donner", "Spenden", "Dona", "Пожертвовать", "Bağış", "Donasi", "Quyên góp"],
    "btn_use": ["Usar", "Use", "Utiliser", "Benutzen", "Usa", "Использовать", "Kullan", "Gunakan", "Sử dụng"],
    "btn_dispatch": ["Enviar", "Despachar", "Mega Envio", "Dispatch", "Send", "Envoyer", "Senden", "Invia", "Отправить", "Gönder",
                     "Kirim", "Gửi"],
    "btn_depart": ["Partir", "Depart", "Go", "Abfahren", "Parti", "Отправиться", "Yola çık", "Berangkat", "Khởi hành"],
    "btn_quick_deploy": ["Implantação rápida", "Quick deploy", "Auto", "Despliegue rápido", "Déploiement rapide",
                         "Schnell", "Rapido", "Быстро", "Hızlı", "Cepat", "Nhanh"],
    "btn_challenge": ["Desafiar", "Challenge", "Défier", "Herausfordern", "Sfida", "Вызов", "Meydan oku", "Tantang",
                      "Thách đấu"],
    "btn_battle": ["Batalha", "Battle", "Batalla", "Combat", "Kampf", "Battaglia", "Бой", "Savaş", "Bertarung",
                   "Chiến đấu", "Lutar", "Fight"],
    "btn_skip": ["Pular", "Skip", "Saltar", "Passer", "Überspringen", "Salta", "Пропустить", "Atla", "Lewati", "Bỏ qua"],
    "btn_like": ["Curtir", "Like", "Me gusta", "J'aime", "Gefällt", "Mi piace", "Нравится", "Beğen", "Suka", "Thích"],
    "btn_appoint": ["Nomear", "Aprovar", "Appoint", "Approve", "Nombrar", "Aprobar", "Nommer", "Ernennen", "Nomina",
                    "Назначить", "Ata", "Tunjuk", "Bổ nhiệm"],
    "btn_help_all": ["Ajudar todos", "Help all", "Ayudar a todos", "Aider tous", "Allen helfen", "Aiuta tutti",
                     "Помочь всем", "Herkese yardım", "Bantu semua", "Giúp tất cả"],
    "btn_coord_go": ["Ir", "Go", "Aller", "Los", "Vai", "Перейти", "Git", "Pergi", "Đi"],
    "btn_join": ["Participar", "Ingressar", "Join", "Unirse", "Rejoindre", "Beitreten", "Partecipa", "Katıl"],
    "btn_greet": ["Cumprimentar", "Saudar", "Greet", "Saludar", "Saluer", "Begrüßen", "Saluta", "Приветствовать",
                  "Selamla", "Sapa", "Chào"],
    "btn_favorites": ["Favoritos", "Marcadores", "Favorites", "Bookmarks", "Favoritos", "Favoris", "Lesezeichen",
                      "Preferiti", "Избранное", "Favoriler", "Favorit", "Yêu thích"],
}

# Alvos que a IA (core/yolo.py) reconhece sozinha: nome no TOSCO -> classes do modelo, em ordem de preferência.
# Valor (classe, score mínimo) quando a classe pede um limiar diferente do padrão (0.5).
YOLO_TARGETS = {
    # navegação
    "btn_to_base": ["Base"], "btn_to_world": ["World"],
    "btn_back": ["Return", "return_btn"], "btn_close": ["close_btn"],
    "btn_confirm": ["confirm_popup", "share_confirm_btn"], "btn_exit_cancel": ["cancel_popup"],
    "btn_alliance": ["Alliance Tab"], "btn_search": ["glass_icon", "Search"], "btn_go": ["btn_go", "search_btn"],
    "coord_input": ["coord_input"], "btn_coord_go": ["coord_search_icon", "btn_go"],
    "btn_mail": ["Mail"], "btn_inventory": ["Inventory"], "btn_events": ["Event"], "btn_heroes": ["Heroes"],
    "btn_home": ["home_btn"], "tab_alliance_war": ["alliance_wars_btn"], "btn_rally_refresh": ["rally_refresh_btn"],
    # marcha
    "btn_march": ["march_icon"], "squad_1": ["team_1"], "squad_2": ["team_2"], "squad_3": ["team_3"],
    "squad_4": ["team_4"], "no_stamina": [("stamina_out", 0.5)], "stamina_bar": ["stamina_bar"],
    "btn_stamina_use": ["stamina_use_btn", "stamina_use_free"],
    # escavações / presentes
    "btn_chat": ["Chat"], "tab_chat_alliance": ["chat_ally"], "chat_input": ["chat_text", "chat_input"],
    "chat_dig": ["Chat Dig Up", "Chat Test Flight", "dig_chat2", "drone_chat"],
    "chat_egg": ["treasure_egg_chat", "treasure_gift_chat"],
    "dig_alert": ["Treasure alert"], "gift_alert": ["treasure_gift", "treasure_egg"],
    "dig_logo": ["dig_center", "flight_center", "Digging Logo", "Flight Logo"],
    "dig_help": ["Dig Help", "Flight Help"], "dig_timer_popup": ["Dig Up Tab", "Flight Test Tab"],
    "dig_timer": ["timer_text"], "dig_claim": [("dig_claim", 0.8)],
    "gift_popup_btn": ["treasure_gift_popup_btn"], "gift_reward": ["treasure_gift_popup_reward"],
    "fire_alert": ["fire_alert"], "fire_claim": ["fire_alert_claim"],
    # rally / combate
    "rally_alert": ["rally_alert_icon"], "btn_join_rally": ["rally_add_btn"], "rally_card": ["rally_card"],
    "btn_rally": ["rally_btn", "Rally Button"], "btn_attack": ["attack_btn"], "btn_battle": ["fight_btn"],
    "btn_challenge": ["challenge_btn"], "btn_heal": ["heal_btn"], "btn_hospital": ["Hospital"],
    # outros
    "btn_use": ["use_btn"], "btn_recruit": ["recruit_btn"], "btn_secret_squad": ["secret_task_icon"],
    "btn_dispatch": ["secret_deploy_btn"], "btn_quick_deploy": ["secret_quick_deploy_btn"],
    "btn_alliance_tech": ["alliance_tech_btn"], "tech_recommended": ["ally_tech_recommend"],
    "btn_donate": ["ally_tech_donate_btn"], "btn_alliance_help": ["Ally Help", "help_icon"],
    "btn_trucks": ["My Trucks"], "btn_plunder": ["plunder_btn"],
}

# Tela principal (base ou mapa) e o que, por cima dela, indica uma janela aberta (fonte: LWFarmBot utils.on_main).
MAIN_CLASSES = ("World", "Base", "Heroes")
OVERLAY_CLASSES = ("Return", "close_btn", "cancel_popup", "chat_ally", "chat_world", "chat_moment", "chat_private",
                   "chat_input", "screen_event", "info_popup", "confirm_popup", "share_popup")

# Prioridade das tarefas (menor = mais urgente). Uma tarefa urgente passa na frente das outras no ciclo e
# interrompe a fila quando o seu sinal aparece na tela (escavação, presente, fogos).
TASK_PRIORITY = {"auto_digs": 1, "resources": 3, "idle_rewards": 4, "auto_join": 5, "hunt": 6, "marshal_guard": 6,
                 "farm": 10, "alliance": 100}
URGENT_SIGNALS = {"auto_digs": ("dig_claim", "dig_alert", "gift_alert")}

# Botões cujo texto é só um rótulo embaixo do ícone (barra lateral do jogo): o toque e a imagem aprendida
# sobem esta fração da altura da tela, para pegar o ícone.
LABEL_UNDER_ICON = {"btn_alliance": 0.03, "btn_mail": 0.03, "btn_inventory": 0.03, "btn_events": 0.03}

# Temas da Corrida Armamentista: palavra-chave -> tema
ARMS_RACE_THEMES = {
    "city": ["Construção", "Building", "Construcción", "Bâtiment", "Gebäude", "Edifici", "Строительство", "İnşa"],
    "tech": ["Pesquisa", "Tecnologia", "Research", "Technology", "Investigación", "Recherche", "Forschung",
             "Ricerca", "Исследование", "Araştırma"],
    "units": ["Tropas", "Unidades", "Unit", "Troops", "Tropas", "Unités", "Einheiten", "Unità", "Войска", "Birlik"],
    "heroes": ["Herói", "Hero", "Héroe", "Héros", "Held", "Eroe", "Герой", "Kahraman"],
    "drone": ["Drone", "Dron", "Дрон"],
    "kill": ["Abate", "Inimigo", "Enemy", "Kill", "Enemigo", "Ennemi", "Feind", "Nemico", "Враг", "Düşman"],
}
