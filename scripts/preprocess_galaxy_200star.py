#!/usr/bin/env python3
"""
Wrapper to run preprocess_galaxy.py on 200+ star filtered data.
Patches DATA_DIR and VIZ_DIR to point to the filtered dataset.
"""
import sys
from pathlib import Path

FILTERED_DIR = Path(__file__).resolve().parent.parent / "packages" / "api" / "data" / "filtered_200star"
VIZ_DIR = FILTERED_DIR / "viz"
VIZ_DIR.mkdir(exist_ok=True)

# Patch the original script's paths before importing
gitvizz_scripts = Path("/data/workspace/code/github_repos/project/GitVizz/backend/scripts")
sys.path.insert(0, str(gitvizz_scripts))

import preprocess_galaxy
preprocess_galaxy.DATA_DIR = FILTERED_DIR
preprocess_galaxy.VIZ_DIR = VIZ_DIR

if __name__ == "__main__":
    preprocess_galaxy.main()
