"""Small HTTP helper for the media panel: duration and audio-track info of input files."""

from __future__ import annotations

import os

from aiohttp import web

import folder_paths
from server import PromptServer

from . import shotlist
from .media import NONE, SHOT_REFS, find_shot_files, probe


@PromptServer.instance.routes.post("/h3easy/shot_list")
async def shot_list(request):
    """What a pasted shot list asks for, and which of its files are in the input folder."""
    shots = shotlist.parse((await request.json()).get("text", ""))
    found = find_shot_files(shots)
    return web.json_response({
        "problems": shotlist.problems(shots),
        "shots": [{"number": shot.number, "seconds": shot.seconds, "continues": shot.continues,
                   "files": [{"tag": ref.tag, "wanted": ref.file, "found": name}
                             for group, _ in SHOT_REFS for ref, name in zip(getattr(shot, group), names[group])]}
                  for shot, names in zip(shots, found)],
    })


@PromptServer.instance.routes.get("/h3easy/media_info")
async def media_info(request):
    name = request.query.get("name", "")
    if not name or name == NONE:
        return web.json_response({"error": "no file"}, status=400)
    try:
        path = os.path.abspath(folder_paths.get_annotated_filepath(name))
    except ValueError:  # Core rejects traversal and malformed names
        return web.json_response({"error": "invalid file name"}, status=400)
    input_dir = os.path.abspath(folder_paths.get_input_directory())
    if os.path.commonpath([path, input_dir]) != input_dir:
        return web.json_response({"error": "outside input directory"}, status=403)
    if not os.path.isfile(path):
        return web.json_response({"error": "not found"}, status=404)
    try:
        return web.json_response(probe(path))
    except Exception as exc:  # unreadable or unsupported container
        return web.json_response({"error": str(exc)}, status=422)
