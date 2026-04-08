"""ComfyUI API client – health check, prompt submission, image upload, result polling, auto start/stop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import random
import uuid
from pathlib import Path
from typing import Optional

import httpx

from openlama.config import get_config, get_config_int

logger = logging.getLogger("openlama.utils.comfyui")

# Track ComfyUI process started by us
_comfy_process: asyncio.subprocess.Process | None = None
_stop_task: asyncio.Task | None = None


async def comfyui_alive() -> bool:
    """Check if ComfyUI backend is running."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{get_config('comfy_base')}/system_stats")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_comfyui_running() -> bool:
    """Start ComfyUI if not running and start_cmd is configured. Returns True if alive."""
    global _stop_task
    if await comfyui_alive():
        # Cancel any pending stop
        if _stop_task and not _stop_task.done():
            _stop_task.cancel()
            _stop_task = None
        return True

    start_cmd = get_config("comfy_start_cmd", "")
    if not start_cmd:
        return False

    logger.info("starting ComfyUI: %s", start_cmd[:100])
    global _comfy_process
    try:
        _comfy_process = await asyncio.create_subprocess_shell(
            start_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as e:
        logger.error("failed to start ComfyUI: %s", e)
        return False

    # Wait for ComfyUI to be ready (max 60s)
    for _ in range(30):
        await asyncio.sleep(2)
        if await comfyui_alive():
            logger.info("ComfyUI started (PID %s)", _comfy_process.pid if _comfy_process else "?")
            return True

    logger.error("ComfyUI did not start within 60s")
    return False


async def schedule_comfyui_stop():
    """Schedule ComfyUI shutdown after delay (if auto_stop enabled)."""
    auto_stop = get_config("comfy_auto_stop", "true").lower() in ("true", "1", "yes")
    if not auto_stop:
        return

    global _stop_task
    # Cancel previous stop task if any
    if _stop_task and not _stop_task.done():
        _stop_task.cancel()

    delay = get_config_int("comfy_stop_delay_sec", 30)
    _stop_task = asyncio.create_task(_delayed_stop(delay))


async def _delayed_stop(delay: int):
    """Wait, then stop ComfyUI if no new work arrived."""
    try:
        await asyncio.sleep(delay)
        await stop_comfyui()
    except asyncio.CancelledError:
        pass  # New work arrived, stop was cancelled


async def stop_comfyui():
    """Stop ComfyUI process."""
    global _comfy_process
    if _comfy_process and _comfy_process.returncode is None:
        logger.info("stopping ComfyUI (PID %s)", _comfy_process.pid)
        try:
            _comfy_process.terminate()
            try:
                await asyncio.wait_for(_comfy_process.wait(), timeout=10)
            except asyncio.TimeoutError:
                _comfy_process.kill()
                await _comfy_process.wait()
            logger.info("ComfyUI stopped")
        except Exception as e:
            logger.error("failed to stop ComfyUI: %s", e)
        _comfy_process = None
        return

    # Fallback: kill by port if we didn't start it but auto_stop is on
    # (skip — only manage processes we started)


async def get_available_nodes() -> set[str]:
    """Get all available node class types from ComfyUI."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{get_config('comfy_base')}/object_info")
            if r.status_code == 200:
                return set(r.json().keys())
    except Exception as e:
        logger.error("failed to get object_info: %s", e)
    return set()


async def validate_workflow(workflow: dict) -> tuple[bool, list[str]]:
    """Validate that all nodes in a workflow exist in ComfyUI.

    Returns: (is_valid, list_of_missing_node_types)
    """
    available = await get_available_nodes()
    if not available:
        return False, ["Cannot connect to ComfyUI or failed to retrieve node info"]

    missing = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        if class_type and class_type not in available:
            missing.append(class_type)

    return len(missing) == 0, missing


async def setup_comfyui() -> dict:
    """Check ComfyUI connection and validate default workflows.

    Returns status dict:
    {
        "connected": bool,
        "txt2img": {"valid": bool, "missing": list},
        "img2img": {"valid": bool, "missing": list},
        "available_workflows": list[str],
    }
    """
    result = {
        "connected": False,
        "txt2img": {"valid": False, "missing": []},
        "img2img": {"valid": False, "missing": []},
        "available_workflows": list_workflows(),
    }

    if not await comfyui_alive():
        return result

    result["connected"] = True

    # Validate txt2img workflow
    try:
        txt2img_name = get_config("comfy_workflow_txt2img", "txt2img_default")
        txt2img_wf = _load_workflow(txt2img_name)
        valid, missing = await validate_workflow(txt2img_wf)
        result["txt2img"] = {"valid": valid, "missing": missing, "name": txt2img_name}
    except FileNotFoundError:
        result["txt2img"] = {"valid": False, "missing": [f"Workflow file not found: {txt2img_name}"], "name": txt2img_name}

    # Validate img2img workflow
    try:
        img2img_name = get_config("comfy_workflow_img2img", "img2img_default")
        img2img_wf = _load_workflow(img2img_name)
        valid, missing = await validate_workflow(img2img_wf)
        result["img2img"] = {"valid": valid, "missing": missing, "name": img2img_name}
    except FileNotFoundError:
        result["img2img"] = {"valid": False, "missing": [f"Workflow file not found: {img2img_name}"], "name": img2img_name}

    return result


async def submit_prompt(prompt_graph: dict, workflow_id: str = "") -> str:
    """Submit a workflow prompt to ComfyUI. Returns prompt_id."""
    payload = {
        "prompt": prompt_graph,
        "client_id": str(uuid.uuid4()),
    }
    if workflow_id:
        payload["extra_data"] = {"workflow_id": workflow_id}

    comfy_base = get_config("comfy_base")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{comfy_base}/prompt", json=payload)
        r.raise_for_status()
        data = r.json()

    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
    return prompt_id


async def poll_result(prompt_id: str, timeout: int | None = None) -> dict:
    """Poll ComfyUI history until the prompt completes. Returns output dict."""
    if timeout is None:
        timeout = get_config_int("comfy_timeout_sec", 120)
    deadline = asyncio.get_event_loop().time() + timeout

    comfy_base = get_config("comfy_base")
    async with httpx.AsyncClient(timeout=10) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{comfy_base}/history/{prompt_id}")
                r.raise_for_status()
                data = r.json()

                entry = data.get(prompt_id)
                if entry:
                    status = entry.get("status", {})
                    if status.get("completed") or status.get("status_str") == "success":
                        return entry
                    # Check for error
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        raise RuntimeError(f"ComfyUI execution error: {msgs}")
                    # Also check if outputs exist (some versions don't set status)
                    outputs = entry.get("outputs", {})
                    if outputs:
                        return entry
            except httpx.HTTPError:
                pass

            await asyncio.sleep(1.5)

    raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out after {timeout}s")


def extract_image_paths(result: dict) -> list[str]:
    """Extract output image file paths from ComfyUI result."""
    paths = []
    comfy_output_dir = get_config("comfy_output_dir")
    outputs = result.get("outputs", {})
    for node_id, node_out in outputs.items():
        images = node_out.get("images", [])
        for img in images:
            filename = img.get("filename", "")
            subfolder = img.get("subfolder", "")
            if filename:
                if subfolder:
                    full_path = Path(comfy_output_dir) / subfolder / filename
                else:
                    full_path = Path(comfy_output_dir) / filename
                if full_path.exists():
                    paths.append(str(full_path))
    return paths


async def upload_image(image_path: str, name: Optional[str] = None) -> str:
    """Upload an image to ComfyUI input directory. Returns the uploaded filename."""
    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    upload_name = name or p.name
    file_bytes = p.read_bytes()

    comfy_base = get_config("comfy_base")
    # ComfyUI expects multipart form data
    async with httpx.AsyncClient(timeout=30) as client:
        files = {"image": (upload_name, file_bytes, "image/png")}
        data = {"type": "input", "overwrite": "true"}
        r = await client.post(f"{comfy_base}/upload/image", files=files, data=data)
        r.raise_for_status()
        resp = r.json()

    returned_name = resp.get("name")
    if not returned_name:
        raise RuntimeError(f"ComfyUI upload did not return name: {resp}")
    return returned_name


def _workflows_dir() -> Path:
    """Get workflows directory path."""
    return Path(get_config("prompts_dir")).parent / "workflows"


def list_workflows() -> list[str]:
    """List available workflow JSON files."""
    d = _workflows_dir()
    if not d.exists():
        return []
    return sorted(f.stem for f in d.glob("*.json"))


def _load_workflow(name: str) -> dict:
    """Load a workflow JSON file by name."""
    p = _workflows_dir() / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(f"Workflow not found: {p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _inject_params(workflow: dict, replacements: dict) -> dict:
    """Inject parameters into a workflow template.

    Scans all node inputs for placeholder values and replaces them:
    - "__PROMPT__" → prompt text
    - "__IMAGE__" → uploaded image name
    - "__NEGATIVE__" → negative prompt
    - KSampler nodes: seed, steps, cfg, denoise auto-detected and replaced
    - EmptySD3LatentImage / EmptyLatentImage: width, height replaced
    """
    import copy
    wf = copy.deepcopy(workflow)

    prompt = replacements.get("prompt", "")
    image = replacements.get("image", "")
    negative = replacements.get("negative", "")
    seed = replacements.get("seed") or random.randint(1, 2**31)
    steps = replacements.get("steps")
    cfg = replacements.get("cfg")
    denoise = replacements.get("denoise")
    width = replacements.get("width")
    height = replacements.get("height")

    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")

        # Replace __PROMPT__ placeholder in any text field
        for key, val in inputs.items():
            if val == "__PROMPT__":
                inputs[key] = prompt
            elif val == "__IMAGE__":
                inputs[key] = image
            elif val == "__NEGATIVE__":
                inputs[key] = negative

        # Auto-detect and replace KSampler params
        if "KSampler" in class_type:
            inputs["seed"] = seed
            if steps is not None:
                inputs["steps"] = steps
            if cfg is not None:
                inputs["cfg"] = cfg
            if denoise is not None:
                inputs["denoise"] = denoise

        # Auto-detect latent image size nodes
        if class_type in ("EmptySD3LatentImage", "EmptyLatentImage"):
            if width is not None:
                inputs["width"] = width
            if height is not None:
                inputs["height"] = height

        # CLIPTextEncode: inject prompt into "text" field
        if class_type == "CLIPTextEncode" and "text" in inputs:
            if inputs["text"] == "__PROMPT__" or not inputs["text"]:
                inputs["text"] = prompt

        # LoadImage: inject image name
        if class_type == "LoadImage" and "image" in inputs:
            if inputs["image"] == "__IMAGE__" or not inputs["image"]:
                inputs["image"] = image

        # TextEncodeQwenImageEditPlus: inject prompt
        if "TextEncode" in class_type and "prompt" in inputs:
            if inputs["prompt"] == "__PROMPT__":
                inputs["prompt"] = prompt
            elif inputs["prompt"] == "__NEGATIVE__":
                inputs["prompt"] = negative

    return wf


def build_txt2img_workflow(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    steps: int = 4,
    cfg: float = 1.0,
    denoise: float = 1.0,
    seed: Optional[int] = None,
) -> dict:
    """Build txt2img workflow from JSON template."""
    wf_name = get_config("comfy_workflow_txt2img", "txt2img_default")
    try:
        template = _load_workflow(wf_name)
    except FileNotFoundError:
        logger.warning("workflow %s not found, using fallback", wf_name)
        raise RuntimeError(
            f"Workflow '{wf_name}' not found.\n"
            f"Save an API format JSON to ~/.config/openlama/workflows/.\n"
            f"Config: openlama config set comfy_workflow_txt2img <name>"
        )

    return _inject_params(template, {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg,
        "denoise": denoise,
        "seed": seed,
    })


def build_img2img_workflow(
    uploaded_image_name: str,
    prompt: str,
    negative_prompt: str = "",
    steps: int = 4,
    cfg: float = 1.0,
    denoise: float = 1.0,
    seed: Optional[int] = None,
) -> dict:
    """Build img2img workflow from JSON template."""
    wf_name = get_config("comfy_workflow_img2img", "img2img_default")
    try:
        template = _load_workflow(wf_name)
    except FileNotFoundError:
        logger.warning("workflow %s not found, using fallback", wf_name)
        raise RuntimeError(
            f"Workflow '{wf_name}' not found.\n"
            f"Save an API format JSON to ~/.config/openlama/workflows/.\n"
            f"Config: openlama config set comfy_workflow_img2img <name>"
        )

    return _inject_params(template, {
        "prompt": prompt,
        "negative": negative_prompt,
        "image": uploaded_image_name,
        "steps": steps,
        "cfg": cfg,
        "denoise": denoise,
        "seed": seed,
    })
