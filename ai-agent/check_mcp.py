#!/usr/bin/env python3
"""
Диагностика подключения к Graylog MCP.
Запуск: python check_mcp.py
Показывает полный ответ сервера и помогает найти причину ошибки.
"""

import base64
import json
import os
import sys
from pathlib import Path

# Загрузка .env
_root = Path(__file__).parent.parent  # LogsAi/
try:
    from dotenv import load_dotenv
    load_dotenv(_root / ".env")
    load_dotenv(_root.parent / "yandexGptCli" / "src" / ".env")
except ImportError:
    pass

import httpx


def main():
    url = os.getenv("GRAYLOG_MCP_URL", "http://127.0.0.1:9000/api/mcp")
    auth_raw = (os.getenv("GRAYLOG_MCP_AUTH") or "").strip()

    print("=" * 60)
    print("Graylog MCP — диагностика")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"GRAYLOG_MCP_AUTH: {auth_raw[:50]}..." if len(auth_raw) > 50 else f"GRAYLOG_MCP_AUTH: '{auth_raw}'")
    print()

    # Проверка формата auth
    auth_value = ""
    if auth_raw.lower().startswith("basic "):
        auth_value = auth_raw[6:].strip()  # после "Basic "
        # Base64: обычно A-Za-z0-9+/=, часто заканчивается на = или ==
        # Сырой токен: только буквы/цифры, без +/=
        has_base64_chars = "+/" in auth_value or auth_value.endswith("=")
        is_likely_base64 = has_base64_chars or (
            len(auth_value) >= 20
            and len(auth_value) % 4 == 0
            and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in auth_value)
        )
        if not is_likely_base64 and len(auth_value) > 30:
            print("⚠️  ВНИМАНИЕ: значение после 'Basic' похоже на сырой API-токен, а не на Base64!")
            print("   Graylog ожидает: Authorization: Basic <base64(TOKEN:token)>")
            print()
            fixed_b64 = base64.b64encode(f"{auth_value}:token".encode()).decode()
            print("   ИСПРАВЛЕНИЕ: закодируйте токен так:")
            print("   echo -n 'YOUR_API_TOKEN:token' | base64 -w0")
            print()
            print(f"   Для вашего токена правильное значение:")
            print(f"   GRAYLOG_MCP_AUTH=Basic {fixed_b64}")
            print()
            print("   Пробуем с исправленным auth...")
            auth_raw = f"Basic {fixed_b64}"
            headers = {"Content-Type": "application/json", "Authorization": auth_raw}
        else:
            headers = {"Content-Type": "application/json"}
            if auth_raw:
                headers["Authorization"] = auth_raw
    else:
        headers = {"Content-Type": "application/json"}
        if auth_raw:
            headers["Authorization"] = auth_raw

    # Graylog 7.x поддерживает 2025-06-18 (см. ответ сервера при ошибке)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "logs-ai-check", "version": "1.0"},
        },
    }

    print("Запрос (initialize):")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print()

    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=10)
        print(f"Ответ: HTTP {r.status_code}")
        print(f"Headers: {dict(r.headers)}")
        print()
        ct = r.headers.get("content-type", "")
        if "application/json" in ct:
            try:
                data = r.json()
                print("Body (JSON):")
                print(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception:
                print("Body (raw):", r.text[:1000])
        else:
            print("Body (raw):", r.text[:1000])
        print()

        if r.status_code == 200:
            print("✅ MCP подключение успешно!")
            sys.exit(0)
        elif r.status_code == 401:
            print("❌ 401 Unauthorized — неверные учётные данные.")
            print("   Проверьте GRAYLOG_MCP_AUTH. Должен быть Base64 от 'TOKEN:token'.")
        elif r.status_code == 400:
            print("❌ 400 Bad Request — сервер отклонил запрос.")
            err = r.json() if "application/json" in ct else {}
            msg = err.get("message") or err.get("error", {}).get("message") or r.text[:200]
            print(f"   Сообщение: {msg}")
        else:
            print(f"❌ Ошибка HTTP {r.status_code}")
        sys.exit(1)

    except httpx.ConnectError as e:
        print(f"❌ Ошибка подключения: {e}")
        print("   Graylog запущен? Доступен ли http://127.0.0.1:9000 ?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Исключение: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
