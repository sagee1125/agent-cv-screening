# Unit tests for grouping JAS applicants by the post they applied for (multi-post advertisements).
from screening_core.posts import (
    base_name,
    group_by_post,
    mentioned_in_post_title,
    order_by_records_page,
    post_counts,
    post_key,
    post_of,
)


# The post value is read from either shape the pipeline passes around: dict rows and dataclasses.
def test_post_of_reads_dicts_and_objects() -> None:
    class Row:
        post = "  Research Assistant  "

    assert post_of({"post": "Research Associate"}) == "Research Associate"
    assert post_of(Row()) == "Research Assistant"
    assert post_of({"post": None}) == ""
    assert post_of({"post": "   "}) == ""
    assert post_of({}) == ""


# Labels are compared case-insensitively with whitespace collapsed.
def test_post_key_normalises_case_and_whitespace() -> None:
    assert post_key("Senior Project Fellow (Full-time)") == "senior project fellow (full-time)"
    assert post_key("  Research   Assistant ") == post_key("research assistant")


# A trailing parenthetical is dropped so full-time and part-time variants share one base name.
def test_base_name_drops_the_trailing_parenthetical() -> None:
    assert base_name("Senior Project Fellow (Full-time)") == "Senior Project Fellow"
    assert base_name("Senior Project Fellow (Part-time)") == "Senior Project Fellow"
    assert base_name("Research Associate") == "Research Associate"
    assert base_name("") == ""


# Cross-check a post against the advertisement's Post title (FR-3).
def test_mentioned_in_post_title() -> None:
    title = "Senior Project Fellow / Postdoctoral Fellow (Full-time/Part-time)"
    assert mentioned_in_post_title(title, "Senior Project Fellow (Full-time)") is True
    assert mentioned_in_post_title(title, "Postdoctoral Fellow (Part-time)") is True
    assert mentioned_in_post_title(title, "Research Assistant") is False


# A single-post advertisement has no post dimension, so it yields no groups and no unassigned rows.
def test_group_by_post_is_inert_for_a_single_post_page() -> None:
    rows = [{"appno": "1"}, {"appno": "2", "post": None}]
    grouping = group_by_post(rows, multi_post=False)
    assert grouping.multi_post is False
    assert grouping.groups == []
    assert grouping.unassigned == []
    assert grouping.labels == []


# Groups keep first-appearance order and preserve the spelling HR saw first.
def test_group_by_post_keeps_page_order_and_first_spelling() -> None:
    rows = [
        {"appno": "1", "post": "Research Associate"},
        {"appno": "2", "post": "Research Assistant"},
        {"appno": "3", "post": "research associate"},
        {"appno": "4", "post": "Research Assistant"},
    ]
    grouping = group_by_post(rows, multi_post=True)
    assert grouping.labels == ["Research Associate", "Research Assistant"]
    assert [row["appno"] for row in grouping.groups[0].rows] == ["1", "3"]
    assert [row["appno"] for row in grouping.groups[1].rows] == ["2", "4"]
    assert grouping.unassigned == []


# A blank post value cannot be placed in any group, so it is returned for HR to confirm (FR-7).
def test_group_by_post_separates_rows_with_no_post() -> None:
    rows = [
        {"appno": "1", "post": "Research Associate"},
        {"appno": "2", "post": "   "},
        {"appno": "3"},
    ]
    grouping = group_by_post(rows, multi_post=True)
    assert grouping.labels == ["Research Associate"]
    assert [row["appno"] for row in grouping.unassigned] == ["2", "3"]


# The universe holds exactly the posts that received an application, never a post nobody applied for.
def test_post_universe_is_derived_from_applicants_only() -> None:
    grouping = group_by_post([{"appno": "1", "post": "Research Assistant"}], multi_post=True)
    assert grouping.labels == ["Research Assistant"]


# The post list counts applicants per post, keyed exactly as the board's groups are keyed, so the
# counts always agree with the sections HR reads (PRD Section 6, FR-11).
def test_post_counts_reports_per_post_totals() -> None:
    rows = [
        {"appno": "1", "post": "Research Associate"},
        {"appno": "2", "post": "Research Assistant"},
        {"appno": "3", "post": "research associate"},
        {"appno": "4", "post": "   "},
        {"appno": "5"},
    ]
    assert post_counts(rows) == [
        {"post": "Research Associate", "applicants": 2},
        {"post": "Research Assistant", "applicants": 1},
    ]


# A single-post page yields no post list at all, so nothing downstream gains an empty dimension.
def test_post_counts_is_empty_without_a_post() -> None:
    assert post_counts([]) == []
    assert post_counts(None) == []
    assert post_counts([{"appno": "1", "post": None}]) == []
    assert post_counts([{"appno": "1", "post": "  "}]) == []


# Every HR-facing list follows the records page's own order, which is why the board's sections, both
# manifests' post lists and the update check can be read side by side (FR-6.3).
def test_order_by_records_page_follows_the_page() -> None:
    items = [("111111", "cv-a"), ("222222", "cv-b"), ("333333", "cv-c")]
    page = [{"appno": "333333"}, {"appno": "111111"}, {"appno": "222222"}]
    assert order_by_records_page(items, page) == [
        ("333333", "cv-c"),
        ("111111", "cv-a"),
        ("222222", "cv-b"),
    ]


# A CV HR passed by hand is not on the page, so it must not displace the order the page gives; it
# keeps its relative place after the applicants the page does list.
def test_order_by_records_page_keeps_unlisted_applicants_last() -> None:
    items = [("hand-1", "cv-a"), ("111111", "cv-b"), ("hand-2", "cv-c"), ("222222", "cv-d")]
    page = [{"appno": "222222"}, {"appno": "111111"}]
    assert order_by_records_page(items, page) == [
        ("222222", "cv-d"),
        ("111111", "cv-b"),
        ("hand-1", "cv-a"),
        ("hand-2", "cv-c"),
    ]


# A page with no candidates at all leaves the sequence exactly as it came in, so an entry point that
# has no records page keeps behaving as it always has.
def test_order_by_records_page_without_a_page_is_a_no_op() -> None:
    items = [("111111", "cv-a"), ("222222", "cv-b")]
    for page in ([], None, [{"appno": None}, {}]):
        assert order_by_records_page(items, page) == items
