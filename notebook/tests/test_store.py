from pathlib import Path

import pytest

from studio.store import Store


def test_seed_profile_is_fitness_but_not_hardcoded_in_logic(tmp_path: Path):
    profile = Store(tmp_path).load_profile()
    assert profile["language"] == "Deutsch"
    assert "Fitness" in profile["niche"]
    assert "keine Trainings- oder Gesundheitsversprechen" in profile["avoid"]


def test_idea_and_text_update_are_saved(tmp_path: Path):
    store = Store(tmp_path)
    draft = store.create_draft("heute Beine")
    store.update_draft(draft["id"], idea="Neue Idee", caption="Neue Caption")
    again = store.load_draft(draft["id"])
    assert again["caption"] == "Neue Caption"
    assert again["idea"] == "Neue Idee"
    assert again["use_logo"] is True
    assert again["logo_position"] == "bottom_right"
    store.update_draft(draft["id"], use_logo=False)
    assert store.load_draft(draft["id"])["use_logo"] is False
    store.update_draft(draft["id"], logo_position="top_left", image_style="none")
    assert store.load_draft(draft["id"])["logo_position"] == "top_left"
    assert store.load_draft(draft["id"])["image_style"] == "none"
    with pytest.raises(ValueError, match="Logo-Position"):
        store.update_draft(draft["id"], logo_position="middle")


def test_original_image_is_kept_apart_from_preview(tmp_path: Path):
    store = Store(tmp_path)
    draft = store.create_draft("idee")
    store.save_original_image(draft["id"], b"original-bytes")
    store.save_preview(draft["id"], b"stamped-bytes")
    assert store.original_image(draft["id"]) == b"original-bytes"
    assert store.preview(draft["id"]) == b"stamped-bytes"


def test_delete_local_draft_removes_only_its_files(tmp_path: Path):
    store = Store(tmp_path)
    draft = store.create_draft("löschen")
    other = store.create_draft("behalten")
    store.save_original_image(draft["id"], b"original")
    store.save_preview(draft["id"], b"preview")
    store.delete_draft(draft["id"])
    assert not list(store.drafts.glob(f"{draft['id']}.*"))
    assert store.load_draft(other["id"])["idea"] == "behalten"
    with pytest.raises(KeyError):
        store.load_draft(draft["id"])


def test_delete_refuses_server_linked_draft(tmp_path: Path):
    store = Store(tmp_path)
    draft = store.create_draft("schon übertragen")
    store.update_draft(draft["id"], server_id="a" * 32)
    with pytest.raises(ValueError, match="Server"):
        store.delete_draft(draft["id"])
    assert store.load_draft(draft["id"])["server_id"] == "a" * 32
