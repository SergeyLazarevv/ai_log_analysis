<?php
/**
 * Simple Graylog seeder (GELF) for local demos.
 *
 * Prereq in Graylog UI:
 *   System -> Inputs -> Launch input -> GELF UDP (or GELF TCP)
 *   Port: 12201 (matches docker-compose port mapping)
 *
 * Usage examples:
 *   php php/graylog_seed.php order_created --order-id=12345
 *   php php/graylog_seed.php order_cancelled --order-id=12345 --reason="payment timeout"
 *   php php/graylog_seed.php sms_error --order-id=12345 --phone="+79990001122"
 *   php php/graylog_seed.php error --count=10
 *   php php/graylog_seed.php exception_db --count=5
 *   php php/graylog_seed.php exception_payment --count=5
 *   php php/graylog_seed.php exception_redis --count=3
 *   php php/graylog_seed.php exception_null --count=5
 *   php php/graylog_seed.php random --count=50 --sleep-ms=100
 *
 * Env vars:
 *   GRAYLOG_GELF_HOST=127.0.0.1
 *   GRAYLOG_GELF_PORT=12201
 *   GRAYLOG_GELF_PROTO=udp   (udp|tcp)
 */

declare(strict_types=1);

function usageAndExit(int $code = 0): void
{
    $script = basename(__FILE__);
    fwrite(STDERR, <<<TXT
{$script} - send demo logs to Graylog (GELF)

Usage:
  php php/{$script} <scenario> [--count=N] [--sleep-ms=MS] [--order-id=ID] [--reason=TEXT] [--phone=PHONE]

Scenarios:
  order_created
  order_cancelled
  sms_error
  error           — лог с текстом "error" (для поиска в Graylog)
  exception_db    — PDOException: потеря соединения с БД
  exception_payment — ConnectException: таймаут платёжного шлюза
  exception_redis — ConnectionException: Redis недоступен
  exception_null  — ErrorException: null pointer в middleware
  random

Env:
  GRAYLOG_GELF_HOST (default 127.0.0.1)
  GRAYLOG_GELF_PORT (default 12201)
  GRAYLOG_GELF_PROTO (default udp; udp|tcp)

Examples:
  php php/{$script} order_created --order-id=12345
  php php/{$script} random --count=100 --sleep-ms=50

TXT);
    exit($code);
}

