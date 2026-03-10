<?php
declare(strict_types=1);

/**
 * Генератор демо-логов пользовательского флоу:
 * - успешная регистрация
 * - успешная отправка уведомления
 * - успешная авторизация
 * - несколько типов ошибок с трейсами, ссылающимися на реальный код в GitLab.
 *
 * Требования по Graylog:
 *   System -> Inputs -> GELF UDP (или TCP), порт 12201 (как в docker-compose).
 *
 * Примеры:
 *   php php/graylog_user_flow_seed.php --count=100 --sleep-ms=50
 */

function parseArgs(array $argv): array
{
    $opts = [
        'count'    => 50,
        'sleep_ms' => 50,
    ];

    foreach (array_slice($argv, 1) as $arg) {
        if (!str_starts_with($arg, '--')) {
            fwrite(STDERR, "Unknown argument: {$arg}\n");
            exit(2);
        }
        [$k, $v] = array_pad(explode('=', substr($arg, 2), 2), 2, null);
        if ($v === null) {
            fwrite(STDERR, "Expected --key=value, got: {$arg}\n");
            exit(2);
        }

        switch ($k) {
            case 'count':
                $opts['count'] = max(1, (int)$v);
                break;
            case 'sleep-ms':
                $opts['sleep_ms'] = max(0, (int)$v);
                break;
            default:
                fwrite(STDERR, "Unknown option: --{$k}\n");
                exit(2);
        }
    }

    return $opts;
}

