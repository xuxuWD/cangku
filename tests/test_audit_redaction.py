from app.audit.redaction import has_sensitive_key, key_tokens, mask_phone


def test_key_tokens_splits_underscore_hyphen_and_camel_case() -> None:
    assert key_tokens("api_key") == {"api", "key"}
    assert key_tokens("x-api-key") == {"x", "api", "key"}
    assert key_tokens("apiKey") == {"api", "key"}
    assert key_tokens("API_KEY") == {"api", "key"}
    assert key_tokens("keyword") == {"keyword"}


def test_has_sensitive_key_blocks_compound_nested_and_camel_case() -> None:
    for value in (
        {"client_secret": "x"},
        {"x-api-key": "x"},
        {"apiKey": "x"},
        {"accessToken": "x"},
        {"Authorization": "x"},
        {"credential": "x"},
        {"headers": {"Authorization": "x"}},
        {"items": [{"clientSecret": "x"}]},
    ):
        assert has_sensitive_key(value) is True


def test_has_sensitive_key_allows_benign_keys() -> None:
    assert has_sensitive_key({"keyword": "a", "topicName": "b", "goal": "c"}) is False
    assert has_sensitive_key({}) is False
    assert has_sensitive_key("text") is False


def test_mask_phone_masks_short_and_full_numbers() -> None:
    assert mask_phone("13800000001") == "138****0001"
    assert mask_phone("1234567") == "*******"
    assert mask_phone("") == ""
