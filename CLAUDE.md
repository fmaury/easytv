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
9. **Éteindre** (`stop`/`play`, idempotents pour plusieurs téléphones) : compte comme quitter la
   chaîne (règle 3 au retour) ; zapper ou changer de vidéo rallume ; pendant l'arrêt, le rescan ne
   lance rien ; non mémorisé (au redémarrage, la TV rejoue). `bedtime` éteint chaque jour à heure
   fixe (vérifié toutes les 15 s ; un saut d'horloge de plus de 5 min, NTP au boot, n'éteint rien).
10. **Volume** : celui de mpv (0–100, pas de 5), indépendant de la TV ; le changer remet le son.

## Architecture

Processus Python unique, `asyncio`. Code dans `src/easytv/`, tests dans `tests/`.

| Module | Rôle | Pur ? |
|---|---|---|
| `config.py` | Lit `config.toml` → dataclass `Config` | oui |
| `library.py` | Scanne `channels_dir` → chaînes et vidéos triées | oui (testé avec `tmp_path`) |
| `state.py` | État (dernière chaîne ; par chaîne : vidéo, position, heure de départ ; volume, son coupé), sauvegarde JSON atomique | oui |
| `tuner.py` | Zapping, vidéo suivante, rebouclage, règle de reprise, contenu disparu, volume | **oui, cœur testé** |
| `banner.py` | Bandeau façon TV en ASS (numéro, nom sans préfixe, titre), jauge de volume, messages, écran « dodo » (visage dessiné : pas de police emoji sur la Pi) | oui |
| `bedtime.py` | Heure du coucher atteinte entre deux vérifications (ignore les sauts d'horloge) | oui |
| `player.py` | Pilote mpv via sa socket JSON IPC : charger, aller à, bandeau et jauge (deux calques `Layer`), événements | non |
| `remote.py` | Commandes (`Action`, `Command`) ↔ `script-message` mpv | oui |
| `web.py` + `web.html` | Télécommande web pour téléphone : serveur HTTP `asyncio` (stdlib), `/api/status`, `/api/command` | non |
| `app.py` | Boucle principale : relie remote → tuner → player, sauvegarde et rescan périodiques | non |
| `ctl.py` | Outil de debug : `python -m easytv.ctl get`/`cmd` sur la socket mpv d'une TV en marche | non |
| `__main__.py` | Point d'entrée `easytv` | non |

- La logique pure (`tuner`, `state`, `library`, `config`) ne dépend ni de mpv, ni des entrées, ni de
  l'horloge : **l'heure est passée en paramètre**.
- **Télécommande web** (`web_port` : 8080 par défaut, 80 sur la Pi ; 0 = désactivée) : les
  commandes passent par `App.submit` → même file d'événements que le clavier (pas de concurrence
  avec mpv). `quit` n'est pas proposé ; `POST /api/command` exige `Content-Type: application/json`
  (bloque les requêtes venant d'autres sites).
- Option `input` : `"keyboard"` (dev sur PC : mpv fenêtré, touches de `KEY_BINDINGS` dans
  `player.py`) ou `"remote"` (Pi : mpv ignore le clavier, on zappe par la page web).

## Stack

- **Cible** : Raspberry Pi 3 Model B (1 Go), Raspberry Pi OS Lite 64 bits sans bureau, service systemd.
  Contraintes matérielles et installation : `.claude/rules/pi.md`.
- **Lecteur** : mpv plein écran en DRM, décodage matériel H.264, bandeau via l'OSD mpv.
- **Télécommande** : la page web, sur les téléphones du Wi-Fi de la maison.
- **Config** : `config.toml` (écrit à la main, `tomllib`), non versionné → modèle `config.example.toml`.
  **État** : `state.json` (écrit par le programme), non versionné.
- **Ajout des vidéos** : SFTP (OpenSSH de la Pi), dans `/media/tv/<chaîne>/`.
- **Outils dev** : uv, ruff, mypy (strict), pytest.

## Commandes

```bash
uv run easytv [--config config.toml] [--fullscreen] [--debug]   # lancer la TV
uv sync                      # dépendances
git config core.hooksPath .githooks   # une fois par clone : active le pre-commit
uv run pytest                # tests
uv run ruff format .         # mise en forme
uv run ruff check --fix .    # lint
uv run mypy                  # typage
uv run python -m easytv.ctl get path time-pos             # interroger la TV en marche
uv run python -m easytv.ctl cmd script-message easytv next_channel   # la piloter (actions : remote.py)
```

Codes de sortie : 0 = quitté (q/Échap, Ctrl+C, SIGTERM), 1 = mpv fermé tout seul ou introuvable
(systemd doit relancer), 2 = config invalide.

`tests/test_player.py` lance le vrai mpv (`--vo=null`) ; `tests/test_e2e.py` lance un vrai EasyTV et
appuie sur chaque bouton de la télécommande par l'API, effet vérifié sur mpv. mpv et ffmpeg
(génération des clips de test) sont obligatoires pour les tests.
Essai réel piloté par Claude : config avec `input = "remote"` (et `--vo=null` sans écran), puis
`easytv.ctl`.
**Page (`web.html`, `web.py`) ou bandeau (`banner.py`) modifié → lancer l'agent `remote-tester`**
(vrai navigateur en taille téléphone, chaque bouton vérifié sur mpv, la page et l'écran de la TV ;
lanceur local : `.claude/scripts/remote-test.sh`).

**Une tâche n'est finie que si** `ruff format --check`, `ruff check`, `mypy` et `pytest` passent.
Le pre-commit (`.githooks/pre-commit`) les relance à chaque commit et refuse le commit en cas d'échec.

## Conventions de code

- Python ≥ 3.11, syntaxe moderne : `dataclass`, `enum`, `pathlib`, `X | None`.
- Code, identifiants, commentaires, commits en anglais ; docs utilisateur en français.
- Tout est typé (mypy strict). Format et lint par ruff (config dans `pyproject.toml`).
  Hooks : ruff après chaque modification de `.py` (`.claude/hooks/ruff.sh`) ; ruff + mypy avant de
  rendre la main si du Python a changé (`.claude/hooks/check.sh`). Modifier les hooks ou les
  réglages demande la validation de l'utilisateur.
- Logique pure séparée des effets (mpv, entrées, disque, horloge), effets derrière de petites interfaces.
- `logging`, jamais `print`. Jamais d'`except` muet.
- Toute nouvelle logique arrive avec ses tests ; les tests ne nécessitent ni Pi ni TV.
- **Tests protégés** : un test qui échoue se corrige dans le code, jamais dans le test. Sans accord
  explicite de l'utilisateur, interdit de modifier ou d'affaiblir un test existant (assert retiré,
  tolérance élargie, `skip`, `xfail`) ou de le supprimer. Seule exception : un changement de
  comportement demandé par l'utilisateur ; dire alors quels tests changent et pourquoi.
  Le pre-commit refuse un test supprimé ou un `skip`/`xfail` ajouté ; le contournement
  `EASYTV_ALLOW_TEST_CHANGES=1` et `--no-verify` sont réservés à l'utilisateur (bloqués par
  `.claude/hooks/guard.sh`).
- Commentaires seulement là où le code n'est pas évident. Petits commits ciblés.

## Raspberry Pi

- Déployer : toujours avec la skill `/deploy-pi`. Diagnostiquer : `/pi-diagnose`.
- `ssh`, `scp`, `rsync` et `git push` demandent la validation de l'utilisateur (`.claude/settings.json`).
- Contraintes matérielles, installation, règles de travail : `.claude/rules/pi.md`.
- Une procédure réussie et appelée à revenir devient une skill dans `.claude/skills/`.

## Feuille de route

`ROADMAP.md`, à mettre à jour à chaque étape terminée.
Config Claude (règles, hooks, skills, agents) : `ROADMAP-CLAUDE.md`, une étape à la fois.
Écarté, à ne pas reproposer : CEC (la TCL ne transmet aucune touche), télécommande physique,
conversion automatique des vidéos.
