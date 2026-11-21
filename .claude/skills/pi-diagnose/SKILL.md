---
name: pi-diagnose
description: Diagnostique EasyTV sur la Raspberry Pi en lecture seule (état du service, erreurs du journal, vidéo en cours, décodage, CPU, température, alimentation, capture de l'écran de la TV). À utiliser quand la TV ou la télécommande web ne marche pas comme prévu, ou pour voir les erreurs d'EasyTV.
argument-hint: "[hôte ssh] [symptôme]"
---

# Diagnostiquer EasyTV sur la Pi

Lire d'abord `.claude/rules/pi.md` : les pannes connues et leurs signatures y sont décrites.

**Lecture seule** : rien n'est modifié, relancé ni supprimé sans l'accord de l'utilisateur.
Chaque `ssh` est soumis à sa validation (permission `ask`) : un `ssh` direct par étape, jamais
dans une boucle ou un script, et dire en clair ce que fait la commande.

**Hôte**, dans cet ordre :
1. `$ARGUMENTS` s'il est donné (son premier mot s'il contient `@` ; le reste décrit le symptôme) ;
2. sinon `.claude/pi.local.env` (fichier perso, ignoré par git) : `PI_USER@PI_HOST` ;
3. sinon, demander à l'utilisateur son utilisateur et le nom (`easytv.local`) ou l'IP de la Pi, proposer de créer
   `.claude/pi.local.env` à partir de `.claude/pi.local.env.example`, et s'arrêter en attendant la
   réponse. Ne jamais deviner l'hôte.

Jamais de mot de passe dans ce fichier ni ailleurs : SSH marche par clé, sudo sans mot de passe
ou saisi par l'utilisateur lui-même. Ne jamais écrire d'adresse ou d'utilisateur perso dans un
fichier versionné.

Ci-dessous `HOST` = cet hôte et
`CTL` = `~/easytv/.venv/bin/python -m easytv.ctl`.

## 1. Système et journal

```bash
ssh HOST 'echo "== service"; systemctl is-active easytv; systemctl show easytv -p NRestarts -p ActiveEnterTimestamp; echo "== erreurs"; journalctl -u easytv -b -p warning --no-pager -o short-iso | tail -40; echo "== machine"; uptime; vcgencmd measure_temp; vcgencmd get_throttled; free -m | head -2; df -h / /media/tv | tail -n +2; timedatectl show -p NTPSynchronized'
```

Les erreurs de mpv sont déjà recopiées dans ce journal (`request_log_messages`).
Pour suivre un problème intermittent, regarder aussi les lignes `INFO` autour de l'heure du
symptôme : `journalctl -u easytv --since "…" --until "…"`.

## 2. Lecture en cours

```bash
ssh HOST 'CTL get path time-pos duration hwdec-current frame-drop-count decoder-frame-drop-count volume mute aid'
```

## 3. Écran de la TV

```bash
ssh HOST 'CTL cmd screenshot-to-file /tmp/easytv-shot.png window && sleep 2 && ls -l /tmp/easytv-shot.png'
scp HOST:/tmp/easytv-shot.png <scratchpad>/easytv-shot.png
```

Puis lire l'image. La capture vient de mpv : elle montre ce que mpv dessine, pas forcément ce que
la TV affiche. En cas d'écran noir réel avec une capture normale, penser au plan DRM refusé
(`pi.md`).

## 4. Interpréter

Confronter aux pannes connues de `pi.md` :

| Signature | Cause probable |
|---|---|
| « Failed to commit atomic request » / « dmabuf interop » | `--hwdec=v4l2m2m` sans `-copy` : écran noir |
| « audio output initialization failed », « Unknown error 524 », `aid=no` | son HDMI perdu (câble, TV éteinte) |
| `hwdec-current=no`, `frame-drop-count` qui monte | vidéo pas en H.264 : à convertir |
| `get_throttled` ≠ `0x0` | alimentation trop faible |
| `NTPSynchronized=no` | heure fausse : la règle de reprise d'1 h se trompe |
| `NRestarts` élevé | plantages : chercher la trace dans le journal |
| « no readable video on … » (TV : « Chaîne indisponible ») | aucune vidéo lisible dans la chaîne |

## 5. Rapport

Symptômes constatés, cause probable, correctif proposé (code, config ou matériel). Si le correctif
touche le code : le faire en local, puis déployer avec la skill `deploy-pi`.
