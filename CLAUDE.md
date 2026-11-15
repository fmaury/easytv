# EasyTV

« TV perso » sur Raspberry Pi 3 Model B branchée en HDMI sur une TV : chaque dossier est une chaîne, chaque
chaîne est une playlist de vidéos, on zappe depuis une page web sur téléphone et chaque chaîne reprend
là où on l'a laissée.

## Règles de comportement

1. **Chaînes** : chaque sous-dossier de `channels_dir` est une chaîne. Chaînes et vidéos sont triées
   par nom, en tri naturel insensible à la casse (`ep2` avant `ep10`) ; préfixer par `01 - `,
   `02 - `… pour fixer l'ordre. Les dossiers vides sont ignorés.
2. **En quittant une chaîne**, on enregistre : vidéo en cours, position, heure de départ.
3. **En revenant sur une chaîne** :
   - avant `resume_timeout` (1 h par défaut) → même vidéo, même position ;
   - après → même vidéo, depuis le début.
4. **Lecture continue** : fin de vidéo → suivante ; après la dernière → retour à la première.
5. **Dernière chaîne mémorisée** : au démarrage, la TV se rallume dessus (règle 3 appliquée).
   L'état est sauvegardé toutes les `save_interval` s (5 par défaut, 30 sur la Pi pour la carte SD)
   et à chaque zapping ; après une coupure, l'heure de départ est celle de la
   dernière sauvegarde.
6. **Contenu disparu** : vidéo mémorisée supprimée → la suivante dans l'ordre de tri ;
   chaîne supprimée → première chaîne.
7. **Vidéo illisible** → loguée et sautée, jamais de plantage. Si aucune vidéo de la chaîne n'est
   lisible → « Chaîne indisponible » (pas de boucle) ; nouvel essai si ses vidéos changent au rescan.
8. **Rescan** périodique des dossiers : ajouts et suppressions pris en compte sans redémarrage.

## Architecture

Processus Python unique, `asyncio`. Code dans `src/easytv/`, tests dans `tests/`.

| Module | Rôle | Pur ? |
|---|---|---|
| `config.py` | Lit `config.toml` → dataclass `Config` | oui |
| `library.py` | Scanne `channels_dir` → chaînes et vidéos triées | oui (testé avec `tmp_path`) |
| `state.py` | État (dernière chaîne ; par chaîne : vidéo, position, heure de départ ; volume, son coupé), sauvegarde JSON atomique | oui |
| `tuner.py` | Zapping, vidéo suivante, rebouclage, règle de reprise, contenu disparu, volume | **oui, cœur testé** |
| `banner.py` | Bandeau façon TV en ASS (numéro, nom sans préfixe, titre), jauge de volume, messages | oui |
| `player.py` | Pilote mpv via sa socket JSON IPC : charger, aller à, bandeau (`osd-overlay`), événements | non |
| `remote.py` | Commandes (`Action`, `Command`) ↔ `script-message` mpv | oui |
| `web.py` + `web.html` | Télécommande web pour téléphone : serveur HTTP `asyncio` (stdlib), `/api/status`, `/api/command` | non |
| `app.py` | Boucle principale : relie remote → tuner → player, sauvegarde et rescan périodiques | non |
| `__main__.py` | Point d'entrée `easytv` | non |

- La logique pure (`tuner`, `state`, `library`, `config`) ne dépend ni de mpv, ni des entrées, ni de
  l'horloge : **l'heure est passée en paramètre**.
- **Télécommande web** (`web_port` : 8080 par défaut, 80 sur la Pi grâce à
  `AmbientCapabilities=CAP_NET_BIND_SERVICE` dans le service ; 0 = désactivée) : les commandes reçues passent
  par `App.submit` → même file d'événements que le clavier (pas de concurrence avec mpv).
  `quit` n'est pas proposé ; `POST /api/command` exige `Content-Type: application/json` (bloque
  les requêtes venant d'autres sites).
- Option `input` de la config : `"keyboard"` (dev sur PC : mpv fenêtré, touches transmises par mpv
  via `script-message`) ou `"remote"` (Pi : mpv ignore le clavier, on zappe par la page web).

## Stack

- **Cible** : Raspberry Pi 3 Model B (1 Go de RAM), Raspberry Pi OS Lite 64 bits (sans bureau), service **systemd**.
- **Lecteur** : mpv plein écran en DRM (sans X/Wayland), décodage matériel H.264,
  bandeau de zapping via l'OSD mpv.
