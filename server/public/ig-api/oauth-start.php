<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
require_once $privateDirectory . '/lib/OAuthBroker.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(404); exit; }
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 4096) { http_response_code(413); exit; }
$header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
$context = AccountContext::resolve($config, $header, '');
if ($header !== '' && $header !== 'Bearer ' && $context === null) { http_response_code(401); exit; }
try {
    $input = json_decode((string)file_get_contents('php://input'), true, 8, JSON_THROW_ON_ERROR);
    if (!is_array($input)) { throw new InvalidArgumentException(); }
    jsonResponse((new OAuthBroker($config, new PostStore($config['private_dir'])))->begin($input, $context));
} catch (JsonException | InvalidArgumentException $error) {
    jsonResponse(['error' => 'Ungültige Verbindungsanfrage.'], 400);
} catch (RuntimeException $error) {
    jsonResponse(['error' => 'Die zentrale Anmeldung ist noch nicht aktiviert oder vorübergehend nicht verfügbar. Bitte wende dich an den App-Betreiber.'], 422);
}
