---
name: deploy-pi
description: Déploie EasyTV sur la Raspberry Pi (git pull, install.sh si nécessaire, relance, vérification). À utiliser pour toute mise à jour de la Pi, dès que l'utilisateur demande de déployer, mettre à jour ou installer le code sur la Pi.
argument-hint: "[hôte ssh]"
---

# Déployer EasyTV sur la Pi

Lire d'abord `.claude/rules/pi.md` (contraintes matérielles, règles de travail sur la Pi).

Chaque `ssh` est soumis à la validation de l'utilisateur (permission `ask`) : un `ssh` direct par
étape, jamais dans une boucle ou un script, et dire en clair ce que fait la commande.

**Hôte** : `$ARGUMENTS` s'il est donné, sinon celui de la mémoire, sinon `easytv.local`.
Ne jamais écrire d'adresse ou d'utilisateur perso dans le dépôt. Ci-dessous, `HOST` = cet hôte et
`CTL` = `~/easytv/.venv/bin/python -m easytv.ctl`.

## 1. Préalables (sur le PC)

1. `git status` : arbre propre, sinon le signaler et s'arrêter.
2. Les 4 vérifications passent : `uv run ruff format --check .`, `uv run ruff check .`,
   `uv run mypy`, `uv run pytest`.
3. `git fetch -q && git status -sb` : si la branche est en avance sur `origin`, proposer
   `git push` (soumis à validation). La Pi fait `git pull` depuis GitHub : rien de non poussé n'y
   arrivera.

## 2. Mettre à jour le code (sur la Pi)

```bash
ssh HOST 'cd ~/easytv && old=$(git rev-parse HEAD) && git pull -q --ff-only && git log --oneline -1 && git diff --name-only "$old" HEAD && date "+%F %T"'
```

Noter l'heure affichée (`SINCE`) et la liste des fichiers changés. Si le pull échoue (modifs
locales sur la Pi, historique divergent) : s'arrêter et montrer l'erreur, ne rien forcer.

## 3. Relancer

- Si `pyproject.toml`, `uv.lock`, `install.sh`, `deploy/` ou `config.example.toml` ont changé :
  `ssh HOST 'cd ~/easytv && ./install.sh'` (il relance lui-même le service ; `config.toml` n'est
  jamais écrasé).
- Sinon, relance sans sudo (le code est installé en mode éditable) :
  `ssh HOST '~/easytv/.venv/bin/python -m easytv.ctl cmd script-message easytv quit'`.
  systemd (`Restart=always`, 3 s) relance EasyTV.
- Rien n'a changé : le dire, pas de relance.

## 4. Vérifier (~15 s après la relance)

```bash
ssh HOST 'systemctl is-active easytv; systemctl show easytv -p ActiveEnterTimestamp; journalctl -u easytv --since "SINCE" -p warning --no-pager -o cat; CTL get path time-pos hwdec-current'
```

Attendu :
- `active`, avec un `ActiveEnterTimestamp` **après** `SINCE` (sinon le service n'a pas redémarré
  et tourne encore l'ancien code) ;
- aucun avertissement nouveau, et surtout pas « Failed to commit atomic request » (écran noir, voir
  `pi.md`) ;
- `path` et `time-pos` présents ;
- `hwdec-current=v4l2m2m-copy` pour une vidéo H.264.

En cas de doute sur l'image : utiliser la skill `pi-diagnose` (elle sait faire une capture d'écran).

## 5. Rapport

Court : commit déployé, mode (pull simple ou `install.sh`), état du service, vidéo en cours,
anomalies.