- **Télécommande** : la page web, sur les téléphones du Wi-Fi de la maison. Pas de télécommande
  physique, par choix : marche chez tout le monde, rien à acheter, plusieurs téléphones à la fois.
- **Config** : `config.toml` (écrit à la main, `tomllib`), non versionné → modèle `config.example.toml`.
- **État** : `state.json` (écrit par le programme), non versionné.
- **Ajout des vidéos** : SFTP (OpenSSH de la Pi), dans `/media/tv/<chaîne>/`.
- **Outils dev** : uv, ruff, mypy (strict), pytest.

## Contraintes matérielles

- Un seul port HDMI (taille normale), qui gère le CEC.
- TV **TCL 50P610** : CEC = « T-Link ». **Aucune touche transmise** à la Pi (voir feuille de route) ;
  CH+ change d'entrée HDMI. Elle affiche « HDMI1 », jamais le nom OSD.
  → zapping par la page web.
  Vérifier les touches reçues : `cec-ctl -d /dev/cec0 --playback -M`.
- Décodage matériel Pi 3 : **H.264 uniquement** (jusqu'à 1080p). Pas de HEVC matériel :
  HEVC, VP9, AV1 saccadent. Pas de conversion automatique dans l'app : vidéos fournies en H.264.
- **mpv sur la Pi : `--hwdec=v4l2m2m-copy`** (décodeur `bcm2835-codec`, image recopiée), `--vo=gpu`
  en DRM. **Ne pas utiliser `v4l2m2m` sans copie : écran noir.** mpv 0.40 n'a pas d'interop dmabuf
  sur la Pi 3 (« drmprime hwdec requires at least one dmabuf interop backend ») et se rabat sur un
  plan overlay DRM que vc4 refuse (« Failed to commit atomic request », errno 22) : image décodée,
  jamais affichée, alors que CPU, fps et images perdues semblent parfaits. Toujours vérifier
  l'absence de ce message (`request_log_messages` sur la socket) ou l'écran réel.
  Mesuré le 2026-11-14 sur un H.264 640×480 : `v4l2m2m-copy` 38 % CPU, 0 image perdue, image OK ;
  logiciel 59 %. 720p/1080p en `-copy` : à mesurer.
  `--vo=gpu-next` impossible (libplacebo exige OpenGL 3, la Pi 3 n'a que GLES 2).
  `--hwdec=auto` ne choisit pas v4l2m2m.
- **Son HDMI perdu** (câble débranché, testé le 2026-11-14) : mpv lit alors chaque vidéo **sans
  son** et la termine en `end-file` « error » (« audio output initialization failed »).
  `ao-reload` ne rétablit rien ; désélectionner puis resélectionner la piste (`aid`) si (mpv la
  désélectionne après un essai raté : retenir son numéro). Erreur vue : « Unknown error 524 »,
  noyau « ASoC error (-22) … i2s-hifi » : ce n'est pas PipeWire.
  → `check_audio` toutes les 10 s, et une vidéo qui a joué puis finit en erreur n'est pas
  « illisible ». Les erreurs de mpv sont recopiées dans le journal (`request_log_messages`).
- USB 2.0 uniquement ; système sur carte SD (le démarrage USB du 3 B demande une activation préalable).
- 1 Go de RAM, pas d'horloge matérielle (heure fausse au boot tant que NTP n'a pas synchronisé).

## Commandes

```bash
uv run easytv [--config config.toml] [--fullscreen] [--debug]   # lancer la TV
uv sync                      # dépendances
uv run pytest                # tests
uv run ruff format .         # mise en forme
uv run ruff check --fix .    # lint
uv run mypy                  # typage
```

Codes de sortie : 0 = quitté (q/Échap, Ctrl+C), 1 = mpv fermé tout seul ou introuvable
(systemd doit relancer), 2 = config invalide.

Touches en mode `input = "keyboard"` (définies dans `KEY_BINDINGS`, `player.py`) :
↑/↓ chaîne suivante/précédente, 1–9 aller à la chaîne, → vidéo suivante, i/Entrée infos,
`-`/`+` volume, m couper le son, s arrêter la vidéo, p la relancer, f plein écran, q/Échap quitter.

Arrêt (`stop`/`play`, idempotents pour plusieurs téléphones) : compte comme quitter la chaîne
(règle 3 au retour) ; zapper ou « vidéo suivante » relance la lecture ; pendant l'arrêt, le rescan
ne lance rien. Non mémorisé : au redémarrage, la TV rejoue.

Volume : celui de mpv (0–100, pas de 5), indépendant de celui de la TV ; changer le volume remet le
son. Jauge et bandeau sont sur deux calques mpv distincts (`Layer`, `player.py`).

`tests/test_player.py` lance le vrai mpv (`--vo=null`) ; il est ignoré si mpv ou ffmpeg manquent.
Pour un essai réel piloté par Claude : `input = "remote"` (la fenêtre ignore le clavier) et envoyer
des `script-message easytv <action>` sur la socket `/tmp/easytv-*/mpv.sock`.

**Une tâche n'est finie que si** `ruff format --check`, `ruff check`, `mypy` et `pytest` passent.

## Conventions de code

- Python ≥ 3.11, syntaxe moderne : `dataclass`, `enum`, `pathlib`, `X | None`.
- Code, identifiants, commentaires, commits en anglais ; docs utilisateur en français.
- Tout est typé (mypy strict). Format et lint par ruff (config dans `pyproject.toml`) ;
  un hook (`.claude/hooks/ruff.sh`) lance ruff après chaque modification de fichier `.py`.
- Logique pure séparée des effets (mpv, entrées, disque, horloge), effets derrière de petites interfaces.
- `logging`, jamais `print`. Jamais d'`except` muet.
- Toute nouvelle logique arrive avec ses tests ; les tests ne nécessitent ni Pi ni TV.
- Commentaires seulement là où le code n'est pas évident. Petits commits ciblés.

## Installation sur la Pi

- `install.sh` (idempotent, = commande de mise à jour après `git pull`) : paquets apt (mpv, git,
  curl, v4l-utils), uv, `uv sync --no-dev --frozen`, `config.toml` depuis `config.example.toml`
  (jamais écrasé ; son HDMI détecté : `vc4hdmi` sur Pi 3, `vc4hdmi0` sur Pi 4), `/media/tv`,
  service systemd, démarrage sans bureau (`multi-user.target`).
- `deploy/easytv.service` : modèle (`@USER@`, `@DIR@`), `Restart=always`, `StateDirectory=easytv`,
  attente NTP (60 s max) avant le lancement.
  systemd arrête le service par SIGTERM : géré comme Ctrl+C (sauvegarde finale de la position).
- `config.example.toml` est le modèle **Pi** : `mpv_args` (`--gpu-context=drm`, `--hwdec=v4l2m2m-copy`,
  `--ao=alsa` + périphérique HDMI : le service tourne hors session, sans PipeWire), `save_interval = 30`.
- Relancer EasyTV sans sudo : envoyer `script-message easytv quit` sur la socket
  `/tmp/easytv-*/mpv.sock` → systemd le relance (le code est installé en mode éditable : un
  `git pull` suffit pour le code Python).
- Capture de l'écran de la TV : `screenshot-to-file` sur la même socket (le fichier est écrit
  en différé : attendre ~2 s).
