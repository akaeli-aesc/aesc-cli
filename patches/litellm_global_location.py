#!/usr/bin/env python3
"""
Patch LiteLLM to fix Vertex AI global location URL construction.

Bug: LiteLLM uses {location}-aiplatform.googleapis.com but for 'global'
it should be aiplatform.googleapis.com (without location prefix).

This patch adds handling for the 'global' location in _get_vertex_url().
"""

import glob
import sys

# Find the litellm common_utils.py file
patterns = [
    "/app/.venv/lib/python*/site-packages/litellm/llms/vertex_ai/common_utils.py",
    ".venv/lib/python*/site-packages/litellm/llms/vertex_ai/common_utils.py",
]

file_path = None
for pattern in patterns:
    matches = glob.glob(pattern)
    if matches:
        file_path = matches[0]
        break

if not file_path:
    print("LiteLLM common_utils.py not found, skipping patch")
    sys.exit(0)

print(f"Patching: {file_path}")

with open(file_path, 'r') as f:
    content = f.read()

# Check if already patched
if "# PATCHED: Handle global location" in content:
    print("Already patched!")
    sys.exit(0)

# Find the _get_vertex_url function and add global handling
old_code = '''def _get_vertex_url(
    mode: all_gemini_url_modes,
    model: str,
    stream: Optional[bool],
    vertex_project: Optional[str],
    vertex_location: Optional[str],
    vertex_api_version: Literal["v1", "v1beta1"],
) -> Tuple[str, str]:
    url: Optional[str] = None
    endpoint: Optional[str] = None
    if mode == "chat":'''

new_code = '''def _get_vertex_url(
    mode: all_gemini_url_modes,
    model: str,
    stream: Optional[bool],
    vertex_project: Optional[str],
    vertex_location: Optional[str],
    vertex_api_version: Literal["v1", "v1beta1"],
) -> Tuple[str, str]:
    url: Optional[str] = None
    endpoint: Optional[str] = None
    # PATCHED: Handle global location - use aiplatform.googleapis.com without location prefix
    if vertex_location == "global":
        if mode == "chat":
            endpoint = "streamGenerateContent" if stream else "generateContent"
            base = f"https://aiplatform.googleapis.com/{vertex_api_version}/projects/{vertex_project}/locations/global/publishers/google/models/{model}:{endpoint}"
            url = base + "?alt=sse" if stream else base
        elif mode == "embedding":
            endpoint = "predict"
            url = f"https://aiplatform.googleapis.com/v1/projects/{vertex_project}/locations/global/publishers/google/models/{model}:{endpoint}"
        if url and endpoint:
            return url, endpoint
    if mode == "chat":'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(file_path, 'w') as f:
        f.write(content)
    print("Patched successfully!")
else:
    print("Could not find target code to patch - LiteLLM version may have changed")
    sys.exit(1)
