import sys

import pytest

import gestion_stock


def test_collect_environment_diagnostics_reports_components(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    diagnostics = gestion_stock.collect_environment_diagnostics()
    assert "tkinter" in diagnostics
    assert diagnostics["tkinter"]["ok"] == gestion_stock.TK_AVAILABLE
    assert "display" in diagnostics
    if sys.platform.startswith("linux"):
        assert diagnostics["display"]["detail"].startswith("DISPLAY=")


def test_main_diagnostics_exit_code_matches_status(capsys, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    expected = 0 if all(info.get("ok") for info in gestion_stock.collect_environment_diagnostics().values()) else 1
    exit_code = gestion_stock.main(["--diagnostics"])
    captured = capsys.readouterr()
    assert "Diagnostic de l'environnement" in captured.out
    assert exit_code == expected


@pytest.mark.skipif(not gestion_stock.TK_AVAILABLE, reason="Tkinter non disponible")
def test_main_gracefully_handles_tkinit_failure(monkeypatch, capsys):
    class FakeError(gestion_stock.tk.TclError):
        pass

    def fake_tk():
        raise FakeError("no display")

    monkeypatch.setattr(gestion_stock.tk, "Tk", fake_tk)
    exit_code = gestion_stock.main([])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "impossible d'initialiser Tkinter" in captured.out
