<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__ . '/bootstrap.php';
$store = new PostStore($config['private_dir']);
(new QueueRunner($config, $store, null, fn(array $post) => AccountContext::client($config, $post),
    fn(int $cursor, DateTimeImmutable $now) => AccountContext::refreshOne($config, $cursor, $now)))->run();
