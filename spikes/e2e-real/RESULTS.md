# End-to-end on real talks

Date: 2026-10-10. Machine: M1 Pro 32GB. Three single-speaker English talks from 38C3, published
on media.ccc.de under CC BY 4.0: "Building Your First LoRa Mesh Network From Scratch" (WillCrash),
"ACE up the sleeve: Hacking into Apple's new USB-C Controller" (stacksmashing) and "Going Long!
Sending weird signals over long haul optical networks" (Ben Cartwright-Cox), recorded by the C3VOC.
The recordings are not in this repository and were not modified; only measurements are reported.
For each: transcribe, accept every filler and >1 s pause suggestion, Clean audio on, export MP4,
then transcribe the export again and compare with the kept words.

Filler counts below are what a recognizer transcribed. They measure the recognizers, not the
speakers.

| | LoRa Mesh | ACE up the sleeve | Going Long |
|---|---|---|---|
| length (min) | 32.9 | 40.2 | 36.2 |
| video | 720x576@25.00 | 1920x1080@25.00 | 1920x1080@25.00 |
| words | 4103 | 6524 | 6538 |
| fillers found | 9 | 0 | 68 |
| pauses > 1 s | 95 | 94 | 68 |
| time cut (s) | 300.1 | 189.2 | 190.0 |
| fillers heard in export | 0 | 0 | 0 |
| kept words differing in re-transcript (%) | 1.7 | 0.8 | 3.5 |
| export length error (s) | -0.17 | -0.03 | -0.03 |
| loudness (LUFS) | -14.2 | -14.3 | -14.6 |
| transcribe (s) | 41.6 | 55.0 | 62.8 |
| preview proxy (s) | 82.0 | 167.1 | 156.0 |
| enhance voice (s) | 127.0 | 155.2 | 140.7 |
| export (s) | 71.8 | 286.5 | 256.4 |

## Reading it

- **Cuts do not clip words.** Of the kept words that read differently in the re-transcript
  (70 / 4,094 and 225 / 6,470), only 4 and 13 sit within 0.35 s of a cut, and those are spelling
  variants ("qsfp 28" vs "qsfp28", "diagr" vs "diagram"). The rest is the recognizer hearing
  jargon differently on a second pass. See `lost.py`.
- **Parakeet's filler counts are too low.** It transcribed 0 to 68 fillers per talk; whisper
  finds many more, and the follow-up below shows Parakeet drops them on long recordings.
- **Dead air is the bigger win on talks**: 3 to 5 minutes per 30 to 40 minutes.
- Exports land within 0.2 s of the planned length; loudness within 0.6 LU of -14.
- Slow parts on 1080p: preview proxy (2.5 to 3 min, now built in the background) and export
  (about 8 minutes of 1080p video per minute of processing).


## Follow-up (2026-10-10): whisper.cpp is the default engine now

Parakeet drops fillers once a recording is longer than a few seconds: on the 48 s synthetic demo it
kept 8 of 11 scripted fillers when each line was transcribed alone and 0 when they were joined.
The same three talks with whisper.cpp large-v3-turbo through pywhispercpp, the filler prompt
carried into every window, DTW token timestamps:

| | LoRa mesh | ACE | long-haul optical |
|---|---|---|---|
| fillers found: Parakeet / whisper | 9 / 37 | 0 / 43 | 68 / 442 |
| time cut (s): Parakeet / whisper | 300.1 / 351.4 | 189.2 / 265.9 | 190.0 / 372.9 |
| fillers heard in export (whisper hears its own export) | 2 | 7 | 3 |
| kept words differing in re-transcript (%): Parakeet / whisper | 1.7 / 2.1 | 0.8 / 1.8 | 3.5 / 3.7 |
| of those, within 0.35 s of a cut edge | 15 (157 cuts) | 31 (169 cuts) | 91 (486 cuts) |
| transcribe (s) | 112.4 | 147.4 | 139.7 |

- **whisper.cpp DTW times run late.** Matched word by word against Parakeet, whisper's starts and
  ends lag by a median 0.14 s (p25 to p75: 0.08 to 0.24 s), the same on all four recordings. Before
  correcting it, the optical talk lost 6.7% of kept words, 332 of them at cut edges ("different",
  "cable", "signal"), and 145 fillers survived the export. Shifting every DTW time by 0.14 s
  (`DTW_LAG`) brought that to 3.7%, 91 and 3.
- **Cuts do not clip words after the correction.** About a third of kept words sit within 0.35 s of
  some cut edge on the optical talk, and about a third of the differing words do (91 of 244): what
  chance alone gives. The rest is the recognizer hearing jargon differently on a second pass.
