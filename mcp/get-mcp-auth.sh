#!/usr/bin/env bash
# Генерирует строку для заголовка Authorization: Basic ... для Graylog MCP.
# Использование: ./get-mcp-auth.sh YOUR_API_TOKEN
# Или: echo "YOUR_API_TOKEN" | xargs -I{} ./get-mcp-auth.sh {}
set -e
TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "Использование: $0 <GRAYLOG_API_TOKEN>" >&2
  echo "Получить токен: Graylog → System → Users and Teams → Tokens" >&2
  exit 1
fi
echo -n "${TOKEN}:token" | base64 -w0
echo
