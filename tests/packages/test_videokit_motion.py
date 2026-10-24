"""videokit: the footage's motion, its transitions and the montage's sound."""

from pathlib import Path
from typing import Any

import pytest
from videokit import ComponentUse, Cut, EditSpec, LayoutSpan, build_edit
from videokit.audio import DUCKED, cut_volume, duck, sound_tracks
from videokit.models import FaceMark
from videokit.motion import (
    ENTER_ZOOM,
    PUNCH,
    face_anchor,
    held_offset,
    scale_keys,
    scale_tweens,
)
from videokit.sounds import Sound

SOURCE = "https://example.test/source.mp4"


def _value(tweens: list[dict[str, Any]], at: float) -> float:
    """The tweened value at ``at``, read the way the renderer would."""
    for tween in tweens:
        if tween["start"] <= at <= tween["start"] + tween["length"]:
            share = (at - tween["start"]) / tween["length"]
            return float(tween["from"] + (tween["to"] - tween["from"]) * share)
    raise AssertionError(f"nothing covers {at}")


def _footage(edit: dict[str, Any]) -> list[dict[str, Any]]:
    return next(
        track["clips"]
        for track in edit["timeline"]["tracks"]
        if track["clips"][0]["asset"]["type"] == "video"
    )


def test_a_cut_creeps_closer_from_its_own_zoom() -> None:
    tweens = scale_tweens(scale_keys(4.0, base=1.15, punches=(), enter="none"), 0, 4)

    assert _value(tweens, 0) == pytest.approx(1.15)
    assert _value(tweens, 4) == pytest.approx(1.15 * 1.04)


def test_a_punch_steps_in_at_once_and_a_second_steps_back_out() -> None:
    keys = scale_keys(6.0, base=1.0, punches=(2.0, 4.0), enter="none")
    tweens = scale_tweens(keys, 0, 6)

    assert _value(tweens, 1.99) == pytest.approx(1.0, abs=0.02)
    assert [t["from"] for t in tweens][1] == pytest.approx(
        PUNCH * (1 + 0.05 * 2 / 6), abs=1e-3
    )
    assert tweens[2]["from"] == pytest.approx(1.0 * (1 + 0.05 * 4 / 6), abs=1e-3)


def test_a_punch_on_the_edge_of_a_cut_is_left_out() -> None:
    keys = scale_keys(3.0, base=1.0, punches=(0.2, 2.8), enter="none")

    assert len(keys) == 1


def test_a_zoom_transition_lands_from_closer_and_carries_on() -> None:
    keys = scale_keys(3.0, base=1.0, punches=(), enter="zoom")
    tweens = scale_tweens(keys, 0, 3)

    assert tweens[0]["from"] == pytest.approx(ENTER_ZOOM * tweens[0]["to"], abs=1e-3)
    assert tweens[0]["easing"] == "easeOutCubic"
    assert tweens[1]["from"] == tweens[0]["to"]


def test_the_curve_carries_across_a_layout_change_inside_a_cut() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=10, end=16),),
        layouts=(LayoutSpan(start=2, end=4, layout="split_top"),),
        motion="moving",
    )

    clips = _footage(build_edit(spec))

    assert [c["start"] for c in clips] == [0, 2, 4]
    ends = [c["scale"][-1]["to"] for c in clips[:-1]]
    starts = [c["scale"][0]["from"] for c in clips[1:]]
    assert ends == pytest.approx(starts)
    # The sound ramps only where the cut begins and ends.
    volumes = [c["asset"]["volume"] for c in clips]
    assert volumes[0][0]["from"] == 0 and volumes[0][-1]["to"] == 1
    assert volumes[1] == [
        {"from": 1, "to": 1, "start": 0, "length": 2, "interpolation": "linear"}
    ]
    assert volumes[2][-1]["to"] == 0


def test_still_is_the_edit_as_it_was() -> None:
    spec = EditSpec(
        source_url=SOURCE, cuts=(Cut(start=0, end=2), Cut(start=5, end=7, zoom=1.15))
    )

    clips = _footage(build_edit(spec))

    assert "volume" not in clips[0]["asset"]
    assert clips[1]["scale"] == 1.15


