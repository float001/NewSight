#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

.venv/bin/python3 -m vulnwatch --config config.yaml "$@"

# Auto upload generated news markdown to GitHub
# Token should be provided via env: NewSight_GITHUB_TOKEN
if [[ -n "${NewSight_GITHUB_TOKEN:-}" ]]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git add content >/dev/null 2>&1 || true
    if ! git diff --cached --quiet -- content; then
      ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      # Avoid writing git config; set identity per command
      git -c user.name="float001" -c user.email="float0001@gmail.com" \
        commit -m "chore(content): update news (${ts})" >/dev/null 2>&1 || true

      origin="$(git remote get-url origin 2>/dev/null || true)"
      if [[ "$origin" == https://github.com/* ]]; then
        authed_origin="https://x-access-token:${NewSight_GITHUB_TOKEN}@${origin#https://}"
        git push "$authed_origin" HEAD:main >/dev/null 2>&1 || true
      else
        # Fallback: rely on existing auth (SSH / credential helper)
        git push origin HEAD:main >/dev/null 2>&1 || true
      fi
    fi
  fi
fi

