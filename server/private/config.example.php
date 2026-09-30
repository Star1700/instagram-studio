<?php
declare(strict_types=1);

return [
    'upload_password' => '',
    'scheduler_secret' => '',
    'allow_live_publish' => false,
    'oauth_broker_enabled' => false,
    'oauth_signup_allowed' => false,
    'instagram_app_id' => '',
    'instagram_app_secret' => '',
    'redirect_uri' => 'https://www.starseven.at/ig-api/oauth-callback.php',
    'private_dir' => __DIR__,
    'public_out_dir' => dirname(__DIR__) . '/ig-out',
    'public_base_url' => 'https://www.starseven.at/ig-out',
    'token_path' => __DIR__ . '/token.json',
    'max_batch' => 10,
    'max_seconds' => 10.0,
];
