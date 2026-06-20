#!/usr/bin/env bash
# =============================================================================
# setup.sh — NovaPlusBank setup
# Works for both local dev and Render production.
# =============================================================================

set -euo pipefail

info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[ OK ]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
die()   { echo -e "\033[1;31m[ERR ]\033[0m  $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Project root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
[[ -f manage.py ]] || die "manage.py not found. Run from project root."

# ---------------------------------------------------------------------------
# 1. Determine DEBUG
#    Priority: environment variable > .env file > default True (local)
# ---------------------------------------------------------------------------
if [[ -n "${DEBUG:-}" ]]; then
    # Already set in environment (Render sets this via dashboard env vars)
    DEBUG_VALUE="$DEBUG"
elif [[ -f .env ]]; then
    _debug=$(grep -E '^DEBUG=' .env | cut -d= -f2 | tr -d '[:space:]"'"'" || true)
    DEBUG_VALUE="${_debug:-True}"
else
    DEBUG_VALUE="True"
fi

info "DEBUG = $DEBUG_VALUE"

# ---------------------------------------------------------------------------
# 2. Python / venv
# ---------------------------------------------------------------------------
if [[ -d .venv ]]; then
    info "Activating virtual environment (.venv)"
    source .venv/bin/activate
elif command -v python3 &>/dev/null; then
    warn "No .venv found — using system python3."
else
    die "python3 not found."
fi

# ---------------------------------------------------------------------------
# 3. Dependencies
# ---------------------------------------------------------------------------
info "Installing dependencies..."
if [[ -f pyproject.toml ]] && command -v uv &>/dev/null; then
    uv sync
elif [[ -f requirements.txt ]]; then
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
else
    warn "No pyproject.toml or requirements.txt found — skipping."
fi
ok "Dependencies ready."

# ---------------------------------------------------------------------------
# 4. Create .env for local dev only (never on Render — it has env vars set)
# ---------------------------------------------------------------------------
if [[ ! -f .env && "$DEBUG_VALUE" != "False" && "$DEBUG_VALUE" != "0" ]]; then
    warn ".env not found. Creating minimal local .env..."
    cat > .env <<'EOF'
DEBUG=True
SECRET_KEY=django-insecure-local-dev-key-change-me
ALLOWED_HOSTS=localhost,127.0.0.1
SITE_ID=1
DEFAULT_FROM_EMAIL=NovaPlusBank <noreply@novaplusbank.com>
TIME_ZONE=UTC
EOF
    ok ".env created for local dev."
fi

# ---------------------------------------------------------------------------
# 5. Migrations
# ---------------------------------------------------------------------------
info "Running migrations..."
python manage.py migrate --run-syncdb
ok "Migrations complete."

# ---------------------------------------------------------------------------
# 6. Static files — only in production
# ---------------------------------------------------------------------------
if [[ "$DEBUG_VALUE" == "False" || "$DEBUG_VALUE" == "0" ]]; then
    info "Production: running collectstatic..."
    python manage.py collectstatic --noinput
    ok "Static files collected."
else
    info "Dev mode: skipping collectstatic."
fi

# ---------------------------------------------------------------------------
# 7. Superuser — local only
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

echo ""
ok "Setup complete!"
if [[ "$DEBUG_VALUE" == "True" || "$DEBUG_VALUE" == "1" ]]; then
    echo "  Run: python manage.py runserver"
    echo ""
fi