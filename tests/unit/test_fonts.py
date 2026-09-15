from importlib.resources import files

from manhwatok.adapters.fonts import body, bold, display, montserrat


def test_fonts_load_at_requested_size():
    assert display(84).size == 84
    assert body(40).size == 40


def test_weights_really_differ():
    text = "Hello World"
    assert display(40).getlength(text) > bold(40).getlength(text) > body(40).getlength(text)


def test_fonts_are_cached():
    assert display(84) is display(84)
    assert montserrat(40, 600) is body(40)


def test_only_montserrat_is_bundled():
    bundled = {p.name for p in (files("manhwatok") / "assets" / "fonts").iterdir()}
    assert bundled == {"Montserrat-Variable.ttf", "OFL-Montserrat.txt"}
