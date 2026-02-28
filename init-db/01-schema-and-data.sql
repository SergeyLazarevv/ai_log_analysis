-- Таблицы и тестовые данные для Logs AI (Graylog + Postgres MCP)
-- Запускается при первом старте контейнера postgres из /docker-entrypoint-initdb.d

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    total_cents INTEGER NOT NULL,
    status      VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 10 пользователей
INSERT INTO users (id, email, name) VALUES
(1, 'alex.ivanov@example.com', 'Алексей Иванов'),
(2, 'maria.petrova@example.com', 'Мария Петрова'),
(3, 'dmitry.sidorov@example.com', 'Дмитрий Сидоров'),
(4, 'elena.kozлова@example.com', 'Елена Козлова'),
(5, 'sergey.novikov@example.com', 'Сергей Новиков'),
(6, 'anna.morozova@example.com', 'Анна Морозова'),
(7, 'andrey.volkov@example.com', 'Андрей Волков'),
(8, 'olga.sokolova@example.com', 'Ольга Соколова'),
(9, 'nikolay.lebedev@example.com', 'Николай Лебедев'),
(10, 'irina.popova@example.com', 'Ирина Попова')
ON CONFLICT (id) DO NOTHING;

-- Сброс последовательности для id (если вставляли с явным id)
SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 1) FROM users));

-- 10 заказов (привязка к user_id 1..10)
INSERT INTO orders (user_id, total_cents, status) VALUES
(1, 150000, 'completed'),
(2, 89000, 'completed'),
(3, 210000, 'pending'),
(4, 45000, 'completed'),
(5, 120000, 'shipped'),
(6, 67000, 'completed'),
(7, 189000, 'cancelled'),
(8, 32000, 'completed'),
(9, 95000, 'pending'),
(10, 110000, 'completed');
