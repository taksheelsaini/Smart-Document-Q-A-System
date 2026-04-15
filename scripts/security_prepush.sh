#!/usr/bin/env bash
set -euo pipefail

echo "[1/3] Verify .env is ignored and untracked"
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "ERROR: .env is tracked in git. Remove it before push."
  exit 1
fi
if ! git check-ignore .env >/dev/null 2>&1; then
  echo "ERROR: .env is not ignored by gitignore."
  exit 1
fi

echo "[2/3] Secret pattern scan on tracked files"
SECRET_REGEX='(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----|xoxb-[0-9A-Za-z-]{20,})'
if git grep -nE "$SECRET_REGEX" -- . >/tmp/docqa_secret_hits.txt; then
  echo "ERROR: potential secret(s) found in tracked files"
  cat /tmp/docqa_secret_hits.txt
  exit 1
fi

echo "[3/3] Optional security tools"
if command -v pip-audit >/dev/null 2>&1; then
  pip-audit -r requirements.txt || true
else
  echo "WARN: pip-audit not installed locally"
fi
if command -v bandit >/dev/null 2>&1; then
  bandit -q -r app || true
else
  echo "WARN: bandit not installed locally"
fi

echo "Security pre-push checks passed."
