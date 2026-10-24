from metaads.adapter import _issues
from metaads.campaign_rows import IssueRow
from metaads.text import plain_text

# What Meta wrote on an ad set whose page it had restricted, as stored.
RESTRICTED_PAGE = (
    "You can&#039;t create ads for this Page because it&#039;s restricted "
    "from advertising.<br /><br /><br /><a "
    'href="https://www.facebook.com/accountquality/advertising_access/'
    '?enforcement=3">See Details</a>'
)


def test_markup_and_entities_are_gone():
    assert plain_text(RESTRICTED_PAGE) == (
        "You can't create ads for this Page because it's restricted from advertising."
    )


def test_plain_sentence_is_kept_as_it_is():
    assert plain_text("  Ad set is paused.  ") == "Ad set is paused."
    assert plain_text("") == ""


def test_bare_ampersand_survives():
    assert plain_text("Terms & conditions") == "Terms & conditions"


def test_issue_reaches_the_domain_as_plain_text():
    (issue,) = _issues(
        (
            IssueRow(
                error_code=2446173,
                error_summary="Ad Can&#039;t Be Published",
                error_message=RESTRICTED_PAGE,
            ),
        )
    )
    assert issue.summary == "Ad Can't Be Published"
    assert "<" not in issue.message
    assert "&#039;" not in issue.message
