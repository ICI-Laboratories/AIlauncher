#!/usr/bin/env bash
#
# Instalador rápido de LMServ para Ubuntu/Debian
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

command -v sudo >/dev/null 2>&1 || die "Se requiere 'sudo'."
command -v apt-get >/dev/null 2>&1 || die "Este script está pensado para Ubuntu/Debian."

print_info "Iniciando la instalación de LMServ…"

# --- INICIO DE LA CORRECCIÓN ---
print_info "Instalando dependencias del sistema (incluyendo libcurl)..."
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git python3-venv python3-pip build-essential cmake libcurl4-openssl-dev
# --- FIN DE LA CORRECCIÓN ---

if [ -d "$VENV_DIR" ]; then
  print_info "El entorno virtual '$VENV_DIR' ya existe."
else
  print_info "Creando entorno virtual en '$VENV_DIR'…"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

print_info "Actualizando pip/setuptools/wheel…"
python -m pip install -q --upgrade pip setuptools wheel

print_info "Instalando paquetes de Python…"
python -m pip install -q -r requirements.txt
python -m pip install -q -e .

print_success "Dependencias de Python instaladas."

print_info "Compilando llama.cpp…"
USE_CUDA_FLAG="--no-cuda"

if [ "$FORCE_ACCEL" = "cuda" ]; then
  USE_CUDA_FLAG="--cuda"
elif [ "$FORCE_ACCEL" = "cpu" ]; then
  USE_CUDA_FLAG="--no-cuda"
elif command -v nvidia-smi &> /dev/null; then
    if $ASSUME_YES; then
      USE_CUDA_FLAG="--cuda"
    else
      read -r -p "GPU NVIDIA detectada. ¿Deseas compilar con soporte CUDA? (s/n) " REPLY
      if [[ "$REPLY" =~ ^[Ss]$ ]]; then
        USE_CUDA_FLAG="--cuda"
      fi
    fi
fi

lmserv install llama --output-dir build "$USE_CUDA_FLAG"
print_success "llama.cpp compilado correctamente."

echo
print_success "¡Instalación completa!"
echo
print_info "Para usar el servidor:"
cat <<'EOF'

PASO 1: Activa el entorno virtual
   source env/bin/activate

PASO 2: Lanza el servidor con un modelo de Hugging Face
   export API_KEY=mysecret
   lmserv serve -m ggml-org/gemma-3-1b-it-GGUF
EOF