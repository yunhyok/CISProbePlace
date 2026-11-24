# CIS Probe Placement Scriptor

Windows GUI tool for generating Ansys Electronics Desktop / HFSS IronPython placement scripts for directional CIS probe layouts.

Keep product coordinate files, board layouts and HFSS models in private storage. The examples in this repository use synthetic pins.

## Usage

1. For a CSV or XLSX coordinate table, use these headers:

   ```csv
   X좌표,Y좌표,Net Name
   ```

   `X` / `PIN_X` / `PIX_X`, `Y` / `PIN_Y` and `NET_NAME` / `NET` are accepted as aliases. An optional `Source_probe name` column names the HFSS group to copy for each row.

2. An Allegro symbol pin report is also accepted. It needs all of these headers:

   ```csv
   REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME
   ```

   `COMP_DEVICE_TYPE` is accepted as an alias for `COMP_DEVICE`.

3. For a Sigrity text SPD, open the `.spd` file with **Browse Coordinate File** and click **Load Inputs**. Choose the DUT component and site. The default is site 0, then 1, then the lowest available number. A `SITE3` instance supplies its own pins, including shared nets such as `DGND`. For pins grouped by net name, `CLK/3` and `U3_CLK` both identify site 3. Pins without a site assignment can be selected separately.
4. Prepare an HFSS source model for each group used in the preview. Place its bond point at the model origin. Named input groups come from `Source_probe name` or Allegro `COMP_DEVICE`. Ungrouped pins use `Source_Group` unless the app recognizes staggered bonding rows.
5. Inspect the white pin map. A marker shows the bonding position, the HFSS source group by color and the assumed probe tip direction by its triangle. Read the pin's die edge in the **SIDE** column or tooltip. CSV and XLSX coordinates are centered on the input layout. SPD coordinates are centered on the selected component and site. Use **Change DUT / site** to switch sites.
6. For two-, three- or four-sided layouts with alternating bonding rows, open **Pin editing → Tips point**. With **Toward center**, outer-row pads use the long probe and inner-row pads use the short probe. **Toward outside** reverses the assignments. Set **Long group** and **Short group** to the actual HFSS group names (defaults `LongProbe` and `ShortProbe`). Named input groups take precedence unless **Replace input groups** is enabled. The table and map tooltips show the estimated type, including **Undetermined** for ambiguous pins. Coordinates alone give relative length.
7. Click a pin on the map or a row in the table, or drag a rectangle on the map to pick multiple pins at once. Hold Ctrl while clicking or dragging to toggle individual or boxed pins, and right-drag to pan when zoomed in. Assign an HFSS source group to the picked pins. Manual groups take precedence. For a corner pad whose intended side differs from the automatic result, set its **CIS side**. Choosing **Auto** restores its original classification.
8. Check `SOURCE_GROUP` and `SIDE`, then generate the AEDT script. By default the script includes all pins passing the filters. Enable **Place picked pins only** to export a subset. Each pin keeps the side determined from the complete layout of the active input or site. The four rotation settings control the corresponding HFSS design variables.
9. Run the generated script in AEDT/HFSS.

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
