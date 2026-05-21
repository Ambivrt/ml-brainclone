# Farry Setup -- Video Agent

Farry is the video modality agent. It handles video understanding, analysis, and generation using multimodal AI models.

- **Larry** -- thinks, plans, orchestrates
- **Barry** -- sees (images)
- **Harry** -- hears and speaks (audio)
- **Garry** -- shapes (3D)
- **Farry** -- watches and directs (video)

---

## Status: Planned

Farry is designed but not yet active. It is waiting for the Gemini Omni Flash API to become generally available. The architecture and integration points are defined below.

---

## What Farry Will Do

| Domain | Function |
|--------|----------|
| Video understanding | Analyze footage, describe scenes, extract key moments |
| Timeline analysis | Identify important segments, transitions, and narrative structure |
| Clip generation | Generate short video clips from prompts or scene descriptions |
| Multimodal reasoning | Combine video, audio, and text understanding in a single pass |
| Event extraction | Pull structured data from video content (meetings, presentations, events) |

---

## Architecture

Farry runs as an on-demand subprocess, similar to Barry and Harry. Larry invokes it when a task requires video capabilities.

```
User request ("analyze this video")
        |
        v
Larry receives message
        |
        v
Farry invoked (on-demand subprocess)
        |
        v
Gemini Omni Flash processes video
        |
        v
Result returned to Larry -> user
```

---

## Technology

| Component | Role |
|-----------|------|
| **Gemini Omni Flash** | Primary model for video understanding and generation |
| **Bus integration** | Posts results as bus events for other agents to consume |
| **Vault logging** | All video analysis results stored as vault notes |

---

## Integration Points

- **Larry**: Invokes Farry for video tasks, receives structured results
- **Barry**: Can hand off video frames to Barry for image analysis or generation
- **Harry**: Can extract audio tracks for Harry to process (transcription, TTS)
- **Milla**: Video analysis results indexed in semantic memory
- **Brains Bus**: Posts `video_analysis` events for downstream processing

---

## Prerequisites

| Component | Required? | Notes |
|-----------|-----------|-------|
| **Gemini Omni Flash API access** | Yes | Google AI Studio or Vertex AI |
| **FFmpeg** | Yes | Video frame extraction and processing |
| **GPU (CUDA)** | Recommended | Faster local preprocessing |

---

## Installation

When the API becomes available:

1. Configure Gemini Omni Flash API credentials.
2. Copy the Farry script to `03-projects/ml-brainclone/agents/farry.py`.
3. Register Farry in the daemon-manager (on-demand mode, not continuous).
4. Add bus event routing for `video_analysis` kind.

---

## See Also

- [larry-setup.md](larry-setup.md) -- Larry (Claude Code) configuration
- [barry-setup.md](barry-setup.md) -- Barry image agent (similar on-demand pattern)
- [harry-setup.md](harry-setup.md) -- Harry audio agent
- [agent-capabilities.md](agent-capabilities.md) -- Capability matrix for all agents
