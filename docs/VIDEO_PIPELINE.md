# Video pipeline: SOP → script → Motion → voiceover → MP4

Limit: **under 3 minutes per video**. Keep narration at or below about 330 English words. Arabic and Malayalam usually run longer when spoken.

1. **Script (Claude):** Claude drafts `content/modules/<slug>/script.en.md` (scenes = ON SCREEN + NARRATION) and the quiz in `module.yaml` from the SOP/manual.
   The SME reviews and approves. Anything not in the source document is not added.
2. **Translate (Claude + human review):** `script.ar.md`, `script.hi.md`, `script.ml.md`, and the `ar/hi/ml` keys in `module.yaml`.
   A fluent colleague must check technical and safety wording before release.
3. **Voiceover (Voice Studio, by admin):** record one audio file per language from the NARRATION lines.
   Note where each scene starts in the audio (mm:ss). Motion uses these times.
4. **Visuals (Claude Motion artifact):** one Motion video per language, built from the ON SCREEN lines, with scene lengths matched to that language's voiceover.
   Arabic on-screen text is laid out right to left. Export MP4 from Motion.
5. **Merge audio + video (ffmpeg):**
   ```bash
   ffmpeg -i visuals_ar.mp4 -i voice_ar.mp3 -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k -shortest -movflags +faststart ar.mp4
   ```
   Check the length is under 3 minutes: `ffprobe -v error -show_entries format=duration -of csv=p=0 ar.mp4`
6. **Upload:** `/admin/modules` → module → language row → Upload.
7. **Changing content later:** edit the files, bump `version` in `module.yaml`, then import, upload the new videos and re-assign.
   Records of the old version stay valid for that version.

## Status
| Module | Language | Motion film | Length | Voiceover | Uploaded |
|---|---|---|---|---|---|
| pt-01 Raw Material Composition | EN | https://claude.ai/artifact/6cXuwHA1cBXKuzAjCkueRX | 2:30 (scene starts match `script.en.md`) | pending | no |

The Motion films are silent on purpose. The voiceover is the only audio track, added in step 5.
