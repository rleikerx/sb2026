# Shadowbane Asset Viewer

A professional asset viewer for Shadowbane game assets with 3D rendering, skeletal animation playback, and export capabilities.

## Features

### Current (Phase 1 - Complete)
- ✅ Asset browser with searchable tree view
- ✅ Load assets from arcane_dump/ folders
- ✅ Browse meshes, textures, skeletons, motions, renders, and CObjects
- ✅ Dark-themed UI with dockable panels

### Coming Soon
- **Phase 2**: 3D mesh rendering with textures
- **Phase 3**: Skeletal animation playback
- **Phase 4**: Export to OBJ, GLTF, and FBX formats
- **Phase 5**: Performance optimizations and polish

## Installation

### Prerequisites
- Python 3.8 or higher
- An `arcane_dump/` folder holding the client's `*.cache` archives

The viewer reads assets straight out of the cache archives — there is no
extraction step and nothing is written to disk. `arcane_dump/` needs these
seven files, in any folder layout (they are matched by filename):

```
CObjects.cache  CZone.cache  Mesh.cache  Motion.cache
Render.cache    Skeleton.cache  Textures.cache
```

### Setup

1. **Create virtual environment**:
   ```bash
   python -m venv viewer_env
   viewer_env\Scripts\activate      # macOS/Linux: source viewer_env/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Viewer

```bash
viewer_env\Scripts\activate      # macOS/Linux: source viewer_env/bin/activate
python main.py
```

## Usage

### Asset Browser
- **Browse**: Expand categories (Meshes, Textures, etc.) to view assets
- **Select**: Click an asset to select it
- **Search**: Type in the search box to filter assets by ID

### Keyboard Shortcuts
- `Ctrl+O` - Open cache file (coming soon)
- `Ctrl+E` - Export asset (Phase 4)
- `Ctrl+Q` - Quit application

### Menu Options
- **File → Open Cache File**: Load assets directly from .cache files (coming soon)
- **File → Export Asset**: Export selected asset to OBJ/GLTF (Phase 4)
- **View → Asset Browser**: Toggle asset browser panel
- **View → Timeline**: Toggle animation timeline (Phase 3)
- **Help → About**: About dialog

## Development Status

| Phase | Status | Features |
|-------|--------|----------|
| Phase 1 | ✅ Complete | Asset browser, UI framework, asset loading |
| Phase 2 | 🔄 Next | 3D rendering, camera controls, texture display |
| Phase 3 | ⏳ Planned | Skeletal animation, timeline, playback |
| Phase 4 | ⏳ Planned | OBJ/GLTF export |
| Phase 5 | ⏳ Planned | Optimization, polish |

## Architecture

```
shadowbane_viewer/
├── main.py                          # Application entry point
├── ui/                              # Qt UI components
│   ├── main_window.py              # Main window
│   ├── asset_browser.py            # Asset tree view
│   ├── opengl_viewport.py          # 3D viewport (Phase 2)
│   └── animation_timeline.py       # Timeline widget (Phase 3)
├── rendering/                       # OpenGL rendering (Phase 2-3)
├── animation/                       # Animation system (Phase 3)
├── assets/                          # Asset management
│   ├── cache_archive.py            # Random-access *.cache reader
│   ├── asset_manager.py            # Central asset loader
│   └── asset_catalog.py            # COBJECT -> assembled asset graph
└── export/                          # Export functionality (Phase 4)
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'arcane'"
Run `main.py` from the repo root — it puts the repo on `sys.path` itself.

### "arcane_dump missing caches"
The startup dialog names which archives could not be found. Check that every
`*.cache` file listed under Prerequisites is present somewhere beneath
`arcane_dump/`:
```bash
find arcane_dump -name '*.cache'
```
`.cache.ver` files are version stamps, not archives — they don't count.

### PyQt6 installation issues
If PyQt6 fails to install, try:
```bash
pip install --upgrade pip
pip install PyQt6
```

## Testing

To test Phase 1:
1. Launch the application
2. Verify the asset browser shows categories with asset counts
3. Expand "Meshes" category
4. Click on a mesh ID - status bar should show selection
5. Check console output for asset details (vertex count, etc.)
6. Try the search box to filter assets
7. Use View menu to toggle browser visibility

## License

This tool is for educational and preservation purposes related to the Shadowbane MMORPG.

## Credits

- Built with PyQt6 and PyOpenGL
- Uses the arcane/ asset extraction framework
- Shadowbane © 2002 Wolfpack Studios / Ubisoft
