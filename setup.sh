#!/usr/bin/env bash
#
# Instalador rápido de LMServ para Ubuntu/Debian
# Uso:
#   ./setup.sh [--yes] [--cuda | --cpu]
# Vars opcionales:
#   VENV_DIR (por defecto: env)
#
set -Eeuo pipefail
IFS=$'\n\t'
VENV_DIR="${VENV_DIR:-env}"

print_info()    { echo -e "\n\033[34m[INFO] 🚀 $*\033[0m"; }
print_success() { echo -e "\033[32m[ÉXITO] ✅ $*\033[0m"; }
print_warning() { echo -e "\033[33m[AVISO] ⚠️ $*\033[0m"; }
print_error()   { echo -e "\033[31m[ERROR] ❌ $*\033[0m"; }
die()           { print_error "$*"; exit 1; }
trap 'print_error "Fallo en línea $LINENO. Revisa el log anterior."' ERR

ASSUME_YES=false
FORCE_ACCEL=""

# ── Parseo de flags ───────────────────────────────────────────────────────────
while (($#)); do
  case "$1" in
    -y|--yes) ASSUME_YES=true ;;
    --cuda)   FORCE_ACCEL="cuda" ;;
    --cpu|--no-cuda) FORCE_ACCEL="cpu" ;;
    -h|--help)
      cat <<EOF
Uso: $0 [--yes] [--cuda | --cpu]
  --yes     Ejecuta sin prompts (útil para CI)
  --cuda    Fuerza compilación con CUDA
  --cpu     Fuerza compilación solo CPU
Variables:
  VENV_DIR  Directorio del entorno virtual (default: $VENV_DIR)
EOF
      exit 0;;
    *) die "Argumento no reconocido: $1" ;;
  esac
  shift
done

# ── Prechequeos ───────────────────────────────────────────────────────────────
command -v sudo >/dev/null 2>&1 || die "Se requiere 'sudo'."
command -v apt-get >/dev/null 2>&1 || die "Este script está pensado para Ubuntu/Debian."

print_info "Iniciando la instalación de LMServ…"

# ── Paquetes del sistema ──────────────────────────────────────────────────────
print_info "Instalando dependencias del sistema…"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git python3-venv python3-pip build-essential

# ── Entorno virtual ──────────────────────────────────────────────────────────
if [ -d "$VENV_DIR" ]; then
  print_info "El entorno virtual '$VENV_DIR' ya existe."
else
  print_info "Creando entorno virtual en '$VENV_DIR'…"
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

print_info "Actualizando pip/setuptools/wheel…"
python -m pip install -q --upgrade pip setuptools wheel

print_info "Instalando paquetes de Python…"
if [ -f "requirements.txt" ]; then
  python -m pip install -q -r requirements.txt
else
  print_warning "No se encontró requirements.txt; continúo."
fi

python -m pip install -q -e .
command -v lmserv >/dev/null 2>&1 || die "El comando 'lmserv' no se encontró tras la instalación."

print_success "Dependencias de Python instaladas."

# ── Compilar llama.cpp ───────────────────────────────────────────────────────
print_info "Compilando llama.cpp…"
USE_CUDA_FLAG="--no-cuda"

detect_nvidia=false
command -v nvidia-smi >/dev/null 2>&1 && detect_nvidia=true

if [ "$FORCE_ACCEL" = "cuda" ]; then
  USE_CUDA_FLAG="--cuda"
  print_info "Compilación forzada con CUDA (flag --cuda)."
elif [ "$FORCE_ACCEL" = "cpu" ]; then
  USE_CUDA_FLAG="--no-cuda"
  print_info "Compilación forzada para CPU (flag --cpu)."
else
  if $detect_nvidia; then
    if $ASSUME_YES; then
      USE_CUDA_FLAG="--cuda"
      print_info "GPU NVIDIA detectada; --yes activo ⇒ compilaré con CUDA."
    else
      read -r -p "GPU NVIDIA detectada. ¿Deseas compilar con soporte CUDA? (s/n) " REPLY
      if [[ "$REPLY" =~ ^[Ss]$ ]]; then
        USE_CUDA_FLAG="--cuda"
        print_info "Se compilará con soporte CUDA."
      else
        print_info "Se compilará solo para CPU."
      fi
    fi
  else
    print_warning "No se detectó una GPU NVIDIA. Se compilará solo para CPU."
  fi
fi

lmserv install llama --output-dir . "$USE_CUDA_FLAG"
print_success "llama.cpp compilado correctamente."

# ── Mensaje final ────────────────────────────────────────────────────────────
echo
print_success "¡Instalación completa!"
echo
print_info "Para usar el servidor con un modelo de Hugging Face (descarga automática en el primer uso):"
cat <<'EOF'

PASO 1: Activa el entorno virtual
   source env/bin/activate   # o: source "$VENV_DIR/bin/activate"

PASO 2: Lanza el servidor especificando el modelo
   export API_KEY=mysecret
   lmserv serve -m ggml-org/gemma-3-1b-it-GGUF

Nota:
 - El primer arranque con '-m owner/repo' descargará el modelo a la caché de llama.cpp.
 - Si prefieres un modelo local .gguf, usa: lmserv serve -m /ruta/a/tu/modelo.gguf
EOF
