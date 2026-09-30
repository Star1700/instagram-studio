<?php
declare(strict_types=1);
require_once __DIR__ . '/helpers.php';
require_once __DIR__ . '/../lib/InstagramClient.php';

$root = __DIR__ . '/client-' . bin2hex(random_bytes(8));
mkdir($root, 0700);
$tokenPath = $root . '/token.json';
$writeToken = static function (array $changes = []) use ($tokenPath): void {
    $token = $changes + ['access_token' => str_repeat('t', 40), 'user_id' => '1234567890',
        'issued_at' => '2026-09-25T12:00:00Z', 'expires_at' => '2026-11-25T12:00:00Z'];
    file_put_contents($tokenPath, json_encode($token, JSON_THROW_ON_ERROR));
};
$calls = [];
$transport = static function (string $method, string $url, array $parameters) use (&$calls): array {
    $calls[] = [$method, $url, $parameters];
    if (str_ends_with($url, '/media')) { return ['id' => '456']; }
    if (str_ends_with($url, '/media_publish')) { return ['id' => '789']; }
    if (str_contains($url, 'refresh_access_token')) { return ['access_token' => str_repeat('n', 40), 'expires_in' => 5184000]; }
    return ['status_code' => 'FINISHED'];
};
try {
    $writeToken(); $client = new GraphInstagramClient($tokenPath, $transport);
    check($client->createContainer('https://www.starseven.at/ig-out/a.jpg', 'Text', 'Alt') === '456', 'container id');
    check($calls[0][0] === 'POST' && str_ends_with($calls[0][1], '/1234567890/media'), 'container endpoint');
    check($calls[0][2]['alt_text'] === 'Alt' && strlen($calls[0][2]['access_token']) === 40, 'container fields');
    check($client->containerStatus('456') === 'FINISHED', 'container status');
    check($client->publish('456') === '789', 'publish response parsed');

    $calls = []; $writeToken(['issued_at' => '2026-09-20T12:00:00Z', 'expires_at' => '2026-10-02T12:00:00Z']);
    $client->refreshIfNeeded(new DateTimeImmutable('2026-09-27T12:00:00Z'));
    $refreshed = json_decode(file_get_contents($tokenPath), true, 16, JSON_THROW_ON_ERROR);
    check(count($calls) === 1 && str_contains($calls[0][1], 'refresh_access_token'), 'refresh called near expiry');
    check($refreshed['access_token'] === str_repeat('n', 40), 'refreshed token saved');
    check($refreshed['user_id'] === '1234567890', 'user id preserved');

    $calls = []; $client->refreshIfNeeded(new DateTimeImmutable('2026-09-28T12:00:00Z'));
    check($calls === [], 'fresh token not refreshed');
    echo "instagram_client: ok\n";
} finally {
    if (is_file($tokenPath)) { unlink($tokenPath); }
    rmdir($root);
}
