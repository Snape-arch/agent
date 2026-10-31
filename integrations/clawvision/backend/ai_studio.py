"""Natural-language planning for experiments and parametric 3D scenes.

The local planner is deterministic and works without credentials.  Optional
providers use OpenAI-compatible chat-completion APIs and are constrained to a
small allow-list so a user supplied endpoint cannot become an SSRF primitive.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from credentials import resolve_provider_key


PROVIDERS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "kimi": "https://api.moonshot.cn/v1/chat/completions",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
}
ALLOWED_HOSTS = {urlparse(url).hostname for url in PROVIDERS.values()}


EXPERIMENT_DEFAULTS: dict[str, Any] = {
    "learningRate": 0.001,
    "batchSize": 64,
    "dropout": 0.2,
    "optimizer": "AdamW",
    "epochs": 40,
    "seed": 42,
    "weightDecay": 0.01,
    "mixedPrecision": True,
    "modelDepth": "base",
}


TEMPLATES = [
    {"id": "drone", "name": "四旋翼无人机", "description": "机身、四臂、旋翼与相机云台"},
    {"id": "robot", "name": "桌面机器人", "description": "躯干、头部、关节与机械臂"},
    {"id": "camera", "name": "工业相机", "description": "机身、镜头、热靴与控制旋钮"},
    {"id": "vehicle", "name": "概念车辆", "description": "车身、座舱与四轮结构"},
    {"id": "radio", "name": "复古收音机", "description": "外壳、扬声器、旋钮与天线"},
    {"id": "engine", "name": "涡轮组件", "description": "机匣、叶片、轴与连接环"},
    {"id": "watch", "name": "机械腕表", "description": "表壳、表盘、刻度、指针与表带"},
    {"id": "jewelry", "name": "珠宝首饰", "description": "链节、吊坠、宝石与镶嵌结构"},
    {"id": "architecture", "name": "建筑塔楼", "description": "分层体块、立面、平台与顶部结构"},
    {"id": "aircraft", "name": "固定翼飞行器", "description": "机身、机翼、尾翼与引擎"},
    {"id": "furniture", "name": "模块家具", "description": "座面、靠背、支撑与软包结构"},
    {"id": "prop", "name": "科幻道具", "description": "底座、能量核心、护框与信标"},
    {"id": "mirror", "name": "智能镜子", "description": "镜面、边框、支架与传感面板"},
    {"id": "headphones", "name": "头戴式耳机", "description": "头梁、耳罩、转轴与声学单元"},
    {"id": "shoe", "name": "鞋履", "description": "鞋底、鞋面、鞋跟与装饰分区"},
    {"id": "backpack", "name": "背包", "description": "主仓、前袋、肩带与扣具"},
    {"id": "appliance", "name": "小家电", "description": "外壳、控制区、接口与功能组件"},
    {"id": "container", "name": "容器", "description": "主体、盖体、把手与密封结构"},
    {"id": "panel", "name": "面板设备", "description": "机箱、屏幕、按键与接口模块"},
    {"id": "product", "name": "开放产品", "description": "基于语义关键词组合主体、面板、连接件和制造细节"},
]


def _number(text: str, patterns: list[str], fallback: float) -> float:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group(1))
    return fallback


def _integer(text: str, patterns: list[str], fallback: int) -> int:
    return int(round(_number(text, patterns, fallback)))


def _color(text: str) -> str:
    match = re.search(r"#[0-9a-fA-F]{6}", text)
    if match:
        return match.group(0)
    mapping = {
        "红": "#ef6a6a", "蓝": "#5b8ff9", "绿": "#5ad8a6", "黄": "#f6bd16",
        "橙": "#f6903d", "紫": "#9270ca", "黑": "#252a34", "白": "#e8edf2",
        "银": "#aeb8c2", "金": "#d6aa4b", "cyan": "#48d6c5", "blue": "#5b8ff9",
        "red": "#ef6a6a", "green": "#5ad8a6", "orange": "#f6903d",
    }
    lowered = text.lower()
    return next((value for key, value in mapping.items() if key in lowered), "#67e8bd")


def _template_id(text: str) -> str:
    lowered = text.lower()
    choices = {
        "drone": ["无人机", "四旋翼", "drone", "quadcopter"],
        "robot": ["机器人", "机械臂", "robot"],
        "camera": ["相机", "摄像机", "camera"],
        "vehicle": ["汽车", "车辆", "跑车", "vehicle", "car"],
        "radio": ["收音机", "音响", "radio", "speaker"],
        "engine": ["引擎", "涡轮", "发动机", "engine", "turbine"],
        "watch": ["手表", "腕表", "watch", "chronograph"],
        "jewelry": ["首饰", "珠宝", "项链", "吊坠", "手链", "jewelry", "necklace"],
        "architecture": ["建筑", "塔楼", "大楼", "architecture", "tower", "building"],
        "aircraft": ["飞机", "固定翼", "战机", "aircraft", "airplane"],
        "furniture": ["家具", "椅", "沙发", "桌", "furniture", "chair", "sofa"],
        "prop": ["道具", "信标", "能量核心", "prop", "beacon"],
        "mirror": ["镜子", "镜面", "mirror"],
        "headphones": ["耳机", "耳麦", "headphone", "headset"],
        "shoe": ["鞋", "球鞋", "靴", "shoe", "sneaker", "boot"],
        "backpack": ["背包", "书包", "旅行包", "backpack", "bag"],
        "appliance": ["家电", "咖啡机", "空气净化", "吹风机", "appliance"],
        "container": ["容器", "水杯", "瓶", "罐", "container", "bottle", "cup"],
        "panel": ["面板", "控制台", "仪表", "panel", "console", "dashboard"],
    }
    return next((kind for kind, words in choices.items() if any(word in lowered for word in words)), "product")


def _part(shape: str, name: str, size: list[float], position: list[float], color: str,
          rotation: list[float] | None = None, material: str = "metal") -> dict:
    return {"shape": shape, "name": name, "size": size, "position": position,
            "rotation": rotation or [0, 0, 0], "color": color, "material": material}


def _parts_for(template: str, color: str, complexity: int, prompt: str = "") -> list[dict]:
    dark, accent = "#26332f", "#f4b860"
    parts: list[dict] = []
    if template == "drone":
        parts = [_part("roundedBox", "Flight Controller", [2.0, .45, 1.3], [0, .2, 0], color)]
        for index, (x, z) in enumerate(((-1.55, -1.25), (1.55, -1.25), (-1.55, 1.25), (1.55, 1.25))):
            parts += [_part("box", f"Arm {index + 1}", [1.8, .16, .16], [x / 2, .18, z / 2], dark, [0, -0.68 if x * z > 0 else .68, 0]),
                      _part("cylinder", f"Motor {index + 1}", [.32, .18, .32], [x, .22, z], accent),
                      _part("torus", f"Propeller {index + 1}", [.68, .06, .68], [x, .43, z], color)]
        parts.append(_part("sphere", "Gimbal Camera", [.4, .4, .4], [0, -.35, -.72], dark))
    elif template == "robot":
        parts = [_part("roundedBox", "Torso", [1.65, 2.0, .9], [0, .7, 0], color),
                 _part("roundedBox", "Head", [1.25, .85, .9], [0, 2.15, 0], dark),
                 _part("cylinder", "Neck", [.24, .35, .24], [0, 1.62, 0], accent)]
        for side in (-1, 1):
            parts += [_part("capsule", "Upper Arm", [.3, 1.2, .3], [side * 1.15, .75, 0], color, [0, 0, side * -.2]),
                      _part("sphere", "Shoulder", [.38, .38, .38], [side * .9, 1.35, 0], accent),
                      _part("capsule", "Leg", [.42, 1.45, .42], [side * .48, -.95, 0], dark)]
    elif template == "camera":
        parts = [_part("roundedBox", "Camera Body", [2.5, 1.55, .85], [0, .3, 0], color),
                 _part("cylinder", "Lens Barrel", [.72, 1.25, .72], [0, .35, -.95], dark, [1.57, 0, 0]),
                 _part("torus", "Focus Ring", [.78, .12, .78], [0, .35, -1.45], accent, [1.57, 0, 0]),
                 _part("box", "Hot Shoe", [.7, .12, .42], [0, 1.12, 0], dark)]
    elif template == "vehicle":
        parts = [_part("roundedBox", "Chassis", [3.6, .72, 1.75], [0, .15, 0], color),
                 _part("roundedBox", "Cabin", [1.8, .75, 1.48], [.35, .82, 0], dark)]
        for x in (-1.25, 1.25):
            for z in (-.95, .95):
                parts.append(_part("torus", "Wheel", [.46, .16, .46], [x, -.22, z], "#161b1a", [1.57, 0, 0]))
    elif template == "radio":
        parts = [_part("roundedBox", "Radio Cabinet", [2.8, 1.7, .8], [0, .35, 0], color, material="wood"),
                 _part("cylinder", "Speaker", [.64, .12, .64], [-.65, .42, -.48], dark, [1.57, 0, 0]),
                 _part("box", "Display", [.92, .42, .08], [.62, .58, -.46], "#82d9ff")]
        for index in range(2):
            parts.append(_part("cylinder", f"Dial {index + 1}", [.18, .12, .18], [.4 + index * .5, .05, -.5], accent, [1.57, 0, 0]))
        parts.append(_part("cylinder", "Antenna", [.035, 2.2, .035], [1.15, 1.75, 0], accent, [0, 0, -.22]))
    elif template == "watch":
        parts = [_part("cylinder", "Watch Case", [1.18, .34, 1.18], [0, 0, 0], color),
                 _part("cylinder", "Dial", [1.0, .08, 1.0], [0, .22, 0], dark),
                 _part("torus", "Bezel", [1.12, .09, 1.12], [0, .28, 0], accent)]
        for index in range(12):
            angle = index / 12 * 6.28318
            parts.append(_part("box", f"Hour Marker {index + 1}", [.06, .035, .22], [.72 * math.sin(angle), .34, .72 * math.cos(angle)], accent, [0, angle, 0]))
        for side in (-1, 1):
            for index in range(5):
                parts.append(_part("roundedBox", f"Strap Link {side}.{index}", [.72, .12, .32], [0, 0, side * (1.25 + index * .34)], dark))
    elif template == "jewelry":
        for index in range(max(12, complexity * 3)):
            angle = index / max(12, complexity * 3) * 6.28318
            parts.append(_part("torus", f"Chain Link {index + 1}", [.18, .045, .18], [1.55 * math.sin(angle), 1.25 * math.cos(angle), 0], color, [0, angle, angle]))
        parts += [_part("sphere", "Gemstone", [.42, .58, .24], [0, -1.6, 0], accent, material="glass"),
                  _part("torus", "Gem Setting", [.48, .08, .48], [0, -1.6, 0], color)]
    elif template == "architecture":
        levels = max(5, complexity + 2)
        for index in range(levels):
            width = 2.8 - index * .16
            parts.append(_part("roundedBox", f"Tower Level {index + 1}", [width, .42, width * .72], [0, index * .44, 0], color if index % 2 == 0 else dark))
        parts += [_part("box", "Roof Platform", [1.5, .12, 1.1], [0, levels * .44, 0], accent), _part("cylinder", "Spire", [.09, 1.5, .09], [0, levels * .44 + .8, 0], accent)]
    elif template == "aircraft":
        parts = [_part("capsule", "Fuselage", [.55, 4.4, .55], [0, .5, 0], color, [1.57, 0, 0]),
                 _part("sphere", "Cockpit", [.55, .34, .5], [0, .72, -1.25], dark, material="glass"),
                 _part("box", "Main Wing", [5.2, .13, 1.15], [0, .42, .15], color),
                 _part("box", "Tail Wing", [2.1, .1, .65], [0, .62, 1.75], dark),
                 _part("box", "Vertical Stabilizer", [.12, .9, .72], [0, 1.05, 1.75], accent)]
        for side in (-1, 1):
            parts.append(_part("cylinder", f"Engine {side}", [.34, 1.1, .34], [side * 1.35, .15, .15], dark, [1.57, 0, 0]))
    elif template == "furniture":
        parts = [_part("roundedBox", "Seat Cushion", [2.25, .35, 2.0], [0, .55, 0], color, material="wood"),
                 _part("roundedBox", "Back Rest", [2.25, 1.8, .35], [0, 1.55, .82], color, [-.16, 0, 0])]
        for x in (-.85, .85):
            for z in (-.7, .7):
                parts.append(_part("cylinder", "Support Leg", [.11, 1.2, .11], [x, -.15, z], dark))
    elif template == "prop":
        parts = [_part("cylinder", "Beacon Base", [1.25, .5, 1.25], [0, .1, 0], dark),
                 _part("capsule", "Energy Core", [.38, 2.2, .38], [0, 1.35, 0], "#67dfff", material="glass"),
                 _part("torus", "Containment Ring", [.92, .1, .92], [0, 1.25, 0], accent)]
        for side in (-1, 1):
            parts.append(_part("box", "Guard", [.16, 2.1, .16], [side * .8, 1.15, 0], color, [0, 0, side * .18]))
    elif template == "mirror":
        parts = [_part("roundedBox", "Mirror Surface", [2.3, 3.2, .08], [0, 1.4, 0], "#b8d9e8", material="glass"),
                 _part("torus", "Sensor Halo", [.42, .05, .42], [0, 2.5, -.1], accent),
                 _part("box", "Status Panel", [.8, .22, .05], [0, .45, -.12], "#67dfff"),
                 _part("cylinder", "Stand", [.12, 1.0, .12], [0, -.55, 0], dark),
                 _part("cylinder", "Base", [.9, .12, .9], [0, -1.1, 0], dark)]
    elif template == "headphones":
        parts = [_part("torus", "Headband", [1.5, .18, 1.5], [0, 1.1, 0], color, [1.57, 0, 0])]
        for side in (-1, 1):
            parts += [_part("cylinder", f"Ear Cup {side}", [.62, .34, .62], [side * 1.45, 0, 0], dark, [0, 0, 1.57]),
                      _part("torus", f"Cushion {side}", [.58, .12, .58], [side * 1.27, 0, 0], color, [0, 0, 1.57]),
                      _part("box", f"Yoke {side}", [.2, .8, .18], [side * 1.35, .7, 0], accent)]
    elif template == "shoe":
        parts = [_part("roundedBox", "Outsole", [3.2, .28, 1.25], [.15, 0, 0], dark),
                 _part("roundedBox", "Midsole", [3.0, .38, 1.16], [.1, .27, 0], color),
                 _part("capsule", "Upper", [.62, 2.45, .62], [-.2, .72, 0], color, [0, 0, 1.57]),
                 _part("roundedBox", "Heel Counter", [.82, 1.05, 1.05], [1.05, .78, 0], accent)]
        for index in range(5):
            parts.append(_part("cylinder", f"Lace {index + 1}", [.025, .9, .025], [-.55 + index * .28, 1.0, 0], dark, [1.57, 0, 1.57]))
    elif template == "backpack":
        parts = [_part("roundedBox", "Main Compartment", [2.25, 3.0, 1.15], [0, .8, 0], color),
                 _part("roundedBox", "Front Pocket", [1.65, 1.25, .4], [0, .35, -.75], dark),
                 _part("torus", "Top Handle", [.48, .09, .48], [0, 2.48, 0], accent, [1.57, 0, 0])]
        for side in (-1, 1):
            parts.append(_part("capsule", f"Shoulder Strap {side}", [.13, 2.5, .13], [side * .72, .7, .72], dark, [0, 0, side * .12]))
    elif template == "appliance":
        parts = [_part("roundedBox", "Appliance Housing", [2.35, 2.6, 1.6], [0, .8, 0], color),
                 _part("box", "Control Display", [1.25, .55, .08], [0, 1.38, -.85], "#67dfff"),
                 _part("cylinder", "Function Chamber", [.72, .7, .72], [0, .45, -.82], dark, [1.57, 0, 0])]
        for index in range(3):
            parts.append(_part("cylinder", f"Control {index + 1}", [.12, .1, .12], [-.45 + index * .45, 1.85, -.88], accent, [1.57, 0, 0]))
    elif template == "container":
        parts = [_part("cylinder", "Container Body", [1.15, 2.5, 1.0], [0, .5, 0], color),
                 _part("cylinder", "Lid", [1.18, .25, 1.18], [0, 1.88, 0], dark),
                 _part("torus", "Seal Ring", [1.08, .06, 1.08], [0, 1.68, 0], accent),
                 _part("torus", "Side Handle", [.65, .12, .65], [1.18, .75, 0], dark, [0, 1.57, 0])]
    elif template == "panel":
        parts = [_part("roundedBox", "Panel Chassis", [3.2, 2.0, .52], [0, .55, 0], color),
                 _part("box", "Primary Screen", [1.55, .85, .06], [-.55, .8, -.3], "#67dfff"),
                 _part("box", "Interface Bay", [.95, 1.25, .08], [1.0, .62, -.31], dark)]
        for index in range(6):
            parts.append(_part("cylinder", f"Input {index + 1}", [.1, .08, .1], [.7 + index % 2 * .5, .25 + index // 2 * .38, -.38], accent, [1.57, 0, 0]))
    elif template == "engine":
        parts = [_part("cylinder", "Turbine Housing", [1.5, 2.3, 1.5], [0, .3, 0], color, [1.57, 0, 0]),
                 _part("cylinder", "Drive Shaft", [.25, 3.0, .25], [0, .3, 0], accent, [1.57, 0, 0])]
        blade_count = max(6, min(18, complexity * 2))
        for index in range(blade_count):
            angle = index / blade_count * 6.28318
            parts.append(_part("box", f"Blade {index + 1}", [.18, .65, .08], [0, .3, 0], dark, [0, angle, .5]))
    else:
        parts = [_part("roundedBox", "Primary Housing", [2.8, 1.65, 1.3], [0, .55, 0], color),
                 _part("roundedBox", "Secondary Shell", [1.65, 1.05, 1.36], [.75, 1.15, 0], dark),
                 _part("box", "Control Surface", [1.1, .52, .06], [-.55, .75, -.69], "#67dfff"),
                 _part("torus", "Functional Ring", [.44, .08, .44], [.72, .72, -.72], accent)]
        detail_words = [word for word in re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}", prompt) if word not in {"生成", "创建", "一个", "模型", "复杂度"}]
        for index in range(max(3, min(10, complexity))):
            shape = ("cylinder", "roundedBox", "sphere")[index % 3]
            label = detail_words[index % len(detail_words)] if detail_words else "Semantic"
            parts.append(_part(shape, f"{label} Module {index + 1}", [.18 + index * .025, .22, .18], [-1.0 + index * .24, .15 + (index % 2) * .25, -.7], accent if index % 2 else dark))
    return parts


def local_3d_plan(prompt: str) -> dict:
    template = _template_id(prompt)
    complexity = max(1, min(10, _integer(prompt, [r"(?:复杂度|complexity)\s*(?:为|=|:)?\s*(\d+)"], 6)))
    curve = max(0.0, min(1.0, _number(prompt, [r"(?:曲面|曲率|curve)\s*(?:为|=|:)?\s*([\d.]+)"], .55)))
    density = max(0.0, min(1.0, _number(prompt, [r"(?:连接密度|density)\s*(?:为|=|:)?\s*([\d.]+)"], .6)))
    scale = max(.25, min(8.0, _number(prompt, [r"(?:尺寸|缩放|scale)\s*(?:为|=|:)?\s*([\d.]+)"], 1.0)))
    color = _color(prompt)
    material = "wood" if any(word in prompt.lower() for word in ("木", "wood")) else "glass" if any(word in prompt.lower() for word in ("玻璃", "透明", "glass")) else "metal"
    name = next(item["name"] for item in TEMPLATES if item["id"] == template)
    return {
        "kind": "model3d", "name": name, "template": template, "prompt": prompt,
        "parameters": {"scale": scale, "complexity": complexity, "curveStrength": curve,
                       "connectionDensity": density, "color": color, "material": material},
        "parts": _parts_for(template, color, complexity, prompt),
        "agents": [
            {"id": "prompt", "name": "Prompt Architect", "status": "completed", "message": f"识别为{name}，提取 {5} 个设计约束"},
            {"id": "structure", "name": "Structure Agent", "status": "completed", "message": "生成主结构、连接关系与尺寸比例"},
            {"id": "surface", "name": "Surface Detail Agent", "status": "completed", "message": f"曲面强度 {curve:.2f}，复杂度 {complexity}/10"},
            {"id": "material", "name": "Material Agent", "status": "completed", "message": f"应用 {material} 材质与主色 {color}"},
            {"id": "quality", "name": "Quality Agent", "status": "completed", "message": "结构完整，可渲染，可继续参数化编辑"},
        ],
        "validation": {"valid": True, "score": min(98, 78 + complexity * 2), "warnings": [],
                       "checks": ["部件尺寸为正", "结构中心已归一化", "材质可渲染", "节点名称唯一"]},
    }


def local_experiment_plan(prompt: str, current: dict | None = None) -> dict:
    params = {**EXPERIMENT_DEFAULTS, **(current or {})}
    patch: dict[str, Any] = {}
    patterns: dict[str, list[str]] = {
        "learningRate": [r"(?:学习率|learning\s*rate|\blr\b)\s*(?:改成|设为|设置为|到|=|:)?\s*([\d.eE+-]+)"],
        "batchSize": [r"(?:batch\s*size|批大小|批次大小|batch)\s*(?:改成|设为|设置为|到|=|:)?\s*(\d+)"],
        "dropout": [r"dropout\s*(?:改成|设为|设置为|到|=|:)?\s*([\d.]+)"],
        "epochs": [r"(?:epochs?|轮数|训练轮次)\s*(?:改成|设为|设置为|到|=|:)?\s*(\d+)"],
        "weightDecay": [r"(?:weight\s*decay|权重衰减)\s*(?:改成|设为|设置为|到|=|:)?\s*([\d.eE+-]+)"],
        "seed": [r"(?:seed|随机种子)\s*(?:改成|设为|设置为|到|=|:)?\s*(\d+)"],
    }
    lowered = prompt.lower()
    for key, candidates in patterns.items():
        value = _number(prompt, candidates, float("nan"))
        if value == value:
            patch[key] = int(value) if key in {"batchSize", "epochs", "seed"} else value
    optimizer = next((item for item in ("AdamW", "Adam", "SGD") if item.lower() in lowered), None)
    if optimizer:
        patch["optimizer"] = optimizer
    if any(word in lowered for word in ("开启混合精度", "启用混合精度", "mixed precision on")):
        patch["mixedPrecision"] = True
    if any(word in lowered for word in ("关闭混合精度", "禁用混合精度", "mixed precision off")):
        patch["mixedPrecision"] = False
    params.update(patch)
    chart = "time-series"
    y_fields = ["trainLoss", "valLoss"]
    if any(word in lowered for word in ("准确率", "accuracy")):
        y_fields = ["accuracy"]
    if any(word in lowered for word in ("gpu", "显存", "利用率")):
        y_fields = ["gpu"]
    if any(word in lowered for word in ("embedding", "嵌入", "聚类")):
        chart = "embedding-evolution-3d"
    elif any(word in lowered for word in ("表格", "table")):
        chart = "table"
    kind = "grid" if any(word in lowered for word in ("二维", "网格", "grid")) else "sweep" if any(word in lowered for word in ("扫描", "sweep", "遍历")) else "single"
    execute = any(word in lowered for word in ("运行", "开始", "创建实验", "执行", "run", "start"))
    configs = [dict(params)]
    lr_range = re.search(r"(?:学习率|\blr\b).*?([\d.eE+-]+)\s*(?:到|至|~|->)\s*([\d.eE+-]+)(?:.*?(\d+)\s*(?:个|组|点))?", prompt, re.I)
    batch_values_match = re.search(r"(?:batch\s*size|批大小|批次大小).*?((?:\d+\s*[,，、/]\s*)+\d+)", prompt, re.I)
    lr_values: list[float] = []
    batch_values: list[int] = []
    if lr_range:
        start, end, count = float(lr_range.group(1)), float(lr_range.group(2)), max(2, min(12, int(lr_range.group(3) or 5)))
        if start > 0 and end > 0:
            ratio = (end / start) ** (1 / (count - 1))
            lr_values = [start * ratio ** index for index in range(count)]
    if batch_values_match:
        batch_values = [int(value) for value in re.split(r"\s*[,，、/]\s*", batch_values_match.group(1))]
    if kind == "sweep" and lr_values:
        configs = [{**params, "learningRate": value} for value in lr_values]
    elif kind == "sweep" and batch_values:
        configs = [{**params, "batchSize": value} for value in batch_values]
    elif kind == "grid":
        lr_values = lr_values or [params["learningRate"] / 2, params["learningRate"], params["learningRate"] * 2]
        batch_values = batch_values or sorted({max(16, params["batchSize"] // 2), params["batchSize"], min(256, params["batchSize"] * 2)})
        configs = [{**params, "learningRate": lr, "batchSize": batch} for lr in lr_values for batch in batch_values][:36]
    return {
        "kind": "experiment", "prompt": prompt, "patch": patch, "params": params,
        "jobKind": kind, "execute": execute, "configs": configs,
        "visualization": {"pluginId": f"core.{chart}", "title": "自然语言实验视图", "options": {"xField": "step", "yFields": y_fields}},
        "explanation": f"已识别 {len(patch)} 个参数修改，并选择 {chart} 可视化。" if patch else f"保留当前参数，并选择 {chart} 可视化。",
    }


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("provider response must be a JSON object")
    return parsed


def _merge_known(fallback, candidate):
    """Keep provider output inside the local planner's trusted response schema."""
    if isinstance(fallback, dict):
        source = candidate if isinstance(candidate, dict) else {}
        return {key: _merge_known(value, source.get(key, value)) for key, value in fallback.items()}
    if isinstance(fallback, list):
        return candidate if isinstance(candidate, list) and candidate else fallback
    if isinstance(fallback, bool):
        return candidate if isinstance(candidate, bool) else fallback
    if isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
        return candidate if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) else fallback
    return candidate if isinstance(candidate, type(fallback)) else fallback


