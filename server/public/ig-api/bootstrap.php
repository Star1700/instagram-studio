<?php
declare(strict_types=1);
ini_set('display_errors', '0');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

set_exception_handler(static function (Throwable $error): void {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo '{"error":"Die Serveranfrage konnte nicht verarbeitet werden."}';
});

// Phase 0 verified this fallback directory inside the hosting webroot.
$privateDirectory = dirname(__DIR__) . '/ig-private';
$config = require $privateDirectory . '/config.php';
require_once $privateDirectory . '/lib/Authorization.php';
require_once $privateDirectory . '/lib/PostStore.php';
require_once $privateDirectory . '/lib/QueueRunner.php';
require_once $privateDirectory . '/lib/AccountContext.php';

function authorizeEndpoint(array &$config, string $kind): void {
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if ($kind === 'upload') {
        $context = AccountContext::resolve($config, $header, $_SERVER['HTTP_X_STUDIO_ACCOUNT'] ?? '');
        if ($context !== null) { $config = $context; return; }
        http_response_code(401); exit;
    }
    if (!Authorization::allowed($config, $header, $kind)) {
        http_response_code($kind === 'scheduler' ? 404 : 401);
        exit;
    }
}

function jsonResponse(array $body, int $status = 200): never {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE);
    exit;
}
