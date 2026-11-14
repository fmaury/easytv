# EasyTV

« TV perso » sur Raspberry Pi 3 Model B branchée en HDMI sur une TV : chaque dossier est une chaîne, chaque
chaîne est une playlist de vidéos, on zappe avec la télécommande de la TV et chaque chaîne reprend
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
   L'état est sauvegardé toutes les 5 s ; après une coupure, l'heure de départ est celle de la
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
| `state.py` | État (dernière chaîne ; par chaîne : vidéo, position, heure de départ), sauvegarde JSON atomique | oui |
| `tuner.py` | Zapping, vidéo suivante, rebouclage, règle de reprise, contenu disparu | **oui, cœur testé** |
| `banner.py` | Bandeau façon TV en ASS (numéro, nom sans préfixe, titre) et messages | oui |
| `player.py` | Pilote mpv via sa socket JSON IPC : charger, aller à, bandeau (`osd-overlay`), événements | non |
| `remote.py` | Lit les touches via `evdev` (CEC, télécommande USB, clavier) → actions | non |
| `app.py` | Boucle principale : relie remote → tuner → player, sauvegarde et rescan périodiques | non |
| `__main__.py` | Point d'entrée `easytv` | non |

- La logique pure (`tuner`, `state`, `library`, `config`) ne dépend ni de mpv, ni des entrées, ni de
  l'horloge : **l'heure est passée en paramètre**.
- Option `input` de la config : `"keyboard"` (dev sur PC : mpv fenêtré, touches transmises par mpv
  via `script-message`) ou `"remote"` (Pi : télécommande CEC/USB lue avec `evdev`).

## Stack

- **Cible** : Raspberry Pi 3 Model B (1 Go de RAM), Raspberry Pi OS Lite 64 bits (sans bureau), service **systemd**.
- **Lecteur** : mpv plein écran en DRM (sans X/Wayland), décodage matériel H.264,
  bandeau de zapping via l'OSD mpv.
- **Télécommande** : HDMI-CEC via le pilote noyau (`/dev/cec0`), touches exposées comme
  périphérique d'entrée et lues avec `evdev`.
- **Config** : `config.toml` (écrit à la main, `tomllib`), non versionné → modèle `config.example.toml`.
- **État** : `state.json` (écrit par le programme), non versionné.
- **Ajout des vidéos** : SFTP (OpenSSH de la Pi), dans `/media/tv/<chaîne>/`.
- **Outils dev** : uv, ruff, mypy (strict), pytest.

## Contraintes matérielles

- Un seul port HDMI (taille normale), qui gère le CEC.
- TV **TCL** : CEC = « T-Link » / « Contrôle HDMI ». Flèches, OK, Retour normalement transmis ;
  CH+/CH− et chiffres souvent non → zapping principal sur ↑/↓.
  Vérifier les touches reçues : `cec-ctl -d /dev/cec0 --playback -M`.
- Décodage matériel Pi 3 : **H.264 uniquement** (jusqu'à 1080p). Pas de HEVC matériel :
  HEVC, VP9, AV1 saccadent. Pas de conversion automatique dans l'app : vidéos fournies en H.264.
- **mpv sur la Pi : `--hwdec=v4l2m2m`** (décodeur `bcm2835-codec`, sans copie), `--vo=gpu` en DRM
  (bureau arrêté). Mesuré le 2026-11-14 sur la Pi 3 B : 720p → 19 % CPU, 1080p 6 Mbit/s → 23 % CPU,
  0 image perdue. À éviter : `v4l2m2m-copy` (images perdues), décodage logiciel (82 % CPU en 720p) ;
  `--hwdec=auto` ne choisit pas v4l2m2m.
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
f plein écran, q/Échap quitter.

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

## Travail sur la Pi

Toute commande sur la Pi (SSH, `sudo`, systemd, paquets) est annoncée et validée par l'utilisateur
avant exécution. Les procédures récurrentes deviennent des skills dans `.claude/skills/`
(`/pi-setup`, `/deploy-pi`, `/cec-test`) une fois faites avec succès une première fois.

## Feuille de route

0. Socle : CLAUDE.md, pyproject, outils ✅
1. Logique pure + tests (config, library, state, tuner) ✅
2. Lecteur mpv + clavier → TV fonctionnelle sur PC ✅
3. Robustesse : vidéos illisibles (anti-boucle), logs, bandeau soigné ✅
4. Installation sur la Pi (OS, mpv DRM, systemd, SFTP) + skills `/pi-setup`, `/deploy-pi` ← **en cours**
5. CEC avec la TV TCL + skill `/cec-test`
6. Bonus : effet neige, liste des chaînes sur OK, page web de télécommande, Samba

Mettre à jour la phase en cours à chaque étape terminée.
