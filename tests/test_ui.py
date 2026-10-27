"""Regresiones de interfaz (Qt sin pantalla): asistente, navegación, edición y cola."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from clutchreel.core.demo.models import Highlight
from clutchreel.core.editor.project import new_project
from clutchreel.services.config import StyleSettings
from clutchreel.ui.workers import Worker, WorkerPool
from tests.conftest import ME


@pytest.fixture(scope="module")
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication([])


@pytest.fixture
def state(qapp, monkeypatch):  # type: ignore[no-untyped-def]
    from clutchreel.services import config as config_mod
    from clutchreel.ui.state import AppState

    monkeypatch.setattr(config_mod, "_store", None)  # configuración nueva en el %APPDATA% aislado del test
    st = AppState()
    st.config.ui.first_run_done = True
    st.config.player.steamid64 = 0
    return st


@pytest.fixture
def no_steam(monkeypatch):  # type: ignore[no-untyped-def]
    from clutchreel.utils import paths

    monkeypatch.setattr(paths, "steam_logged_accounts", lambda: [])
    monkeypatch.setattr(paths, "steam_userdata_ids", lambda: [])


@pytest.fixture
def boxes(monkeypatch):  # type: ignore[no-untyped-def]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(str(a[1])) or QMessageBox.StandardButton.Ok)
    return shown


def test_wizard_does_not_guess_the_player(state, match, no_steam, boxes):  # type: ignore[no-untyped-def]
    """Antes, sin cuenta reconocida quedaba seleccionada la primera fila y «Usar recomendado» grababa a otro."""
    from clutchreel.ui.pages.wizard_page import WizardPage

    w = WizardPage(state)
    got: list[object] = []
    w.finished.connect(got.append)
    w.load_match(match)
    assert w._selected_player() == (0, "")
    assert not w.lbl_player_warning.isHidden()
    w._use_recommended()
    assert got == [] and boxes == ["Elige tu jugador"]
    w.tbl_players.selectRow(0)
    w._use_recommended()
    assert len(got) == 1


def test_wizard_preselects_the_known_player(state, match, no_steam):  # type: ignore[no-untyped-def]
    from clutchreel.ui.pages.wizard_page import WizardPage

    state.config.player.steamid64 = ME
    w = WizardPage(state)
    w.load_match(match)
    assert w._selected_player()[0] == ME
    assert w.lbl_player_warning.isHidden()


def test_wizard_existing_recording_requires_a_video(state, match, no_steam, boxes, tmp_path):  # type: ignore[no-untyped-def]
    from clutchreel.ui.pages.wizard_page import WizardPage

    state.config.player.steamid64 = ME
    w = WizardPage(state)
    got: list[object] = []
    w.finished.connect(got.append)
    w.load_match(match)
    w.rb_existing.setChecked(True)
    w._finish()
    assert got == [] and boxes == ["Falta el vídeo"]
    video = tmp_path / "partida completa ñ.mp4"
    video.write_bytes(b"x")
    w.edt_existing.setText(str(video))
    w._finish()
    assert len(got) == 1 and got[0].recording_mode == "existing"  # type: ignore[attr-defined]


def _project(match, tmp_path):  # type: ignore[no-untyped-def]
    hls = [Highlight("3k", 1, 1400, 1400 + 64 * 10, 50.0, "3K", key_tick=1500), Highlight("entry", 3, 17000, 17000 + 64 * 5, 20.0, "entry", key_tick=17050)]
    p = new_project(match, ME, "yo", hls, StyleSettings())
    p.path = str(tmp_path / "p.clutchreel.json")
    return p


def test_trim_drag_is_one_undo_step_and_saved_once(state, match, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Antes, cada paso del deslizador copiaba el proyecto entero y lo escribía en disco."""
    from clutchreel.ui.pages.review_page import ReviewPage

    page = ReviewPage(state)
    state.project = _project(match, tmp_path)
    page.load_project()
    saves: list[int] = []
    monkeypatch.setattr(state, "autosave", lambda: saves.append(1))
    page.sld_start.sliderPressed.emit()
    for v in range(1, 30):
        page.sld_start.setValue(v)
    page.sld_start.sliderReleased.emit()
    assert len(state.undo._undo) == 1
    assert saves == [1]
    assert state.project.clips[0].trim_start == pytest.approx(2.9)
    page._undo()
    assert state.project.clips[0].trim_start == 0.0


