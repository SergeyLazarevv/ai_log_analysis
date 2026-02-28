# Инициализация PostgreSQL

Скрипты из этой папки выполняются при **первом** запуске контейнера `postgres` (volume пустой).

- **01-schema-and-data.sql** — создаёт таблицы `users` и `orders`, заполняет 10 пользователей и 10 заказов (фейковые данные для демо и Postgres MCP).

Подключение к БД: UI Adminer http://127.0.0.1:8080 — в форме входа **Сервер** должен быть `postgres` (имя сервиса в Docker), не 0.0.0.0 и не localhost. Логин/пароль/БД из `LogsAi/.env` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`).
