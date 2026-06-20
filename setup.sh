#!/usr/bin/env bash
# =============================================================================
# setup.sh — NovaPlusBank local development setup
# Run once after cloning, or any time you pull schema changes.
# For DEBUG=True (local), nothing extra is needed for static files —
# Django's built-in dev server serves them automatically.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[ OK ]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
die()   { echo -e "\033[1;31m[ERR ]\033[0m  $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Ensure we're in the project root (same directory as manage.py)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

[[ -f manage.py ]] || die "manage.py not found. Run this script from the project root."

# ---------------------------------------------------------------------------
# 1. Determine DEBUG mode from .env (default: True for local)
# ---------------------------------------------------------------------------
DEBUG_VALUE="True"
if [[ -f .env ]]; then
    _debug=$(grep -E '^DEBUG=' .env | cut -d= -f2 | tr -d '[:space:]"'"'" || true)
    [[ -n "$_debug" ]] && DEBUG_VALUE="$_debug"
fi

info "DEBUG = $DEBUG_VALUE"

# ---------------------------------------------------------------------------
# 2. Python / venv check
# ---------------------------------------------------------------------------
if [[ -d .venv ]]; then
    info "Activating existing virtual environment (.venv)"
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif command -v python3 &>/dev/null; then
    warn "No .venv found — using system python3. Consider: python3 -m venv .venv"
else
    die "python3 not found. Please install Python 3.10+."
fi

# ---------------------------------------------------------------------------
# 3. Install / upgrade dependencies
# ---------------------------------------------------------------------------
info "Installing Python dependencies..."

if [[ -f requirements.txt ]]; then
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
else
    warn "requirements.txt not found — skipping pip install."
fi

# Make sure django-environ is available (needed by settings.py)
python -c "import environ" 2>/dev/null || {
    info "Installing django-environ..."
    pip install --quiet django-environ
}

# Make sure whitenoise is available (needed in prod; harmless in dev)
python -c "import whitenoise" 2>/dev/null || {
    info "Installing whitenoise..."
    pip install --quiet whitenoise
}

# Make sure psycopg2 is available (needed in prod; harmless in dev)
python -c "import psycopg2" 2>/dev/null || {
    info "Installing psycopg2-binary..."
    pip install --quiet psycopg2-binary
}

ok "Dependencies ready."

# ---------------------------------------------------------------------------
# 4. Ensure a .env file exists for local dev
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
    warn ".env not found. Creating a minimal local .env with DEBUG=True..."
    cat > .env <<'EOF'
DEBUG=True
SECRET_KEY=django-insecure-local-dev-key-change-me
ALLOWED_HOSTS=localhost,127.0.0.1
SITE_ID=1
DEFAULT_FROM_EMAIL=NovaPlusBank <noreply@novaplusbank.com>
TIME_ZONE=UTC
EOF
    ok ".env created. Edit it to add production values when needed."
fi

# ---------------------------------------------------------------------------
# 5. Run migrations
# ---------------------------------------------------------------------------
info "Running database migrations..."
python manage.py migrate --run-syncdb
ok "Migrations complete."

# ---------------------------------------------------------------------------
# 6. Static files
#    - DEBUG=True  → Django dev server serves static files automatically.
#                    collectstatic is NOT needed and would clutter the repo.
#    - DEBUG=False → collectstatic is required (WhiteNoise serves from STATIC_ROOT).
# ---------------------------------------------------------------------------
if [[ "$DEBUG_VALUE" == "False" || "$DEBUG_VALUE" == "0" ]]; then
    info "Production mode: running collectstatic..."
    python manage.py collectstatic --noinput
    ok "Static files collected to staticfiles/."
else
    info "Development mode: skipping collectstatic (Django dev server handles it)."
fi

# ---------------------------------------------------------------------------
# 7. Create a default superuser (local only, skipped in prod)
# ---------------------------------------------------------------------------
if [[ "$DEBUG_VALUE" == "True" || "$DEBUG_VALUE" == "1" ]]; then
    info "Creating superuser (if none exists)..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser(email='admin@novaplusbank.com', password='admin')
    print('Superuser created: admin@novaplusbank.com / admin')
else:
    print('Superuser already exists — skipping.')
"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
ok "Setup complete!"
if [[ "$DEBUG_VALUE" == "True" || "$DEBUG_VALUE" == "1" ]]; then
    echo ""
    echo "  Start the dev server with:"
    echo "    python manage.py runserver"
    echo ""
fi