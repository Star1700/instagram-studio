"""Run one isolated Codex text generation using the user's existing sign-in."""
from pathlib import Path
import inspect
import json
import shutil
import subprocess
import tempfile
import os

FIELDS = ("headline", "caption", "hashtags")
ERROR = "Codex konnte die Caption nicht erzeugen. Deine Idee und der Entwurf sind noch da."

TONE_GUIDANCE = {
    "direkt und freundlich": "Schreibe klar und zugewandt. Komm ohne lange Einleitung zur Sache und sprich die Lesenden freundlich an, ohne aufgesetzt vertraulich zu werden.",
    "ruhig und persönlich": "Schreibe warm, ruhig und nahbar. Gib der Beobachtung Raum und vermeide hektische Pointen oder werbliche Übertreibungen.",
    "locker und humorvoll": "Schreibe locker und alltagsnah, mit einem kleinen, passenden Augenzwinkern, wenn die Idee es trägt. Der Humor soll weder die Lesenden noch andere Menschen zum Witz machen.",
    "sachlich und klar": "Schreibe präzise, gut verständlich und ohne Werbesprache. Erkläre den Gedanken in natürlichen Sätzen statt in einer steifen Aufzählung.",
    "motivierend ohne Druck": "Ermutige mit kleinen, erreichbaren Schritten. Vermeide Leistungsdruck, Befehle und das Versprechen eines bestimmten Ergebnisses.",
    "tiefgründig und nachdenklich": "Schreibe reflektiert und ruhig. Zeige eine echte Beobachtung oder einen Gedanken, der nachwirkt, statt künstlich bedeutungsvoll oder pathetisch zu klingen.",
}

EMOJI_GUIDANCE = {
    "Keine Emojis": "Verwende keine Emojis.",
    "Wenige Emojis": "Verwende in der Caption höchstens ein bis zwei passende Emojis, und nur, wenn sie die Aussage unterstützen.",
    "Einige Emojis": "Verwende in der Caption einige passende Emojis, ungefähr zwei bis vier, sinnvoll über den Text verteilt.",
    "Emojis im Überfluss": "Verwende in der Caption auffallend viele passende Emojis, gern über mehrere Sätze verteilt. Der Text soll trotzdem gut lesbar bleiben; Emojis ersetzen keine Wörter.",
}


