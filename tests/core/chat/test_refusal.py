"""Which refusals share one written answer, and what the model is told."""

from core.chat.refusal import RefusalFacts, refusal_key, shareable


def test_a_code_and_subcode_name_one_refusal() -> None:
    key = refusal_key(
        provider="meta",
        error_code="refused",
        error_message="Invalid parameter | Location not recognized | code 100/1487851",
    )

    assert key == "meta:100/1487851"


def test_a_code_alone_is_not_a_key() -> None:
    """100 is every invalid value Meta has; one answer cannot fit them all."""
    key = refusal_key(
        provider="meta", error_code="refused", error_message="Invalid parameter"
    )

    assert key == ""


def test_our_own_code_is_a_key_when_it_names_one_failure() -> None:
    key = refusal_key(
        provider="meta", error_code="site_missing", error_message="no site"
    )

    assert key == "meta:site_missing"


def test_an_unknown_code_is_not_a_key() -> None:
    assert refusal_key(provider="meta", error_code="unknown", error_message="") == ""
    assert refusal_key(provider="meta", error_code="new-one", error_message="") == ""


def test_the_model_reads_metas_words_and_the_advert() -> None:
    facts = RefusalFacts(
        error_code="refused",
        provider_title="Ad Creative Rejected",
        provider_message="Your ad does not follow our policy.",
        developer_message="Invalid parameter | code 100/1815316",
        goal="leads",
        sections={"The audience as sent": {"age_min": 24}},
    )

    text = facts.render()

    assert "Ad Creative Rejected" in text
    assert "Your ad does not follow our policy." in text
    assert "code 100/1815316" in text
    assert "goal: leads" in text
    assert '"age_min":24' in text
    assert "24" in facts.figures()


def test_a_long_section_is_cut() -> None:
    facts = RefusalFacts(error_code="refused", sections={"Draft": {"t": "x" * 5000}})

    assert len(facts.render()) < 3_500


# --- Links -------------------------------------------------------------------

from core.chat.links import Link, link_html, link_text  # noqa: E402

LINKS = {"tolov": Link(label="To'lov sahifasi", url="https://x/pay?asset_id=1&a=b")}


def test_a_known_name_becomes_an_anchor_with_an_escaped_address() -> None:
    drawn = link_html("1. Oching: [[tolov]]", LINKS)

    assert '<a href="https://x/pay?asset_id=1&amp;a=b"' in drawn
    assert "To&#x27;lov sahifasi</a>" in drawn


def test_an_unknown_name_is_removed_not_linked() -> None:
    assert link_html("Oching: [[boshqa]]", LINKS) == "Oching: "


def test_plain_text_spells_the_address() -> None:
    assert (
        link_text("[[tolov]]", LINKS)
        == "To'lov sahifasi (https://x/pay?asset_id=1&a=b)"
    )


def test_an_answer_with_only_words_of_the_sentence_is_shareable() -> None:
    assert shareable("1. Rasmni almashtiring.\n2. 24 soat kuting.")


def test_an_answer_with_somebody_s_budget_or_id_is_not() -> None:
    assert not shareable("Byudjetingiz 45 000 so'm.")
    assert not shareable("Akkaunt 1234567890 bloklangan.")
