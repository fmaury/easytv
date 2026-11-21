---
name: pi-setup
description: Première installation d'EasyTV sur une Raspberry Pi neuve ou effacée (clone du dépôt, install.sh, vérifications, passage au nom easytv.local). À utiliser quand EasyTV n'est pas encore installé sur la Pi. Pour une mise à jour d'une installation existante, c'est deploy-pi.
argument-hint: "<utilisateur@ip-ou-nom>  (obligatoire : easytv.local n'existe qu'après l'installation)"
---

# Installer EasyTV sur une Pi neuve

Lire d'abord `.claude/rules/pi.md` (contraintes matérielles, règles de travail sur la Pi).

Chaque `ssh` est soumis à la validation de l'utilisateur (permission `ask`) : un `ssh` direct par
étape, jamais dans une boucle ou un script, et dire en clair ce que fait la commande.

**Hôte (obligatoire)** : `$ARGUMENTS`, sous la forme `utilisateur@ip` ou
`utilisateur@raspberrypi.local`. Le nom `easytv.local` n'existe pas encore : c'est `install.sh`
qui renomme la Pi. Pas d'utilisateur `pi` par défaut sur Raspberry Pi OS récent : c'est celui créé
dans Raspberry Pi Imager. Si l'argument manque, demander l'utilisateur et l'IP (visible dans
l'interface de la box) et s'arrêter là.
Ci-dessous `HOST` = cet hôte, `SSH` = `ssh -o StrictHostKeyChecking=accept-new` (accepte un hôte
jamais vu, mais refuse toujours une empreinte qui a changé) et
`CTL` = `~/easytv/.venv/bin/python -m easytv.ctl`.
Ne jamais écrire d'adresse ou d'utilisateur perso dans le dépôt (seulement dans la mémoire).

## 1. État des lieux (lecture seule)

```bash
SSH HOST 'hostname; tr -d "\0" </proc/device-tree/model; echo; . /etc/os-release; echo "$PRETTY_NAME $(uname -m)"; sudo -n true 2>/dev/null && echo "sudo: sans mot de passe" || echo "sudo: MOT DE PASSE"; command -v git || echo "git: absent"; ls -d ~/easytv 2>/dev/null || echo "easytv: absent"; systemctl is-enabled easytv 2>/dev/null || true; df -h / | tail -1'
```

S'arrêter et en parler à l'utilisateur si :
- `~/easytv` existe déjà → c'est une mise à jour (`deploy-pi`), ou un nettoyage à décider avec lui ;
- ce n'est pas une Raspberry Pi, ou l'OS n'est pas Raspberry Pi OS / Debian 64 bits ;
- `sudo: MOT DE PASSE` → `install.sh` attendrait une saisie que Claude ne peut pas faire. Faire
  les étapes 2 et 3, puis l'utilisateur lance lui-même l'étape 4 dans Claude Code :
  `! ssh -t HOST 'cd ~/easytv && ./install.sh'` ; reprendre ensuite à l'étape 5.

## 2. git, s'il est absent

```bash
SSH HOST 'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git && git --version'
```

## 3. Récupérer le code

```bash
SSH HOST 'git clone -q https://github.com/fmaury/easytv.git ~/easytv && git -C ~/easytv log --oneline -1'
```

## 4. Installer

```bash
SSH HOST 'cd ~/easytv && ./install.sh'
```

Plusieurs minutes sur une Pi 3 (paquets, uv, dépendances) : timeout long (10 min). Relever dans la
sortie : le nom (`raspberrypi → easytv` ou conservé), la sortie son HDMI détectée, « EasyTV
tourne ». En cas d'échec : montrer l'erreur, ne rien forcer, puis `pi-diagnose` si utile.

## 5. Vérifier

Si la Pi a été renommée, passer par le nouveau nom (c'est aussi le test que `easytv.local`
répond) ; sinon rester sur `HOST` :

```bash
SSH UTILISATEUR@easytv.local 'hostname; systemctl get-default; systemctl is-active easytv; systemctl show easytv -p ActiveEnterTimestamp -p NRestarts; journalctl -u easytv -b -p warning --no-pager -o cat | tail -20; ls /media/tv; CTL get idle-active hwdec-current'
```

Attendu :
- `easytv`, `multi-user.target`, `active`, `NRestarts=0` ;
- aucun avertissement, et surtout pas « Failed to commit atomic request » (écran noir, `pi.md`) ;
- `/media/tv` vide sur une installation neuve : la TV affiche « Aucune chaîne », et mpv n'a pas de
  vidéo (`idle-active=true`) : c'est normal.

Si `easytv.local` ne répond pas (mDNS bloqué par la box, avahi pas encore relancé) : continuer
avec l'IP et le signaler. L'IP marche partout, y compris pour la télécommande (`http://<ip>`).

## 6. Rapport et suite

- Court : modèle et OS, commit installé, nom de la Pi, son HDMI, état du service, anomalies.
- Mettre à jour la mémoire (pas le dépôt) avec l'hôte et l'utilisateur.
- Dire à l'utilisateur la suite :
  - ajouter des vidéos par SFTP dans `/media/tv/<chaîne>/` (en H.264) ;
  - télécommande : `http://easytv.local` sur un téléphone du Wi-Fi de la maison ;
  - mises à jour : `/deploy-pi` ; problème : `/pi-diagnose`.
