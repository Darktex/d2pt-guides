"""Progress reporting: plain numbered lines when piped, a redrawn
single-line bar on a terminal."""

from d2pt_guides.cli import Progress


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
