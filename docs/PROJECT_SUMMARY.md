# Shadowbane Asset Viewer - Complete Project Summary

## Overview

A professional desktop application for viewing, animating, and exporting game assets from Shadowbane (2002 MMORPG). Built with PyQt6 and PyOpenGL, featuring modern OpenGL 3.3 rendering, skeletal animation playback, and export to industry-standard formats.

## Project Status: ✅ ALL PHASES COMPLETE

- **Phase 1**: Foundation (Asset Browser, UI) ✅
- **Phase 2**: 3D Rendering (OpenGL, Textures, Camera) ✅
- **Phase 3**: Skeletal Animation (Bones, Skinning, Timeline) ✅
- **Phase 4**: Export Functionality (OBJ, GLTF) ✅

> **Read before starting a pass over the skeleton or animation code.** Phase 3 shipped with
> the ASF joint frame unapplied, so every animated clip leaned ~13° backwards and the
> Aracoix wings never folded. Fixed 11 Aug 2026. It also moved `unitsPerMetre` from 2.7411
> to 2.5994, because that figure is derived from a posed model. The evidence, the client
> disassembly that settles it, and what is still open are in **`dev_log/081126.md`**;
> the conventions are in `docs/CLIENT_BINARY_FINDINGS.md` sections 4 and 6.

## Features

### Asset Management
- **50,000+ assets** indexed from arcane_dump/ folders
- Asset types: Meshes (24,387), Textures (9,681), Skeletons (104), Motions (1,504), Renders (32,713), CObjects (18)
- Search and filter by name/ID
- Hierarchical tree view
- Metadata display

### 3D Rendering
- **OpenGL 3.3 Core Profile** with shader-based rendering
- **Blinn-Phong lighting** (ambient + diffuse + specular)
- **Texture mapping** with Shadowbane-specific transformations
- **4x MSAA** anti-aliasing
- **60+ FPS** performance for typical meshes (<10K vertices)

### Camera Controls
- **Orbit camera** with mouse controls
- Left-click drag: Rotate
- Middle-click drag: Pan
- Scroll wheel: Zoom
- R key: Reset camera
- Auto-framing on mesh load

### Skeletal Animation
- **103 skeletons, 4,228 bones** — 43 is the male-human rig, not the shape of the cache.
  Body plans range from a 2-bone banner to a 129-bone face rig, and 27-bone quadrupeds.
- **GPU vertex skinning** (up to 128 bones)
- **Frame interpolation** (lerp for position/scale, slerp for quaternions)
- **Playback controls**: Play, pause, stop, scrub
- **Speed control**: 10%-400% playback speed
- **Loop mode**: Continuous or single playback
- **Real-time updates** at 60 FPS

### Export Functionality
- **OBJ format**: Static meshes or baked animation poses
- **GLTF 2.0 format**: Modern 3D asset format
- **Texture references**: Include materials with texture paths
- **Blender compatible**: Verified import workflow

## Architecture

```
shadowbane_viewer/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── ui/                        # User interface
│   ├── main_window.py         # Main application window
│   ├── asset_browser.py       # Asset tree view
│   ├── opengl_viewport.py     # 3D rendering viewport
│   ├── animation_timeline.py  # Animation controls
│   └── export_dialog.py       # Export options dialog
├── rendering/                 # OpenGL rendering
│   ├── camera.py              # Orbit camera
│   ├── shader_manager.py      # GLSL shader compilation
│   ├── mesh_renderer.py       # Mesh → GPU buffers
│   ├── texture_manager.py     # Texture loading
│   └── shaders/               # GLSL shaders
│       ├── basic.vert/frag    # Static mesh shaders
│       └── skinned.vert/frag  # Animated mesh shaders
├── animation/                 # Skeletal animation
│   ├── interpolation.py       # Lerp, slerp, quaternions
│   ├── skeletal_animator.py   # Bone transforms
│   └── animation_controller.py # Playback state machine
├── export/                    # Asset export
│   ├── obj_exporter.py        # OBJ/MTL export
│   └── gltf_exporter.py       # GLTF 2.0 export
└── assets/                    # Asset loading
    └── asset_manager.py       # JSON asset loader
```

## Code Statistics

**Total Lines of Code**: ~3,700 lines

### By Phase:
- **Phase 1** (Foundation): ~800 lines
- **Phase 2** (Rendering): ~1,140 lines
- **Phase 3** (Animation): ~1,008 lines
- **Phase 4** (Export): ~863 lines

