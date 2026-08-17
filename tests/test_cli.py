"""Progress reporting: plain numbered lines when piped, a redrawn
single-line bar on a terminal."""

from d2pt_guides.cli import Progress, stable_guide_id
from d2pt_guides.guide import Guide


def test_stable_guide_id_is_deterministic_and_unique():
    """Filenames must not change between runs — the in-game client tracks a
    followed guide by file name, so a stable name updates it in place."""
    assert stable_guide_id(18, 1, 0) == stable_guide_id(18, 1, 0)
    seen = {
        stable_guide_id(h, p, i)
        for h in range(1, 160)
        for p in range(1, 6)
        for i in range(3)
    }
    assert len(seen) == 159 * 5 * 3  # no collisions


def test_filename_stable_while_time_updated_moves():
    a = Guide(hero="sven", title="t", timestamp=stable_guide_id(18, 1, 0), updated=100)
    b = Guide(hero="sven", title="t", timestamp=stable_guide_id(18, 1, 0), updated=200)
    assert a.filename() == b.filename()
    assert '"TimeUpdated"\t\t"0x0000000000000064"' in a.render()
    assert '"TimeUpdated"\t\t"0x00000000000000C8"' in b.render()


def test_progress_plain_lines_when_piped(capsys):
    p = Progress(3)
    p.step("Sven")
    p.println("wrote sven.build")
    p.step("Naga Siren")
    p.done()
    out = capsys.readouterr()
    assert "[1/3] Sven" in out.out
    assert "wrote sven.build" in out.out
    assert "[2/3] Naga Siren" in out.out
    assert "\r" not in out.err  # no bar redraws off-terminal


def test_progress_bar_on_tty(capsys, monkeypatch):
    p = Progress(2)
    monkeypatch.setattr(p, "tty", True)
    p.step("Sven")
    p.step("Naga Siren")
    p.done()
    out = capsys.readouterr()
    assert "[1/2]" not in out.out  # bar goes to stderr, not stdout
    assert "\r" in out.err
    assert "2/2 (100%)" in out.err
    assert out.err.endswith("\n")
