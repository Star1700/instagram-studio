<?php
declare(strict_types=1);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
require_once $privateDirectory . '/lib/PostMedia.php';
authorizeEndpoint($config, 'upload');
if ($_GET !== [] || (int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 1024) { http_response_code(404); exit; }

try {
    $input = json_decode((string)file_get_contents('php://input'), true, 8, JSON_THROW_ON_ERROR);
    if (!is_array($input) || array_keys($input) !== ['id']
        || !is_string($input['id']) || preg_match('/\A[a-f0-9]{32}\z/', $input['id']) !== 1) {
        throw new InvalidArgumentException('Ungültiger Beitrag.');
    }
} catch (JsonException | InvalidArgumentException $error) {
    jsonResponse(['error' => 'Ungültiger Beitrag.'], 422);
}

$store = new PostStore($config['private_dir']);
$result = $store->withLock(function () use ($store, $config, $input): string {
    $kept = [];
    $found = false;
    foreach ($store->all() as $post) {
        if (($post['id'] ?? '') !== $input['id'] || !AccountContext::owns($post, $config)) { $kept[] = $post; continue; }
        $found = true;
        if (($post['status'] ?? '') === 'sent') { return 'sent'; }
        PostMedia::cleanup($post, $config['public_out_dir']);
    }
    if (!$found) { return 'missing'; }
    $store->save($kept);
    return 'deleted';
});

if ($result === 'missing') { jsonResponse(['error' => 'Beitrag nicht gefunden.'], 404); }
if ($result === 'sent') { jsonResponse(['error' => 'Ein veröffentlichter Beitrag kann hier nicht gelöscht werden.'], 409); }
http_response_code(204);
