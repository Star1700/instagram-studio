<?php
declare(strict_types=1);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
authorizeEndpoint($config, 'upload');
if ($_GET !== []) { http_response_code(404); exit; }
$store = new PostStore($config['private_dir']);
jsonResponse(['accounts' => $store->withLock(fn() => AccountContext::accounts($config))]);
