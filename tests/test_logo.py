from airmirror import logo


def test_sprite_is_32_square_and_uses_known_colours():
    rows = logo.sprite()
    assert len(rows) == 32 and all(len(r) == 32 for r in rows)
    keys = set("".join(rows)) - {"."}
    assert keys <= set(logo.BASE) | {"S", "H"}


def test_states_differ_only_on_the_screen():
    idle, live = logo.render("idle"), logo.render("live")
    assert idle.size == live.size == (32, 32)
    screen_pixel = (16, 22)
    assert idle.getpixel(screen_pixel) != live.getpixel(screen_pixel)
    frog_pixel = (16, 8)
    assert idle.getpixel(frog_pixel) == live.getpixel(frog_pixel)
    assert logo.render("live", scale=4).size == (128, 128)
