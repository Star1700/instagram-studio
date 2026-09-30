<?php
declare(strict_types=1);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
authorizeEndpoint($config, 'upload');
require_once $privateDirectory . '/lib/MediaUpload.php';
$now = new DateTimeImmutable('now', new DateTimeZone('UTC'));
try {
    if (!is_file($config['token_path'])) { throw new InvalidArgumentException('Bitte verbinde zuerst dieses Instagram-Konto.'); }
    $requestId = $_SERVER['HTTP_X_STUDIO_REQUEST_ID'] ?? '';
    if (!is_string($requestId) || preg_match('/\A[a-f0-9]{32}\z/', $requestId) !== 1 || $_GET !== []) {
        throw new InvalidArgumentException('Ungültige Auftragskennung.');
    }
    foreach ($_FILES as $file) {
        if (!is_array($file) || !is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name'])) {
            throw new InvalidArgumentException('Ungültiger Medienupload.');
        }
    }
    $metadata = MediaUpload::validate($_POST, $_FILES, $now);
} catch (InvalidArgumentException $error) { jsonResponse(['error' => $error->getMessage()], 422); }
$store = new PostStore($config['private_dir']);
$post = $store->withLock(fn() => MediaUpload::save($config, $store, $metadata, $_FILES, $requestId));
// Media processing is bounded by the existing minutely worker, including immediate posts.
jsonResponse(['id' => $post['id'], 'status' => $post['status'], 'image_url' => $post['image_url']], 201);
