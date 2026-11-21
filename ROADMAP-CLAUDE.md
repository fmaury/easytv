# Feuille de route Claude : bonnes pratiques

Mise en place de la config Claude Code d'EasyTV (règles, skills, hooks, tests automatiques,
agents), **une étape à la fois** : chaque étape est planifiée, faite, vérifiée, puis cochée ici
avant de passer à la suivante.

Principe directeur : tout ce qui est déterministe (lint, typage, tests) passe par des scripts et
des hooks, qui ne négocient pas. Les skills et les agents servent à ce qui demande du jugement ou
une procédure (déployer, diagnostiquer, regarder une page).

## Étape 0 : socle ✅ (2026-11-21)

- `CLAUDE.md` allégé (184 → 116 lignes). Les détails Pi/mpv/HDMI vont dans `.claude/rules/pi.md`
  (chargé seulement quand on touche aux fichiers Pi), la feuille de route du produit dans
  `ROADMAP.md`.
- Skills `/deploy-pi` (déploiement) et `/pi-diagnose` (diagnostic en lecture seule).
- `ssh`, `scp`, `rsync` et `git push` en `ask` : toujours validés par l'utilisateur.
- Hook Stop : ruff + mypy avant que Claude rende la main, si du Python a changé.
- Outil `python -m easytv.ctl` : interroger et piloter la TV en marche par la socket mpv.

## Étape 1 : valider l'étape 0 en vrai

- **Pourquoi** : les skills et la validation SSH n'ont jamais tourné sur la Pi.
- **Quoi** :
  1. push par l'utilisateur ;
  2. `/deploy-pi` ;
  3. `/pi-diagnose` ;
  4. corriger les skills d'après ce qui coince.
- **Fini quand** :
  - chaque `ssh` a demandé une validation ;
  - la Pi tourne avec le dernier commit ;
  - le diagnostic produit un rapport et une capture de la TV.

## Étape 2 : tests protégés et pre-commit ✅ (2026-11-21)

- **Pourquoi** : pytest doit tourner automatiquement à chaque fin de feature (le commit), et Claude
  ne doit jamais affaiblir un test pour le faire passer.
- **Quoi** :
  - Règle « tests protégés » dans `CLAUDE.md` : on corrige le code, jamais le test. Modifier,
    affaiblir, `skip`, `xfail` ou supprimer un test demande l'accord explicite de l'utilisateur.
  - `.githooks/pre-commit`, versionné et activé par `git config core.hooksPath .githooks`. Il lance
    ruff, mypy et pytest. Le moindre échec refuse le commit.
  - Garde-fou : commit refusé si un `def test_` disparaît ou si un `skip`/`xfail` apparaît.
    Contournement réservé à l'utilisateur : `EASYTV_ALLOW_TEST_CHANGES=1 git commit …`.
  - `.claude/hooks/guard.sh` (PreToolUse sur `Bash`) : interdit à Claude `--no-verify`,
    `git commit -n`, `EASYTV_ALLOW_TEST_CHANGES` et `core.hooksPath`.
  - README, section « Développement » : activation du hook.
  - Ajouté en cours de route : modifier `.githooks/`, `.claude/hooks/` ou `.claude/settings.json`
    demande la validation de l'utilisateur (`ask`), pour que Claude ne puisse pas affaiblir les
    garde-fous eux-mêmes.
  - Limite connue : le garde lit la commande comme du texte brut. Une commande Bash qui contient
    seulement le mot (dans un message de commit, par exemple) est bloquée aussi : passer alors par
    l'outil d'édition de fichiers ou reformuler.
- **Fini quand** :
  - un commit avec une erreur de type, un test supprimé ou un `xfail` ajouté est refusé ;
  - un `--no-verify` lancé par Claude est bloqué.

## Étape 3 : test de bout en bout de la télécommande

- **Pourquoi** : la chaîne page web → App → vrai mpv n'est testée nulle part. Chaque morceau ne
  l'est que séparément, avec des faux.
- **Quoi** : `tests/test_e2e.py`.
  - Mise en place : vrai `python -m easytv`, mpv sans image ni son, 2 chaînes de clips générés par
    ffmpeg.
  - Chaque action de la page est envoyée par `POST /api/command`, puis l'état réel est vérifié par
    `/api/status` et par `easytv.ctl` : chaîne et vidéo en cours, volume, son coupé, éteint ou
    allumé.
  - Ignoré si mpv ou ffmpeg manquent.
- **Fini quand** : toutes les touches de la page sont couvertes, et le test tourne dans le
  pre-commit.

## Étape 4 : skill `/try-remote` (navigateur)

- **Pourquoi** : le JavaScript de `web.html` et la mise en page sur téléphone ne sont pas testés.
  Juger un rendu demande des yeux.
- **Quoi** :
  - EasyTV lancé en local ;
  - page ouverte à la taille d'un téléphone dans le navigateur disponible ;
  - clic sur chaque bouton, effet vérifié par `easytv.ctl` ;
  - captures de la page et de l'écran de la TV ;
  - rapport.
- **Fini quand** : la skill a tourné une fois et produit son rapport.

## Étape 5 (optionnelle) : agent « nouvel utilisateur »

- **Pourquoi** : un regard neuf, sans le contexte des conversations passées, sur le README et la
  page. Un agent (`.claude/agents/*.md`) travaille dans sa propre conversation, avec ses consignes
  et ses outils, puis rend un rapport. Son avis reste celui d'une IA, pas d'un vrai utilisateur.
- **Quoi** : `.claude/agents/nouvel-utilisateur.md`.
  - Consigne : jouer quelqu'un qui découvre EasyTV, suivre le README et utiliser la page, puis
    rapporter où il bloque et ce qui est confus.
  - Outils en lecture seule et navigateur.
- **Fini quand** : un premier rapport est produit et ses retours sont triés avec l'utilisateur.

## Étape 6 (optionnelle) : CI GitHub Actions

- **Pourquoi** : un témoin indépendant du PC. Il repart d'un clone propre, ce qui attrape un
  fichier oublié dans un commit ou une dépendance absente de `uv.lock` (le pre-commit, lui, teste
  le dossier local). Il marche même si le hook n'est pas installé.
- **Quoi** : `.github/workflows/ci.yml` (Ubuntu, mpv + ffmpeg, `setup-uv`, `uv sync --frozen`,
  les 4 vérifications).
- **Fini quand** : ✅ sur GitHub après un push.
- Décision : à prendre après l'étape 2. Pour un projet solo, le pre-commit couvre l'essentiel.
