"""ComfyUI-H3-Easy: one-node MiniMax H3 video + audio generation."""

WEB_DIRECTORY = "./web"

try:
    from comfy_api.latest import ComfyExtension
except ImportError:  # imported outside ComfyUI, e.g. by pytest
    ComfyExtension = None

if not __package__:  # loaded as a plain module (pytest rootdir), not as a custom node package
    ComfyExtension = None

if ComfyExtension is not None:
    from .h3easy import server_routes  # noqa: F401  (registers /h3easy/media_info)
    from .h3easy.nodes import NODES

    class H3EasyExtension(ComfyExtension):
        async def get_node_list(self):
            return NODES

    async def comfy_entrypoint() -> ComfyExtension:
        return H3EasyExtension()
