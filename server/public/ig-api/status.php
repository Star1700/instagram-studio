<?php
declare(strict_types=1);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
authorizeEndpoint($config, 'upload');
if ($_GET !== []) { http_response_code(404); exit; }
$store = new PostStore($config['private_dir']);
$posts = $store->withLock(function () use ($store, $config): array {
    $allowed = ['id', 'status', 'caption', 'alt_text', 'publish_at', 'image_url', 'container_status', 'error', 'media_type'];
    return array_map(static function (array $post) use ($allowed): array {
        return array_intersect_key($post, array_flip($allowed));
    }, array_values(array_filter($store->all(), fn(array $post): bool => AccountContext::owns($post, $config))));
});
jsonResponse(['posts' => $posts]);