def test_transitions_come_in_their_own_way() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(
            Cut(start=0, end=2),
            Cut(start=4, end=6, enter="fade"),
            Cut(start=8, end=10, enter="slide"),
            Cut(start=12, end=14, enter="flash"),
        ),
        motion="moving",
    )

    edit = build_edit(spec)

    clips = _footage(edit)
    assert [c.get("transition", {}).get("in") for c in clips] == [
        None,
        "fadeFast",
        "slideUpFast",
        None,
    ]
    flash = edit["timeline"]["tracks"][0]["clips"]
    assert [c["start"] for c in flash] == [5.9]
    assert "gsap.timeline()" in flash[0]["asset"]["js"]


def test_cut_volume_ramps_only_the_ends_that_are_cuts() -> None:
    assert cut_volume(2.0, head=0.06, tail=0.0) == [
        {"from": 0, "to": 1, "start": 0, "length": 0.06, "interpolation": "linear"},
        {"from": 1, "to": 1, "start": 0.06, "length": 1.94, "interpolation": "linear"},
    ]


def test_music_drops_under_speech_and_comes_back_in_the_gaps() -> None:
    tweens = duck([(1.0, 3.0), (3.2, 4.0), (8.0, 9.0)], length=10.0, level=0.2)

    low = 0.2 * DUCKED
    assert _value(tweens, 0.5) == pytest.approx(0.2)
    assert _value(tweens, 2.0) == pytest.approx(low)
    # A pause shorter than the join keeps it down.
    assert _value(tweens, 3.1) == pytest.approx(low)
    assert _value(tweens, 6.0) == pytest.approx(0.2)
    assert _value(tweens, 8.5) == pytest.approx(low)
    assert _value(tweens, 10.0) == pytest.approx(0.2)
    assert tweens[0]["start"] == 0
    assert sum(t["length"] for t in tweens) == pytest.approx(10.0)


def test_speech_from_the_first_moment_starts_the_music_low() -> None:
    tweens = duck([(0.0, 2.0)], length=4.0, level=0.5)

    assert _value(tweens, 0.0) == pytest.approx(0.5 * DUCKED)


def test_music_ducks_under_the_subtitled_speech_when_moving() -> None:
    from videokit import CaptionLine, CaptionWord

    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=6),),
        captions=(
            CaptionLine(
                start=1, end=2, words=(CaptionWord(text="salom", start=1, end=2),)
            ),
        ),
        music_url="https://example.test/music.mp3",
        motion="moving",
    )

    music = build_edit(spec)["timeline"]["tracks"][-1]["clips"][0]

    assert isinstance(music["asset"]["volume"], list)


def _ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    catalogue = {}
    for name in ("pop", "whoosh", "ding", "click", "swoosh", "snap"):
        path = tmp_path / f"{name}.mp3"
        path.write_bytes(b"mp3")
        catalogue[name] = Sound(
            name=name, prompt="-", seconds=0.5, length=0.5, path=path
        )
    monkeypatch.setattr("videokit.audio.sounds", lambda: catalogue)


def test_each_component_and_transition_plays_its_sound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ready(monkeypatch, tmp_path)
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=3), Cut(start=5, end=8, enter="slide")),
        components=(
            ComponentUse(name="hook_title", zone="TOP_TITLE", start=0, length=2,
                         props={"text": "Salom"}),
            ComponentUse(name="lower_third", zone="LOWER_THIRD", start=3.2,
                         length=2.5),
        ),
        sound_urls={"whoosh": "https://s/whoosh.mp3", "swoosh": "https://s/sw.mp3"},
        motion="moving",
    )  # fmt: skip

    tracks = sound_tracks(spec, cut_starts=[0.0, 3.0])

    clips = [c for track in tracks for c in track["clips"]]
    assert sorted((c["start"], c["asset"]["src"]) for c in clips) == [
        (0.0, "https://s/whoosh.mp3"),
        (3.0, "https://s/whoosh.mp3"),
        (3.2, "https://s/sw.mp3"),
    ]
    assert all(c["asset"]["volume"] < 1 for c in clips)
    # The two near 3 s overlap, so they sit on separate tracks.
    assert len(tracks) == 2


def test_a_sound_with_no_address_is_left_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ready(monkeypatch, tmp_path)
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=3),),
        components=(
            ComponentUse(name="lower_third", zone="LOWER_THIRD", start=0, length=2.5),
        ),
        motion="moving",
    )

    assert sound_tracks(spec, cut_starts=[0.0]) == []


