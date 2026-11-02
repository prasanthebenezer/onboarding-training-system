# Video pipeline: SOP → script → Motion → voiceover → MP4

Limit: **under 3 minutes per video**. Keep narration at or below about 330 English words. Arabic and Malayalam usually run longer when spoken.

1. **Script (Claude):** Claude drafts `content/modules/<slug>/script.en.md` (scenes = ON SCREEN + NARRATION) and the quiz questions from the SOP/manual. The quiz is entered in Admin → Courses & lessons.
   The SME reviews and approves. Anything not in the source document is not added.
2. **Translate (Claude + human review):** `script.ar.md`, `script.hi.md`, `script.ml.md`, and the Arabic/Hindi/Malayalam quiz text (the *Translations* section of each question in the lesson editor).
   A fluent colleague must check technical and safety wording before release.
3. **Voiceover (Voice Studio, by admin):** voice tools read time cues aloud and can't place speech at a time, so record **one clip per scene**:
   ```bash
   python3 scripts/voiceover.py export content/modules/<slug> --lang en
   ```
   This writes `content/modules/<slug>/voiceover/en/scene01.txt ...` (narration only, no cues) and prints each scene's time slot.
   Paste each file into Voice Studio separately and save the clips as `scene01.mp3`, `scene02.mp3`, ... in one folder.
   **Easier with VoiceStudio (github.com/debpalash/VoiceStudio): one pass, no separate clips.**
   ```bash
   python3 scripts/voiceover.py srt content/modules/<slug> --lang en
   ```
   This writes `content/modules/<slug>/voiceover/en/narration.en.srt`: one subtitle per sentence, timed inside its scene.
   In VoiceStudio open **Dub**, load the silent MP4 exported from Motion, click **Import .srt**, pick a voice,
   set **Timing: Concise** (natural speed, each line starts on its cue), skip Translate, **Generate**, then export MP4.
   Do NOT use Strict slot (stretches speech to fill each cue) or Stretch Video (changes the video length).
4. **Visuals (Claude Motion artifact):** one Motion video per language, built from the ON SCREEN lines, with scene lengths matched to that language's voiceover.
   Arabic on-screen text is laid out right to left. Export MP4 from Motion.
5. **Place the clips on the timeline and add them to the video:**
   ```bash
   python3 scripts/voiceover.py assemble content/modules/<slug> --lang en --clips path/to/clips --video visuals_en.mp4 --out en.mp4
   ```
   Each clip starts exactly at its scene time from `script.<lang>.md`. If a clip is longer than its scene, nothing is written and the script names the clip:
   shorten that text or speed up the voice for that clip. Without `--video` it writes just the audio track (`--out voice_en.m4a`).
6. **Upload:** `/admin/modules` → lesson → language row → Upload.
7. **Changing content later:** Courses & lessons → **Revise** on the lesson publishes the next version. Untick *Copy the current videos* if the video changes, upload the new videos, then re-assign.
   Records of the old version stay valid for that version.

## Status
| Module | Language | Motion film | Length | Voiceover | Uploaded |
|---|---|---|---|---|---|
| pt-01 Raw Material Composition | EN | https://claude.ai/artifact/6cXuwHA1cBXKuzAjCkueRX | 2:30 (scene starts match `script.en.md`) | pending | no |

The Motion films are silent on purpose. The voiceover is the only audio track, added in step 5.
