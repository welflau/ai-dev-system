"""GenerateImageAction — 识别到用户想生图时，输出参数卡片让用户确认后入队。"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult

_VALID_ENGINES = ("", "gemini", "gemini2", "jimeng", "midjourney", "nano-banana")
_VALID_RATIOS  = ("1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2")
_VALID_SIZES   = ("2K", "4K", "1K")


class GenerateImageAction(ActionBase):

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return "识别到用户想生成/画一张图片时，生成参数卡片让用户确认，不自动入队。"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户明确说「生成/画/出/做一张图」「帮我生图」等时使用。"
                "生成带参数的卡片让用户确认，不会立即生图。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "英文生图 prompt，尽量详细描述画面内容、风格、光线等",
                    },
                    "engine": {
                        "type": "string",
                        "description": "生图引擎，可选 gemini/gemini2/jimeng/midjourney，留空用系统默认",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "description": "宽高比，如 1:1 / 16:9 / 9:16 / 4:3，默认 1:1",
                    },
                    "image_size": {
                        "type": "string",
                        "description": "图片尺寸，如 2K / 4K，默认 2K",
                    },
                },
                "required": ["prompt"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        prompt = (context.get("prompt") or "").strip()
        if not prompt:
            return ActionResult(success=False, error="生图 prompt 不能为空")

        engine       = (context.get("engine") or "").strip()
        aspect_ratio = (context.get("aspect_ratio") or "1:1").strip()
        image_size   = (context.get("image_size") or "2K").strip()

        if engine not in _VALID_ENGINES:
            engine = ""
        if aspect_ratio not in _VALID_RATIOS:
            aspect_ratio = "1:1"
        if image_size not in _VALID_SIZES:
            image_size = "2K"

        return ActionResult(
            success=True,
            data={
                "type": "generate_image",
                "prompt": prompt,
                "engine": engine,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            },
        )