- `README.md` : guide utilisateur en français (carte SD → SSH → `install.sh` → vidéos par SFTP).

## Travail sur la Pi

Toute commande sur la Pi (SSH, `sudo`, systemd, paquets) est annoncée et validée par l'utilisateur
avant exécution. Les procédures récurrentes deviennent des skills dans `.claude/skills/`
(`/pi-setup`, `/deploy-pi`, `/cec-test`) une fois faites avec succès une première fois.

## Feuille de route

0. Socle : CLAUDE.md, pyproject, outils ✅
1. Logique pure + tests (config, library, state, tuner) ✅
2. Lecteur mpv + clavier → TV fonctionnelle sur PC ✅
3. Robustesse : vidéos illisibles (anti-boucle), logs, bandeau soigné ✅
4. Installation sur la Pi : `install.sh`, service systemd, README ✅
5. Télécommande : page web sur téléphone, avec volume ✅
   - CEC : **la TCL 50P610 ne transmet aucune touche** (testé le 2026-11-14 : Pi seule sur le bus,
     CEC 1.4, identifiant fabricant TCL, type tuner → rien ; la TV demande seulement le nom OSD).
     Elle sait en revanche basculer sur l'entrée de la Pi (`active-source`).
   - Télécommande physique (infrarouge GPIO ou USB via `evdev`) : **écartée** le 2026-11-14,
     la page web suffit.
6. Bonus : effet neige, liste des chaînes sur OK, Samba

Mettre à jour la phase en cours à chaque étape terminée.