function gelfSend(array $gelf, string $host, int $port, string $proto): void
{
    $payload = json_encode($gelf, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($payload === false) {
        throw new RuntimeException('Failed to JSON-encode GELF payload');
    }

    $target = "{$proto}://{$host}:{$port}";
    $fp = @stream_socket_client($target, $errno, $errstr, 1.0);
    if ($fp === false) {
        throw new RuntimeException("Failed to connect to {$target}: [{$errno}] {$errstr}");
    }
    stream_set_timeout($fp, 1);

    $data = ($proto === 'tcp') ? ($payload . "\0") : $payload;
    $written = fwrite($fp, $data);
    fclose($fp);

    if ($written === false || $written === 0) {
        throw new RuntimeException("Failed to send GELF payload to {$target}");
    }
}

function nowFloat(): float
{
    return microtime(true);
}

function randomUserId(): int
{
    return random_int(1, 1000);
}

function randomOrderId(): int
{
    return random_int(1, 10_000);
}

function buildGelf(
    string $shortMessage,
    int $level,
    array $extraFields = [],
    ?string $facility = 'php-user-flow'
): array {
    $host = gethostname() ?: 'localhost';

    $gelf = [
        'version'       => '1.1',
        'host'          => $host,
        'short_message' => $shortMessage,
        'timestamp'     => nowFloat(),
        'level'         => $level, // 3=error, 4=warning, 6=info
        '_facility'     => $facility,
        '_app'          => 'user-service',
        '_env'          => 'local',
    ];

    foreach ($extraFields as $k => $v) {
        $k = ltrim((string)$k);
        if ($k === '') {
            continue;
        }
        $key       = str_starts_with($k, '_') ? $k : ('_' . $k);
        $gelf[$key] = $v;
    }

    return $gelf;
}

/**
 * Стектрейсы, связанные с реальными путями в GitLab.
 *
 * ВАЖНО: создайте в GitLab проект с такими же путями файлов, например:
 *   app/Services/User/RegistrationService.php
 *   app/Services/Notification/EmailNotifier.php
 *   app/Http/Controllers/Auth/LoginController.php
 * Тогда агент сможет взять путь + строку из трейса и вызвать gitlab_get_file.
 */
function getStackTrace(string $type, int $userId, int $orderId): string
{
    switch ($type) {
        case 'registration_db':
            return <<<TRACE
PDOException: SQLSTATE[40001]: Serialization failure: 1213 Deadlock found when trying to get lock in /var/www/html/vendor/laravel/framework/src/Illuminate/Database/Connection.php:712

Stack trace:
#0 /var/www/html/vendor/laravel/framework/src/Illuminate/Database/Connection.php(712): PDOStatement->execute()
#1 /var/www/html/vendor/laravel/framework/src/Illuminate/Database/Connection.php(671): Illuminate\Database\Connection->runQueryCallback('insert into `us...', Array, Object(Closure))
#2 /var/www/html/app/Services/User/RegistrationService.php(57): Illuminate\Database\Connection->insert('insert into `us...', Array)
#3 /var/www/html/app/Http/Controllers/Auth/RegisterController.php(88): App\Services\User\RegistrationService->registerUser({$userId}, 'user{$userId}@example.com')
#4 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Controller.php(54): App\Http\Controllers\Auth\RegisterController->store(Object(Illuminate\Http\Request))
#5 {main}
TRACE;

        case 'notification_smtp':
            return <<<TRACE
Swift_TransportException: Failed to authenticate on SMTP server with username "no-reply@example.com" using 2 possible authenticators in /var/www/html/vendor/swiftmailer/swiftmailer/lib/classes/Swift/Transport/Esmtp/AuthHandler.php:181

Stack trace:
#0 /var/www/html/vendor/swiftmailer/swiftmailer/lib/classes/Swift/Transport/EsmtpTransport.php(313): Swift_Transport_Esmtp_AuthHandler->afterEhlo(Object(Swift_SmtpTransport))
#1 /var/www/html/vendor/swiftmailer/swiftmailer/lib/classes/Swift/Mailer.php(79): Swift_Transport_EsmtpTransport->send(Object(Swift_Message), Array)
#2 /var/www/html/app/Services/Notification/EmailNotifier.php(42): Swift_Mailer->send(Object(Swift_Message))
#3 /var/www/html/app/Jobs/SendUserRegisteredEmail.php(35): App\Services\Notification\EmailNotifier->sendRegistrationEmail({$userId}, 'user{$userId}@example.com')
#4 {main}
TRACE;

        case 'login_null':
        default:
            return <<<TRACE
ErrorException: Trying to access array offset on value of type null in /var/www/html/app/Http/Controllers/Auth/LoginController.php:134

Stack trace:
#0 /var/www/html/vendor/laravel/framework/src/Illuminate/Foundation/Bootstrap/HandleExceptions.php(255): Illuminate\Foundation\Bootstrap\HandleExceptions->handleError(8, 'Trying to acces...', '/var/www/html/a...', 134)
#1 /var/www/html/app/Http/Controllers/Auth/LoginController.php(134): Illuminate\Foundation\Bootstrap\HandleExceptions->Illuminate\Foundation\Bootstrap\{closure}(8, 'Trying to acces...', '/var/www/html/a...', 134)
#2 /var/www/html/app/Http/Controllers/Auth/LoginController.php(72): App\Http\Controllers\Auth\LoginController->buildUserResponse(NULL)
#3 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Controller.php(54): App\Http\Controllers\Auth\LoginController->login(Object(Illuminate\Http\Request))
#4 {main}
TRACE;
    }
}

function buildExceptionGelf(
    string $exceptionClass,
    string $message,
    string $traceType,
    int $userId,
    int $orderId,
    array $extra = []
): array {
    $trace       = getStackTrace($traceType, $userId, $orderId);
    $fullMessage = "{$exceptionClass}: {$message}\n\n{$trace}";

    return buildGelf(
        "{$exceptionClass}: {$message}",
        3,
        array_merge([
            'exception_class'   => $exceptionClass,
            'exception_message' => $message,
            'stack_trace'       => $trace,
            'source'            => 'user-service',
            'user_id'           => $userId,
            'order_id'          => $orderId,
            'event'             => 'exception',
        ], $extra),
        'php-user-flow'
    ) + ['full_message' => $fullMessage];
}

function randomSuccessLog(): array
{
    $userId  = randomUserId();
    $orderId = randomOrderId();

    $scenarios = ['user_registered', 'notification_sent', 'user_logged_in'];
    $s         = $scenarios[array_rand($scenarios)];

    switch ($s) {
        case 'user_registered':
            return buildGelf(
                "Пользователь #{$userId} успешно зарегистрирован",
                6,
                [
                    'event'     => 'user_registered',
                    'user_id'   => $userId,
                    'email'     => "user{$userId}@example.com",
                    'source'    => 'auth',
                    'component' => 'registration',
                ]
            );

        case 'notification_sent':
            return buildGelf(
                "Уведомление о регистрации отправлено пользователю #{$userId}",
                6,
                [
                    'event'     => 'notification_sent',
                    'user_id'   => $userId,
                    'email'     => "user{$userId}@example.com",
                    'channel'   => 'email',
                    'template'  => 'user_registered',
                    'source'    => 'notifications',
                    'component' => 'email-notifier',
                ]
            );

        case 'user_logged_in':
        default:
            return buildGelf(
                "Пользователь #{$userId} успешно авторизован",
                6,
                [
                    'event'     => 'user_logged_in',
                    'user_id'   => $userId,
                    'source'    => 'auth',
                    'ip'        => '127.0.0.1',
                    'user_agent'=> 'DemoBrowser/1.0',
                ]
            );
    }
}

function randomErrorLog(): array
{
    $userId  = randomUserId();
    $orderId = randomOrderId();

    $scenarios = ['registration_db', 'notification_smtp', 'login_null'];
    $s         = $scenarios[array_rand($scenarios)];

    switch ($s) {
        case 'registration_db':
            return buildExceptionGelf(
                'PDOException',
                'Deadlock found when trying to get lock; try restarting transaction',
                'registration_db',
                $userId,
                $orderId,
                ['component' => 'registration']
            );

        case 'notification_smtp':
            return buildExceptionGelf(
                'Swift_TransportException',
                'Failed to authenticate on SMTP server',
                'notification_smtp',
                $userId,
                $orderId,
                ['component' => 'email-notifier']
            );

        case 'login_null':
        default:
            return buildExceptionGelf(
                'ErrorException',
                'Trying to access array offset on value of type null',
                'login_null',
                $userId,
                $orderId,
                ['component' => 'auth-controller']
            );
    }
}

function randomLog(): array
{
    // Примерно 70% успешных событий, 30% ошибок
    if (mt_rand(1, 100) <= 70) {
        return randomSuccessLog();
    }
    return randomErrorLog();
}

// ── main ────────────────────────────────────────────────────────────────────

$opts  = parseArgs($argv);
$count = (int)$opts['count'];
$sleep = (int)$opts['sleep_ms'];

$host  = getenv('GRAYLOG_GELF_HOST') ?: '127.0.0.1';
$port  = (int)(getenv('GRAYLOG_GELF_PORT') ?: '12201');
$proto = strtolower(getenv('GRAYLOG_GELF_PROTO') ?: 'udp');
if (!in_array($proto, ['udp', 'tcp'], true)) {
    fwrite(STDERR, "Invalid GRAYLOG_GELF_PROTO={$proto} (expected udp|tcp)\n");
    exit(2);
}

for ($i = 0; $i < $count; $i++) {
    $gelf = randomLog();
    try {
        gelfSend($gelf, $host, $port, $proto);
        $msg = $gelf['short_message'] ?? '(no short_message)';
        fwrite(STDOUT, "sent: {$msg}\n");
    } catch (Throwable $e) {
        fwrite(STDERR, "send failed: {$e->getMessage()}\n");
        exit(1);
    }

    if ($sleep > 0 && $i < $count - 1) {
        usleep($sleep * 1000);
    }
}