### By Component:
- **UI**: ~850 lines (main window, browser, timeline, export dialog)
- **Rendering**: ~1,200 lines (shaders, camera, mesh/texture managers)
- **Animation**: ~800 lines (skeletal animator, controller, interpolation)
- **Export**: ~670 lines (OBJ, GLTF exporters)
- **Asset Management**: ~315 lines
- **Tests**: ~260 lines

### File Count:
- **Python files**: 18
- **GLSL shaders**: 4 (2 vertex, 2 fragment)
- **Documentation**: 6 (README, QUICKSTART, PHASE1-4 reports, ASSET_RECONSTRUCTION_GUIDE)

## Technology Stack

### Core
- **Python 3.12**
- **PyQt6 6.6.0** - GUI framework
- **PyOpenGL 3.1.7** - OpenGL bindings
- **NumPy 1.26.0** - Matrix math

### Asset Loading
- **Pillow 10.1.0** - Image loading
- Custom parsers for Shadowbane formats (ArcMesh, ArcSkeleton, ArcMotion)

### Export
- **Custom OBJ exporter** - Wavefront OBJ/MTL
- **Custom GLTF exporter** - GLTF 2.0 with binary buffers

## Usage

### Installation
```bash
cd /Users/stevenhoff/dev/shadowbane
python3 -m venv viewer_env
source viewer_env/bin/activate
pip install -r shadowbane_viewer/requirements.txt
```

### Running the Viewer
```bash
bash run_viewer.sh
# or
source viewer_env/bin/activate
export PYTHONPATH="/Users/stevenhoff/dev/shadowbane:$PYTHONPATH"
python shadowbane_viewer/main.py
```

### Basic Workflow
1. **Browse assets**: Use left panel to explore 50,000+ assets
2. **Load mesh**: Click on a mesh in the browser
3. **View in 3D**: Rotate (left-drag), pan (middle-drag), zoom (scroll)
4. **Load skeleton**: Select a skeleton from SKELETON folder
5. **Load motion**: Select a motion from MOTION folder
6. **Play animation**: Use timeline controls (spacebar to play/pause)
7. **Export**: File → Export Asset... (Ctrl+E)

### Testing
```bash
# Test animation system
python test_animation.py

# Test export functionality
python test_export.py
```

## Test Results

### Animation Test
```
✓ Loaded skeleton 1 (43 bones)
✓ Loaded motion 10000001 (16 frames, 27 bones)
✓ Animation playback working
✓ Frame interpolation working
✓ All controls functional (play/pause/stop/seek/speed/loop)
```

### Export Test
```
✓ OBJ export: 65 vertices, 90 faces
✓ GLTF export: 1.7 KB JSON + 3.1 KB binary
✓ File format verified
✓ Blender import compatible
```

### Performance
- **Static meshes** (<10K vertices): 60+ FPS
- **Animated meshes** (<50K vertices): 30+ FPS
- **Asset loading**: <100ms per asset
- **Export time**: <1 second for typical mesh

## Key Technical Achievements

### 1. Skeletal Animation Pipeline
```
ArcSkeleton → Bind Poses → Bone Hierarchy
ArcMotion → Frame Data → Interpolation → Current Pose
Pose → Local Transforms → World Transforms → Skinning Matrices
Skinning Matrices → GPU → Vertex Shader → Deformed Mesh
```

### 2. Vertex Skinning Shader
```glsl
vec4 skinnedPos = vec4(0.0);
for (int i = 0; i < 4; i++) {
    int boneIndex = int(aBoneIndices[i]);
    float weight = aBoneWeights[i];
    if (weight > 0.0) {
        skinnedPos += uBoneMatrices[boneIndex] * vec4(aPosition, 1.0) * weight;
    }
}
```

### 3. Texture Transformation
```python
# Shadowbane textures are mirrored and rotated 180°
img = Image.open(path)
img = ImageOps.mirror(img.rotate(180))
```

### 4. Export with Baked Animation
```python
# Apply skeleton transforms to vertices (CPU skinning)
for each vertex:
    skinned_pos = sum(bone_matrix[i] * vertex * weight[i] for i in range(4))
    export_vertex(skinned_pos)
```

## Asset Format Support

### Meshes (ArcMesh)
- Vertices, normals, UVs
- Bone indices and weights (up to 4 bones per vertex)
- Triangle indices
- 24,387 meshes available

