"""
新建项目破冰 —— 根据名称 / 描述 / traits 给出可选开发方向

不调 LLM，创建流程不被阻塞。UE 项目仍走 propose_ue_framework，本模块只覆盖其余类型。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("actions.chat.propose_project_icebreak")


def _blob(*parts: str) -> str:
    return " ".join(p for p in parts if p).lower()


def _has_any(text: str, keys: List[str]) -> bool:
    return any(k in text for k in keys)


def _opt(oid: str, label: str, prompt: str, hint: str = "") -> Dict[str, str]:
    return {"id": oid, "label": label, "prompt": prompt, "hint": hint}


def build_icebreak_payload(
    name: str,
    description: str = "",
    traits: Optional[List[str]] = None,
    tech_stack: str = "",
) -> Dict[str, Any]:
    """根据项目背景生成破冰分析 + 可点选项。"""
    name = (name or "").strip() or "新项目"
    description = (description or "").strip()
    traits = [str(t) for t in (traits or []) if str(t).strip()]
    tech_stack = (tech_stack or "").strip()
    text = _blob(name, description, tech_stack, " ".join(traits))

    engine = next((t.split(":", 1)[-1] for t in traits if t.startswith("engine:")), "")
    platform = next((t.split(":", 1)[-1] for t in traits if t.startswith("platform:")), "")
    category = next((t.split(":", 1)[-1] for t in traits if t.startswith("category:")), "")
    is_game = "category:game" in traits or _has_any(text, [
        "game", "游戏", "flappy", "snake", "tetris", "fps", "rpg", "塔防", "贪吃蛇",
    ])

    analysis, options = _analyze(name, description, text, traits, engine, platform, category, is_game)
    options.append(_opt(
        "custom",
        "我有别的想法",
        f"项目是「{name}」。先别按你猜的方向做，等我说明白再规划第一个需求。",
        "自己描述",
    ))

    return {
        "type": "propose_icebreak",
        "project_name": name,
        "analysis": analysis,
        "options": options,
        "traits": traits,
        "source": "heuristic",
    }


def _analyze(
    name: str,
    description: str,
    text: str,
    traits: List[str],
    engine: str,
    platform: str,
    category: str,
    is_game: bool,
) -> tuple[str, List[Dict[str, str]]]:
    desc_hint = f"：{description}" if description else ""

    if _has_any(text, ["flappy", "flap", "小鸟飞", "飞翔小鸟", "飞小鸟"]):
        return (
            f"从项目名「{name}」看，很像 Flappy Bird 类休闲跳跃。{description and '描述：' + description or '还没写玩法细节，先定载体再出可玩原型。'}",
            [
                _opt("h5", "网页版 Flappy Bird",
                     f"做「{name}」网页版 Flappy Bird：点击/空格上升、管道障碍、记分与重开。先出可玩原型，不要先做后台。",
                     "最快出可玩原型"),
                _opt("godot", "Godot 2D 客户端",
                     f"用 Godot 4 做「{name}」2D Flappy Bird：场景、物理、分数、重开。先出可玩关卡。",
                     "适合后续扩成完整游戏"),
                _opt("wechat", "微信小游戏",
                     f"把「{name}」做成微信小游戏版 Flappy Bird，先出可玩原型，再补分享和排行榜。",
                     "适合传播"),
            ],
        )

    if _has_any(text, ["snake", "贪吃蛇"]):
        return (
            f"「{name}」像贪吃蛇。先定平台，再做移动、吃食物、撞墙/撞自己。",
            [
                _opt("h5", "网页版贪吃蛇", f"做「{name}」网页贪吃蛇，键盘控制，先出可玩原型。", "最快"),
                _opt("godot", "Godot 2D", f"用 Godot 4 做「{name}」贪吃蛇，先出可玩关卡。", "客户端"),
                _opt("wechat", "微信小游戏", f"把「{name}」做成微信小游戏贪吃蛇。", "传播"),
            ],
        )

    if _has_any(text, ["tetris", "俄罗斯方块"]):
        return (
            f"「{name}」像俄罗斯方块。核心是方块生成、旋转、消行和计分。",
            [
                _opt("h5", "网页版俄罗斯方块", f"做「{name}」网页俄罗斯方块，先出可玩原型。", "最快"),
                _opt("godot", "Godot 2D", f"用 Godot 4 做「{name}」俄罗斯方块。", "客户端"),
            ],
        )

    if _has_any(text, ["fps", "射击", "first person", "第一人称"]):
        return (
            f"「{name}」偏射击/FPS{desc_hint}。先定引擎，再做移动和开火。",
            [
                _opt("ue", "UE5 第一人称", f"用 UE5 做「{name}」FPS，先出移动、开火、简单关卡。", "3D 品质"),
                _opt("godot", "Godot 3D 射击", f"用 Godot 4 做「{name}」射击原型。", "更轻"),
                _opt("design", "先写玩法策划", f"先给「{name}」写一页射击玩法策划（核心循环、武器、关卡），确认后再开工。", "先对齐"),
            ],
        )

    if _has_any(text, ["rpg", "角色扮演", "回合"]):
        return (
            f"「{name}」偏 RPG{desc_hint}。建议先定最小可玩循环，而不是一次性做完整世界观。",
            [
                _opt("combat", "先做战斗原型", f"「{name}」先做最小战斗循环（角色、敌人、胜负），不做大地图。", "验证手感"),
                _opt("design", "先写设定与需求", f"先整理「{name}」的世界观、职业和第一章需求列表，确认后再开发。", "先对齐"),
                _opt("web", "网页 Demo", f"用网页先做「{name}」的对话/战斗 Demo，验证循环。", "最快"),
            ],
        )

    if _has_any(text, ["shop", "商城", "电商", "购物"]):
        return (
            f"「{name}」偏电商/商城{desc_hint}。建议先做商品列表 + 下单闭环。",
            [
                _opt("web", "网页商城原型", f"做「{name}」网页商城：商品列表、详情、购物车、下单页。先出可点原型。", "最快"),
                _opt("wechat", "微信小程序商城", f"把「{name}」做成微信小程序商城，先出商品和下单。", "微信生态"),
                _opt("admin", "先做后台", f"「{name}」先做商品/订单管理后台，前台稍后。", "运营向"),
            ],
        )

    if _has_any(text, ["blog", "博客", "cms", "内容"]):
        return (
            f"「{name}」偏内容站/博客{desc_hint}。",
            [
                _opt("web", "博客站点", f"做「{name}」博客：文章列表、详情、发布。先出可浏览原型。", "最快"),
                _opt("admin", "先做编辑后台", f"「{name}」先做文章编辑和发布后台。", "内容运营"),
            ],
        )

    if is_game:
        if engine.startswith("godot"):
            return (
                f"「{name}」是游戏，已标 Godot{desc_hint}。建议先出最小可玩关卡。",
                [
                    _opt("playable", "先出可玩原型", f"用 Godot 做「{name}」最小可玩原型：一个场景、一套核心操作、胜负条件。", "推荐"),
                    _opt("design", "先写玩法策划", f"先给「{name}」写核心循环和关卡策划，确认后再进编辑器。", "先对齐"),
                ],
            )
        if engine in ("none", "") and (platform == "web" or _has_any(text, ["html", "h5", "网页"])):
            return (
                f"「{name}」像网页游戏{desc_hint}。建议 HTML5 先出可玩原型。",
                [
                    _opt("h5", "HTML5 可玩原型", f"用网页做「{name}」可玩原型，先验证核心玩法。", "最快"),
                    _opt("godot", "改用 Godot 2D", f"「{name}」改用 Godot 4 做 2D 客户端，先出可玩关卡。", "后续更好扩"),
                    _opt("design", "先写玩法策划", f"先给「{name}」写一页玩法策划，确认后再开发。", "先对齐"),
                ],
            )
        return (
            f"「{name}」是游戏项目{desc_hint}。还没完全定载体，先选一条路。",
            [
                _opt("h5", "网页可玩原型", f"用网页先做「{name}」核心玩法原型。", "最快验证"),
                _opt("godot", "Godot 2D/3D", f"用 Godot 4 做「{name}」，先出最小可玩关卡。", "独立游戏常用"),
                _opt("design", "先写策划再开工", f"先给「{name}」写核心循环、目标和第一关，确认后再开发。", "先对齐"),
            ],
        )

    if "platform:wechat" in traits or _has_any(text, ["小程序", "wechat", "微信"]):
        return (
            f"「{name}」偏微信小程序{desc_hint}。建议先做首页 + 一个核心流程。",
            [
                _opt("mvp", "小程序 MVP", f"做「{name}」微信小程序：首页和一个核心流程，先能点通。", "推荐"),
                _opt("design", "先列页面和需求", f"先列出「{name}」的页面结构和前 3 条需求，确认后再开发。", "先对齐"),
            ],
        )

    if "platform:web" in traits or category == "app" or _has_any(text, ["web", "网站", "网页", "系统", "平台"]):
        return (
            f"「{name}」偏网页应用{desc_hint}。建议先做主流程，而不是一次做完全部后台。",
            [
                _opt("mvp", "先做主流程原型", f"做「{name}」网页 MVP：核心页面和主流程先能走通。", "推荐"),
                _opt("req", "先拆第一条需求", f"根据「{name}」{desc_hint} 拆出第一条可开发需求，创建工单。", "走工单流"),
                _opt("design", "先写功能清单", f"先给「{name}」列功能清单和页面结构，确认后再开发。", "先对齐"),
            ],
        )

    trait_line = "、".join(traits) if traits else "尚未标注类型"
    return (
        f"项目「{name}」已创建（{trait_line}）{desc_hint}。我还不能 100% 锁定形态，请选一个起步方式。",
        [
            _opt("mvp", "先做最小可用原型", f"根据「{name}」{desc_hint} 先做最小可用原型，验证主流程。", "推荐"),
            _opt("req", "先创建第一条需求", f"帮「{name}」分析并创建第一条开发需求。", "走工单流"),
            _opt("design", "先讨论方向再开工", f"先根据「{name}」讨论 2-3 个可行方向和取舍，我选定后再开发。", "先对齐"),
        ],
    )


async def persist_project_icebreak(
    project_id: str,
    name: str,
    description: str = "",
    traits: Optional[List[str]] = None,
    tech_stack: str = "",
) -> Dict[str, Any]:
    """把破冰消息写入项目会话，刷新后能直接看到。"""
    from api.chat import _save_chat_message
    from database import db
    from utils import generate_id, now_iso

    payload = build_icebreak_payload(name, description, traits, tech_stack)
    session_id = generate_id("sess-")
    intro = (
        f"项目「{payload['project_name']}」已就绪。{payload['analysis']}\n"
        "请选一个方向，我会据此创建第一个需求。"
    )
    await _save_chat_message(
        project_id=project_id,
        role="assistant",
        content=intro,
        action=payload,
        session_id=session_id,
    )
    try:
        await db.update(
            "chat_sessions",
            {"title": f"破冰 · {payload['project_name']}", "updated_at": now_iso()},
            "id = ?",
            (session_id,),
        )
    except Exception:
        pass
    return {
        "type": "propose_icebreak",
        "project_id": project_id,
        "session_id": session_id,
        "persisted": True,
        "reason": "新建项目破冰：方向卡片已写入项目聊天",
    }
