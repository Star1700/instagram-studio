<?php
declare(strict_types=1);
$method = $_SERVER['REQUEST_METHOD'] ?? '';
if (!in_array($method, ['GET', 'POST'], true)) { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
authorizeEndpoint($config, 'upload');
if ($method === 'GET') {
    if ($_GET !== [] || !is_file($config['token_path'])) { http_response_code(404); exit; }
    $saved = json_decode((string)file_get_contents($config['token_path']), true, 16, JSON_THROW_ON_ERROR);
    $expires = new DateTimeImmutable($saved['expires_at']);
    $remaining = $expires->getTimestamp() - time();
    if ($remaining < 1 || !is_string($saved['access_token'] ?? null)
        || !is_string($saved['user_id'] ?? null)) { http_response_code(404); exit; }
    jsonResponse(['access_token' => $saved['access_token'], 'user_id' => $saved['user_id'],
        'expires_in' => $remaining,
        'expires_at' => $expires->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s\Z')]);
}
if ($_GET !== [] || (int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 16384) { http_response_code(404); exit; }
try {
    $raw = file_get_contents('php://input');
    $input = json_decode($raw === false ? '' : $raw, true, 16, JSON_THROW_ON_ERROR);
    if (!is_array($input) || array_diff(array_keys($input), ['access_token', 'user_id', 'expires_in']) !== []
        || array_diff(['access_token', 'user_id', 'expires_in'], array_keys($input)) !== []) {
        throw new InvalidArgumentException('Ungültige Instagram-Erlaubnis.');
    }
    $accessToken = $input['access_token']; $userId = $input['user_id']; $expiresIn = $input['expires_in'];
    if (!is_string($accessToken) || strlen($accessToken) < 20 || strlen($accessToken) > 4096
        || preg_match('/[\x00-\x20\x7f]/', $accessToken)
        || !is_string($userId) || !preg_match('/\A[0-9]{1,32}\z/', $userId)
        || !is_int($expiresIn) || $expiresIn < 3600 || $expiresIn > 7000000) {
        throw new InvalidArgumentException('Ungültige Instagram-Erlaubnis.');
    }
} catch (JsonException|InvalidArgumentException $error) {
    jsonResponse(['error' => $error->getMessage()], 422);
}
$now = new DateTimeImmutable('now', new DateTimeZone('UTC'));
try {
    $identity = GraphInstagramClient::inspectToken($accessToken);
    if ((string)($identity['user_id'] ?? '') !== $userId
        || ($config['account_id'] !== '' && $config['account_id'] !== $userId)) {
        throw new RuntimeException('Account mismatch');
    }
} catch (Throwable $error) { jsonResponse(['error' => 'Die Instagram-Verbindung konnte nicht bestätigt werden.'], 422); }
if ($config['tenant'] !== 'owner' && $config['account_id'] === '') {
    jsonResponse(['error' => 'Bitte wähle ein Instagram-Konto.'], 422);
}
$token = ['access_token' => $accessToken, 'user_id' => $userId,
    'username' => (string)($identity['username'] ?? ''),
    'issued_at' => $now->format('Y-m-d\TH:i:s\Z'),
    'expires_at' => $now->modify('+' . $expiresIn . ' seconds')->format('Y-m-d\TH:i:s\Z')];
$store = new PostStore($config['private_dir']);
$store->withLock(function () use ($config, $token): void {
    $path = $config['token_path']; $temporary = $path . '.' . bin2hex(random_bytes(12)) . '.tmp';
    if (!is_dir(dirname($path)) && !mkdir(dirname($path), 0700, true)) { throw new RuntimeException('Token directory unavailable'); }
    try {
        $json = json_encode($token, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT) . "\n";
        if (file_put_contents($temporary, $json, LOCK_EX) !== strlen($json)) { throw new RuntimeException('Token write failed'); }
        chmod($temporary, 0600);
        if (!rename($temporary, $path)) { throw new RuntimeException('Token replace failed'); }
    } finally {
        if (file_exists($temporary)) { unlink($temporary); }
    }
});
http_response_code(204);
