<?php
declare(strict_types=1);
require_once __DIR__ . '/scheduler_test.php';
require_once __DIR__ . '/../lib/AccountContext.php';
require_once __DIR__ . '/../lib/OAuthBroker.php';

$root = __DIR__ . '/work-' . bin2hex(random_bytes(8));
mkdir($root, 0700);
$config = testConfig($root) + ['private_dir' => $root, 'token_path' => $root . '/token.json',
    'oauth_broker_enabled' => true, 'oauth_signup_allowed' => true,
    'instagram_app_id' => 'fake-app', 'instagram_app_secret' => 'fake-secret',
    'redirect_uri' => 'https://example.test/callback'];
$store = new PostStore($root);
$calls = [];
$transport = function (string $method, string $url, array $input) use (&$calls): array {
    $calls[] = $url;
    if (str_contains($url, 'api.instagram.com/oauth')) {
        return ['access_token' => 'short-fake', 'permissions' => 'instagram_business_basic,instagram_business_content_publish'];
    }
    if (str_contains($url, '/access_token')) { return ['access_token' => str_repeat('fake', 10), 'expires_in' => 5184000]; }
    return ['user_id' => '123', 'username' => 'friend', 'account_type' => 'MEDIA_CREATOR'];
};
try {
    $broker = new OAuthBroker($config, $store, $transport);
    $state = str_repeat('a', 64); $verifier = str_repeat('b', 64); $key = str_repeat('c', 64);
    $url = $broker->begin(['state' => $state, 'verifier_hash' => hash('sha256', $verifier), 'key_hash' => hash('sha256', $key)], null);
    check(!str_contains(json_encode($url), 'fake-secret'), 'app secret never returned');
    check($broker->pickup($state, $verifier) === null, 'pending does not produce a token');
    $path = $root . '/oauth-codes/' . $state;
    $pending = json_decode(file_get_contents($path . '.pending'), true);
    $pending['code'] = 'fake-code'; file_put_contents($path . '.result', json_encode($pending)); unlink($path . '.pending');
    check($broker->pickup($state, str_repeat('d', 64)) === null && $calls === [], 'wrong verifier cannot exchange');
    $result = $broker->pickup($state, $verifier);
    check($result['state'] === 'connected' && $result['account']['id'] === '123', 'new installation connects');
    check(!str_contains(json_encode($result), str_repeat('fake', 10)), 'token not in OAuth result');
    check($broker->pickup($state, $verifier) === $result && count($calls) === 3, 'lost response retry exchanges once');
    $mine = AccountContext::resolve($config, 'Bearer ' . $key, '123');
    check($mine !== null && is_file($mine['token_path']), 'installation key only gets its token');
    $other = AccountContext::resolve($config, 'Bearer ' . $key, '456');
    check(!is_file($other['token_path']), 'unknown account has no token');
    check(AccountContext::resolve($config, 'Bearer bad', '123') === null, 'invalid key denied');
    check(AccountContext::resolve($config, 'Bearer ' . $key, '../123') === null, 'account traversal denied');
    check(!AccountContext::owns(['account_key' => 'owner'], $mine), 'owner posts hidden from friend');
    check(AccountContext::owns(['account_key' => $mine['account_key']], $mine), 'own posts visible');
    $owner = AccountContext::resolve($config, 'Bearer ' . $config['upload_password'], '');
    check(AccountContext::owns(samplePost(), $owner), 'legacy owner posts preserved');
    check(count(AccountContext::accounts($mine)) === 1 && count(AccountContext::accounts($owner)) === 0, 'account lists isolated');
    $store->withLock(function () use ($store, $mine): void {
        $post = samplePost(); $post['request_id'] = str_repeat('9', 32); $post['account_key'] = $mine['account_key'];
        $post['status'] = 'sent';
        $store->save([$post]);
        check($store->findRequest($post['request_id'], $mine['account_key'])['id'] === $post['id'], 'retry returns the sent post instead of creating another');
        check($store->findRequest($post['request_id'], 'owner') === null, 'same request ID on another account stays isolated');
        check($store->findRequest('', $mine['account_key']) === null, 'empty request ID cannot match');
    });
    $expired = $pending; $expired['created_at'] = time() - 1900;
    file_put_contents($path . '.result', json_encode($expired));
    check($broker->pickup($state, $verifier) === null, 'expired result rejected');
    $badState = str_repeat('e', 64);
    $broker->begin(['state' => $badState, 'verifier_hash' => hash('sha256', $verifier), 'key_hash' => hash('sha256', $key)], null);
    $badPath = $root . '/oauth-codes/' . $badState;
    $denied = json_decode(file_get_contents($badPath . '.pending'), true);
    $denied['code'] = 'fake-denied-code';
    file_put_contents($badPath . '.result', json_encode($denied)); unlink($badPath . '.pending');
    $limited = new OAuthBroker($config, $store, fn() => ['access_token' => 'private-fake-short', 'permissions' => 'instagram_business_basic']);
    $rejected = false;
    try { $limited->pickup($badState, $verifier); }
    catch (RuntimeException $error) { $rejected = !str_contains($error->getMessage(), 'private-fake-short'); }
    check($rejected && count($store->withLock(fn() => $store->readJson('clients.json'))) === 1, 'missing publish permission grants no installation access');
    $broken = new class implements InstagramClient {
        public function createContainer(string $url, string $caption, string $alt): string { throw new RuntimeException('private-provider-error'); }
        public function containerStatus(string $id): string { throw new RuntimeException('unreachable'); }
        public function publish(string $id): string { throw new RuntimeException('unreachable'); }
    };
    $healthy = new FakeIg();
    $store->withLock(fn() => $store->save([samplePost(), samplePost(str_repeat('b', 32))]));
    (new QueueRunner($config, $store, null, fn(array $post) => $post['id'] === str_repeat('a', 32) ? $broken : $healthy))->run();
    $after = $store->withLock(fn() => $store->all());
    check($after[0]['status'] === 'scheduled' && $after[1]['status'] === 'container_pending', 'one unreachable account does not block another');
    check(!str_contains(json_encode($after), 'private-provider-error'), 'provider details never enter user-visible queue errors');
    $disabled = $config; $disabled['oauth_broker_enabled'] = false;
    $rejected = false;
    try { (new OAuthBroker($disabled, $store))->begin([], null); } catch (RuntimeException) { $rejected = true; }
    check($rejected, 'disabled broker cannot start');
    echo "accounts and oauth: ok\n";
} finally {
    $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($iterator as $item) { $item->isDir() ? rmdir($item->getPathname()) : unlink($item->getPathname()); }
    rmdir($root);
}
