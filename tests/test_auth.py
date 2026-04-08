"""Tests for auth module – password hashing, verification."""

from auth import hash_password, verify_password


def test_hash_and_verify():
    pw = "strong_password_123"
    hashed = hash_password(pw)
    assert isinstance(hashed, str)
    assert hashed != pw
    assert verify_password(pw, hashed) is True


def test_wrong_password():
    hashed = hash_password("correct_password")
    assert verify_password("wrong_password", hashed) is False


def test_different_hashes():
    """Same password should produce different hashes (salt)."""
    pw = "same_password"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2  # bcrypt uses random salt
    assert verify_password(pw, h1) is True
    assert verify_password(pw, h2) is True


def test_empty_password():
    hashed = hash_password("")
    assert verify_password("", hashed) is True
    assert verify_password("notempty", hashed) is False
