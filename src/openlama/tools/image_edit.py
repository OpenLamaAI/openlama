"""Tool: image_edit – edit images using ComfyUI Qwen Image Edit backend."""

from pathlib import Path

from openlama.tools.registry import register_tool
from openlama.logger import get_logger

logger = get_logger("tools.image_edit")
from openlama.config import get_config, get_config_int, get_config_float
from openlama.utils.comfyui_client import (
    build_img2img_workflow,
    ensure_comfyui_running,
    extract_image_paths,
    poll_result,
    schedule_comfyui_stop,
    submit_prompt,
    upload_image,
    validate_workflow,
)


def _find_latest_upload(user_id: int) -> str | None:
    """Find the most recently uploaded image for this user."""
    upload_dir = Path(get_config("upload_temp_dir"))
    if not upload_dir.exists():
        return None
    # Look for files matching user_id pattern
    candidates = sorted(
        upload_dir.glob(f"{user_id}_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


async def _execute(args: dict) -> str:
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return "Please provide an edit prompt (e.g., 'change the sky to sunset')."

    # Ensure ComfyUI is running
    if not await ensure_comfyui_running():
        return ("ComfyUI backend is not running.\n"
                "Set the start command: openlama config set comfy_start_cmd \"<command>\"")

    # Find input image
    image_path = args.get("image_path", "").strip()
    user_id = args.get("_user_id", 0)

    if not image_path and user_id:
        image_path = _find_latest_upload(user_id) or ""

    if not image_path:
        return (
            "No image to edit. Please send an image first, then request the edit."
        )

    if not Path(image_path).exists():
        return f"Image file not found: {image_path}"

    negative_prompt = args.get("negative_prompt", "")
    seed = args.get("seed")
    steps = args.get("steps", get_config_int("comfy_steps", 4))
    cfg = args.get("cfg", get_config_float("comfy_cfg", 1.0))

    try:
        # Upload image to ComfyUI
        uploaded_name = await upload_image(image_path)
        logger.info("uploaded %s → %s", image_path, uploaded_name)

        # Build and submit workflow
        workflow = build_img2img_workflow(
            uploaded_image_name=uploaded_name,
            prompt=prompt,
            negative_prompt=negative_prompt,
            steps=steps,
            cfg=cfg,
            denoise=get_config_float("comfy_denoise", 1.0),
            seed=seed,
        )

        valid, missing = await validate_workflow(workflow)
        if not valid:
            return f"Workflow validation failed. Missing nodes: {', '.join(missing)}\nPlease install the required custom nodes in ComfyUI."

        prompt_id = await submit_prompt(workflow)
        logger.info("submitted prompt_id=%s", prompt_id)

        # Poll for result
        result = await poll_result(prompt_id)
        image_paths = extract_image_paths(result)

        if not image_paths:
            return "Image editing completed but no output file was found."

        await schedule_comfyui_stop()

        path = image_paths[0]
        return f"[IMAGE:{path}]\nImage editing complete: {prompt[:100]}"

    except TimeoutError:
        return "Image editing timed out. Please try again."
    except Exception as e:
        return f"Image editing error: {e}"


register_tool(
    name="image_edit",
    description=(
        "Edit existing images using the ComfyUI Qwen Image Edit backend. "
        "Use when the user sends an image and requests edits. "
        "English prompts yield the best results. "
        "If the user requests in another language, translate to English for the prompt."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Image edit prompt (English recommended, e.g., 'change the background to a beach')",
            },
            "image_path": {
                "type": "string",
                "description": "Path to the image file to edit (if not specified, uses the user's most recently uploaded image)",
            },
            "negative_prompt": {
                "type": "string",
                "description": "Undesired elements (e.g., 'blurry, low quality')",
            },
            "seed": {
                "type": "integer",
                "description": "Seed value (same seed = same result)",
            },
            "steps": {
                "type": "integer",
                "description": "Number of editing steps (default: 4)",
            },
            "cfg": {
                "type": "number",
                "description": "CFG scale (default: 1.0)",
            },
        },
        "required": ["prompt"],
    },
    execute=_execute,
    admin_only=True,
)
