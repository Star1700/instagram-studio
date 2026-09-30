import json
from pathlib import Path

from studio.codex_text import _prompt, generate


def test_runner_gets_ephemeral_schema_and_a_cwd_outside_the_repo():
    seen = {}

    def runner(argv, cwd):
        seen.update(argv=argv, cwd=cwd)
        return json.dumps({
            "headline": "Weiter", "caption": "Ein Satz.", "hashtags": "#ruhe",
        })

    output = generate(
        {"language": "de", "niche": "Fitness", "tone": "ruhig", "avoid": "keine Versprechen"},
        {"idea": "morgen trainieren", **{field: "" for field in ("headline", "caption", "hashtags", "alt_text", "image_prompt")}},
        None, runner,
    )
    assert output["headline"] == "Weiter"
    assert "--ephemeral" in seen["argv"] and "--output-schema" in seen["argv"]
    assert seen["cwd"] != str(Path.cwd())
    assert "AGENTS.md" not in " ".join(seen["argv"])


def test_regenerate_one_part_keeps_the_other_fields():
    def runner(argv, cwd):
        return json.dumps({"headline": "Nur neu", "caption": "ignoriert", "hashtags": ""})

    draft = {"idea": "x", "headline": "Alt", "caption": "Bleibt", "hashtags": "#a",
             "alt_text": "alt", "image_prompt": "prompt"}
    output = generate({"language": "de", "avoid": ""}, draft, "headline", runner)
    assert output["headline"] == "Nur neu"
    assert output["caption"] == "Bleibt"
    assert "alt_text" not in output
    assert "image_prompt" not in output


def test_prompt_only_contains_writing_fields():
    seen = {}

    def runner(argv, cwd, prompt):
        seen["prompt"] = prompt
        return json.dumps({"headline": "Neu", "caption": "Text", "hashtags": "#fit"})

    generate(
        {"language": "de", "niche": "Fitness", "tone": "freundlich", "logo_path": "private-logo.png",
         "references": {"portrait": "private-reference.jpg"}},
        {"id": "private-id", "server_id": "private-server-id", "idea": "Training",
         **{field: "" for field in ("headline", "caption", "hashtags", "alt_text")},
         "image_prompt": "SECRET_IMAGE_PROMPT"},
        None, runner,
    )
    assert "Fitness" in seen["prompt"] and "Training" in seen["prompt"]
    assert "private-logo" not in seen["prompt"]
    assert "private-reference" not in seen["prompt"]
    assert "private-id" not in seen["prompt"]
    assert "SECRET_IMAGE_PROMPT" not in seen["prompt"]
    assert "image_prompt" not in seen["prompt"]


def test_prompt_translates_style_and_emoji_choice_into_writing_guidance():
    profile = {"language": "Deutsch", "niche": "Familienalltag", "tone": "locker und humorvoll",
               "emoji": "Emojis im Überfluss", "hashtags": "3 bis 8, deutsch", "avoid": "Keine Erziehungsversprechen"}
    draft = {"idea": "Aufräumen mit Kindern", "caption": "", "image_prompt": "Ein unvollständiges Poster"}
    prompt = _prompt(profile, draft, None)
    assert "kleinen, passenden Augenzwinkern" in prompt
    assert "auffallend viele passende Emojis" in prompt
    assert "Der langfristige Schwerpunkt des Instagram-Kontos" in prompt
    assert "Wenn die heutige Idee davon abweicht" in prompt
    assert "erfinde keine Fakten" in prompt
    assert "Gedankenstriche" in prompt
    assert "Ein unvollständiges Poster" not in prompt
    assert "image_prompt" not in prompt
    assert '"Aufräumen mit Kindern"' in prompt
