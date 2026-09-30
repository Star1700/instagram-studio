<?php
declare(strict_types=1);
ini_set('display_errors', '0');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'");
header('Content-Type: text/html; charset=utf-8');
function callbackPage(string $message, int $status): never {
    http_response_code($status);
    echo '<!doctype html><html lang="de"><meta charset="utf-8"><title>Instagram Studio</title>'
        . '<meta name="viewport" content="width=device-width,initial-scale=1">'
        . '<body style="font:18px system-ui;max-width:42rem;margin:4rem auto;padding:0 1rem">'
        . '<h1>Instagram Studio</h1><p>' . htmlspecialchars($message, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . '</p></body></html>';
    exit;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') { callbackPage('Ungültige Anfrage.', 404); }
if ($_GET === ['done' => '1']) { callbackPage('Kehre zu Studio zurück. Dort wird deine Verbindung geprüft. Du kannst dieses Fenster schließen.', 200); }
$state = $_GET['state'] ?? '';
$code = $_GET['code'] ?? '';
$denied = isset($_GET['error']);
if (!is_string($state) || !preg_match('/\A[a-f0-9]{64}\z/', $state)
    || (!$denied && (!is_string($code) || strlen($code) < 8 || strlen($code) > 4096))) {
    callbackPage('Die Freigabe konnte nicht zugeordnet werden. Starte Instagram verbinden in Studio erneut.', 400);
}
$root = dirname(__DIR__) . '/ig-private';
require_once $root . '/lib/PostStore.php';
$store = new PostStore($root);
try {
    $ok = $store->withLock(function () use ($root, $state, $code, $denied): bool {
        $pending = $root . '/oauth-codes/' . $state . '.pending';
        if (!is_file($pending)) { return false; }
        $saved = json_decode((string)file_get_contents($pending), true, 8, JSON_THROW_ON_ERROR);
        if (($saved['created_at'] ?? 0) < time() - 1800) { unlink($pending); return false; }
        $result = $saved;
        if ($denied) { $result['error'] = 'denied'; }
        else { $result['code'] = str_ends_with($code, '#_') ? substr($code, 0, -2) : $code; }
        $path = $root . '/oauth-codes/' . $state . '.result';
        if (file_put_contents($path, json_encode($result, JSON_THROW_ON_ERROR), LOCK_EX) === false) { throw new RuntimeException('write'); }
        chmod($path, 0600); unlink($pending); return true;
    });
    if (!$ok) { callbackPage('Diese Freigabe ist abgelaufen. Starte Instagram verbinden in Studio erneut.', 400); }
} catch (Throwable $error) { callbackPage('Die Freigabe konnte nicht gespeichert werden. Bitte versuche es in Studio erneut.', 500); }
header('Location: /ig-api/oauth-callback.php?done=1', true, 303);
exit;