def _default_runner(argv: list[str], cwd: str, prompt: str) -> str:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError(ERROR)
    command = [executable, *argv[1:]]
    try:
        login = subprocess.run([executable, "login", "status"], capture_output=True, timeout=12,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if login.returncode != 0 or b"chatgpt" not in (login.stdout + login.stderr).lower():
            raise RuntimeError("Bitte melde Codex mit deinem ChatGPT-Konto an. Studio verwendet keinen API-Key.")
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        result = subprocess.run(command, cwd=cwd, input=prompt.encode("utf-8"), text=False, capture_output=True,
                                timeout=180, check=False, env=environment,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(ERROR) from None
    if result.returncode != 0:
        raise RuntimeError(ERROR)
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError(ERROR) from None


def _prompt(profile: dict, draft: dict, part: str | None) -> str:
    niche = (profile.get("niche") or "").strip()
    tone = (profile.get("tone") or "").strip()
    avoid = (profile.get("avoid") or "").strip()
    hashtags = (profile.get("hashtags") or "").strip()
    language = profile.get("language") or "Deutsch"
    emoji = profile.get("emoji") or "Wenige Emojis"
    current = {field: draft.get(field, "") for field in FIELDS}
    focus = (
        "Schreibe Überschrift, Caption und Hashtags. Eine Überschrift und Hashtags dürfen leer bleiben, wenn sie nicht passen."
        if part is None else
        f"Schreibe nur {part} neu. Gib die anderen beiden Felder aus dem vorhandenen Entwurf unverändert zurück."
    )
    guidance = [
        "Du schreibst für einen Instagram-Beitrag. Die heutige Idee ist der konkrete Auftrag; verwandle sie in eine Caption, die wie von einem Menschen geschrieben klingt und eine erkennbare Aussage hat.",
        "Greife passende Einzelheiten der Idee auf, aber erfinde keine Fakten, Zahlen, Zitate, persönlichen Erlebnisse oder Gewissheiten, die nicht im Entwurf stehen. Gib keine Trainings-, Gesundheits-, Diät- oder Erziehungsversprechen ab.",
        "Schreibe in natürlichen Sätzen statt in KI-Floskeln oder Werbesprache. Vermeide Gedankenstriche (— und –) im erzeugten Text; verwende lieber Punkt, Komma oder Doppelpunkt.",
        f"Schreibe auf {language}. {TONE_GUIDANCE.get(tone, 'Setze die eigene Tonbeschreibung als Schreibstil um: ' + json.dumps(tone, ensure_ascii=False) + '. Bleibe natürlich und zur heutigen Idee passend.')}",
    ]
    if niche:
        guidance.append(
            "Der langfristige Schwerpunkt des Instagram-Kontos ist " + json.dumps(niche, ensure_ascii=False)
            + ". Das ist Hintergrund für Wortwahl und Perspektive, keine Pflicht, jedes Thema darauf umzubiegen. Wenn die heutige Idee davon abweicht, schreibe über die heutige Idee."
        )
    guidance.append(EMOJI_GUIDANCE.get(emoji, EMOJI_GUIDANCE["Wenige Emojis"]))
    guidance.append(
        "Schreibe die Hashtags ausschließlich ins Feld hashtags, nicht an das Ende der Caption. "
        + ("Richte Anzahl und Sprache an dieser Vorgabe aus: " + json.dumps(hashtags, ensure_ascii=False) + ". " if hashtags else "Wähle nur wenige passende Hashtags, wenn sie nützlich sind. ")
        + "Nutze keine sachfremden Trend-Hashtags."
    )
    if avoid:
        guidance.append("Zusätzliche Vorgabe des Kontos: " + json.dumps(avoid, ensure_ascii=False) + ".")
    guidance.extend([
        "Die Überschrift ist eine kurze, eigenständige Zeile und deutlich kürzer als die Caption. Die Caption soll nicht bloß die Überschrift wiederholen.",
        focus,
        "Antworte ausschließlich als JSON nach dem vorgegebenen Schema mit den drei Zeichenketten headline, caption und hashtags. Kein Markdown und kein Begleittext.",
        "Heutige Idee:\n" + json.dumps(draft.get("idea", ""), ensure_ascii=False),
        "Bereits vorhandene Texte, die du bei Bedarf behutsam verbessern kannst:\n" + json.dumps(current, ensure_ascii=False),
    ])
    return "\n\n".join(guidance)


def generate(profile: dict, draft: dict, part: str | None, runner=None) -> dict:
    if part not in (None, *FIELDS):
        raise ValueError("Unbekanntes Textfeld.")
    schema = Path(__file__).with_name("codex_schema.json").resolve()
    argv = ["codex", "exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
            "-c", 'model_provider="openai"', "--output-schema", str(schema)]
    from .settings import codex_settings
    effective = codex_settings(profile)
    if effective.get("model") and effective["model"] != "Codex-Standard":
        argv += ["--model", effective["model"]]
    if effective.get("effort"):
        argv += ["-c", "model_reasoning_effort=" + json.dumps(effective["effort"])]
    argv.append("-")
    prompt = _prompt(profile, draft, part)
    selected_runner = runner or _default_runner
    try:
        with tempfile.TemporaryDirectory(prefix="studio-codex-") as scratch:
            parameters = inspect.signature(selected_runner).parameters
            stdout = selected_runner(argv, scratch, prompt) if len(parameters) >= 3 else selected_runner(argv, scratch)
        generated = json.loads(stdout)
        if not isinstance(generated, dict) or set(generated) != set(FIELDS):
            raise ValueError
        if any(not isinstance(generated[field], str) for field in FIELDS):
            raise ValueError
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        raise RuntimeError(ERROR) from None
    if part is None:
        return generated
    merged = {field: str(draft.get(field, "")) for field in FIELDS}
    merged[part] = generated[part]
    return merged
