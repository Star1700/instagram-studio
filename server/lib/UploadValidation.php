<?php
declare(strict_types=1);

final class UploadValidation {
    public static function metadata(array $fields, DateTimeImmutable $now): array {
        if (array_diff(array_keys($fields), ['caption', 'alt_text', 'publish_at']) !== []) { throw new InvalidArgumentException('Unbekannte Upload-Felder.'); }
        $caption = $fields['caption'] ?? '';
        $alt = $fields['alt_text'] ?? '';
        $when = $fields['publish_at'] ?? '';
        foreach ([$caption, $alt, $when] as $value) {
            if (!is_string($value) || preg_match('//u', $value) !== 1) { throw new InvalidArgumentException('Ungültige Texteingabe.'); }
        }
        if (preg_match_all('/./us', $caption) > 2200) { throw new InvalidArgumentException('Die Caption darf höchstens 2200 Zeichen haben.'); }
        if (preg_match_all('/./us', $alt) > 1000) { throw new InvalidArgumentException('Der Alternativtext darf höchstens 1000 Zeichen haben.'); }
        if (preg_match_all('/(?:^|\s)#[\p{L}\p{N}_]+/u', $caption) > 30) { throw new InvalidArgumentException('Höchstens 30 Hashtags.'); }
        if (preg_match_all('/(?:^|\s)@[\p{L}\p{N}_.]+/u', $caption) > 20) { throw new InvalidArgumentException('Höchstens 20 Erwähnungen.'); }
        if ($when === '') { $when = $now->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s\Z'); }
        $time = DateTimeImmutable::createFromFormat('!Y-m-d\TH:i:s\Z', $when, new DateTimeZone('UTC'));
        if (!$time || $time->format('Y-m-d\TH:i:s\Z') !== $when) { throw new InvalidArgumentException('Bitte eine gültige UTC-Uhrzeit angeben.'); }
        return ['caption' => $caption, 'alt_text' => $alt, 'publish_at' => $when];
    }

    public static function jpeg(string $data): string {
        if (strlen($data) > 8000000) { throw new InvalidArgumentException('Das Bild darf höchstens 8 MB groß sein.'); }
        $size = @getimagesizefromstring($data);
        if (!$size || $size[2] !== IMAGETYPE_JPEG) { throw new InvalidArgumentException('Bitte ein gültiges JPEG hochladen.'); }
        if ($size[0] < 1 || $size[1] < 1 || $size[0] * $size[1] > 20000000) { throw new InvalidArgumentException('Das Bild ist zu groß.'); }
        $ratio = $size[0] / $size[1];
        if ($ratio < 0.8 || $ratio > 1.91) { throw new InvalidArgumentException('Das Seitenverhältnis muss zwischen 4:5 und 1,91:1 liegen.'); }
        $image = @imagecreatefromstring($data);
        if ($image === false) { throw new InvalidArgumentException('Das JPEG konnte nicht gelesen werden.'); }
        ob_start();
        try { imagejpeg($image, null, 92); $clean = ob_get_contents(); }
        finally { ob_end_clean(); imagedestroy($image); }
        if (!is_string($clean) || strlen($clean) > 8000000) { throw new InvalidArgumentException('Das Bild darf höchstens 8 MB groß sein.'); }
        return $clean;
    }
}
