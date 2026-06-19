# CIS Probe Placement Scriptor

Windows GUI tool for generating Ansys Electronics Desktop / HFSS IronPython placement scripts for directional CIS probe layouts.

## Usage

1. Prepare an Allegro symbol pin report as CSV or XLSX.
2. Required headers:

   ```csv
   REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME
   ```

   `PIX_X` is accepted as an alias for `PIN_X`, and `COMP_DEVICE_TYPE` is accepted as an alias for `COMP_DEVICE`.

3. In HFSS, place source probe objects into groups named `Source_<COMP_DEVICE>`.
4. Run the app, load the pin report, filter the target pins, verify `SIDE` and `SOURCE_GROUP`, then generate the AEDT script.
5. Run the generated script in AEDT/HFSS.

The app includes `Tutorial > How to Use` with the full Korean guide and sample CSV.

## Build

```powershell
python -m pytest
powershell.exe -ExecutionPolicy Bypass -NoProfile -File .\build_exe.ps1
& 'C:\Program Files\Inno Setup 7\ISCC.exe' .\CISProbePlacementScriptor.iss
```

The installer is written to `installer\CISProbePlacementScriptorSetup.exe`.
