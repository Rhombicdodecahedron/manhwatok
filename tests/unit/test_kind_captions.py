from manhwatok.domain.caption import upload_description
from manhwatok.domain.models import PostKind
from tests.unit.fakes import manhwa, post


def test_a_similar_post_names_its_seed():
    p = post(kind=PostKind.SIMILAR, seed=manhwa(anilist_id=99, title="Seed"))
    assert upload_description(p).startswith("If you liked Seed, read:\n1. Title 1\n")
