import pytest

from core.leads.regions import REGIONS, RegionIndex, by_region, fold

INDEX = RegionIndex(
    cities=[
        ("toshkent", ["Chirchiq", "Чирчик", "Yangiyo'l"]),
        ("fargona", ["Qo'qon", "Коканд", "Marg'ilon"]),
        ("nowhere", ["Atlantis"]),
    ]
)


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Toshkent", "toshkent_shahri"),
        ("Tashkent", "toshkent_shahri"),
        ("г. Ташкент", "toshkent_shahri"),
        ("Toshkent shahri", "toshkent_shahri"),
        ("Tashkent Region", "toshkent"),
        ("Toshkent viloyati", "toshkent"),
        ("Ташкентская область", "toshkent"),
        ("Farg'ona", "fargona"),
        ("Fargʻona viloyati", "fargona"),
        ("Fergana Region", "fargona"),
        ("Фарғона", "fargona"),
        ("Qashqadaryo Region", "qashqadaryo"),
        ("Кашкадарьинская область", "qashqadaryo"),
        ("Republic of Karakalpakstan", "qoraqalpogiston"),
        ("Qoraqalpog'iston Respublikasi", "qoraqalpogiston"),
        ("Samarkand", "samarqand"),
        ("  SAMARQAND  ", "samarqand"),
        ("Bukhara Region", "buxoro"),
        ("Khorezm", "xorazm"),
    ],
)
def test_region_names_in_every_spelling(text: str, key: str) -> None:
    assert INDEX.region_of(text) == key


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Chirchiq", "toshkent"),
        ("Чирчик", "toshkent"),
        ("Yangi yo'l", "toshkent"),
        ("Qo'qon", "fargona"),
        ("Коканд", "fargona"),
    ],
)
def test_cities_the_caller_knows(text: str, key: str) -> None:
    assert INDEX.region_of(text) == key


@pytest.mark.parametrize("text", ["", "   ", "Moskva", "Atlantis", "-"])
def test_names_no_region(text: str) -> None:
    assert INDEX.region_of(text) is None


def test_fold_reports_the_region_word() -> None:
    assert fold("Farg'ona viloyati").base == "fargona"
    assert fold("Farg'ona viloyati").says_region
    assert not fold("Farg'ona").says_region


def test_by_region_adds_up_and_counts_the_unplaced() -> None:
    rows = [("Toshkent", 5), ("Tashkent", 2), ("Tashkent Region", 3), ("Moskva", 4)]
    found, unplaced = by_region(rows, index=INDEX)
    assert found == {"toshkent_shahri": 7, "toshkent": 3}
    assert unplaced == 4


def test_fourteen_regions() -> None:
    assert len(REGIONS) == 14
    assert len({key for key, _ in REGIONS}) == 14
