# Installation unter Windows

## Voraussetzungen

- Windows 11 und Internetzugang.
- Codex ist installiert und mit ChatGPT angemeldet.
- Zum Veröffentlichen: ein Instagram-Creator- oder Business-Konto.

## Installation mit Codex

Gib Codex den Repository-Link und diesen Auftrag:

> Klone dieses Repository in einen eigenen Projektordner und installiere Instagram Studio mit notebook/install-studio.ps1.

Codex führt im Projektordner aus:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\notebook\install-studio.ps1
```

Der Installer richtet Python und die benötigten Pakete ein, erstellt eine eigene leere Konfiguration und legt die Desktop-Verknüpfung **Studio** an. Vorhandene Einstellungen und Entwürfe bleiben erhalten. Der bereitgestellte Online-Dienst wird automatisch verwendet; eine eigene Servereinrichtung ist nicht nötig.

## Instagram verbinden

1. **Studio** öffnen und unter **Dein Schreibstil** die gewünschten Einstellungen wählen.
2. Falls eine Tester-Einladung nötig ist, das Konto vom App-Betreiber einladen lassen. Die Einladung auf dem PC im Instagram-Browser annehmen: **Einstellungen → Berechtigungen für Apps und Websites → Apps und Websites → Tester-Einladungen**. Dafür den Desktop-Browser verwenden, nicht die Handy-App.
3. In Studio **Instagram verbinden** wählen und die Freigabe bei Instagram bestätigen.

Das Instagram-Passwort wird nur bei Instagram eingegeben und nicht in Studio gespeichert.

## Updates und Hilfe

Für ein Update alle Studio-Tabs schließen und Codex bitten, das Repository zu aktualisieren und den Installer erneut auszuführen. Persönliche Daten bleiben erhalten.

Wenn die Installation abbricht, die Fehlermeldung in Codex prüfen lassen. Falls Python nicht automatisch installiert werden kann, Python 3.12 von [python.org](https://www.python.org/downloads/windows/) installieren und den Installer erneut starten.

[Bedienhilfe](DASHBOARD_GUIDE.md)
