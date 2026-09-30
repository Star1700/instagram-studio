<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';
require_once $privateDirectory . '/lib/OAuthBroker.php';
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(404); exit; }
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 4096) { http_response_code(413); exit; }
try {
    $input = json_decode((string)file_get_contents('php://input'), true, 8, JSON_THROW_ON_ERROR);
    if (!is_array($input) || !is_string($input['state'] ?? null) || !is_string($input['verifier'] ?? null)) {
        throw new InvalidArgumentException();
    }
    $result = (new OAuthBroker($config, new PostStore($config['private_dir'])))->pickup($input['state'], $input['verifier']);
    if ($result === null) { http_response_code(404); exit; }
    jsonResponse($result);
} catch (JsonException | InvalidArgumentException $error) {
    jsonResponse(['error' => 'Ungültige Verbindungsanfrage.'], 400);
} catch (RuntimeException $error) {
    jsonResponse(['error' => 'Instagram konnte die Verbindung nicht bestätigen. Prüfe das Creator-Konto, die angenommene Tester-Einladung und beide Freigaben. Starte anschließend erneut.'], 422);
}
