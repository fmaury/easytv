# Feuille de route

À mettre à jour à chaque étape terminée.

0. Socle : CLAUDE.md, pyproject, outils ✅
1. Logique pure + tests (config, library, state, tuner) ✅
2. Lecteur mpv + clavier → TV fonctionnelle sur PC ✅
3. Robustesse : vidéos illisibles (anti-boucle), logs, bandeau soigné ✅
4. Installation sur la Pi : `install.sh`, service systemd, README ✅
5. Télécommande : page web sur téléphone, avec volume, bouton dodo, heure du coucher, barre de
   progression, liste des chaînes ✅
6. Bonus : effet neige ✅ (au changement de chaîne et au rallumage), liste des chaînes sur OK,
   Samba
7. Chaîne mix « Doodingue » ✅ : la chaîne 1 mélange tous les épisodes de toutes les chaînes
   (les autres sont décalées d'un numéro). Choix faits : mélange tiré une fois puis gardé, avec
   reprise comme les autres chaînes ; un épisode ajouté s'insère au hasard ; seulement à partir
   de 2 chaînes ; nom réglable (`mix`, `""` pour s'en passer).

## Écarté

- **Télécommande physique** (infrarouge GPIO ou USB via `evdev`) : écartée le 2026-11-14, la page
  web suffit (marche chez tout le monde, rien à acheter, plusieurs téléphones à la fois).
- **Conversion automatique des vidéos** : les vidéos sont fournies en H.264 (voir le README).
