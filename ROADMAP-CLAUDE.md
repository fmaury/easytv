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

## Étape 3 : test de bout en bout de la télécommande ✅ (2026-11-21)

- **Pourquoi** : la chaîne page web → App → vrai mpv n'est testée nulle part. Chaque morceau ne
  l'est que séparément, avec des faux.
- **Quoi** : `tests/test_e2e.py`.
  - Mise en place : vrai `python -m easytv`, mpv sans image ni son, 2 chaînes de clips générés par
    ffmpeg.
  - Chaque action de la page est envoyée par `POST /api/command`, puis l'état réel est vérifié par
    `/api/status` et par `easytv.ctl` : chaîne et vidéo en cours, volume, son coupé, éteint ou
    allumé.
  - mpv et ffmpeg obligatoires : pas de `skipif`, le test échoue s'ils manquent (décision de
    l'utilisateur : mpv est indispensable à EasyTV).
  - En plus, dans `tests/test_web.py` : chaque `data-action` de `web.html` est une action connue, et
    chaque action proposée a son bouton (une faute de frappe rendrait un bouton muet).
- **Fini quand** : toutes les touches de la page sont couvertes, et le test tourne dans le
  pre-commit.
- **Résultat** : 9 tests (~6 s), stables sur 5 passes. Un sabotage volontaire est détecté : volume
  changé dans l'état mais pas appliqué à mpv, ou faute de frappe dans un bouton.
- **Ce qui reste hors champ** : les vrais clics JavaScript et l'affichage (étape 4), l'image réelle
  et la Pi.

## Étape 4 : agent `remote-tester` (navigateur Playwright) ✅ (2026-11-21)

- **Pourquoi** : le JavaScript de `web.html` et la mise en page sur téléphone ne sont pas testés
  (l'étape 3 envoie les commandes directement à l'API). Juger un rendu demande des yeux : bouton
  😴/📺, barre de progression, liste des chaînes (☰), « Son coupé », textes qui débordent.
- **Pourquoi un agent** : un test dans le navigateur produit beaucoup de matière (description de
  la page après chaque clic, captures, définitions des outils Playwright). L'agent travaille dans
  sa propre conversation et ne rend qu'un court rapport : la conversation principale reste
  légère. Il peut tourner en arrière-plan.