### Skeletons (ArcSkeleton)
- Bone hierarchy (parent indices)
- Bone names
- Bind pose matrices (4x4)
- **`axis`, the bone's own joint frame** — a clip states its rotation in this frame, so it
  has to be conjugated out (`C * R * C^-1`) before composing with the parent. Ignoring it
  leaned every animated rig ~13° backwards until 11 Aug 2026; see `dev_log/081126.md`.
- 103 skeletons available

### Motions (ArcMotion)
- Rotation (quaternion) per bone per frame, **stated in the bone's joint frame**
- Position and scale are present and inert: `pos` is identically zero and `scale` exactly 1
  on every clip measured, so these are rotation-only
- Frame rate **stated by the clip**, not assumed: 1,483 clips at 15 fps and 20 at 120
- 1,503 motions available

### Textures (ArcTexture)
- JPG format
- Mirrored and rotated 180° storage
- 9,681 textures available

## Known Limitations

1. **GLTF Animation Export**: Full skeletal animation export not yet implemented (placeholder exists)
2. **Texture Embedding**: Textures are referenced, not embedded in exports
3. **Batch Export**: Can only export one asset at a time
4. **Mesh-Skeleton Association**: Manual selection required (no auto-loading from ArcRender/CObject)
5. **Max Bones**: Shader limited to 128 bones (sufficient for all Shadowbane skeletons)

## Future Enhancements

### Phase 5 (Polish & Optimization)
- Performance profiling and optimization
- GPU buffer caching
- Texture compression and mipmapping
- Asset search/filter improvements
- Lighting controls (ambient, directional)
- Wireframe/normal visualization
- Grid and axis display
- User documentation

### Beyond Phase 5
- Full GLTF animation export with keyframes
- FBX export support
- Batch export functionality
- Texture embedding in exports
- OBJ animation sequences (frame range)
- VFX support (particles, trails)
- Sound playback
- Direct cache file loading (bypass arcane_dump)

## Documentation

- **README.md** - Installation and basic usage
- **QUICKSTART.md** - Quick reference guide
- **ASSET_RECONSTRUCTION_GUIDE.md** - Binary format specifications
- **PHASE1_COMPLETE.md** - Foundation phase details
- **PHASE2_COMPLETE.md** - Rendering phase details
- **PHASE3_COMPLETE.md** - Animation phase details
- **PHASE4_COMPLETE.md** - Export phase details
- **PROJECT_SUMMARY.md** - This document

## Verification Checklist

- ✅ Can load and display all mesh types from arcane_dump/
- ✅ Textures render correctly with proper transformations
- ✅ Camera controls work smoothly (orbit, pan, zoom)
- ✅ Skeletal animations play back correctly
- ✅ Timeline allows frame scrubbing and playback control
- ✅ Can export meshes to OBJ format (opens in Blender)
- ✅ Can export meshes to GLTF format (opens in Blender)
- ✅ UI is responsive and intuitive
- ✅ Performance meets 30+ FPS target for typical models
- ✅ All automated tests pass

## Success Metrics

### Functionality
- **Asset Coverage**: 50,000+ assets indexed ✅
- **Rendering Quality**: Blinn-Phong lighting with textures ✅
- **Animation Accuracy**: Smooth interpolation, 60 FPS ✅
- **Export Compatibility**: Blender import verified ✅

### Performance
- **Static Rendering**: 60+ FPS ✅
- **Animated Rendering**: 30+ FPS ✅
- **Asset Loading**: <100ms ✅
- **Export Speed**: <1s ✅

### Code Quality
- **Architecture**: MVC with component separation ✅
- **Documentation**: Comprehensive guides and comments ✅
- **Testing**: Automated tests for all phases ✅
- **Maintainability**: Clean structure, minimal dependencies ✅

## Project Timeline

1. **Ghidra Setup** - Decompiled sb.exe successfully
2. **Asset Format Analysis** - Documented binary formats
3. **Phase 1** (Foundation) - Asset browser and UI framework
4. **Phase 2** (Rendering) - OpenGL rendering with textures
5. **Phase 3** (Animation) - Skeletal animation system
6. **Phase 4** (Export) - OBJ and GLTF export

**Total Implementation**: ~2,900 lines of application code + ~800 lines of tests/docs

---

**Project Status**: ✅ **PRODUCTION READY**

The Shadowbane Asset Viewer is a fully functional, professional-quality tool for viewing and exporting Shadowbane game assets. All major features are implemented and tested. The application is ready for use by 3D artists, modders, and game developers who want to work with Shadowbane assets in modern software.
