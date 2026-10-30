# -*- coding: utf-8 -*-
"""Pure helpers for speech-to-text servers that take audio in short pieces.

No Odoo imports here on purpose: keep this unit-testable in isolation. The
Odoo image has no ffmpeg, so audio is cut without decoding it: MP3 on frame
boundaries, PCM WAV on sample frames.
"""
import bisect
import difflib
import io
import re
import wave

# MPEG audio Layer III tables, indexed by the header fields.
_MP3_BITRATES_KBPS = {
    'mpeg1': (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    'mpeg2': (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
# Version bits -> sample rates; 0b01 is reserved.
_MP3_SAMPLE_RATES = {
    0b11: (44100, 48000, 32000),  # MPEG-1
    0b10: (22050, 24000, 16000),  # MPEG-2
    0b00: (11025, 12000, 8000),   # MPEG-2.5
}

# Words compared at a chunk seam, and the shortest run of them that counts as
# the overlap both chunks transcribed.
STITCH_WINDOW_WORDS = 40
STITCH_MIN_MATCH_WORDS = 3


def sniff_audio_mime(data, fallback='application/octet-stream'):
    """MIME type of the audio in `data`, by its magic bytes.

    File names lie here: recordings are always downloaded to a '.mp3' file,
    but S3 keeps them as WAV.
    """
    head = data[:12]
    if head[:4] == b'RIFF' and head[8:12] == b'WAVE':
        return 'audio/wav'
    if head[:3] == b'ID3' or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return 'audio/mpeg'
    if head[:4] == b'OggS':
        return 'audio/ogg'
    if head[:4] == b'fLaC':
        return 'audio/flac'
    if head[:5] == b'#!AMR':
        return 'audio/amr'
    if head[4:8] == b'ftyp':
        return 'audio/mp4'
    if head[:4] == b'\x1aE\xdf\xa3':
        return 'audio/webm'
    return fallback


def mp3_frames(data):
    """[(offset, length, seconds)] of the MPEG Layer III frames in `data`.

    An ID3v2 tag at the start is skipped, and so is any byte that does not
    start a valid frame header (an ID3v1 tag at the end, garbage).
    """
    pos = 0
    if data[:3] == b'ID3' and len(data) >= 10:
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        pos = 10 + size + (10 if data[5] & 0x10 else 0)
    frames = []
    end = len(data)
    while pos + 4 <= end:
        b1, b2 = data[pos + 1], data[pos + 2]
        version, layer = (b1 >> 3) & 0b11, (b1 >> 1) & 0b11
        bitrate_index, rate_index = b2 >> 4, (b2 >> 2) & 0b11
        if (data[pos] != 0xFF or b1 & 0xE0 != 0xE0 or version == 0b01 or layer != 0b01
                or bitrate_index in (0, 15) or rate_index == 3):
            pos += 1
            continue
        rate = _MP3_SAMPLE_RATES[version][rate_index]
        mpeg1 = version == 0b11
        kbps = _MP3_BITRATES_KBPS['mpeg1' if mpeg1 else 'mpeg2'][bitrate_index]
        length = (144 if mpeg1 else 72) * kbps * 1000 // rate + ((b2 >> 1) & 1)
        frames.append((pos, length, (1152 if mpeg1 else 576) / rate))
        pos += length
    return frames


def _windows(total, chunk_seconds, overlap_seconds):
    """(start, end) seconds of consecutive chunks; each but the first starts
    `overlap_seconds` before the previous one ends. A last piece no longer
    than the overlap is added to the chunk before it rather than sent alone."""
    windows, start = [], 0.0
    while True:
        end = start + chunk_seconds + overlap_seconds
        if end >= total - overlap_seconds:
            windows.append((start, total))
            return windows
        windows.append((start, end))
        start += chunk_seconds


def split_mp3(data, chunk_seconds, overlap_seconds):
    """Cut an MP3 into [(start, end, bytes)] chunks on frame boundaries.

    A chunk holds the frames that start within its window. None when `data`
    has no MP3 frames.
    """
    frames = mp3_frames(data)
    if not frames:
        return None
    starts, t = [], 0.0
    for frame in frames:
        starts.append(t)
        t += frame[2]
    chunks = []
    for start, end in _windows(t, chunk_seconds, overlap_seconds):
        first, last = bisect.bisect_left(starts, start), bisect.bisect_left(starts, end) - 1
        if last < first:
            continue
        chunks.append((start, end, data[frames[first][0]:frames[last][0] + frames[last][1]]))
    return chunks


def split_wav(data, chunk_seconds, overlap_seconds):
    """Cut a PCM WAV into [(start, end, wav bytes)] chunks on sample frames.

    None when the `wave` module cannot read it (compressed WAV such as
    mu-law): the caller sends it whole.
    """
    try:
        with wave.open(io.BytesIO(data)) as source:
            params = source.getparams()
            pcm = source.readframes(params.nframes)
    except (wave.Error, EOFError):
        return None
    if not params.framerate or not params.nframes:
        return None
    frame_size = params.nchannels * params.sampwidth
    total = params.nframes / params.framerate
    chunks = []
    for start, end in _windows(total, chunk_seconds, overlap_seconds):
        first = int(start * params.framerate) * frame_size
        last = int(end * params.framerate) * frame_size
        out = io.BytesIO()
        with wave.open(out, 'wb') as target:
            target.setnchannels(params.nchannels)
            target.setsampwidth(params.sampwidth)
            target.setframerate(params.framerate)
            target.writeframes(pcm[first:last])
        chunks.append((start, end, out.getvalue()))
    return chunks


def split_audio(data, mime, chunk_seconds, overlap_seconds):
    """Chunks of MP3 or PCM WAV audio, or None for any other format."""
    if mime == 'audio/mpeg':
        return split_mp3(data, chunk_seconds, overlap_seconds)
    if mime == 'audio/wav':
        return split_wav(data, chunk_seconds, overlap_seconds)
    return None


def _norm(word):
    return re.sub(r"[^\w]", '', word.lower())


def stitch(texts):
    """Drop from each text the words its predecessor already transcribed.

    Consecutive chunks share a few seconds of audio, so the end of one text
    and the start of the next repeat the same words. The longest run of
    matching words (case and punctuation ignored) between the last
    STITCH_WINDOW_WORDS of one and the first STITCH_WINDOW_WORDS of the next
    is the seam: the earlier text is cut where the run starts, the later one
    keeps the run. Shorter than STITCH_MIN_MATCH_WORDS words → no seam, both
    texts are kept whole. Returns the texts in order, possibly emptied.
    """
    words = [text.split() for text in texts]
    for i in range(1, len(words)):
        before, after = words[i - 1], words[i]
        tail, head = before[-STITCH_WINDOW_WORDS:], after[:STITCH_WINDOW_WORDS]
        matcher = difflib.SequenceMatcher(
            None, [_norm(w) for w in tail], [_norm(w) for w in head], autojunk=False)
        match = matcher.find_longest_match(0, len(tail), 0, len(head))
        if match.size >= STITCH_MIN_MATCH_WORDS:
            words[i - 1] = before[:len(before) - len(tail) + match.a]
            words[i] = after[match.b:]
    return [' '.join(w) for w in words]