- **Quoi** : `.claude/agents/remote-tester.md`.
  - Navigateur : **Playwright MCP**, qui ouvre sa propre fenêtre (visible), en émulation de
    téléphone, sans extension ni session perso. Déclaré **dans l'agent seulement** (`mcpServers`),
    pas dans un `.mcp.json` de projet : il démarre avec l'agent et s'arrête après, sans rien
    coûter aux autres sessions. Version épinglée, lancée par `npx` (Node déjà installé),
    navigateur de Playwright téléchargé une fois (~150 Mo).
  - Consignes (l'agent ne sait rien de nos conversations, tout doit être écrit dans son fichier) :
    1. lancer EasyTV en local avec des vidéos de test, `input = "remote"` ;
    2. ouvrir la page à la taille d'un téléphone ;
    3. cliquer sur chaque bouton, vérifier l'effet sur mpv (`easytv.ctl`) et sur la page ;
    4. captures de la page et de l'écran de la TV (`screenshot-to-file`), enregistrées dans des
       fichiers ;
    5. arrêter EasyTV ;
    6. rapport court : chaque bouton OK/KO, défauts d'affichage, chemins des captures.
  - Outils : terminal (EasyTV, `easytv.ctl`), lecture de fichiers, Playwright. Aucune
    modification du code : il constate, la correction se fait ensuite dans la conversation
    principale.
  - Lancement : voir « Comment les agents se lancent » ci-dessous. Ligne à ajouter dans
    `CLAUDE.md` : « page (`web.html`) ou bandeau (`banner.py`) modifié → lancer `remote-tester` ».
- **À vérifier en le mettant en place** : la déclaration d'un MCP propre à un agent dans la
  version actuelle de Claude Code (sinon : `.mcp.json` de projet).
- **Fini quand** : l'agent a tourné une fois, en vrai, et rendu son rapport avec les captures.
- **Résultat du premier essai** : 12 boutons OK / 0 KO, aucun défaut de mise en page (pas de
  défilement horizontal en 412 px). Ses retours ont corrigé ses propres outils :
  - le bandeau ne reste que 4 s : la capture arrivait après → `remote-test.sh arm`, rafale de
    captures lancée juste avant le clic ;
  - mpv refuse de capturer sans vidéo (TV éteinte) → capture de la seule fenêtre mpv, par son
    titre ; interdiction de capturer tout le bureau (l'agent l'avait fait en dépannage) ;
  - noms des boutons, chemins des captures Playwright, reprise de position à ne pas prendre pour
    un bug : précisés dans ses consignes.
  - Seule la capture mpv en mode `window` montre le bandeau : `/pi-diagnose` et `pi.md` corrigés.
- **Mise en place** : un dossier `.claude/agents/` créé en cours de session n'est vu qu'après un
  redémarrage de Claude Code.

## Comment les agents se lancent

Un agent (`.claude/agents/*.md`) n'est pas une skill : c'est un assistant à part, avec ses
consignes et ses outils, qui travaille dans sa propre conversation (éventuellement en
arrière-plan) et rend un rapport, que Claude transmet. Un seul travail par agent. Il ne coûte
rien quand il ne tourne pas. Trois façons de le lancer :

1. **Claude le lance quand la tâche correspond** à sa `description` (renforcé par une ligne dans
   `CLAUDE.md`).
2. **L'utilisateur le demande** : « teste les boutons », « vérifie le README », ou en le nommant
   (`@agent-remote-tester`).
3. **Par une skill**, seulement si une commande `/…` est voulue : une skill peut s'exécuter dans
   un agent (`/test-boutons` → `remote-tester`).

## Étape 5 : agent `readme-tester`

- **Pourquoi** : un regard neuf, sans le contexte des conversations passées. Son avis reste celui
  d'une IA, pas d'un vrai utilisateur.
- **Quoi** : `.claude/agents/readme-tester.md`.
  - Consigne : jouer quelqu'un qui découvre EasyTV, lire tout le README, **exécuter pour de vrai**
    la partie « Développement » sur le PC (lancer EasyTV en local) en ne suivant que le README.
  - Rapport : ce qui l'a bloqué, ce qu'il a dû deviner, ce qui est confus ou manquant.
  - Outils : terminal et lecture de fichiers. Aucune modification : les corrections du README
    se font ensuite dans la conversation principale.
- **Fini quand** : un premier rapport est produit et ses retours sont triés avec l'utilisateur.

## Étape 6 (optionnelle) : agent `install-tester`

- **Pourquoi** : vérifier le guide d'installation sur la Pi sans Pi.
- **Quoi** : `.claude/agents/install-tester.md`.
  - Relire `install.sh` et la partie Pi du README : disent-ils la même chose ?
  - Passer `install.sh` à shellcheck (vérificateur de scripts bash).
  - Éventuellement, lancer `install.sh` dans un Debian jetable (Docker est sur le PC), pour
    attraper un paquet introuvable ou une erreur de syntaxe.
  - Rapport, sans modification.
- **Limite** : il ne reproduit pas la Pi. Pas d'ARM, de HDMI, de son, de `systemctl` réel ni de
  renommage de la machine. Le vrai test d'installation reste la Pi, que `/deploy-pi` exerce quand
  `install.sh` change.
- **Fini quand** : un premier rapport est produit et trié avec l'utilisateur.

## Étape 7 (optionnelle) : CI GitHub Actions

- **Pourquoi** : un témoin indépendant du PC. Il repart d'un clone propre, ce qui attrape un
  fichier oublié dans un commit ou une dépendance absente de `uv.lock` (le pre-commit, lui, teste
  le dossier local). Il marche même si le hook n'est pas installé.
- **Quoi** : `.github/workflows/ci.yml` (Ubuntu, mpv + ffmpeg, `setup-uv`, `uv sync --frozen`,
  les 4 vérifications).
- **Fini quand** : ✅ sur GitHub après un push.
- Décision : à prendre après l'étape 2. Pour un projet solo, le pre-commit couvre l'essentiel.
