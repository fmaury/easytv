---
name: pi-setup
description: Première installation d'EasyTV sur une Raspberry Pi neuve ou effacée (clone du dépôt, install.sh, vérifications, passage au nom easytv.local). À utiliser quand EasyTV n'est pas encore installé sur la Pi. Pour une mise à jour d'une installation existante, c'est pi-deploy.
argument-hint: "<utilisateur@ip-ou-nom>  (obligatoire : easytv.local n'existe qu'après l'installation)"
---

# Installer EasyTV sur une Pi neuve

Lire d'abord `.claude/rules/pi.md` (contraintes matérielles, règles de travail sur la Pi).

Chaque `ssh` est soumis à la validation de l'utilisateur (permission `ask`) : un `ssh` direct par
étape, jamais dans une boucle ou un script, et dire en clair ce que fait la commande.

**Hôte**, dans cet ordre :
1. `$ARGUMENTS` s'il est donné (`utilisateur@ip` ou `utilisateur@raspberrypi.local`) ;
2. sinon `.claude/pi.local.env` (fichier perso, ignoré par git) : `PI_USER@PI_IP` ;
3. sinon, demander à l'utilisateur son utilisateur et l'IP de la Pi (visible dans l'interface de la box), proposer de créer
   `.claude/pi.local.env` à partir de `.claude/pi.local.env.example`, et s'arrêter en attendant la
   réponse. Ne jamais deviner l'hôte.

Jamais de mot de passe dans ce fichier ni ailleurs : SSH marche par clé, sudo sans mot de passe
ou saisi par l'utilisateur lui-même. Ne jamais écrire d'adresse ou d'utilisateur perso dans un
fichier versionné.

Pas `PI_HOST` ni `easytv.local` ici : ce nom n'existe pas encore, c'est `install.sh` qui renomme
la Pi. Pas d'utilisateur `pi` par défaut sur Raspberry Pi OS récent : c'est celui créé dans
Raspberry Pi Imager.
Ci-dessous `HOST` = cet hôte, `SSH` = `ssh -o StrictHostKeyChecking=accept-new` (accepte un hôte
jamais vu, mais refuse toujours une empreinte qui a changé) et
`CTL` = `~/easytv/.venv/bin/python -m easytv.ctl`.

## 0. Connexion par clé SSH

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new HOST true && echo "clé OK"
```

En cas d'échec (`Permission denied`) : la Pi n'accepte que le mot de passe, que Claude ne doit
jamais voir. L'utilisateur installe sa clé une fois, en tapant lui-même le mot de passe :
`! ssh-copy-id HOST` (s'il n'a pas de clé : `! ssh-keygen -t ed25519` d'abord). Puis reprendre.

## 1. État des lieux (lecture seule)

```bash
SSH HOST 'hostname; tr -d "\0" </proc/device-tree/model; echo; . /etc/os-release; echo "$PRETTY_NAME $(uname -m)"; sudo -n true 2>/dev/null && echo "sudo: sans mot de passe" || echo "sudo: MOT DE PASSE"; command -v git || echo "git: absent"; ls -d ~/easytv 2>/dev/null || echo "easytv: absent"; systemctl is-enabled easytv 2>/dev/null || true; df -h / | tail -1'
```

S'arrêter et en parler à l'utilisateur si :
- `~/easytv` existe déjà → c'est une mise à jour (`pi-deploy`), ou un nettoyage à décider avec lui ;
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
SSH HOST 'date "+%F %T"; cd ~/easytv && ./install.sh'
```

Noter l'heure affichée (`SINCE`). Plusieurs minutes sur une Pi 3 (paquets, uv, dépendances) :
timeout long (10 min). Relever dans la sortie : le nom (`raspberrypi → easytv` ou conservé), la
sortie son HDMI détectée, « EasyTV tourne » ou « a planté puis redémarré » (surveillé 15 s).
En cas d'échec : montrer l'erreur, ne rien forcer, puis `pi-diagnose` si utile.

## 5. Vérifier (~20 s après la fin d'`install.sh`)

Si la Pi a été renommée, passer par le nouveau nom (c'est aussi le test que `easytv.local`
répond) ; sinon rester sur `HOST` :

```bash
SSH UTILISATEUR@easytv.local 'hostname; systemctl get-default; systemctl is-active easytv; systemctl show easytv -p ActiveEnterTimestamp -p NRestarts; journalctl -u easytv --since "SINCE" -p warning --no-pager -o cat | tail -20; ls /media/tv; CTL get idle-active path hwdec-current'
```

Attendu :
- `easytv`, `multi-user.target`, `active`, `NRestarts=0` ;
- aucun avertissement (seul « Can't open TTY for VT control » est normal), et surtout pas
  « Failed to commit atomic request » (écran noir, `pi.md`) ;
- `/media/tv` vide (Pi neuve) : la TV affiche « Aucune chaîne », `idle-active=true` sans `path` ;
  `/media/tv` avec des chaînes (vidéos gardées) : `path` présent et
  `hwdec-current=v4l2m2m-copy`.

`NRestarts` > 0 ou « Failed » : EasyTV a planté puis systemd l'a relancé. Lire tout le journal
depuis `SINCE` (`journalctl -u easytv --since "SINCE" --no-pager -o short-iso`, sans `-p`) pour
trouver la trace d'erreur, et la signaler même si le service tourne à nouveau.

Si `easytv.local` ne répond pas (mDNS bloqué par la box, avahi pas encore relancé) : continuer
avec l'IP et le signaler. L'IP marche partout, y compris pour la télécommande (`http://<ip>`).

## 6. Rapport et suite

- Court : modèle et OS, commit installé, nom de la Pi, son HDMI, état du service, anomalies.
- Créer ou mettre à jour `.claude/pi.local.env` (`PI_USER`, `PI_IP`, et `PI_HOST=easytv.local`
  si ce nom répond, sinon l'IP), pour que `/pi-deploy` et `/pi-diagnose` marchent sans argument.
- Dire à l'utilisateur la suite :
  - ajouter des vidéos par SFTP dans `/media/tv/<chaîne>/` (en H.264) ;
  - télécommande : `http://easytv.local` sur un téléphone du Wi-Fi de la maison ;
  - mises à jour : `/pi-deploy` ; problème : `/pi-diagnose`.