def test_pending_edit_is_saved_into_its_own_project(state, match, tmp_path):  # type: ignore[no-untyped-def]
    from clutchreel.ui.pages.review_page import ReviewPage

    page = ReviewPage(state)
    first = _project(match, tmp_path)
    state.project = first
    page.load_project()
    page.chk_slow.setChecked(not first.clips[0].slow_motion)  # edición con guardado diferido
    other = _project(match, tmp_path)
    other.path = str(tmp_path / "otro.clutchreel.json")
    state.project = other
    page.load_project()  # al cambiar de proyecto se guarda lo pendiente en el primero
    assert Path(first.path).exists() and not Path(other.path).exists()


def test_reopening_previous_project_stays_in_review(state, match, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Antes: «No = abrir el proyecto anterior» abría el proyecto y saltaba a la Cola."""
    from clutchreel.services.history import HistoryEntry
    from clutchreel.ui import dialogs
    from clutchreel.ui.main_window import MainWindow

    proj = _project(match, tmp_path)
    proj.save()
    demo = tmp_path / "partida.dem"
    demo.write_bytes(b"PBDEMS2" + b"\x00" * 10)
    state.history.add(HistoryEntry(str(demo), "fp", "de_test", "yo", "1-0", time.time(), proj.path))
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda *a, **k: False)
    win = MainWindow(state, QApplication.windowIcon())
    win.analyze_demos([demo])
    assert win.stack.currentIndex() == 2 and not win.queue.jobs
    win._quitting = True


def test_worker_progress_is_throttled(qapp):  # type: ignore[no-untyped-def]
    got: list[tuple[int, str]] = []

    def job(progress, cancel):  # type: ignore[no-untyped-def]
        for i in range(500):
            progress(i / 1000.0, "Grabando…")
        progress(0.6, "Comprobando el clip…")
        return "ok"

    w = Worker(job)
    w.progress.connect(lambda p, m: got.append((p, m)))
    w.run()  # en este hilo: las señales llegan directas
    assert len(got) < 20  # antes: 501 avisos
    assert got[-1] == (60, "Comprobando el clip…")  # los cambios de texto siempre llegan


def test_wait_all_waits_for_slow_cleanup(qapp):  # type: ignore[no-untyped-def]
    pool = WorkerPool()
    finished = threading.Event()

    def job(progress, cancel):  # type: ignore[no-untyped-def]
        cancel.wait()
        time.sleep(1.0)  # «parar OBS y restaurar CS2» tras cancelar
        finished.set()

    pool.start(Worker(job))
    assert pool.wait_all(10000, keep_alive=QApplication.processEvents)
    assert finished.is_set()


def test_cards_shrink_with_the_window(state, match, tmp_path):  # type: ignore[no-untyped-def]
    """Al encoger la ventana las tarjetas conservaban el ancho anterior y se cortaba su columna derecha."""
    from clutchreel.ui.pages.review_page import ReviewPage
    from clutchreel.ui.widgets.clip_card import ClipCard

    page = ReviewPage(state)
    state.project = _project(match, tmp_path)
    page.load_project()
    page.resize(1400, 800)
    page.show()
    QApplication.processEvents()
    page.resize(900, 700)
    for _ in range(10):
        QApplication.processEvents()
        time.sleep(0.02)
    card = page.lst.itemWidget(page.lst.item(0))
    assert isinstance(card, ClipCard)
    assert card.width() <= page.lst.viewport().width()
    assert card.lbl_score.geometry().right() <= card.width()
    page.hide()
