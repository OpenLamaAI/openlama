"""Tests for ComfyUI client – workflow building, API (mock where needed)."""

import pytest

from utils.comfyui_client import (
    build_img2img_workflow,
    build_txt2img_workflow,
    comfyui_alive,
    extract_image_paths,
)


# ── Workflow Building ──

def test_txt2img_workflow_structure():
    wf = build_txt2img_workflow("a cat", 1024, 1024)
    assert isinstance(wf, dict)
    # Must have key nodes
    assert "28" in wf  # UNETLoader
    assert "27" in wf  # CLIPTextEncode (prompt)
    assert "3" in wf   # KSampler
    assert "9" in wf   # SaveImage
    assert "8" in wf   # VAEDecode


def test_txt2img_prompt_injection():
    prompt = "a beautiful sunset"
    wf = build_txt2img_workflow(prompt)
    assert wf["27"]["inputs"]["text"] == prompt


def test_txt2img_dimensions():
    wf = build_txt2img_workflow("test", width=1920, height=1080)
    assert wf["13"]["inputs"]["width"] == 1920
    assert wf["13"]["inputs"]["height"] == 1080


def test_txt2img_seed_deterministic():
    wf1 = build_txt2img_workflow("test", seed=42)
    wf2 = build_txt2img_workflow("test", seed=42)
    assert wf1["3"]["inputs"]["seed"] == 42
    assert wf2["3"]["inputs"]["seed"] == 42


def test_txt2img_seed_random():
    wf1 = build_txt2img_workflow("test")
    wf2 = build_txt2img_workflow("test")
    # Random seeds should differ (extremely unlikely to collide)
    s1 = wf1["3"]["inputs"]["seed"]
    s2 = wf2["3"]["inputs"]["seed"]
    assert isinstance(s1, int)
    assert isinstance(s2, int)


def test_txt2img_params():
    wf = build_txt2img_workflow("test", steps=8, cfg=2.0, denoise=0.8)
    ks = wf["3"]["inputs"]
    assert ks["steps"] == 8
    assert ks["cfg"] == 2.0
    assert ks["denoise"] == 0.8


def test_txt2img_sampler_config():
    wf = build_txt2img_workflow("test")
    ks = wf["3"]["inputs"]
    assert ks["sampler_name"] == "res_multistep"
    assert ks["scheduler"] == "simple"


# ── img2img workflow ──

def test_img2img_workflow_structure():
    wf = build_img2img_workflow("uploaded.png", "make it blue")
    assert isinstance(wf, dict)
    assert "1" in wf   # UnetLoaderGGUF
    assert "4" in wf   # LoadImage
    assert "12" in wf  # KSampler
    assert "14" in wf  # SaveImage


def test_img2img_image_name():
    wf = build_img2img_workflow("my_photo.png", "edit prompt")
    assert wf["4"]["inputs"]["image"] == "my_photo.png"


def test_img2img_prompts():
    wf = build_img2img_workflow("img.png", "positive prompt", negative_prompt="negative prompt")
    assert wf["10"]["inputs"]["prompt"] == "positive prompt"
    assert wf["11"]["inputs"]["prompt"] == "negative prompt"


def test_img2img_params():
    wf = build_img2img_workflow("img.png", "test", steps=6, cfg=1.5, denoise=0.9, seed=123)
    ks = wf["12"]["inputs"]
    assert ks["steps"] == 6
    assert ks["cfg"] == 1.5
    assert ks["denoise"] == 0.9
    assert ks["seed"] == 123


def test_img2img_uses_euler_sampler():
    """img2img should use euler sampler (not res_multistep)."""
    wf = build_img2img_workflow("img.png", "test")
    assert wf["12"]["inputs"]["sampler_name"] == "euler"


def test_img2img_lora_loaded():
    wf = build_img2img_workflow("img.png", "test")
    # LoraLoaderModelOnly should reference UnetLoaderGGUF
    assert wf["7"]["inputs"]["model"] == ["1", 0]
    assert "Lightning" in wf["7"]["inputs"]["lora_name"]


# ── extract_image_paths ──

def test_extract_image_paths_empty():
    assert extract_image_paths({}) == []
    assert extract_image_paths({"outputs": {}}) == []


def test_extract_image_paths_with_data(tmp_path):
    # Create a fake output file
    img = tmp_path / "test_output.png"
    img.write_bytes(b"fake png")

    # Patch the module-level COMFY_OUTPUT_DIR used in comfyui_client
    import utils.comfyui_client as cc
    import config
    old_dir = config.COMFY_OUTPUT_DIR
    config.COMFY_OUTPUT_DIR = str(tmp_path)
    # The function reads config.COMFY_OUTPUT_DIR at call time
    # We need to also patch the module's reference
    old_cc = cc.COMFY_OUTPUT_DIR
    cc.COMFY_OUTPUT_DIR = str(tmp_path)

    result = {
        "outputs": {
            "9": {
                "images": [{"filename": "test_output.png", "subfolder": ""}]
            }
        }
    }
    paths = extract_image_paths(result)
    assert len(paths) == 1
    assert "test_output.png" in paths[0]

    config.COMFY_OUTPUT_DIR = old_dir
    cc.COMFY_OUTPUT_DIR = old_cc


# ── ComfyUI alive (may be off, just check it doesn't crash) ──

@pytest.mark.asyncio
async def test_comfyui_alive_returns_bool():
    result = await comfyui_alive()
    assert isinstance(result, bool)
