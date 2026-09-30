<?php
declare(strict_types=1);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
authorizeEndpoint($config, 'upload');
require_once $privateDirectory . '/lib/UploadValidation.php';
$now = new DateTimeImmutable('now', new DateTimeZone('UTC'));
try {
    if (!is_file($config['token_path'])) { throw new InvalidArgumentException('Bitte verbinde zuerst dieses Instagram-Konto.'); }
    $requestId = $_SERVER['HTTP_X_STUDIO_REQUEST_ID'] ?? '';
    if (!is_string($requestId) || ($requestId !== '' && !preg_match('/\A[a-f0-9]{32}\z/', $requestId))) { throw new InvalidArgumentException('Ungültige Auftragskennung.'); }
    if ($_GET !== [] || count($_FILES) !== 1 || !isset($_FILES['image']) || !is_array($_FILES['image'])) { throw new InvalidArgumentException('Bitte genau ein JPEG hochladen.'); }
    $file = $_FILES['image'];
    if (($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK || !is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name'])) { throw new InvalidArgumentException('Das Bild konnte nicht hochgeladen werden.'); }
    if (($file['size'] ?? 0) > 8000000) { throw new InvalidArgumentException('Das Bild darf höchstens 8 MB groß sein.'); }
    $metadata = UploadValidation::metadata($_POST, $now);
    $data = UploadValidation::jpeg(file_get_contents($file['tmp_name']));
} catch (InvalidArgumentException $error) { jsonResponse(['error' => $error->getMessage()], 422); }

$store = new PostStore($config['private_dir']);
$runner = new QueueRunner($config, $store, null, fn(array $post) => AccountContext::client($config, $post));
$result = $store->withLock(function () use ($store, $config, $metadata, $data, $runner, $now, $requestId): array {
    $posts = $store->all();
    $saved = $store->findRequest($requestId, $config['account_key']);
    if ($saved !== null) {
        return ['id' => $saved['id'], 'status' => $saved['status'], 'image_url' => $saved['image_url']];
    }
    if (count($posts) >= 1000) { throw new RuntimeException('Queue capacity reached'); }
    $id = bin2hex(random_bytes(16));
    $filename = $id . '.jpg';
    $imagePath = $config['public_out_dir'] . '/' . $filename;
    $post = $metadata + ['id' => $id, 'account_key' => $config['account_key'], 'request_id' => $requestId, 'status' => 'scheduled', 'image_file' => $filename,
        'image_url' => $config['public_base_url'] . '/' . $filename,
        'container_id' => null, 'ig_media_id' => null, 'error' => null];
    $handle = fopen($imagePath, 'xb');
    if (!$handle) { throw new RuntimeException('Image creation failed'); }
    try {
        if (fwrite($handle, $data) !== strlen($data)) { throw new RuntimeException('Image write failed'); }
        fclose($handle); $handle = null;
        chmod($imagePath, 0644);
        $posts[] = $post;
        $store->save($posts);
    } catch (Throwable $error) {
        if (is_resource($handle)) { fclose($handle); }
        if (is_file($imagePath)) { unlink($imagePath); }
        throw $error;
    }
    if (new DateTimeImmutable($metadata['publish_at']) <= $now) {
        $runner->runLocked($now);
        foreach ($store->all() as $saved) { if ($saved['id'] === $id) { $post = $saved; break; } }
    }
    return ['id' => $id, 'status' => $post['status'], 'image_url' => $post['image_url']];
});
jsonResponse($result, 201);
