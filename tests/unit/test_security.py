from app.core.security import generate_api_key, hash_api_key


def test_generate_api_key_has_prefix_and_is_unique() -> None:
    first = generate_api_key()
    second = generate_api_key()
    assert first.startswith("ne_")
    assert second.startswith("ne_")
    assert first != second


def test_hash_api_key_is_deterministic() -> None:
    raw = "ne_example-key"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_hash_api_key_differs_for_different_inputs() -> None:
    assert hash_api_key("ne_a") != hash_api_key("ne_A")


def test_hash_api_key_is_not_the_raw_key() -> None:
    raw = generate_api_key()
    hashed = hash_api_key(raw)
    assert hashed != raw
    assert len(hashed) == 64
    int(hashed, 16)  # raises if not hex
