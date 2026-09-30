<?php
declare(strict_types=1);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
authorizeEndpoint($config, 'scheduler');
if ($_GET !== [] || (int)($_SERVER['CONTENT_LENGTH'] ?? 0) !== 0 || file_get_contents('php://input') !== '') { http_response_code(404); exit; }
$store = new PostStore($config['private_dir']);
(new QueueRunner($config, $store, null, fn(array $post) => AccountContext::client($config, $post),
    fn(int $cursor, DateTimeImmutable $now) => AccountContext::refreshOne($config, $cursor, $now)))->run();
http_response_code(204);
