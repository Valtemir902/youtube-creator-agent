# Device-first media pipeline

## Goal

The production publishing path must avoid storing full user videos on the Creator Agent VPS. Large media should be processed on the user's device and uploaded directly to YouTube whenever the client platform supports the required local engine.

## Target flow

1. The user selects a video and optional thumbnail on the device.
2. A local media engine reads only the audio track. It must not decode video frames for transcription.
3. Audio is normalized for speech and processed as a stream. Preferred profile: mono, 16 kHz, Opus 12-24 kbps, VAD enabled.
4. Transcription runs locally when the device can sustain it. A cloud fallback may receive only bounded compressed voice chunks, never the original full video.
5. The Creator Agent receives transcript/evidence and performs channel-aware research, SEO, metadata generation, captions and publishing strategy.
6. The user reviews a complete preview and explicitly approves publication.
7. The device uploads the original video directly to a resumable YouTube upload session. The Creator Agent backend never proxies the full media body in the device-first path.
8. Progress is synchronized to the dashboard without reload using an event stream or equivalent state channel.
9. After YouTube returns the video id, the backend applies permitted thumbnail/caption/metadata operations and refreshes dashboard state.

## Local engine strategy

### Android

Primary: MediaExtractor + MediaCodec. Read the compressed audio track, decode audio only, downmix/resample, apply VAD and encode Opus. FFmpeg mobile is a compatibility fallback, not the primary path.

### iOS

Primary: AVFoundation / AVAssetReader with equivalent audio-only processing. FFmpeg mobile is a compatibility fallback.

### Desktop

Native FFmpeg or platform-native media APIs. Never decode the video stream when only audio is needed.

## Resource model

The local engine processes short bounded chunks and releases each chunk after acknowledgement. It must not build a second hour-long audio file unless a platform forces that behavior.

Recommended chunk duration: 5-15 seconds. Recommended speech bitrate: 12-24 kbps. The engine may raise bitrate temporarily for noisy speech or technical vocabulary.

## VPS storage policy

The device-first path stores no video file on the VPS.

The legacy staging path remains only as a bounded compatibility fallback while device clients are rolled out. It must enforce all of the following:

- short session TTL;
- per-tenant concurrent-session limit;
- per-tenant staged-byte quota;
- minimum free-disk reserve checked before session creation;
- minimum free-disk reserve rechecked before every chunk write;
- cleanup after cancel, success and expiration;
- no user-controlled filesystem paths;
- explicit final confirmation before YouTube mutation.

The fallback must fail closed with HTTP 507 before writing data when safe storage headroom is unavailable.

## Direct YouTube upload

The long-term production implementation should use a resumable YouTube upload session initialized by the trusted backend and consumed by the device, subject to browser/mobile platform constraints. The OAuth refresh token stays server-side. A resumable upload URL must be treated as a short-lived bearer capability and must never be logged.

If a browser cannot safely upload directly because of platform or CORS constraints, the product should use the native local engine/app bridge rather than silently proxying multi-gigabyte video through the VPS.

## Security and privacy

- Never expose Google refresh tokens to browser JavaScript or the local helper.
- Never log upload session URLs, OAuth codes, transcripts, access tokens or media contents.
- Bind every job to tenant + authenticated subject + random high-entropy job id.
- Make mutation approvals single-use and short-lived.
- Use idempotency keys for publication state transitions.
- Keep transcript retention minimal and bounded. Delete it after the optimization package is accepted/cancelled unless the user explicitly enables history.
- Validate MIME type, extension, declared size and actual bytes independently.
- Protect all per-user quotas server-side. Client-side limits are display hints only.

## Failure handling

The pipeline must survive app backgrounding, network loss and YouTube resumable-upload retries. State transitions should be explicit: selected, extracting, transcribing, researching, ready_for_review, approved, uploading, processing_on_youtube, published, failed, cancelled.

A retry must continue the same resumable upload/job when possible. It must not create duplicate YouTube videos after an ambiguous network failure.

## Rollout

1. Keep current VPS fallback bounded and safe.
2. Add device capability negotiation and local-engine handshake.
3. Add local audio extraction/transcription.
4. Add AI optimization preview using transcript + channel intelligence.
5. Add direct resumable upload to YouTube.
6. Add captions/thumbnail/post-publication sync.
7. Disable VPS full-video staging by default once device-first coverage is sufficient.