function parseArgs(array $argv): array
{
    $scenario = $argv[1] ?? null;
    if ($scenario === null || in_array($scenario, ['-h', '--help'], true)) {
        usageAndExit(0);
    }

    $opts = [
        'scenario' => $scenario,
        'count' => 1,
        'sleep_ms' => 0,
        'order_id' => null,
        'reason' => null,
        'phone' => null,
    ];

    foreach (array_slice($argv, 2) as $arg) {
        if (!str_starts_with($arg, '--')) {
            fwrite(STDERR, "Unknown argument: {$arg}\n");
            usageAndExit(2);
        }
        [$k, $v] = array_pad(explode('=', substr($arg, 2), 2), 2, null);
        if ($v === null) {
            fwrite(STDERR, "Expected --key=value, got: {$arg}\n");
            usageAndExit(2);
        }

        switch ($k) {
            case 'count':
                $opts['count'] = max(1, (int)$v);
                break;
            case 'sleep-ms':
                $opts['sleep_ms'] = max(0, (int)$v);
                break;
            case 'order-id':
                $opts['order_id'] = (string)$v;
                break;
            case 'reason':
                $opts['reason'] = (string)$v;
                break;
            case 'phone':
                $opts['phone'] = (string)$v;
                break;
            default:
                fwrite(STDERR, "Unknown option: --{$k}\n");
                usageAndExit(2);
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

    // GELF framing expects a null byte terminator on TCP; UDP accepts raw JSON.
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

function randomOrderId(): string
{
    return (string)random_int(1, 10);
}

function buildGelf(
    string $shortMessage,
    int $level,
    array $extraFields = [],
    ?string $facility = 'php-seeder'
): array {
    $host = gethostname() ?: 'localhost';

    // GELF 1.1 required fields: version, host, short_message, timestamp, level
    $gelf = [
        'version' => '1.1',
        'host' => $host,
        'short_message' => $shortMessage,
        'timestamp' => nowFloat(),
        'level' => $level, // syslog level (0..7). 3=error, 4=warning, 6=info
        '_facility' => $facility,
        '_app' => 'laravel-stub',
        '_env' => 'local',
    ];

    // Graylog convention: additional fields must start with underscore.
    foreach ($extraFields as $k => $v) {
        $k = ltrim((string)$k);
        if ($k === '') {
            continue;
        }
        $key = str_starts_with($k, '_') ? $k : ('_' . $k);
        $gelf[$key] = $v;
    }

    return $gelf;
}

/**
 * Возвращает фиксированный стектрейс для заданного типа ошибки.
 * Один тип ошибки = одна корневая причина = одинаковый трейс.
 * Это позволяет нейросети группировать однотипные инциденты.
 */
function getStackTrace(string $errorType, string $orderId): string
{
    switch ($errorType) {

        case 'db':
            return <<<TRACE
PDOException: SQLSTATE[HY000] [2002] Connection refused in /var/www/html/vendor/laravel/framework/src/Illuminate/Database/Connectors/Connector.php:71

Stack trace:
#0 /var/www/html/vendor/laravel/framework/src/Illuminate/Database/Connectors/Connector.php(71): PDO->__construct('mysql:host=db;d...', 'app_user', '***', Array)
#1 /var/www/html/vendor/laravel/framework/src/Illuminate/Database/Connectors/MySqlConnector.php(53): Illuminate\Database\Connectors\Connector->createPdoConnection('mysql:host=db;d...', 'app_user', '***', Array)
#2 /var/www/html/vendor/laravel/framework/src/Illuminate/Database/DatabaseManager.php(376): Illuminate\Database\Connectors\MySqlConnector->connect(Array)
#3 /var/www/html/vendor/laravel/framework/src/Illuminate/Database/DatabaseManager.php(241): Illuminate\Database\DatabaseManager->makeConnection('mysql')
#4 /var/www/html/app/Repositories/OrderRepository.php(124): Illuminate\Database\DatabaseManager->connection('mysql')
#5 /var/www/html/app/Services/OrderService.php(89): App\Repositories\OrderRepository->findById({$orderId})
#6 /var/www/html/app/Http/Controllers/OrderController.php(45): App\Services\OrderService->getOrder({$orderId})
#7 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Controller.php(54): App\Http\Controllers\OrderController->show(Object(Illuminate\Http\Request))
#8 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/ControllerDispatcher.php(45): Illuminate\Routing\Controller->callAction('show', Array)
#9 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Route.php(261): Illuminate\Routing\ControllerDispatcher->dispatch(Object(Illuminate\Routing\Route), Object(App\Http\Controllers\OrderController), 'show')
#10 {main}
TRACE;

        case 'payment':
            return <<<TRACE
GuzzleHttp\Exception\ConnectException: cURL error 28: Operation timed out after 5001 milliseconds with 0 bytes received (see https://curl.haxx.se/libcurl/c/libcurl-errors.html) for https://3dsec.sberbank.ru/payment/rest/register.do in /var/www/html/vendor/guzzlehttp/guzzle/src/Handler/CurlFactory.php:211

Stack trace:
#0 /var/www/html/vendor/guzzlehttp/guzzle/src/Handler/CurlFactory.php(158): GuzzleHttp\Handler\CurlFactory::createRejection(Object(GuzzleHttp\Handler\EasyHandle), Array)
#1 /var/www/html/vendor/guzzlehttp/guzzle/src/Handler/CurlFactory.php(105): GuzzleHttp\Handler\CurlFactory::finishError(Object(GuzzleHttp\Handler\CurlHandler), Object(GuzzleHttp\Handler\EasyHandle), Object(GuzzleHttp\Handler\CurlFactory))
#2 /var/www/html/vendor/guzzlehttp/guzzle/src/Handler/CurlHandler.php(45): GuzzleHttp\Handler\CurlFactory->finish(Object(GuzzleHttp\Handler\CurlHandler), Object(GuzzleHttp\Handler\EasyHandle))
#3 /var/www/html/app/Services/Payment/SberbankGateway.php(112): GuzzleHttp\Handler\CurlHandler->__invoke(Object(GuzzleHttp\Psr7\Request), Array)
#4 /var/www/html/app/Services/Payment/PaymentService.php(67): App\Services\Payment\SberbankGateway->charge({$orderId}, 2490)
#5 /var/www/html/app/Jobs/ProcessPayment.php(88): App\Services\Payment\PaymentService->processOrder(Object(App\Models\Order))
#6 /var/www/html/vendor/laravel/framework/src/Illuminate/Queue/Jobs/Job.php(154): App\Jobs\ProcessPayment->handle()
#7 /var/www/html/vendor/laravel/framework/src/Illuminate/Queue/Worker.php(422): Illuminate\Queue\Jobs\Job->fire()
#8 /var/www/html/vendor/laravel/framework/src/Illuminate/Queue/Worker.php(374): Illuminate\Queue\Worker->process('redis', Object(Illuminate\Queue\Jobs\RedisJob), Object(Illuminate\Queue\WorkerOptions))
#9 {main}
TRACE;

        case 'redis':
            return <<<TRACE
Predis\Connection\ConnectionException: Connection refused [tcp://127.0.0.1:6379] in /var/www/html/vendor/predis/predis/src/Connection/AbstractConnection.php:182

Stack trace:
#0 /var/www/html/vendor/predis/predis/src/Connection/AbstractConnection.php(155): Predis\Connection\AbstractConnection->onConnectionError('Connection refu...')
#1 /var/www/html/vendor/predis/predis/src/Connection/StreamConnection.php(130): Predis\Connection\AbstractConnection->connect()
#2 /var/www/html/vendor/predis/predis/src/Connection/StreamConnection.php(165): Predis\Connection\StreamConnection->createResource()
#3 /var/www/html/vendor/laravel/framework/src/Illuminate/Redis/Connectors/PredisConnector.php(43): Predis\Connection\StreamConnection->connect()
#4 /var/www/html/vendor/laravel/framework/src/Illuminate/Cache/RedisStore.php(272): Illuminate\Redis\Connectors\PredisConnector->connect(Array, Array)
#5 /var/www/html/vendor/laravel/framework/src/Illuminate/Cache/Repository.php(387): Illuminate\Cache\RedisStore->get('session:user:{$orderId}')
#6 /var/www/html/app/Http/Middleware/CheckSession.php(38): Illuminate\Cache\Repository->get('session:user:{$orderId}')
#7 /var/www/html/vendor/laravel/framework/src/Illuminate/Pipeline/Pipeline.php(167): App\Http\Middleware\CheckSession->handle(Object(Illuminate\Http\Request), Object(Closure))
#8 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Router.php(726): Illuminate\Pipeline\Pipeline->Illuminate\Pipeline\{closure}(Object(Illuminate\Http\Request))
#9 {main}
TRACE;

        case 'null':
        default:
            return <<<TRACE
ErrorException: Trying to access array offset on value of type null in /var/www/html/app/Http/Middleware/CheckOrderStatus.php:34

Stack trace:
#0 /var/www/html/vendor/laravel/framework/src/Illuminate/Foundation/Bootstrap/HandleExceptions.php(255): Illuminate\Foundation\Bootstrap\HandleExceptions->handleError(8, 'Trying to acces...', '/var/www/html/a...', 34)
#1 /var/www/html/app/Http/Middleware/CheckOrderStatus.php(34): Illuminate\Foundation\Bootstrap\HandleExceptions->Illuminate\Foundation\Bootstrap\{closure}(8, 'Trying to acces...', '/var/www/html/a...', 34)
#2 /var/www/html/app/Http/Middleware/CheckOrderStatus.php(34): App\Http\Middleware\CheckOrderStatus->resolveStatus(NULL)
#3 /var/www/html/vendor/laravel/framework/src/Illuminate/Pipeline/Pipeline.php(167): App\Http\Middleware\CheckOrderStatus->handle(Object(Illuminate\Http\Request), Object(Closure))
#4 /var/www/html/app/Http/Middleware/AuthenticateApi.php(29): Illuminate\Pipeline\Pipeline->Illuminate\Pipeline\{closure}(Object(Illuminate\Http\Request))
#5 /var/www/html/vendor/laravel/framework/src/Illuminate/Pipeline/Pipeline.php(167): App\Http\Middleware\AuthenticateApi->handle(Object(Illuminate\Http\Request), Object(Closure))
#6 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Router.php(726): Illuminate\Pipeline\Pipeline->Illuminate\Pipeline\{closure}(Object(Illuminate\Http\Request))
#7 /var/www/html/vendor/laravel/framework/src/Illuminate/Routing/Route.php(261): Illuminate\Routing\Router->Illuminate\Routing\{closure}(Object(Illuminate\Http\Request))
#8 {main}
TRACE;
    }
}

function buildExceptionGelf(
    string $exceptionClass,
    string $message,
    string $traceType,
    string $orderId,
    array $extra = []
): array {
    $trace = getStackTrace($traceType, $orderId);
    $fullMessage = "{$exceptionClass}: {$message}\n\n{$trace}";

    return buildGelf(
        "{$exceptionClass}: {$message}",
        3,
        array_merge([
            'exception_class'   => $exceptionClass,
            'exception_message' => $message,
            'stack_trace'       => $trace,
            'source'            => 'laravel-stub',
            'order_id'          => $orderId,
        ], $extra),
        'php-seeder'
    ) + ['full_message' => $fullMessage];
}

function emitScenario(string $scenario, array $opts): array
{
    $orderId = $opts['order_id'] ?? randomOrderId();

    switch ($scenario) {
        case 'order_created':
            return buildGelf(
                "Заказ #{$orderId} оформлен",
                6,
                [
                    'event' => 'order_created',
                    'order_id' => $orderId,
                    'status' => 'created',
                    'source' => 'checkout',
                ]
            );

        case 'order_cancelled':
            $reason = $opts['reason'] ?? 'user_cancelled';
            return buildGelf(
                "Заказ #{$orderId} отменен ({$reason})",
                4,
                [
                    'event' => 'order_cancelled',
                    'order_id' => $orderId,
                    'status' => 'cancelled',
                    'reason' => $reason,
                    'source' => 'orders',
                ]
            );

        case 'sms_error':
            $phone = $opts['phone'] ?? '+79990000000';
            return buildGelf(
                "Ошибка отправки SMS для заказа #{$orderId} на {$phone}",
                3,
                [
                    'event' => 'sms_error',
                    'order_id' => $orderId,
                    'phone' => $phone,
                    'provider' => 'demo-sms',
                    'error_code' => 'SMS_PROVIDER_TIMEOUT',
                    'source' => 'notifications',
                ]
            );

        case 'error':
            // Сообщение с "error" в тексте — для проверки поиска в Graylog (query: error)
            $reason = $opts['reason'] ?? 'Connection timeout';
            return buildGelf(
                "Application error: {$reason} (order #{$orderId})",
                3,
                [
                    'event' => 'app_error',
                    'order_id' => $orderId,
                    'error_type' => 'runtime',
                    'source' => 'php-seeder',
                ]
            );

        case 'exception_db':
            return buildExceptionGelf(
                'PDOException',
                'SQLSTATE[HY000] [2002] Connection refused',
                'db',
                $orderId,
                ['event' => 'exception', 'component' => 'database']
            );

        case 'exception_payment':
            return buildExceptionGelf(
                'GuzzleHttp\Exception\ConnectException',
                'cURL error 28: Operation timed out after 5001 milliseconds',
                'payment',
                $orderId,
                ['event' => 'exception', 'component' => 'payment-gateway']
            );

        case 'exception_redis':
            return buildExceptionGelf(
                'Predis\Connection\ConnectionException',
                'Connection refused [tcp://127.0.0.1:6379]',
                'redis',
                $orderId,
                ['event' => 'exception', 'component' => 'redis']
            );

        case 'exception_null':
            return buildExceptionGelf(
                'ErrorException',
                'Trying to access array offset on value of type null',
                'null',
                $orderId,
                ['event' => 'exception', 'component' => 'middleware']
            );

        case 'random':
            $scenarios = [
                'order_created', 'order_cancelled', 'sms_error', 'error',
                'exception_db', 'exception_payment', 'exception_redis', 'exception_null',
            ];
            return emitScenario($scenarios[array_rand($scenarios)], $opts);

        default:
            fwrite(STDERR, "Unknown scenario: {$scenario}\n");
            usageAndExit(2);
    }
}

$opts = parseArgs($argv);

$host = getenv('GRAYLOG_GELF_HOST') ?: '127.0.0.1';
$port = (int)(getenv('GRAYLOG_GELF_PORT') ?: '12201');
$proto = strtolower(getenv('GRAYLOG_GELF_PROTO') ?: 'udp');
if (!in_array($proto, ['udp', 'tcp'], true)) {
    fwrite(STDERR, "Invalid GRAYLOG_GELF_PROTO={$proto} (expected udp|tcp)\n");
    exit(2);
}

$count = (int)$opts['count'];
$sleepMs = (int)$opts['sleep_ms'];

for ($i = 0; $i < $count; $i++) {
    $gelf = emitScenario($opts['scenario'], $opts);
    try {
        gelfSend($gelf, $host, $port, $proto);
        $msg = $gelf['short_message'] ?? '(no short_message)';
        fwrite(STDOUT, "sent: {$msg}\n");
    } catch (Throwable $e) {
        fwrite(STDERR, "send failed: {$e->getMessage()}\n");
        exit(1);
    }

    if ($sleepMs > 0 && $i < ($count - 1)) {
        usleep($sleepMs * 1000);
    }
}
