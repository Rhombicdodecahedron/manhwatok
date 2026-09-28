from manhwatok.domain.caption import upload_description
from manhwatok.domain.models import PostKind
from tests.unit.fakes import manhwa, post


def test_a_similar_post_names_its_seed():
    p = post(kind=PostKind.SIMILAR, seed=manhwa(anilist_id=99, title="Seed"))
    assert upload_description(p).startswith("If you liked Seed, read:\n1. Title 1\n")


def test_a_versus_post_lists_its_rounds():
    from manhwatok.domain.post import PostItem

    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2, 3, 4)]
    text = upload_description(post(items=items, kind=PostKind.VERSUS))
    assert text.startswith("1. T1 vs T2\n2. T3 vs T4\n")


def test_a_guess_post_keeps_its_answers_below_the_fold():
    from manhwatok.domain.post import PostItem

    items = [PostItem(manhwa=manhwa(anilist_id=i, title=f"T{i}")) for i in (1, 2)]
    text = upload_description(post(items=items, kind=PostKind.GUESS))
    assert text.startswith("Guess all 2 before you swipe!")
    assert "Answers:\n1. T1\n2. T2" in text
