<?php
declare(strict_types=1);

interface InstagramClient {
    public function createContainer(string $imageUrl, string $caption, string $alt): string;
    public function containerStatus(string $containerId): string;
    public function publish(string $containerId): string;
}

interface RefreshableInstagramClient extends InstagramClient {
    public function refreshIfNeeded(DateTimeImmutable $now): void;
}

interface MediaInstagramClient extends InstagramClient {
    public function createReel(string $url, string $caption): string;
    public function createCarouselItem(string $url, string $alt): string;
    public function createCarousel(array $children, string $caption): string;
}

final class GraphInstagramClient implements RefreshableInstagramClient, MediaInstagramClient {
    private Closure $transport;

    public function __construct(private readonly string $tokenPath, ?Closure $transport = null) {
        $this->transport = $transport ?? Closure::fromCallable([$this, 'request']);
    }

    public static function inspectToken(string $accessToken): array {
        $client = new self('');
        return $client->request('GET', 'https://graph.instagram.com/v26.0/me',
            ['fields' => 'user_id,username', 'access_token' => $accessToken]);
    }

    public function createContainer(string $imageUrl, string $caption, string $alt): string {
        $token = $this->token();
        $response = ($this->transport)('POST',
            'https://graph.instagram.com/v26.0/' . rawurlencode($token['user_id']) . '/media',
            ['image_url' => $imageUrl, 'caption' => $caption, 'alt_text' => $alt,
                'access_token' => $token['access_token']]);
        return $this->requiredId($response);
    }

    public function containerStatus(string $containerId): string {
        $token = $this->token();
        $response = ($this->transport)('GET',
            'https://graph.instagram.com/v26.0/' . rawurlencode($containerId),
            ['fields' => 'status_code', 'access_token' => $token['access_token']]);
        $status = $response['status_code'] ?? null;
        if (!is_string($status) || !in_array($status, ['IN_PROGRESS', 'FINISHED', 'ERROR', 'EXPIRED'], true)) {
            throw new RuntimeException('Invalid Instagram container status');
        }
        return $status;
    }

    private function createMedia(array $fields): string {
        $token = $this->token();
        return $this->requiredId(($this->transport)('POST',
            'https://graph.instagram.com/v26.0/' . rawurlencode($token['user_id']) . '/media',
            $fields + ['access_token' => $token['access_token']]));
    }

    public function createReel(string $url, string $caption): string {
        return $this->createMedia(['media_type' => 'REELS', 'video_url' => $url, 'caption' => $caption, 'share_to_feed' => 'true']);
    }

    public function createCarouselItem(string $url, string $alt): string {
        return $this->createMedia(['image_url' => $url, 'alt_text' => $alt, 'is_carousel_item' => 'true']);
    }

    public function createCarousel(array $children, string $caption): string {
        if (count($children) < 2 || count($children) > 10) { throw new InvalidArgumentException('Invalid carousel size'); }
        return $this->createMedia(['media_type' => 'CAROUSEL', 'children' => implode(',', $children), 'caption' => $caption]);
    }

    public function publish(string $containerId): string {
        $token = $this->token();
        $response = ($this->transport)('POST',
            'https://graph.instagram.com/v26.0/' . rawurlencode($token['user_id']) . '/media_publish',
            ['creation_id' => $containerId, 'access_token' => $token['access_token']]);
        return $this->requiredId($response);
    }

    public function refreshIfNeeded(DateTimeImmutable $now): void {
        $token = $this->token();
        $now = $now->setTimezone(new DateTimeZone('UTC'));
        $expires = new DateTimeImmutable($token['expires_at']);
        $issued = new DateTimeImmutable($token['issued_at']);
        if ($expires > $now->modify('+7 days') || $issued > $now->modify('-24 hours')) { return; }
        $response = ($this->transport)('GET', 'https://graph.instagram.com/refresh_access_token', [
            'grant_type' => 'ig_refresh_token', 'access_token' => $token['access_token'],
        ]);
        $accessToken = $response['access_token'] ?? null;
        $expiresIn = $response['expires_in'] ?? null;
        if (!is_string($accessToken) || strlen($accessToken) < 20 || !is_int($expiresIn) || $expiresIn < 3600) {
            throw new RuntimeException('Invalid Instagram refresh response');
        }
        $token['access_token'] = $accessToken;
        $token['issued_at'] = $now->format('Y-m-d\TH:i:s\Z');
        $token['expires_at'] = $now->modify('+' . $expiresIn . ' seconds')->format('Y-m-d\TH:i:s\Z');
        $this->writeToken($token);
    }

    private function token(): array {
        $raw = file_get_contents($this->tokenPath);
        if ($raw === false) { throw new RuntimeException('Instagram token unavailable'); }
        $token = json_decode($raw, true, 32, JSON_THROW_ON_ERROR);
        foreach (['access_token', 'user_id', 'issued_at', 'expires_at'] as $key) {
            if (!isset($token[$key]) || !is_string($token[$key]) || $token[$key] === '') {
                throw new RuntimeException('Invalid Instagram token');
            }
        }
        if (!preg_match('/\A[0-9]{1,32}\z/', $token['user_id'])) { throw new RuntimeException('Invalid Instagram user'); }
        return $token;
    }

    private function writeToken(array $token): void {
        $temporary = $this->tokenPath . '.' . bin2hex(random_bytes(12)) . '.tmp';
        try {
            $json = json_encode($token, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT) . "\n";
            if (file_put_contents($temporary, $json, LOCK_EX) !== strlen($json)) { throw new RuntimeException('Token write failed'); }
            chmod($temporary, 0600);
            if (!rename($temporary, $this->tokenPath)) { throw new RuntimeException('Token replace failed'); }
        } finally {
            if (file_exists($temporary)) { unlink($temporary); }
        }
    }

    private function requiredId(array $response): string {
        $id = $response['id'] ?? null;
        if (!is_string($id) || !preg_match('/\A[0-9]{1,64}\z/', $id)) { throw new RuntimeException('Invalid Instagram response'); }
        return $id;
    }

    private function request(string $method, string $url, array $parameters): array {
        $options = ['http' => ['method' => $method, 'timeout' => 8, 'ignore_errors' => true,
            'header' => "Accept: application/json\r\n"]];
        if (isset($parameters['access_token']) && !isset($parameters['grant_type'])) {
            $options['http']['header'] .= 'Authorization: Bearer ' . $parameters['access_token'] . "\r\n";
            unset($parameters['access_token']);
        }
        if ($method === 'GET') {
            $url .= '?' . http_build_query($parameters, '', '&', PHP_QUERY_RFC3986);
        } else {
            $body = http_build_query($parameters, '', '&', PHP_QUERY_RFC3986);
            $options['http']['header'] .= "Content-Type: application/x-www-form-urlencoded\r\n";
            $options['http']['content'] = $body;
        }
        $raw = @file_get_contents($url, false, stream_context_create($options));
        if ($raw === false) { throw new RuntimeException('Instagram request failed'); }
        $status = 0;
        foreach ($http_response_header ?? [] as $header) {
            if (preg_match('/\AHTTP\/\S+\s+(\d{3})\b/', $header, $match)) { $status = (int)$match[1]; }
        }
        $response = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
        if ($status < 200 || $status >= 300 || !is_array($response)) { throw new RuntimeException('Instagram request rejected'); }
        return $response;
    }
}
