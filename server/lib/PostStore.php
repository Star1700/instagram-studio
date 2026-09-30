<?php
declare(strict_types=1);

final class PostStore {
    private bool $locked = false;
    public function __construct(public readonly string $directory) {}

    public function withLock(callable $action, bool $nonblocking = false): mixed {
        if ($this->locked) { throw new LogicException('Nested queue lock'); }
        $handle = fopen($this->directory . '/processing.lock', 'c+b');
        if ($handle === false) { throw new RuntimeException('Lock unavailable'); }
        try {
            if (!flock($handle, LOCK_EX | ($nonblocking ? LOCK_NB : 0))) { return false; }
            $this->locked = true;
            return $action();
        } finally {
            $this->locked = false;
            flock($handle, LOCK_UN);
            fclose($handle);
        }
    }

    private function requireLock(): void {
        if (!$this->locked) { throw new LogicException('Queue access requires the shared lock'); }
    }

    public function readJson(string $name, array $default = []): array {
        $this->requireLock();
        if (!in_array($name, ['posts.json', 'scheduler-state.json', 'clients.json'], true)) { throw new LogicException('Invalid state file'); }
        $path = $this->directory . '/' . $name;
        if (!file_exists($path)) { return $default; }
        $raw = file_get_contents($path);
        if ($raw === false) { throw new RuntimeException('State unavailable'); }
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) { throw new RuntimeException('Invalid state'); }
        return $data;
    }

    public function writeJson(string $name, array $data): void {
        $this->requireLock();
        if (!in_array($name, ['posts.json', 'scheduler-state.json', 'clients.json'], true)) { throw new LogicException('Invalid state file'); }
        $path = $this->directory . '/' . $name;
        $temporary = $path . '.' . bin2hex(random_bytes(12)) . '.tmp';
        try {
            $json = json_encode($data, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) . "\n";
            if (file_put_contents($temporary, $json, LOCK_EX) !== strlen($json)) { throw new RuntimeException('State write failed'); }
            chmod($temporary, 0600);
            if (!rename($temporary, $path)) { throw new RuntimeException('State replace failed'); }
        } finally {
            if (file_exists($temporary)) { unlink($temporary); }
        }
    }

    public function all(): array { return $this->readJson('posts.json'); }
    public function save(array $posts): void { $this->writeJson('posts.json', array_values($posts)); }

    public function findRequest(string $requestId, string $accountKey): ?array {
        $this->requireLock();
        if ($requestId === '') { return null; }
        foreach ($this->all() as $post) {
            if (($post['request_id'] ?? '') === $requestId && ($post['account_key'] ?? 'owner') === $accountKey) {
                return $post;
            }
        }
        return null;
    }
}
