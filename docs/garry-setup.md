# Garry Setup — Spatial Brain (3D, Game Engine, Image-to-3D)

Garry is Larry's spatial agent. Controls Unity Editor via CLI + MCP (150+ tools), converts images to 3D meshes (GLB) via Trellis 2, and handles Blender workflows via MCP.

---

## Quick Start

### Unity (Game Engine)

```bash
# Install Unity CLI (comes with Unity Hub)
unity --version

# Install Pipeline package in Unity project
unity pipeline install --project-path "/path/to/project"

# Configure MCP for Claude Code
unity mcp configure claude-code --project-path "/path/to/project"

# Verify Pipeline is running (Unity Editor must be open)
unity pipeline list

# Check editor status via MCP
# → 150+ tools available: scene hierarchy, components, build, test, scripting
```

### Image-to-3D

```bash
# Convert image to 3D mesh
python agents/garry_service.py generate "path/to/image.png"

# With custom output directory
python agents/garry_service.py generate "image.png" --output "path/to/output/"

# Check status
python agents/garry_service.py status
```

---

## Architecture

### Unity Pipeline

```
User → Larry → Garry (Claude Code with unity-editor-mcp)
  → Unity CLI manages editor lifecycle
  → Pipeline package (com.unity.pipeline) runs TCP server on port 7800
  → MCP exposes 150+ tools: scene, hierarchy, components, build, test, scripting
  → Claude Code controls Unity Editor programmatically
```

### Image-to-3D Pipeline

```
User → Larry → garry_service.py (CLI)
  → rembg removes background (local, GPU-accelerated)
  → Trellis 2 generates 3D mesh (HuggingFace/fal.ai API)
  → GLB output saved to {{GARRY_PATH}}/
  → Optional: Blender import via Blender MCP
  → Bus event: garry-mesh-generated
  → Metadata logged (source image, params, output path)
```

---

## File Structure

```
{{GARRY_PATH}}/
├── meshes/                 ← Generated 3D meshes (GLB/FBX)
│   ├── characters/         ← Character meshes
│   ├── environments/       ← Scene/environment meshes
│   ├── props/              ← Object meshes
│   └── raw/                ← Unsorted output
├── textures/               ← Extracted/generated textures
├── blender/                ← Blender project files (.blend)
└── source/                 ← Source images used for generation
```

---

## Prerequisites

| Component | Required? | Notes |
|-----------|-----------|-------|
| **Unity 6+ (Hub)** | For game dev | Unity CLI (`unity` v1.0.0-beta.6+) ships with Hub |
| **com.unity.pipeline** | For Unity MCP | `unity pipeline install` adds it to project |
| **Python 3.10+** | Yes | Runtime |
| **rembg** | For image-to-3D | Background removal (`pip install rembg[gpu]` for CUDA) |
| **Trellis 2** | For image-to-3D | Image-to-3D model (via HuggingFace or fal.ai API) |
| **Blender 4.0+** | Optional | For import, rigging, and scene assembly |
| **NVIDIA GPU (CUDA)** | Recommended | Accelerates rembg and local Trellis inference |
| **fal.ai API key** | Optional | For cloud-based Trellis inference (alternative to local) |

### Install rembg

```bash
# GPU-accelerated (recommended)
pip install rembg[gpu]

# CPU-only fallback
pip install rembg
```

### Trellis 2 Setup

Trellis 2 can run locally (requires significant VRAM) or via fal.ai API:

```bash
# Option 1: fal.ai (cloud, easier setup)
pip install fal-client
# Set FAL_KEY in environment or config

# Option 2: Local (requires ~8GB VRAM)
# Follow Trellis 2 repo instructions: https://github.com/microsoft/TRELLIS
```

### Unity CLI + MCP

Unity CLI ships with Unity Hub. The MCP bridge requires the Pipeline package inside the Unity project:

```bash
# 1. Verify Unity CLI
unity --version

# 2. Install Pipeline package
unity pipeline install --project-path "/path/to/unity-project"

# 3. Configure Claude Code MCP
unity mcp configure claude-code --project-path "/path/to/unity-project" --yes
# This writes unity-editor-mcp to ~/.claude.json

# 4. Open Unity Editor (Pipeline server starts automatically on port 7800)
unity editor open --project-path "/path/to/unity-project"

# 5. Verify MCP tools (should show 150+ tools)
unity pipeline list
```

**Key MCP tool categories:**
- Scene: `get_scene_hierarchy`, `open_scene`, `create_gameobject`, `set_transform`
- Components: `add_component`, `set_component_properties`, `get_serialized_fields`
- Build: `build`, `build_status`, `switch_build_target`
- Test: `run_tests`, `test_status`, `list_tests`
- Scripting: `create_script`, `eval`, `eval_file`, `recompile`
- Assets: `find_assets`, `create_asset`, `import_asset`
- Console: `console`, `get_console_logs`, `clear_console`
- Capture: `capture_scene_view`, `capture_game_view`, `screenshot`

### Blender MCP (Optional)

For programmatic Blender import, install the Blender MCP server:

```bash
pip install blender-mcp
# Configure in .mcp.json
```

---

## Pipeline

### 1. Background Removal

Every input image passes through rembg first. This isolates the subject for cleaner 3D reconstruction.

```
Input image → rembg → Clean subject (transparent background) → Trellis 2
```

### 2. Mesh Generation

Trellis 2 converts the cleaned image to a 3D mesh in GLB format.

### 3. Post-Processing

- GLB saved to `{{GARRY_PATH}}/meshes/<category>/`
- Source image copied to `{{GARRY_PATH}}/source/`
- Metadata logged: source path, generation params, output path, timestamp
- Bus event emitted: `garry-mesh-generated`

### 4. Blender Import (Optional)

When a mesh needs rigging, texturing, or scene assembly, Garry imports it into Blender via MCP.

---

## Barry → Garry Pipeline

Barry-generated images can flow directly into Garry for 3D conversion:

```
Barry generates image → Image saved to {{ASSETS_PATH}}/
  → Larry invokes Garry with image path
  → Garry produces GLB mesh
  → Mesh available for Blender scene assembly
```

---

## Bus Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `garry-mesh-request` | In | `{image_path, category, params}` |
| `garry-mesh-generated` | Out | `{mesh_path, source_image, format, vertices}` |
| `garry-error` | Out | `{error, image_path}` |

---

## Configuration

`agents/garry-config.json`:

```json
{
  "garry_root": "{{GARRY_PATH}}",
  "trellis_backend": "fal",
  "rembg_model": "u2net",
  "default_format": "glb",
  "blender_mcp": false,
  "log_file": "agents/logs/garry.log"
}
```

---

## Placeholders

| Placeholder | Replace with |
|-------------|--------------|
| `{{GARRY_PATH}}` | Path to your 3D assets directory (e.g., `~/3d-assets`) |
| `{{ASSETS_PATH}}` | Path to your Barry image assets (for pipeline integration) |
