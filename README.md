# CIS Probe Placement Scriptor

Windows GUI tool for generating Ansys Electronics Desktop / HFSS IronPython placement scripts for directional CIS probe layouts.

## Usage

1. Prepare the probe coordinates as CSV or XLSX. Required headers:

   ```csv
   X좌표,Y좌표,Net Name
   ```

   `X` / `PIN_X` / `PIX_X`, `Y` / `PIN_Y` and `NET_NAME` / `NET` are accepted as aliases. An optional `Source_probe name` column names the HFSS group to copy for each row.

2. An Allegro symbol pin report is also accepted. It needs all of these headers:

   ```csv
   REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME
   ```

   `COMP_DEVICE_TYPE` is accepted as an alias for `COMP_DEVICE`.

3. In HFSS, place the source probe objects into groups: `Source_Group` by default, the group named in `Source_probe name` when that column is used, or `Source_<COMP_DEVICE>` for an Allegro report.
4. Run the app, load the file, filter the target coordinates, verify `SIDE` and `SOURCE_GROUP`, then generate the AEDT script.
5. Run the generated script in AEDT/HFSS.

The full Korean guide is built into the app: press `F1` or open `Help > How to Use`. It is shown inside the application (no web browser is needed) and covers the input file formats in detail, HFSS group preparation, the screen layout, side recognition and troubleshooting.

## Build

```powershell
python -m pip install -r requirements.txt
python -m pytest
powershell.exe -ExecutionPolicy Bypass -NoProfile -File .\build_exe.ps1
& 'C:\Program Files\Inno Setup 7\ISCC.exe' .\CISProbePlacementScriptor.iss
```

The installer is written to `installer\CISProbePlacementScriptorSetup-<version>.exe`.

`dist\CISProbePlacementScriptor\CISProbePlacementScriptor.exe --smoke` starts the packaged app without showing a window and exits with code 0 when the Qt plugins and the built-in help are in place.

## Release

The `Build and release` GitHub Actions workflow tests the app, builds the installer on Windows and checks that it installs and starts. It publishes the GitHub release `v<version>` with the installer attached when a commit on `main` carries a new version together with its notes:

1. Set the new version in `cisprobeplace/__init__.py` and `CISProbePlacementScriptor.iss`.
2. Describe the release in `release_notes/v<version>.md`.
3. Merge to `main`.

Pushing a `v<version>` tag, or running the workflow manually on `main` with `publish` enabled, publishes as well.
