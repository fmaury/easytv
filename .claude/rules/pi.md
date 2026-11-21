---
paths:
  - "src/easytv/player.py"
  - "src/easytv/app.py"
  - "src/easytv/ctl.py"
  - "config.example.toml"
  - "install.sh"
  - "deploy/**"
  - "README.md"
---

# Raspberry Pi : matériel, installation, travail sur la Pi

## Travail sur la Pi

- Toute commande sur la Pi (SSH, `sudo`, systemd, paquets) est validée par l'utilisateur :
  `ssh`, `scp`, `rsync` et `git push` sont en `ask` dans `.claude/settings.json`. Un `ssh` direct
  par commande, jamais caché dans une boucle ou un script (sinon la validation ne s'applique pas),
  et chaque commande expliquée en clair.
- Première installation : skill `pi-setup` (hôte en argument, `utilisateur@ip`). Mettre à jour :
  skill `pi-deploy`. Diagnostiquer : skill `pi-diagnose`.
- Adresse et utilisateur de la Pi : `.claude/pi.local.env` (perso, ignoré par git ; modèle
  `.claude/pi.local.env.example`), jamais dans un fichier versionné (le dépôt sert à tout le
  monde). **Aucun mot de passe** nulle part : SSH par clé (`ssh-copy-id`), sudo saisi par
  l'utilisateur lui-même s'il en demande un.
- Interroger ou piloter EasyTV : `~/easytv/.venv/bin/python -m easytv.ctl get|cmd …` (socket
  `/tmp/easytv-*/mpv.sock`).

## Contraintes matérielles

- Un seul port HDMI (taille normale), qui gère le CEC.
- TV **TCL 50P610** : CEC = « T-Link ». **Aucune touche transmise** à la Pi (voir `ROADMAP.md`) ;
  CH+ change d'entrée HDMI. Elle affiche « HDMI1 », jamais le nom OSD.
  → zapping par la page web.
  Vérifier les touches reçues : `cec-ctl -d /dev/cec0 --playback -M`.
- Décodage matériel Pi 3 : **H.264 uniquement** (jusqu'à 1080p). Pas de HEVC matériel :
  HEVC, VP9, AV1 saccadent. Pas de conversion automatique dans l'app : vidéos fournies en H.264.
- **mpv sur la Pi : `--hwdec=v4l2m2m-copy`** (décodeur `bcm2835-codec`, image recopiée), `--vo=gpu`
  en DRM. **Ne pas utiliser `v4l2m2m` sans copie : écran noir.** mpv 0.40 n'a pas d'interop dmabuf
  sur la Pi 3 (« drmprime hwdec requires at least one dmabuf interop backend ») et se rabat sur un
  plan overlay DRM que vc4 refuse (« Failed to commit atomic request », errno 22) : image décodée,
  jamais affichée, alors que CPU, fps et images perdues semblent parfaits. Toujours vérifier
  l'absence de ce message (`request_log_messages` sur la socket) ou l'écran réel.
  Mesuré le 2026-11-14 sur un H.264 640×480 : `v4l2m2m-copy` 38 % CPU, 0 image perdue, image OK ;
  logiciel 59 %. 720p/1080p en `-copy` : à mesurer.
  `--vo=gpu-next` impossible (libplacebo exige OpenGL 3, la Pi 3 n'a que GLES 2).
  `--hwdec=auto` ne choisit pas v4l2m2m.
- **Son HDMI perdu** (câble débranché, testé le 2026-11-14) : mpv lit alors chaque vidéo **sans
  son** et la termine en `end-file` « error » (« audio output initialization failed »).
  `ao-reload` ne rétablit rien ; désélectionner puis resélectionner la piste (`aid`) si (mpv la
  désélectionne après un essai raté : retenir son numéro). Erreur vue : « Unknown error 524 »,
  noyau « ASoC error (-22) … i2s-hifi » : ce n'est pas PipeWire.
  → `check_audio` toutes les 10 s, et une vidéo qui a joué puis finit en erreur n'est pas
  « illisible ». Les erreurs de mpv sont recopiées dans le journal (`request_log_messages`).
- USB 2.0 uniquement ; système sur carte SD (le démarrage USB du 3 B demande une activation préalable).
- 1 Go de RAM, pas d'horloge matérielle (heure fausse au boot tant que NTP n'a pas synchronisé).

## Installation sur la Pi

- `install.sh` (idempotent, = commande de mise à jour après `git pull`) : paquets apt (mpv, git,
  curl, v4l-utils), uv, `uv sync --no-dev --frozen`, `config.toml` depuis `config.example.toml`
  (jamais écrasé ; son HDMI détecté : `vc4hdmi` sur Pi 3, `vc4hdmi0` sur Pi 4), `/media/tv`,
  nom `raspberrypi` → `easytv` (seulement le nom par défaut ; `/etc/hosts`, `hostnamectl`,
  `preserve_hostname: true` pour cloud-init, relance d'avahi), service systemd, démarrage sans
  bureau (`multi-user.target`).
  Pourquoi le nom d'Imager peut ne pas s'appliquer : sa ligne `hostname` restée commentée dans
  `/boot/firmware/user-data` (cas vu le 2026-11-15).
- `deploy/easytv.service` : modèle (`@USER@`, `@DIR@`), `Restart=always`, `StateDirectory=easytv`,
  attente NTP (60 s max) avant le lancement.
  systemd arrête le service par SIGTERM : géré comme Ctrl+C (sauvegarde finale de la position).
- `config.example.toml` est le modèle **Pi** : `mpv_args` (`--gpu-context=drm`, `--hwdec=v4l2m2m-copy`,
  `--ao=alsa` + périphérique HDMI : le service tourne hors session, sans PipeWire), `save_interval = 30`.
- Relancer EasyTV sans sudo : `python -m easytv.ctl cmd script-message easytv quit` → systemd le
  relance (le code est installé en mode éditable : un `git pull` suffit pour le code Python).
- Capture de l'écran de la TV : `python -m easytv.ctl cmd screenshot-to-file <fichier> window` (`window` : avec le bandeau ; écrit en
  différé : attendre ~2 s).
- `README.md` : guide utilisateur en français (carte SD → SSH → `install.sh` → vidéos par SFTP).