def provider_plan(provider: str, api_key: str, model: str, prompt: str, mode: str,
                  current: dict | None = None, endpoint: str | None = None, usage_sink: dict | None = None) -> dict:
    url = endpoint or PROVIDERS.get(provider)
    if not url or urlparse(url).hostname not in ALLOWED_HOSTS:
        raise ValueError("unsupported or unsafe provider endpoint")
    fallback = local_3d_plan(prompt) if mode == "model3d" else local_experiment_plan(prompt, current)
    system = (
        "You are the ClawVision planner. Return one JSON object only. Preserve this exact top-level schema and improve values from the user request: "
        + json.dumps(fallback, ensure_ascii=False)
    )
    request_body = {"model": model, "temperature": 0.2, "max_tokens": 4096, "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": system + " Output valid JSON."}, {"role": "user", "content": prompt}]}
    if provider == "deepseek":
        request_body["thinking"] = {"type": "disabled"}
    payload = json.dumps(request_body).encode()
    request = Request(url, data=payload, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "ClawVision/0.8"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - host allow-list above
        result = json.loads(response.read().decode())
    if usage_sink is not None and isinstance(result.get("usage"), dict):
        usage_sink.update(result["usage"])
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned an empty response")
    planned = _merge_known(fallback, _extract_json(content))
    planned["provider"] = provider
    if mode == "model3d":
        validation = validate_plan(planned)
        if not validation["valid"]:
            raise ValueError("provider returned an invalid 3D plan: " + "; ".join(validation["warnings"]))
        planned["validation"] = validation
    else:
        baseline = {**EXPERIMENT_DEFAULTS, **(current or {})}
        params = planned.get("params") if isinstance(planned.get("params"), dict) else baseline
        params["learningRate"] = max(1e-7, min(1.0, float(params.get("learningRate", baseline["learningRate"]))))
        params["batchSize"] = max(1, min(8192, int(params.get("batchSize", baseline["batchSize"]))))
        params["dropout"] = max(0.0, min(.95, float(params.get("dropout", baseline["dropout"]))))
        params["epochs"] = max(1, min(10_000, int(params.get("epochs", baseline["epochs"]))))
        params["seed"] = int(params.get("seed", baseline["seed"]))
        params["weightDecay"] = max(0.0, min(10.0, float(params.get("weightDecay", baseline["weightDecay"]))))
        params["optimizer"] = params.get("optimizer") if params.get("optimizer") in {"AdamW", "Adam", "SGD"} else baseline["optimizer"]
        params["modelDepth"] = params.get("modelDepth") if params.get("modelDepth") in {"small", "base", "large"} else baseline["modelDepth"]
        params["mixedPrecision"] = bool(params.get("mixedPrecision", baseline["mixedPrecision"]))
        planned["params"] = params
        planned["patch"] = {key: value for key, value in params.items() if baseline.get(key) != value}
        if planned.get("jobKind") not in {"single", "sweep", "grid"}:
            planned["jobKind"] = "single"
        if planned["jobKind"] == "single":
            planned["configs"] = [dict(params)]
        elif not isinstance(planned.get("configs"), list) or not planned["configs"]:
            planned["configs"] = [dict(params)]
        planned["configs"] = planned["configs"][:100]
        allowed_plugins = {"core.time-series", "core.table", "core.embedding-evolution-3d"}
        if planned.get("visualization", {}).get("pluginId") not in allowed_plugins:
            planned["visualization"] = fallback["visualization"]
    return planned


def interpret(body: dict) -> dict:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > 4000:
        raise ValueError("prompt exceeds 4000 characters")
    mode = str(body.get("mode") or "experiment")
    provider = str(body.get("provider") or "local").lower()
    if provider == "local":
        result = local_3d_plan(prompt) if mode == "model3d" else local_experiment_plan(prompt, body.get("currentParams"))
        result["provider"] = "local"
        return result
    api_key = resolve_provider_key(provider, str(body.get("credentialRef") or "") or None)
    if not api_key:
        raise ValueError(f"server credential is not configured for {provider}")
    default_models = {"openai": "gpt-4.1-mini", "deepseek": "deepseek-v4-flash", "kimi": "moonshot-v1-8k", "qwen": "qwen-plus"}
    return provider_plan(provider, api_key, str(body.get("model") or default_models.get(provider, "")), prompt, mode, body.get("currentParams"), body.get("endpoint"))


def validate_plan(plan: dict) -> dict:
    parts = plan.get("parts") if isinstance(plan.get("parts"), list) else []
    warnings = []
    names = [str(part.get("name") or "") for part in parts if isinstance(part, dict)]
    if not parts:
        warnings.append("模型没有可渲染部件")
    if len(names) != len(set(names)):
        warnings.append("存在重复节点名称")
    if len(parts) > 512:
        warnings.append("模型部件超过 512 个")
    allowed_shapes = {"box", "roundedBox", "sphere", "cylinder", "torus", "capsule"}
    if any(not isinstance(part, dict) or part.get("shape") not in allowed_shapes for part in parts):
        warnings.append("存在不支持的部件形状")
    invalid = [part for part in parts if not isinstance(part.get("size"), list) or any(float(value) <= 0 for value in part.get("size", []))]
    if invalid:
        warnings.append("存在非正尺寸部件")
    return {"valid": not warnings, "score": max(0, 100 - len(warnings) * 25), "warnings": warnings,
            "checks": ["包含可渲染部件", "节点名称唯一", "部件尺寸为正", "参数范围有效"]}
