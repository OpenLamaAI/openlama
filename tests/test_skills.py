"""Tests for src/openlama/core/skills.py — skill discovery, matching, CRUD, and caching."""

import time

import pytest

from openlama.core.skills import (
    _parse_frontmatter,
    _invalidate_cache,
    build_skills_section,
    delete_skill,
    discover_skills,
    load_skill,
    match_skill,
    save_skill,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure skill cache is cleared before and after each test."""
    _invalidate_cache()
    yield
    _invalidate_cache()


# ── _parse_frontmatter ──


def test_parse_frontmatter_valid():
    text = '---\nname: greeting\ndescription: "Say hello"\ntrigger: "hi,hello"\n---\nBody content here.'
    meta, body = _parse_frontmatter(text)
    assert meta["name"] == "greeting"
    assert meta["description"] == "Say hello"
    assert meta["trigger"] == "hi,hello"
    assert body == "Body content here."


def test_parse_frontmatter_no_frontmatter():
    text = "Just plain text, no frontmatter."
    meta, body = _parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_unclosed():
    text = "---\nname: broken\nThis never closes"
    meta, body = _parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_empty_string():
    meta, body = _parse_frontmatter("")
    assert meta == {}
    assert body == ""


def test_parse_frontmatter_comments_skipped():
    text = "---\n# comment line\nname: test\n---\nBody"
    meta, body = _parse_frontmatter(text)
    assert meta["name"] == "test"
    assert "comment" not in meta


def test_parse_frontmatter_strips_quotes():
    text = '---\nname: "quoted"\n---\nBody'
    meta, body = _parse_frontmatter(text)
    assert meta["name"] == "quoted"


# ── discover_skills ──


def test_discover_skills_empty_dir(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = discover_skills()
    assert result == []


def test_discover_skills_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: tmp_path / "nonexistent")
    result = discover_skills()
    assert result == []


def test_discover_skills_with_skills(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skill_a = skills_dir / "greet"
    skill_a.mkdir(parents=True)
    (skill_a / "SKILL.md").write_text(
        '---\nname: greet\ndescription: "Greeting skill"\ntrigger: "hi,hello"\n---\nSay hi!',
        encoding="utf-8",
    )
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = discover_skills()
    assert len(result) == 1
    assert result[0]["name"] == "greet"
    assert result[0]["description"] == "Greeting skill"
    assert result[0]["trigger"] == "hi,hello"
    assert result[0]["body"] == "Say hi!"


def test_discover_skills_skips_non_dirs(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "stray_file.txt").write_text("not a skill")
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = discover_skills()
    assert result == []


def test_discover_skills_skips_malformed(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    bad_skill = skills_dir / "bad"
    bad_skill.mkdir(parents=True)
    # Missing SKILL.md entirely
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = discover_skills()
    assert result == []


# ── load_skill ──


def test_load_skill_found(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "code"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: code\ndescription: "Coder"\ntrigger: "code"\n---\nWrite code.',
        encoding="utf-8",
    )
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    skill = load_skill("code")
    assert skill is not None
    assert skill["name"] == "code"


def test_load_skill_not_found(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    assert load_skill("nonexistent") is None


# ── match_skill ──


def test_match_skill_matching(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "weather"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: weather\ndescription: "Weather info"\ntrigger: "weather,forecast"\n---\nCheck weather.',
        encoding="utf-8",
    )
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = match_skill("What is the weather today?")
    assert result is not None
    assert result["name"] == "weather"


def test_match_skill_no_match(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "weather"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: weather\ndescription: "Weather info"\ntrigger: "weather,forecast"\n---\nCheck weather.',
        encoding="utf-8",
    )
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = match_skill("Tell me a joke")
    assert result is None


def test_match_skill_empty_text(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    assert match_skill("") is None
    assert match_skill(None) is None


def test_match_skill_best_score(tmp_path, monkeypatch):
    """Skill with more keyword matches should win."""
    skills_dir = tmp_path / "skills"
    for name, trigger in [("a", "search"), ("b", "search,web")]:
        d = skills_dir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: "test"\ntrigger: "{trigger}"\n---\nBody',
            encoding="utf-8",
        )
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    result = match_skill("web search query")
    assert result is not None
    assert result["name"] == "b"


# ── save_skill & delete_skill ──


def test_save_and_delete_skill(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)

    path = save_skill("myskill", "A test skill", "test,demo", "Do the thing.")
    assert (skills_dir / "myskill" / "SKILL.md").exists()

    # Verify content is loadable
    skill = load_skill("myskill")
    assert skill is not None
    assert skill["description"] == "A test skill"
    assert "Do the thing." in skill["body"]

    # Delete
    assert delete_skill("myskill") is True
    assert not (skills_dir / "myskill").exists()

    # Delete again returns False
    _invalidate_cache()
    assert delete_skill("myskill") is False


# ── build_skills_section ──


def test_build_skills_section_empty(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    assert build_skills_section() == ""


def test_build_skills_section_non_empty(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    save_skill("demo", "Demo skill", "demo", "Instructions here.")
    section = build_skills_section()
    assert "## Available Skills" in section
    assert "demo" in section
    assert "Demo skill" in section


# ── Cache invalidation ──


def test_cache_invalidated_on_save(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)

    # First discovery — empty
    assert discover_skills() == []

    # Save a skill — cache should be invalidated
    save_skill("cached", "Test cache", "cache", "Body")
    result = discover_skills()
    assert len(result) == 1
    assert result[0]["name"] == "cached"


def test_cache_invalidated_on_delete(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)

    save_skill("todelete", "Will be deleted", "del", "Body")
    assert len(discover_skills()) == 1

    delete_skill("todelete")
    assert len(discover_skills()) == 0


def test_cache_ttl_serves_cached(tmp_path, monkeypatch):
    """Within TTL, discover_skills should return cached results even if disk changed."""
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)

    save_skill("first", "First", "first", "Body")
    result1 = discover_skills()
    assert len(result1) == 1

    # Manually add a skill on disk without invalidating cache
    d = skills_dir / "sneaky"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text('---\nname: sneaky\n---\nHidden', encoding="utf-8")

    # Cache is still valid — should not see the sneaky skill
    result2 = discover_skills()
    assert len(result2) == 1

    # After invalidation, both are visible
    _invalidate_cache()
    result3 = discover_skills()
    assert len(result3) == 2