def test_a_punch_is_a_new_clip_that_starts_closer() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=10, end=16),),
        punches=(2.0,),
        motion="moving",
    )

    clips = _footage(build_edit(spec))

    assert [(c["start"], c["asset"]["trim"]) for c in clips] == [(0, 10), (2, 12)]
    before, after = clips[0]["scale"][-1]["to"], clips[1]["scale"][0]["from"]
    assert after == pytest.approx(before * PUNCH, abs=1e-3)
    # One continuous tween per clip: nothing for the renderer to drift across.
    assert all(len(c["scale"]) == 1 for c in clips)


# --- Held on the face ----------------------------------------------------------


def test_the_offset_keeps_the_face_where_it_was_as_the_picture_grows() -> None:
    scale = [{"from": 1.0, "to": 1.3, "start": 0, "length": 4.0,
              "interpolation": "linear"}]  # fmt: skip

    held = held_offset(scale, (0.4586, 0.5651))

    # Measured on stage: a face at x 0.4586 stays there when the clip is
    # scaled about its middle and moved by -(s - 1)(x - 0.5).
    assert held["x"][0]["to"] == round(0.3 * (0.5 - 0.4586), 4)
    assert held["y"][0]["to"] == round(0.3 * (0.5651 - 0.5), 4)
    assert held["x"][0]["from"] == 0 and held["y"][0]["length"] == 4.0
    face_x = 0.5 + 1.3 * (0.4586 - 0.5) + held["x"][0]["to"]
    assert face_x == pytest.approx(0.4586, abs=1e-4)


def test_a_moving_cut_with_a_face_seen_is_held_on_it_split_or_not() -> None:
    face = FaceMark(at=1.0, box=(300, 800, 700, 1300), guard=(380, 950, 620, 1250))
    spec = EditSpec(
        source_url="https://example.test/s.mp4",
        cuts=(Cut(start=0, end=6),),
        motion="moving",
        faces=(face,),
        layouts=(LayoutSpan(start=3, end=6, layout="split_top"),),
    )

    first, second = build_edit(spec)["timeline"]["tracks"][-1]["clips"]

    assert face_anchor(spec.faces, 0, 6) == (0.463, 0.5729)
    # Left of the middle: the picture moves right as it grows.
    assert first["offset"]["x"][-1]["to"] > 0
    # The split moves the held footage down on top of the hold.
    held = held_offset(second["scale"], (0.463, 0.5729))
    assert second["offset"]["y"][0]["from"] == round(held["y"][0]["from"] - 0.1, 4)


def test_a_burst_flashes_and_lands_from_closer_with_a_whoosh() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=3), Cut(start=4, end=8, enter="burst")),
        motion="moving",
        sound_urls={"whoosh": "https://example.test/whoosh.mp3"},
    )

    edit = build_edit(spec)
    footage = _footage(edit)
    flashes = [
        c for t in edit["timeline"]["tracks"] for c in t["clips"]
        if c["asset"].get("html") == "<div id=f></div>"
    ]  # fmt: skip
    sounds = [
        c["start"] for t in edit["timeline"]["tracks"] for c in t["clips"]
        if c["asset"].get("src", "").endswith("whoosh.mp3")
    ]  # fmt: skip

    assert [f["start"] for f in flashes] == [2.9]
    assert footage[1]["scale"][0]["from"] > footage[1]["scale"][0]["to"]
    assert sounds == [3.0]


def test_a_beat_plays_its_own_sound_and_the_opening_rises_in() -> None:
    urls = {
        n: f"https://example.test/{n}.mp3" for n in ("pop", "thud", "sparkle", "riser")
    }
    hook = ComponentUse(
        name="hook_counter", zone="TOP_TITLE", start=0.0, length=4.0,
        props={"value": "50%", "pill": "CHEGIRMA"}, beats={"slam": 2.2},
    )  # fmt: skip
    spec = EditSpec(
        source_url=SOURCE, cuts=(Cut(start=0, end=6),), motion="moving",
        components=(hook,), sound_urls=urls,
    )  # fmt: skip

    played = sorted(
        (c["start"], c["asset"]["src"].rsplit("/", 1)[1], c["asset"]["volume"])
        for t in sound_tracks(spec, cut_starts=[0.0])
        for c in t["clips"]
    )

    # The pop as it comes in, the riser under it, the sparkle on the count's
    # landing (its manifest's moment, none given) and the thud on the slam.
    assert [(at, name) for at, name, _ in played] == [
        (0.0, "pop.mp3"),
        (0.0, "riser.mp3"),
        (1.4, "sparkle.mp3"),
        (2.2, "thud.mp3"),
    ]
    assert dict((n, v) for _, n, v in played)["riser.mp3"] < 0.6
