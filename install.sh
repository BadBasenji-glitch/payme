#!/bin/bash
#
# payme Installation Script
# Run this on your Home Assistant host
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/yourrepo/payme/main/install.sh | bash
#   or
#   ./install.sh
#
# Supported platforms:
#   - Home Assistant OS (Green, Yellow, generic x86/RPi)
#   - Home Assistant Supervised
#   - Home Assistant Container
#   - Home Assistant Core
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Version requirements
MIN_HA_VERSION="2021.9.0"
MIN_PYTHON_VERSION="3.9"

# Configuration
HA_CONFIG="${HA_CONFIG:-/config}"
PAYME_SCRIPTS="$HA_CONFIG/scripts/payme"
PAYME_PYSCRIPT="$HA_CONFIG/pyscript"
PAYME_WWW="$HA_CONFIG/www/payme"
PAYME_STORAGE="$HA_CONFIG/.storage/payme"
PAYME_BACKUP="$HA_CONFIG/backups/payme"

# Source directory (where install.sh is located)
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Installation type (detected)
HA_INSTALL_TYPE="unknown"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                    payme Installer                        ║"
echo "║         Automated Bill Payment for Home Assistant         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Detect Home Assistant installation type
detect_ha_type() {
    echo -e "${BLUE}[0/8]${NC} Detecting Home Assistant installation..."

    # Check for Home Assistant OS indicators
    if [[ -f /etc/alpine-release ]] && [[ -d /config ]]; then
        if command -v ha &> /dev/null; then
            HA_INSTALL_TYPE="os"
            echo -e "  ${GREEN}✓${NC} Home Assistant OS detected"

            # Try to detect hardware
            if [[ -f /etc/haos-release ]]; then
                local board=$(grep BOARD /etc/haos-release 2>/dev/null | cut -d= -f2)
                if [[ -n "$board" ]]; then
                    echo -e "  ${CYAN}ℹ${NC} Hardware: $board"
                fi
            fi
        else
            HA_INSTALL_TYPE="container"
            echo -e "  ${GREEN}✓${NC} Home Assistant Container detected (Alpine)"
        fi
    # Check for Supervised
    elif [[ -f /etc/hassio.json ]] || [[ -d /usr/share/hassio ]]; then
        HA_INSTALL_TYPE="supervised"
        echo -e "  ${GREEN}✓${NC} Home Assistant Supervised detected"
    # Check for Container on Debian/Ubuntu
    elif [[ -f /etc/debian_version ]] && [[ -d /config ]]; then
        HA_INSTALL_TYPE="container"
        echo -e "  ${GREEN}✓${NC} Home Assistant Container detected (Debian)"
    # Check for Core installation
    elif [[ -d "$HOME/.homeassistant" ]] || [[ -n "$VIRTUAL_ENV" ]]; then
        HA_INSTALL_TYPE="core"
        if [[ -z "$HA_CONFIG" ]] || [[ "$HA_CONFIG" == "/config" ]]; then
            HA_CONFIG="$HOME/.homeassistant"
        fi
        echo -e "  ${GREEN}✓${NC} Home Assistant Core detected"
        echo -e "  ${CYAN}ℹ${NC} Config path: $HA_CONFIG"
    else
        echo -e "  ${YELLOW}!${NC} Could not detect installation type"
        echo -e "  ${CYAN}ℹ${NC} Assuming standard paths (/config)"
    fi

    # Update paths if HA_CONFIG changed
    PAYME_SCRIPTS="$HA_CONFIG/scripts/payme"
    PAYME_PYSCRIPT="$HA_CONFIG/pyscript"
    PAYME_WWW="$HA_CONFIG/www/payme"
    PAYME_STORAGE="$HA_CONFIG/.storage/payme"
    PAYME_BACKUP="$HA_CONFIG/backups/payme"
}

# Check Python version
check_python_version() {
    if command -v python3 &> /dev/null; then
        local py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        local py_major=$(echo "$py_version" | cut -d. -f1)
        local py_minor=$(echo "$py_version" | cut -d. -f2)

        if [[ $py_major -ge 3 ]] && [[ $py_minor -ge 9 ]]; then
            echo -e "  ${GREEN}✓${NC} Python $py_version (meets minimum $MIN_PYTHON_VERSION)"
            return 0
        else
            echo -e "  ${RED}✗${NC} Python $py_version (requires $MIN_PYTHON_VERSION+)"
            return 1
        fi
    else
        echo -e "  ${RED}✗${NC} Python 3 not found"
        return 1
    fi
}

