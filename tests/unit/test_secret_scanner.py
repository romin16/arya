from scripts.check_secrets import scan_text


def test_secret_scanner_detects_credential_patterns_without_returning_values():
    fake_key = "sk-proj-" + "A" * 32
    fake_mail = "private" + "@" + "fictional" + ".local"
    fake_phone = "+" + "44 20" + " 1234" + " 5678"
    found = scan_text(
        f"OPENAI_API_KEY={fake_key}; contact={fake_mail}; backup={fake_phone}; "
        "GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-" + "B" * 24
    )
    assert {"OpenAI/API key", "Google OAuth client secret", "email address", "phone number"} <= found
    assert fake_key not in " ".join(found)
    assert fake_mail not in " ".join(found)
    assert fake_phone not in " ".join(found)


def test_secret_scanner_ignores_documented_placeholders_and_reserved_domains():
    assert not scan_text(
        "OPENAI_API_KEY=; contact=you@example.com; support=user@example.org; "
        "mail=person@example.test; key=YOUR_PORCUPINE_ACCESS_KEY"
    )
