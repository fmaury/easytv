#!/usr/bin/env bash
# Installe ou met à jour EasyTV sur une Raspberry Pi.
# À lancer depuis le dossier du dépôt, avec l'utilisateur normal (pas root) :
#     ./install.sh
# Peut être relancé sans risque : c'est aussi la commande de mise à jour (après `git pull`).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(id -un)"
CHANNELS_DIR="/media/tv"
SERVICE="/etc/systemd/system/easytv.service"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
fail() { printf '\033[1;31mErreur : %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. Vérifications -------------------------------------------------------
step "Vérifications"
[[ "$(id -u)" -ne 0 ]] || fail "lance ce script avec ton utilisateur normal, pas avec sudo ni root."
command -v sudo >/dev/null || fail "sudo est nécessaire."
[[ -f "$DIR/pyproject.toml" && -f "$DIR/deploy/easytv.service" ]] \
    || fail "lance ce script depuis le dossier du dépôt EasyTV."
case "$(uname -m)" in
    aarch64 | armv7l) info "Machine : $(tr -d '\0' </proc/device-tree/model 2>/dev/null || uname -m)" ;;
    *) info "Attention : ce n'est pas une Raspberry Pi ($(uname -m)), on continue quand même." ;;
esac
# Ask for the password once if needed (`sudo -v` would ask even with NOPASSWD rules).
sudo true

# --- 2. Paquets système -----------------------------------------------------
step "Installation des paquets (mpv, git, curl, v4l-utils)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mpv git curl v4l-utils >/dev/null
info "mpv $(mpv --version | head -1 | cut -d' ' -f2)"

# --- 3. uv --------------------------------------------------------------------
step "Installation de uv"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
info "$(uv --version)"

# --- 4. EasyTV ----------------------------------------------------------------
step "Installation d'EasyTV"
(cd "$DIR" && uv sync --no-dev --frozen --quiet)
info "$DIR/.venv/bin/easytv"

# --- 5. Configuration ---------------------------------------------------------
step "Configuration"
if [[ -f "$DIR/config.toml" ]]; then
    info "config.toml existe déjà : conservé tel quel."
else
    cp "$DIR/config.example.toml" "$DIR/config.toml"
    info "config.toml créé à partir de config.example.toml."
    # The HDMI sound card is "vc4hdmi" on a Pi 3 but "vc4hdmi0" on a Pi 4.
    hdmi_audio="$(aplay -L 2>/dev/null | grep -m1 '^hdmi:CARD=vc4hdmi' || true)"
    if [[ -n "$hdmi_audio" ]]; then
        sed -i "s|alsa/hdmi:CARD=vc4hdmi,DEV=0|alsa/$hdmi_audio|" "$DIR/config.toml"
        info "Son HDMI : $hdmi_audio"
    else
        info "Attention : pas de sortie son HDMI détectée, à régler dans config.toml (mpv_args)."
    fi
fi

# --- 6. Dossier des chaînes ---------------------------------------------------
step "Dossier des chaînes : $CHANNELS_DIR"
sudo install -d -o "$USER_NAME" -g "$USER_NAME" "$CHANNELS_DIR"
info "Un sous-dossier par chaîne, par exemple $CHANNELS_DIR/01 - Dessins animés/"

# --- 7. Service systemd -------------------------------------------------------
step "Service de démarrage automatique"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@DIR@|$DIR|g" "$DIR/deploy/easytv.service" \
    | sudo tee "$SERVICE" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --quiet easytv
info "$SERVICE"

# --- 8. Démarrage sans bureau -------------------------------------------------
step "Démarrage en mode TV (sans bureau)"
if [[ "$(systemctl get-default)" == "graphical.target" ]]; then
    sudo systemctl set-default multi-user.target >/dev/null
    sudo systemctl stop display-manager 2>/dev/null || true
    info "Le bureau ne démarre plus automatiquement : l'écran est réservé à EasyTV."
    info "Pour le retrouver : sudo systemctl set-default graphical.target && sudo reboot"
else
    info "Déjà en mode console."
fi

# --- 9. Lancement -------------------------------------------------------------
step "Lancement d'EasyTV"
sudo systemctl restart easytv
sleep 3
if systemctl is-active --quiet easytv; then
    info "EasyTV tourne."
else
    fail "le service ne démarre pas. Voir : journalctl -u easytv -n 50"
fi

cat <<EOF

EasyTV est installé.
  Vidéos     : $CHANNELS_DIR/<chaîne>/   (par SFTP : utilisateur $USER_NAME, port 22)
  Config     : $DIR/config.toml
  Logs       : journalctl -u easytv -f
  Redémarrer : sudo systemctl restart easytv
  Mettre à jour : cd $DIR && git pull && ./install.sh
EOF
