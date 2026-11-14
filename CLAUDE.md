# EasyTV

« TV perso » sur Raspberry Pi 4 branchée en HDMI sur une TV : chaque dossier est une chaîne, chaque
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
7. **Vidéo illisible** → loguée et sautée, jamais de plantage.
8. **Rescan** périodique des dossiers : ajouts et suppressions pris en compte sans redémarrage.

## Architecture

Processus Python unique, `asyncio`. Code dans `src/easytv/`, tests dans `tests/`.

| Module | Rôle | Pur ? |
|---|---|---|
| `config.py` | Lit `config.toml` → dataclass `Config` | oui |
| `library.py` | Scanne `channels_dir` → chaînes et vidéos triées | oui (testé avec `tmp_path`) |
| `state.py` | État (dernière chaîne ; par chaîne : vidéo, position, heure de départ), sauvegarde JSON atomique | oui |
| `tuner.py` | Zapping, vidéo suivante, rebouclage, règle de reprise, contenu disparu | **oui, cœur testé** |
| `player.py` | Pilote mpv via sa socket JSON IPC : charger, aller à, OSD, événement fin de vidéo | non |
| `remote.py` | Lit les touches via `evdev` (CEC, télécommande USB, clavier) → actions | non |
| `app.py` | Boucle principale : relie remote → tuner → player, sauvegarde et rescan périodiques | non |
| `__main__.py` | Point d'entrée `easytv` | non |

- La logique pure (`tuner`, `state`, `library`, `config`) ne dépend ni de mpv, ni des entrées, ni de
  l'horloge : **l'heure est passée en paramètre**.
- Option `input` de la config : `"keyboard"` (dev sur PC : mpv fenêtré, touches transmises par mpv
  via `script-message`) ou `"remote"` (Pi : télécommande CEC/USB lue avec `evdev`).

## Stack

- **Cible** : Raspberry Pi 4, Raspberry Pi OS Lite 64 bits (sans bureau), service **systemd**.
- **Lecteur** : mpv plein écran en DRM (sans X/Wayland), décodage matériel H.264/HEVC,
  bandeau de zapping via l'OSD mpv.
- **Télécommande** : HDMI-CEC via le pilote noyau (`/dev/cec0`), touches exposées comme
  périphérique d'entrée et lues avec `evdev`.
- **Config** : `config.toml` (écrit à la main, `tomllib`), non versionné → modèle `config.example.toml`.
- **État** : `state.json` (écrit par le programme), non versionné.
- **Ajout des vidéos** : SFTP (OpenSSH de la Pi), dans `/media/tv/<chaîne>/`.
- **Outils dev** : uv, ruff, mypy (strict), pytest.

## Contraintes matérielles

- TV branchée sur le port **HDMI 0** de la Pi 4 (le plus proche de l'USB-C) : seul port CEC fiable.
- TV **TCL** : CEC = « T-Link » / « Contrôle HDMI ». Flèches, OK, Retour normalement transmis ;
  CH+/CH− et chiffres souvent non → zapping principal sur ↑/↓.
  Vérifier les touches reçues : `cec-ctl -d /dev/cec0 --playback -M`.
- Décodage matériel Pi 4 : H.264 et HEVC uniquement. Pas de conversion automatique dans l'app :
  les vidéos sont fournies dans un format compatible.

## Commandes

```bash
uv sync                      # dépendances
uv run pytest                # tests
uv run ruff format .         # mise en forme
uv run ruff check --fix .    # lint
uv run mypy                  # typage
```

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
2. Lecteur mpv + clavier → TV fonctionnelle sur PC ← **en cours**
3. Robustesse : sauvegarde périodique, rescan, vidéos illisibles, logs, bandeau
4. Installation sur la Pi (OS, mpv DRM, systemd, SFTP) + skills `/pi-setup`, `/deploy-pi`
5. CEC avec la TV TCL + skill `/cec-test`
6. Bonus : effet neige, liste des chaînes sur OK, page web de télécommande, Samba

Mettre à jour la phase en cours à chaque étape terminée.