# Check if running as correct user
check_permissions() {
    if [[ ! -w "$HA_CONFIG" ]]; then
        echo -e "${RED}Error: Cannot write to $HA_CONFIG${NC}"
        echo "Make sure you have write permissions to the Home Assistant config directory."
        echo ""
        echo "If using Home Assistant OS, run this from the Terminal add-on."
        echo "If using Container/Core, you may need sudo."
        exit 1
    fi
}

# Create directory structure
create_directories() {
    echo -e "${BLUE}[1/8]${NC} Creating directory structure..."

    mkdir -p "$PAYME_SCRIPTS"
    mkdir -p "$PAYME_PYSCRIPT/modules/payme"
    mkdir -p "$PAYME_WWW"
    mkdir -p "$PAYME_STORAGE"
    mkdir -p "$PAYME_BACKUP"

    echo -e "  ${GREEN}✓${NC} $PAYME_SCRIPTS"
    echo -e "  ${GREEN}✓${NC} $PAYME_PYSCRIPT/modules/payme"
    echo -e "  ${GREEN}✓${NC} $PAYME_WWW"
    echo -e "  ${GREEN}✓${NC} $PAYME_STORAGE"
    echo -e "  ${GREEN}✓${NC} $PAYME_BACKUP"
}

# Copy Python scripts
copy_scripts() {
    echo -e "${BLUE}[2/8]${NC} Copying Python scripts..."

    local scripts=(
        "config.py"
        "storage.py"
        "formatting.py"
        "http_client.py"
        "iban.py"
        "dedup.py"
        "girocode.py"
        "gemini.py"
        "google_photos.py"
        "wise.py"
        "notify.py"
        "poll.py"
        "authorize_google.py"
        "update_bic_db.py"
    )

    for script in "${scripts[@]}"; do
        if [[ -f "$SOURCE_DIR/$script" ]]; then
            cp "$SOURCE_DIR/$script" "$PAYME_SCRIPTS/"
            echo -e "  ${GREEN}✓${NC} $script"
        else
            echo -e "  ${RED}✗${NC} $script (not found)"
        fi
    done

    # Make scripts executable
    chmod +x "$PAYME_SCRIPTS"/*.py 2>/dev/null || true
}

# Copy pyscript files
copy_pyscript() {
    echo -e "${BLUE}[3/8]${NC} Copying pyscript integration..."

    if [[ -f "$SOURCE_DIR/pyscript/modules/payme/__init__.py" ]]; then
        cp "$SOURCE_DIR/pyscript/modules/payme/__init__.py" "$PAYME_PYSCRIPT/modules/payme/"
        echo -e "  ${GREEN}✓${NC} modules/payme/__init__.py"
    fi

    if [[ -f "$SOURCE_DIR/pyscript/modules/payme/entities.py" ]]; then
        cp "$SOURCE_DIR/pyscript/modules/payme/entities.py" "$PAYME_PYSCRIPT/modules/payme/"
        echo -e "  ${GREEN}✓${NC} modules/payme/entities.py"
    fi

    if [[ -f "$SOURCE_DIR/pyscript/payme_triggers.py" ]]; then
        cp "$SOURCE_DIR/pyscript/payme_triggers.py" "$PAYME_PYSCRIPT/"
        echo -e "  ${GREEN}✓${NC} payme_triggers.py"
    fi
}

# Copy dashboard files
copy_dashboard() {
    echo -e "${BLUE}[4/8]${NC} Copying dashboard card..."

    if [[ -f "$SOURCE_DIR/www/payme/payme-card.js" ]]; then
        cp "$SOURCE_DIR/www/payme/payme-card.js" "$PAYME_WWW/"
        echo -e "  ${GREEN}✓${NC} payme-card.js"
    fi
}

# Check Python dependencies
check_dependencies() {
    echo -e "${BLUE}[5/8]${NC} Checking dependencies..."

    local missing=()
    local qr_missing=false

    # Check Python version
    check_python_version || missing+=("python3.9+")

    # Check for pyzbar (optional, for QR codes)
    if python3 -c "import pyzbar" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} pyzbar installed"
    else
        echo -e "  ${YELLOW}!${NC} pyzbar not installed (QR detection disabled)"
        qr_missing=true
    fi

    # Check for cv2 (optional, for QR codes)
    if python3 -c "import cv2" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} opencv installed"
    else
        echo -e "  ${YELLOW}!${NC} opencv not installed (QR detection disabled)"
        qr_missing=true
    fi

    # Check for libzbar (platform-specific check)
    local zbar_found=false
    if [[ -f /usr/lib/libzbar.so.0 ]] || [[ -f /usr/lib/libzbar.so ]]; then
        zbar_found=true
    elif ldconfig -p 2>/dev/null | grep -q libzbar; then
        zbar_found=true
    elif [[ -f /usr/lib/aarch64-linux-gnu/libzbar.so.0 ]]; then
        zbar_found=true  # ARM64
    elif command -v apk &>/dev/null && apk info zbar 2>/dev/null | grep -q zbar; then
        zbar_found=true  # Alpine
    fi

    if $zbar_found; then
        echo -e "  ${GREEN}✓${NC} libzbar found"
    else
        echo -e "  ${YELLOW}!${NC} libzbar not found (QR detection disabled)"
        qr_missing=true
    fi

    # Show platform-specific install instructions for QR dependencies
    if $qr_missing; then
        echo ""
        echo -e "  ${CYAN}To enable QR code detection, install:${NC}"
        case "$HA_INSTALL_TYPE" in
            os)
                echo -e "    ${CYAN}# Run in Terminal add-on:${NC}"
                echo -e "    apk add zbar"
                echo -e "    pip install pyzbar opencv-python-headless"
                echo ""
                echo -e "  ${YELLOW}Note: These packages may need reinstalling after HA updates${NC}"
                ;;
            supervised|container)
                if [[ -f /etc/alpine-release ]]; then
                    echo -e "    apk add zbar"
                    echo -e "    pip install pyzbar opencv-python-headless"
                else
                    echo -e "    apt-get install libzbar0"
                    echo -e "    pip install pyzbar opencv-python-headless"
                fi
                ;;
            core)
                echo -e "    # System package:"
                echo -e "    sudo apt-get install libzbar0  # Debian/Ubuntu"
                echo -e "    # or: brew install zbar        # macOS"
                echo -e ""
                echo -e "    # Python packages (in your venv):"
                echo -e "    pip install pyzbar opencv-python-headless"
                ;;
            *)
                echo -e "    pip install pyzbar opencv-python-headless"
                echo -e "    # Plus system zbar library for your platform"
                ;;
        esac
        echo ""
        echo -e "  ${CYAN}payme will use Gemini OCR for all bills until QR is available${NC}"
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Missing required dependencies: ${missing[*]}${NC}"
        exit 1
    fi
}

# Initialize BIC database
init_bic_database() {
    echo -e "${BLUE}[6/8]${NC} Initializing BIC database..."

    if [[ -f "$PAYME_STORAGE/bic_db.json" ]]; then
        echo -e "  ${YELLOW}!${NC} BIC database already exists, skipping"
    else
        cd "$PAYME_SCRIPTS"
        if python3 update_bic_db.py 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} BIC database initialized"
        else
            echo -e "  ${YELLOW}!${NC} Could not initialize BIC database (will retry on first use)"
        fi
    fi
}

# Generate configuration template
generate_config() {
    echo -e "${BLUE}[7/8]${NC} Generating configuration templates..."

    # Check if pyscript config exists
    if grep -q "pyscript:" "$HA_CONFIG/configuration.yaml" 2>/dev/null; then
        echo -e "  ${YELLOW}!${NC} pyscript already configured in configuration.yaml"
    else
        cat >> "$HA_CONFIG/configuration.yaml" << 'EOF'

# payme - Automated Bill Payment
pyscript:
  allow_all_imports: true
  hass_is_global: true
  apps:
    payme:
      gemini_api_key: !secret payme_gemini_api_key
      wise_api_token: !secret payme_wise_api_token
      wise_profile_id: !secret payme_wise_profile_id
      album_name: "bill-pay"
      notify_service: "mobile_app_phone"  # Change to your device
EOF
        echo -e "  ${GREEN}✓${NC} Added pyscript config to configuration.yaml"
    fi

    # Create secrets template if needed
    if [[ ! -f "$PAYME_STORAGE/secrets_template.yaml" ]]; then
        cat > "$PAYME_STORAGE/secrets_template.yaml" << 'EOF'
# Add these lines to your /config/secrets.yaml file:

payme_gemini_api_key: "your-gemini-api-key-here"
payme_wise_api_token: "your-wise-api-token-here"
payme_wise_profile_id: "your-wise-profile-id-here"
EOF
        echo -e "  ${GREEN}✓${NC} Created secrets template at $PAYME_STORAGE/secrets_template.yaml"
    fi
}

# Print next steps
print_next_steps() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              Installation Complete!                       ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Show detected platform
    case "$HA_INSTALL_TYPE" in
        os)
            echo -e "  ${CYAN}Platform: Home Assistant OS${NC}"
            ;;
        supervised)
            echo -e "  ${CYAN}Platform: Home Assistant Supervised${NC}"
            ;;
        container)
            echo -e "  ${CYAN}Platform: Home Assistant Container${NC}"
            ;;
        core)
            echo -e "  ${CYAN}Platform: Home Assistant Core${NC}"
            ;;
    esac
    echo -e "  ${CYAN}Config: $HA_CONFIG${NC}"
    echo ""

    echo -e "${YELLOW}Next Steps:${NC}"
    echo ""
    echo "1. Add secrets to $HA_CONFIG/secrets.yaml:"
    echo "   (see template at $PAYME_STORAGE/secrets_template.yaml)"
    echo ""
    echo -e "   ${BLUE}payme_gemini_api_key:${NC} Get from https://makersuite.google.com/app/apikey"
    echo -e "   ${BLUE}payme_wise_api_token:${NC} Get from https://wise.com/settings/api-tokens"
    echo -e "   ${BLUE}payme_wise_profile_id:${NC} Visible in Wise dashboard URL"
    echo ""
    echo "2. Set up Google OAuth:"
    echo "   cd $PAYME_SCRIPTS"
    echo "   export GOOGLE_CLIENT_ID='your-client-id'"
    echo "   export GOOGLE_CLIENT_SECRET='your-secret'"
    echo "   python3 authorize_google.py"
    echo ""
    echo "3. Create 'bill-pay' album in Google Photos"
    echo ""
    echo "4. Update notify_service in configuration.yaml"
    echo "   (change 'mobile_app_phone' to your device name)"
    echo ""
    echo "5. Add dashboard card to Lovelace:"
    echo "   resources:"
    echo "     - url: /local/payme/payme-card.js"
    echo "       type: module"
    echo ""

    # Platform-specific restart command
    echo "6. Restart Home Assistant:"
    case "$HA_INSTALL_TYPE" in
        os|supervised)
            echo "   ha core restart"
            ;;
        container)
            echo "   docker restart homeassistant"
            ;;
        core)
            echo "   systemctl restart home-assistant@homeassistant"
            echo "   # or restart your HA process manually"
            ;;
        *)
            echo "   # Restart your Home Assistant instance"
            ;;
    esac
    echo ""
    echo -e "${BLUE}Documentation:${NC} See INSTALL.md for detailed instructions"
    echo ""
}

# Uninstall function
uninstall() {
    echo -e "${YELLOW}Uninstalling payme...${NC}"

    read -p "This will remove all payme files. Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi

    rm -rf "$PAYME_SCRIPTS"
    rm -rf "$PAYME_PYSCRIPT/modules/payme"
    rm -f "$PAYME_PYSCRIPT/payme_triggers.py"
    rm -rf "$PAYME_WWW"

    echo -e "${GREEN}payme files removed.${NC}"
    echo ""
    echo "Note: The following were preserved:"
    echo "  - $PAYME_STORAGE (tokens, history)"
    echo "  - $PAYME_BACKUP (backups)"
    echo "  - configuration.yaml entries"
    echo "  - secrets.yaml entries"
    echo ""
    echo "Remove these manually if desired."
}

# Main
main() {
    # Check for uninstall flag
    if [[ "$1" == "--uninstall" || "$1" == "-u" ]]; then
        uninstall
        exit 0
    fi

    # Check for help flag
    if [[ "$1" == "--help" || "$1" == "-h" ]]; then
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  -h, --help       Show this help message"
        echo "  -u, --uninstall  Remove payme installation"
        echo ""
        echo "Environment variables:"
        echo "  HA_CONFIG        Home Assistant config path (default: /config)"
        exit 0
    fi

    detect_ha_type
    check_permissions
    create_directories
    copy_scripts
    copy_pyscript
    copy_dashboard
    check_dependencies
    init_bic_database
    generate_config
    print_next_steps
}

main "$@"
