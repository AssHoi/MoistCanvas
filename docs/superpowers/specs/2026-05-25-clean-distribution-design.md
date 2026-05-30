# Clean Distribution Design

## Goal

Create a clean MoistCanvas package that can be shared with other users without local secrets, generated media, cache files, logs, Git metadata, or bundled runtime files.

## Package Contents

The clean package includes only the files needed for a new user to install and run MoistCanvas:

- `main.py`
- `requirements.txt`
- `README.md`
- `README-FIRST.txt`
- `安装依赖.bat`
- `运行文件.bat`
- `static/`
- `data/api_providers.json`
- `scripts/build_clean_zip.ps1`

## Excluded Local Data

The package must not include:

- `API/.env`
- `.env`
- `runtime/`
- `output/`
- `history.json`
- `data/canvases_v2/`
- `data/*_cache.json`
- `dist/`
- `*.log`
- `__pycache__/`
- `.git/`
- editor and OS metadata

## Packaging Approach

Use a PowerShell script at `scripts/build_clean_zip.ps1`. The script builds from an explicit allowlist instead of compressing the whole project directory. This keeps accidental private files out of the ZIP even if more local data appears later.

The script writes `dist/MoistCanvas-Clean.zip`, recreating a temporary staging folder on each run. It validates required files before packaging and prints the generated ZIP path.

## Documentation

Rewrite `README.md` as readable Chinese documentation for distribution and developer use. Keep `README-FIRST.txt` short and user-facing so recipients can open it first after extracting the ZIP.

## Verification

After packaging, inspect the ZIP contents and confirm it contains required app files and does not contain local secrets, runtime dependencies, output media, history, caches, logs, or Git files.
