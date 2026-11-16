#!/usr/bin/env bash
# hq.sh: call any Message Centre tool from a Claude project session (no MCP needed).
#   hq.sh doctor                      checks env, network and token; prints only ok / the problem, never the token
#   hq.sh <tool> ['<json args>']      POST $HQ_URL/hq/<tool>, prints the JSON answer (exit 1 when ok is false)
# Needs HQ_URL (https://hq.zenkio.uk, host only) and HQ_TOKEN in the environment, and the host allowed in the network policy.
set -u
die() { echo "hq: $*" >&2; exit 2; }
[ -n "${HQ_URL:-}" ] || die "HQ_URL is not set (environment setting of this project's cloud environment; new settings only reach NEW sessions)"
[ -n "${HQ_TOKEN:-}" ] || die "HQ_TOKEN is not set (environment setting; ask Iman or Zenkio to add this agent's token there, never paste it in chat)"
HQ_URL="${HQ_URL%/}"
call() { # tool json -> body on stdout, http status on fd 3
  curl -sS --max-time 20 -o - -w '\n%{http_code}' -X POST "$HQ_URL/hq/$1" \
    -H "Authorization: Bearer $HQ_TOKEN" -H 'content-type: application/json' -d "$2" 2>&1
}
tool="${1:-}"; [ -n "$tool" ] || die "usage: hq.sh doctor | hq.sh <tool> ['<json>']"
if [ "$tool" = doctor ]; then
  out=$(call hq_whoami '{}'); code="${out##*$'\n'}"; body="${out%$'\n'*}"
  case "$code" in
    200) echo "hq: ok ($(printf '%s' "$body" | sed -n 's/.*"project_id":"\([^"]*\)".*/\1/p;s/.*"me":"\([^"]*\)".*/\1/p' | head -1))"; exit 0 ;;
    401) die "token rejected (401): revoked, mistyped, or this agent's name is not in the register. Ask Iman for a new token." ;;
    403|000|"") die "cannot reach $HQ_URL (code ${code:-none}): the host is probably not in the environment's network allowlist, or the path hit the Access login. Allow the host hq.zenkio.uk." ;;
    *) die "unexpected answer $code from $HQ_URL" ;;
  esac
fi
out=$(call "$tool" "${2:-{\}}"); code="${out##*$'\n'}"; body="${out%$'\n'*}"
printf '%s\n' "$body"
case "$code" in 200) printf '%s' "$body" | grep -q '"ok":false' && exit 1; exit 0 ;; 401) die "token rejected (401)" ;; *) exit 1 ;; esac
