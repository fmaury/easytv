# Feuille de route

À mettre à jour à chaque étape terminée.

0. Socle : CLAUDE.md, pyproject, outils ✅
1. Logique pure + tests (config, library, state, tuner) ✅
2. Lecteur mpv + clavier → TV fonctionnelle sur PC ✅
3. Robustesse : vidéos illisibles (anti-boucle), logs, bandeau soigné ✅
4. Installation sur la Pi : `install.sh`, service systemd, README ✅
5. Télécommande : page web sur téléphone, avec volume, bouton dodo, heure du coucher, barre de
   progression, liste des chaînes ✅
6. Bonus : effet neige, liste des chaînes sur OK, Samba
7. Chaîne « mix » : la chaîne 1 est créée automatiquement et mélange au hasard tous les épisodes
   de toutes les chaînes (les autres chaînes sont décalées d'un numéro). À trancher avant de
   commencer :
   - ordre aléatoire tiré une fois puis gardé (reprise comme les autres chaînes, règle 3), ou
     nouveau tirage à chaque tour ;
   - vidéos ajoutées ou supprimées au rescan : insérées au hasard dans l'ordre en cours ;
   - nom affiché (« Mix », « Tout »…) ; chaîne présente seulement s'il y a au moins deux chaînes ?

## Écarté

- **CEC** : la TCL 50P610 ne transmet aucune touche (testé le 2026-11-14 : Pi seule sur le bus,
  CEC 1.4, identifiant fabricant TCL, type tuner → rien ; la TV demande seulement le nom OSD).
  Elle sait en revanche basculer sur l'entrée de la Pi (`active-source`).
- **Télécommande physique** (infrarouge GPIO ou USB via `evdev`) : écartée le 2026-11-14, la page
  web suffit (marche chez tout le monde, rien à acheter, plusieurs téléphones à la fois).
- **Conversion automatique des vidéos** : les vidéos sont fournies en H.264 (voir le README).
