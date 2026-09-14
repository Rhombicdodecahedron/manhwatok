from manhwatok.adapters.fonts import anton, inter, inter_extrabold, inter_semibold


def test_fonts_load_at_requested_size():
    assert anton(84).size == 84
    assert inter_semibold(40).size == 40


def test_inter_weights_really_differ():
    text = "Hello World"
    assert inter_extrabold(40).getlength(text) > inter_semibold(40).getlength(text)


def test_fonts_are_cached():
    assert anton(84) is anton(84)
    assert inter(40, 600) is inter_semibold(40)
