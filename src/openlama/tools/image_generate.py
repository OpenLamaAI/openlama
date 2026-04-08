"""Tool: image_generate – text-to-image generation via ComfyUI backend."""

from openlama.tools.registry import register_tool
from openlama.config import get_config_int, get_config_float
from openlama.logger import get_logger

logger = get_logger("tools.image_generate")
from openlama.utils.comfyui_client import (
    build_txt2img_workflow,
    ensure_comfyui_running,
    extract_image_paths,
    poll_result,
    schedule_comfyui_stop,
    submit_prompt,
    validate_workflow,
)

# Standard size presets
SIZE_PRESETS = {
    "1:1": (1024, 1024),
    "4:5": (1088, 1344),
    "3:4": (1024, 1344),
    "9:16": (1088, 1920),
    "16:9": (1920, 1088),
}


async def _execute(args: dict) -> str:
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return "Please provide an image generation prompt."

    # Ensure ComfyUI is running (auto-start if configured)
    if not await ensure_comfyui_running():
        return ("ComfyUI backend is not running.\n"
                "Set the start command: openlama config set comfy_start_cmd \"<command>\"")

    # Parse size
    aspect = args.get("aspect_ratio", "1:1")
    if aspect in SIZE_PRESETS:
        width, height = SIZE_PRESETS[aspect]
    else:
        width = args.get("width", 1024)
        height = args.get("height", 1024)
        # Clamp to valid range
        width = max(256, min(2048, width))
        height = max(256, min(2048, height))

    seed = args.get("seed")
    steps = args.get("steps", get_config_int("comfy_steps", 4))
    cfg = args.get("cfg", get_config_float("comfy_cfg", 1.0))

    try:
        # Build workflow from template
        workflow = build_txt2img_workflow(
            prompt=prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            denoise=get_config_float("comfy_denoise", 1.0),
            seed=seed,
        )

        # Validate required nodes exist
        valid, missing = await validate_workflow(workflow)
        if not valid:
            return f"Workflow validation failed. Missing nodes: {', '.join(missing)}\nPlease install the required custom nodes in ComfyUI."

        prompt_id = await submit_prompt(workflow)
        logger.info("submitted prompt_id=%s, %dx%d", prompt_id, width, height)

        # Poll for result
        result = await poll_result(prompt_id)
        image_paths = extract_image_paths(result)

        if not image_paths:
            return "Image generation completed but no output file was found."

        # Schedule ComfyUI stop after delay
        await schedule_comfyui_stop()

        # Return special format that chat handler detects
        path = image_paths[0]
        return f"[IMAGE:{path}]\nImage generation complete: {width}x{height}, prompt: {prompt[:100]}"

    except TimeoutError:
        return "Image generation timed out. Please try again."
    except Exception as e:
        return f"Image generation error: {e}"


register_tool(
    name="image_generate",
    description=(
        "Generate images from text prompts using the ComfyUI backend. "
        "English prompts yield the best results. "
        "If the user requests in another language, translate to English for the prompt."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Image generation prompt (English recommended)",
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Image aspect ratio: 1:1, 4:5, 3:4, 9:16, 16:9",
                "enum": ["1:1", "4:5", "3:4", "9:16", "16:9"],
                "default": "1:1",
            },
            "width": {
                "type": "integer",
                "description": "Custom width (256-2048, used when aspect_ratio is not specified)",
            },
            "height": {
                "type": "integer",
                "description": "Custom height (256-2048, used when aspect_ratio is not specified)",
            },
            "seed": {
                "type": "integer",
                "description": "Seed value (same seed = same result, random if not specified)",
            },
            "steps": {
                "type": "integer",
                "description": "Number of generation steps (default: 4, higher = better quality but slower)",
            },
            "cfg": {
                "type": "number",
                "description": "CFG scale (default: 1.0)",
            },
        },
        "required": ["prompt"],
    },
    execute=_execute,
)
