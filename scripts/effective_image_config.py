"""Resolve validated task choices into one non-secret backend execution snapshot."""

import argparse
import json
from pathlib import Path


def build(validation, aspect_ratio=None):
    if not validation.get("valid") or validation.get("errors"):
        raise ValueError("A passing current parameter-validation result is required")
    if validation["scope"] not in ("full", "images", "plan") or validation["route"]["starting_point"] == 5:
        raise ValueError("This task has no image-generation configuration")
    if validation["route"].get("use_image_gen", {}).get("value", 1) != 1:
        raise ValueError("image-gen is disabled; no image-gen execution snapshot is applicable")
    effective, numbers = validation["effective_parameters"], validation["parameters"]
    supplements = validation.get("supplements", {})
    ratio = effective["aspect_ratio"]
    if numbers["aspect_ratio"]["number"] == 1:
        if not aspect_ratio:
            raise ValueError("Per-image aspect ratio must be resolved from the approved plan")
        ratio = aspect_ratio
    elif aspect_ratio and aspect_ratio != ratio:
        raise ValueError("Per-image aspect ratio contradicts task choice")
    if ratio not in ("1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
                     "16:9", "9:16", "2:1", "1:2", "21:9", "9:21"):
        raise ValueError("Unsupported aspect ratio")
    variants = numbers["variants_per_image"]["number"]
    count = {1: 1, 2: 2}.get(variants, supplements.get("variants_per_image"))
    batch = numbers["generation_batch_size"]["number"]
    batch_size = {1: 1, 2: 2, 3: 4}.get(batch, supplements.get("generation_batch_size"))
    compression = numbers.get("output_compression", {}).get("number", 1)
    background = effective["background"]
    request = {
        "GPT_IMAGE2_MODEL": effective["model"], "GPT_IMAGE2_N": count,
        "GPT_IMAGE2_MODE": "current", "GPT_IMAGE2_RESOLUTION": effective["resolution"],
        "GPT_IMAGE2_ASPECT_RATIO": ratio, "GPT_IMAGE2_QUALITY": effective["quality"],
        "GPT_IMAGE2_BACKGROUND": "" if background == "design" else background,
        "GPT_IMAGE2_OUTPUT_FORMAT": effective["output_format"]
            if numbers["output_format"]["number"] != 1 else "",
        "GPT_IMAGE2_OUTPUT_COMPRESSION": {1: "", 2: 70, 3: 90}.get(
            compression, supplements.get("output_compression")),
        "GPT_IMAGE2_MODERATION": effective.get("moderation") or "",
        "GPT_IMAGE2_SHOW_INFO": effective["show_info"],
    }
    return {"schema_version": 1, "request_defaults": request,
            "prompt_settings": {key: effective.get(key) for key in
                                ("preset", "type", "density", "style", "palette", "language",
                                 "reference_usage", "watermark.enabled", "watermark.position")},
            "prompt_supplements": {key: supplements[key] for key in
                                   ("palette", "watermark.content", "author_name") if key in supplements},
            "references": supplements.get("references", []),
            "scheduling": {"batch_size": batch_size, "limit": supplements.get("limit"),
                           "existing_images": effective.get("existing_images")},
            "storage": {"output_dir": effective["output_dir"],
                        "custom_output_dir": supplements.get("output_dir")},
            "limits": "Prompt settings must be applied to each prompt; scheduling and request limits "
                      "are enforced by the caller. This file contains no service credentials."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--aspect-ratio")
    args = parser.parse_args()
    print(json.dumps(build(json.loads(args.validation.read_text(encoding="utf-8-sig")),
                           args.aspect_ratio), ensure_ascii=False, indent=2))
