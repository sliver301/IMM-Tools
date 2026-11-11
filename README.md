# IMM-Tools

A pyRevit extension (**IMM** tab) with small tools that speed up everyday Revit work.

## Tools

| Panel | Tools |
|---|---|
| CAD | DWG Layer Visibility, Draw Layer (Selected / All), DWG Isolate (Isolate Layer / Reset), DWG Style (Style / Reset) |
| Modeling | Bubble Control (grid and level bubbles) |
| Modify | Find & Replace |
| Section Box | Toggle, Create, Settings, Grow, Shrink |
| View | VV Apply, VV Temp, VV Settings (2D / 3D templates), VV Annotations, VV Categories |

Every button has a hover tooltip describing what it does.

## Install

With the pyRevit CLI:

```
pyrevit extend ui IMM https://github.com/sliver301/IMM-Tools.git
```

Or manually: clone this repo into a folder named `IMM.extension`, add the parent folder under
pyRevit Settings > Custom Extension Directories, then reload pyRevit.

## Requirements

Revit with [pyRevit](https://github.com/pyrevitlabs/pyRevit) 4.8 or newer.

## Notes

The tools keep their settings in pyRevit's config and in the extension's `data` folder.

## License

MIT, see [LICENSE](LICENSE).
