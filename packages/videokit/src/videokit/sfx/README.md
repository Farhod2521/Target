# Sounds

Short sounds the montage plays under its graphics and transitions. Each one
is described in `sounds.json` (what it is, how long it was asked for) and
lives here as `<name>.mp3`, made once by ElevenLabs Sound Effects and
levelled with FFmpeg so it sits under the speech:

```bash
uv run python manage.py montage_make_sounds            # only the missing ones
uv run python manage.py montage_make_sounds --again pop
```

The command writes each file's measured length back into `sounds.json`.
A component names its sound in its `manifest.json` (`"sfx": "pop"`, as it
comes in) and a sound for each beat that has one (`"sounds": {"slam":
"thud"}`, `"start"` for as it comes in); the name must be one of these.
The soft ones carry their own `volume`: `riser` (under the opening
headline) and `pad` (under the closing card).
