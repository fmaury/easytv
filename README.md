# EasyTV

Transforme une Raspberry Pi branchée sur ta TV en **chaînes de télé perso** :

- chaque **dossier** est une chaîne, chaque chaîne enchaîne ses vidéos en boucle ;
- on **zappe** d'une chaîne à l'autre ;
- chaque chaîne **reprend là où on l'a laissée** (si on revient dans l'heure ; au-delà, la vidéo
  repart du début) ;
- au démarrage, la TV se rallume sur la dernière chaîne regardée.

On zappe **depuis son téléphone** : une page web, sur le Wi-Fi de la maison, avec les boutons et la
liste des chaînes ([voir plus bas](#5-zapper-avec-le-téléphone)).

> ⚠️ **Télécommande de la TV** : selon les modèles, la TV ne transmet pas ses touches à la Pi
> (c'est le cas des TCL testées). Une télécommande dédiée est à l'étude.

---

## Ce qu'il te faut

| | |
|---|---|
| **Raspberry Pi** | Pi 3 ou Pi 4 (testé sur Pi 3 Model B) |
| **Carte SD** | 16 Go minimum, classe A1/A2 de marque (les vidéos sont stockées dessus) |
| **Alimentation** | Officielle de préférence : 5 V / 2,5 A (Pi 3) ou 3 A USB-C (Pi 4) |
| **Câble HDMI** | Vers la TV (sur Pi 4 : le port **HDMI 0**, le plus proche de l'alimentation) |
| **Réseau** | Câble Ethernet conseillé, ou Wi-Fi |
| **Un PC** | Pour préparer la carte SD, se connecter et envoyer les vidéos |

**Format des vidéos : H.264** (la plupart des `.mp4`). La Pi le décode en matériel, fluide jusqu'en
1080p. Les vidéos HEVC/x265, VP9 ou AV1 saccadent : voir [convertir une vidéo](#convertir-une-vidéo-en-h264).

---

## 1. Préparer la carte SD

1. Installe **Raspberry Pi Imager** depuis [raspberrypi.com/software](https://www.raspberrypi.com/software/).
2. Choisis :
   - **Appareil** : ton modèle de Raspberry Pi ;
   - **Système** : *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)** (sans bureau) ;
   - **Stockage** : ta carte SD.
3. Quand Imager propose de **personnaliser l'OS**, clique sur **« Modifier réglages »**
   (et surtout pas « Non ») :
   - **Général** : nom d'hôte `easytv`, ton nom d'utilisateur et un mot de passe, fuseau horaire
     `Europe/Paris`, clavier `fr`, et le Wi-Fi si tu n'as pas de câble ;
   - **Services** : coche **Activer SSH** (avec ta clé publique si tu en as une, sinon par mot de passe).
4. Enregistre, réponds **Oui**, et lance l'écriture.

> La version **avec bureau** marche aussi : l'installation désactive le bureau au démarrage
> (réversible).

## 2. Premier démarrage et connexion

1. Carte SD dans la Pi, HDMI sur la TV, Ethernet, puis **l'alimentation en dernier**.
2. Attends **2 à 3 minutes** (la Pi redémarre une fois toute seule au premier démarrage).
3. Depuis ton PC :
   ```bash
   ssh ton-utilisateur@easytv.local
   ```
   Si `easytv.local` ne répond pas, cherche l'adresse IP de la Pi dans l'interface de ta box et
   utilise `ssh ton-utilisateur@192.168.x.x`.

<details>
<summary>La personnalisation n'a pas été appliquée (SSH fermé, nom <code>raspberrypi</code>) ?</summary>

Branche un clavier sur la Pi, crée l'utilisateur proposé à l'écran (choisis bien le clavier
**French**), puis :

```bash
sudo raspi-config
```

- *Interface Options* → *SSH* → *Yes*
- *System Options* → *Hostname* → `easytv`
- *Localisation Options* → *Timezone* → *Europe* → *Paris*

Valide, laisse la Pi redémarrer, et reprends à l'étape 3.
</details>

## 3. Installer EasyTV

Sur la Pi (connecté en SSH) :

```bash
git clone https://github.com/fmaury/easytv.git
cd easytv
./install.sh
```

Le script te demande ton mot de passe une fois, puis installe tout (mpv, EasyTV, le démarrage
automatique). À la fin, la TV affiche **« Aucune chaîne »** : il ne reste qu'à ajouter des vidéos.

## 4. Ajouter des vidéos

Les vidéos vont dans **`/media/tv`**, avec **un sous-dossier par chaîne** :

```
/media/tv/
├── 01 - Dessins animés/
│   ├── episode 01.mp4
│   └── episode 02.mp4
├── 02 - Documentaires/
└── 03 - Films/
```

- Les chaînes et les vidéos sont triées par nom, dans l'ordre naturel (`ep2` avant `ep10`).
  Le préfixe `01 - ` fixe l'ordre des chaînes et n'est pas affiché à l'écran.
- Les dossiers vides et les fichiers qui ne sont pas des vidéos sont ignorés.
- Les ajouts et suppressions sont pris en compte **en moins de 30 secondes**, sans redémarrer.

**Envoyer les fichiers depuis ton PC**, au choix :

- **FileZilla** : hôte `sftp://easytv.local` (le `sftp://` est indispensable), ton utilisateur et
  ton mot de passe, port `22`. Puis glisse tes dossiers dans `/media/tv`.
- **En ligne de commande** :
  ```bash
  scp -r "01 - Dessins animés" ton-utilisateur@easytv.local:/media/tv/
  ```

SFTP passe par SSH : rien d'autre à installer sur la Pi.

### Convertir une vidéo en H.264

Si une vidéo saccade, convertis-la **sur ton PC** (bien plus rapide que la Pi) avec
[ffmpeg](https://ffmpeg.org/) :

```bash
ffmpeg -i entree.mkv -c:v libx264 -preset medium -crf 21 -vf "scale='min(1920,iw)':-2" -c:a aac sortie.mp4
```

## 5. Zapper avec le téléphone

Sur un téléphone connecté au **Wi-Fi de la maison**, ouvre dans le navigateur :

**`http://easytv.local:8080`**

Si la page ne s'ouvre pas, utilise l'adresse IP de la Pi à la place, par exemple
`http://192.168.1.31:8080`. EasyTV l'affiche au démarrage dans son journal
(`journalctl -u easytv | grep "web remote"`), ou `hostname -I` sur la Pi la donne.

La page affiche la chaîne en cours et permet de :

- passer à la **chaîne suivante ou précédente** ;
- aller **directement à une chaîne** en la touchant dans la liste ;
- **monter, baisser ou couper le son** (une jauge s'affiche en haut à droite de la TV ; le volume
  est retenu, même après un redémarrage) ;
- passer à la **vidéo suivante** ;
- réafficher le **bandeau d'infos** sur la TV.

**Astuce** : ajoute la page à l'écran d'accueil (menu du navigateur → « Ajouter à l'écran
d'accueil ») pour l'ouvrir comme une application.

Tous les téléphones de la maison peuvent s'en servir, sans rien installer. La page n'est pas
accessible depuis Internet, seulement depuis le réseau de la maison.

## 6. Configuration

Le fichier `~/easytv/config.toml` est créé à l'installation (jamais écrasé ensuite). Après une
modification : `sudo systemctl restart easytv`.

| Réglage | Par défaut | Rôle |
|---|---|---|
| `channels_dir` | `/media/tv` | Dossier des chaînes |
| `resume_timeout` | `3600` | Délai (s) pendant lequel une chaîne reprend à la seconde près ; au-delà, la vidéo repart du début |
| `save_interval` | `30` | Fréquence (s) de sauvegarde de la position (l'état est aussi sauvegardé à chaque zapping) |
| `rescan_interval` | `30` | Fréquence (s) de détection des nouvelles vidéos |
| `state_file` | `/var/lib/easytv/state.json` | Mémoire des positions |
| `input` | `remote` | `remote` (télécommande) ou `keyboard` (clavier, sur PC) |
| `mpv_args` | réglages Pi | Options du lecteur vidéo (décodage matériel, son HDMI) |
| `web_port` | `8080` | Port de la page web de télécommande (`0` la désactive) |
| `video_extensions` | `.mp4 .mkv .avi .mov .m4v .webm .ts` | Extensions reconnues |

## 7. Mettre à jour

```bash
cd ~/easytv && git pull && ./install.sh
```

## 8. En cas de problème

| Besoin | Commande |
|---|---|
| Voir ce que fait EasyTV en direct | `journalctl -u easytv -f` |
| Redémarrer EasyTV | `sudo systemctl restart easytv` |
| Arrêter EasyTV | `sudo systemctl stop easytv` |
| Vérifier l'alimentation (`0x0` = OK) | `vcgencmd get_throttled` |
| Retrouver le bureau (version avec bureau) | `sudo systemctl set-default graphical.target && sudo reboot` |

- **« Chaîne indisponible »** : aucune vidéo de la chaîne n'est lisible (fichier abîmé ou format non
  supporté). La chaîne réessaie dès que ses fichiers changent.
- **Image qui saccade** : vidéo pas en H.264 → [convertir](#convertir-une-vidéo-en-h264).
- **Plantages au hasard** : souvent une alimentation trop faible (`vcgencmd get_throttled` ≠ `0x0`).

## Développement

EasyTV tourne aussi sur un PC Linux, dans une fenêtre, au clavier (↑/↓ pour zapper) :

```bash
uv sync
cp config.example.toml config.toml   # puis : input = "keyboard", mpv_args = [], channels_dir à adapter
uv run easytv
uv run pytest
```

Architecture, règles de comportement et conventions : voir [`CLAUDE.md`](CLAUDE.md).
