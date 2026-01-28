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
    return (string)random_int(10000, 99999);
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

        case 'random':
            $scenarios = ['order_created', 'order_cancelled', 'sms_error'];
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