- whisper's filler count depends on how the audio is fed: 28 s windows through whisper-cli found
  50 / 64 / 402, one pass with the prompt carried found 37 / 43 / 442. Not tuned further.
- Transcription takes 2 to 2.5 minutes per 35 to 40 minute talk on an M-series Mac, against about
  1 minute for Parakeet.


## Follow-up (2026-10-10): chunked decoding without timestamp tokens

The recognizer now always gets a named language, never predicts timestamp tokens, and decodes the
audio in chunks of 20 to 28 s that end in the middle of the longest quiet stretch. Each chunk is
prompted with the filler prompt plus the last 60 words of the previous chunk. Word times still come
from DTW only. Pauses are tightened directly instead of suggested. Same three talks, same method:

| | LoRa mesh | ACE | long-haul optical |
|---|---|---|---|
| fillers found: one pass / chunks without context / chunks with context | 37 / 47 / 43 | 43 / 52 / 61 | 442 / 373 / 460 |
| fillers heard in export: one pass / chunks with context | 2 / 5 | 7 / 9 | 3 / 9 |
| kept words differing in re-transcript (%): one pass / chunks with context | 2.1 / 1.4 | 1.8 / 1.6 | 3.7 / 2.3 |
| of those, within 0.35 s of a cut edge | 13 (165 cuts) | 26 (181 cuts) | 62 (502 cuts) |
| time removed (s) | 352.4 | 275.6 | 390.5 |
| export length error (s) | -0.36 | -0.16 | -0.37 |
| loudness (LUFS) | -14.2 | -14.3 | -14.4 |
| transcribe (s) | 140.2 | 160.9 | 172.0 |

- **Without the previous chunk's text, whisper writes fewer fillers** (373 against 442 on the
  optical talk) and more of them survive the export (92). Carrying the last 60 words back in
  restores the habit: 460 found, 9 left.
- Word times match the one-pass run: matched words start and end within 0.01 s (interquartile), so
  `DTW_LAG` stays at 0.14 s.
- Kept-word differences went down on all three talks; slightly more fillers are heard in the export
  (23 against 12 of 564 and 522 suggested).
- Exports with a few hundred kept ranges failed on ffmpeg 9 ("Cannot allocate memory" while
  parsing the select expression, which nested one level per range). The expression is now a
  balanced sum; covered by a test.


## Follow-up (2026-10-10): English-only small.en

The default model is now Whisper small.en (English only, about 470 MB), still chunked, prompted
and DTW-timed as above. Fillers are trimmed directly and pauses tightened. The export is heard back
by large-v3-turbo (`run.py --judge large-v3-turbo`), so every run is judged by the same ear.

small.en puts an "um" into the last few hundredths of a second before the next word and stretches
the word before it over the sound: the matched filler starts sit a median 0.1 s later than
large-v3-turbo's, many fillers last 0.02 to 0.12 s, and a cut leaves most of the sound in. A
filler shorter than 0.55 s now starts 0.55 s before its end, taking the time from the word before
(which keeps at least 0.1 s). Measured on WAV exports without Clean audio, heard by turbo:

| fillers heard after export | LoRa mesh | ACE | long-haul optical |
|---|---|---|---|
| large-v3-turbo transcript | 2 | 6 | 10 |
| small.en, as transcribed | 24 | 18 | 182 |
| small.en, fillers widened to 0.45 / 0.55 / 0.7 s | 12 / 11 / 8 | 5 / 3 / 1 | 32 / 37 / 24 |

Kept-word differences stayed within 0.2 points of the unwidened run at 0.45 and 0.55 s and rose by
up to 0.4 points at 0.7 s. medium.en was also tried: on the optical talk it wrote 65 fillers where
the others wrote about 460, and took longer than turbo.

Full runs with 0.55 s (MP4, Clean audio on, heard by turbo):

| | LoRa mesh | ACE | long-haul optical |
|---|---|---|---|
| fillers found / heard in export | 48 / 9 | 75 / 11 | 459 / 31 |
| time removed (s) | 313.0 | 203.2 | 387.7 |
| kept words differing (%) | 3.5 | 3.0 | 4.5 |
| of those, within 0.35 s of a cut edge | 20 (148 cuts) | 45 (172 cuts) | 133 (493 cuts) |
| export length error (s) | -0.20 | -0.16 | -0.10 |
| loudness (LUFS) | -14.1 | -14.3 | -14.3 |
| transcribe (s) | 70.2 | 107.8 | 102.0 |

Kept-word differences are higher than in the runs above partly because two different models now
transcribe and re-transcribe.
