"""MCP resources, resource templates, prompts, and completions for Xianyu."""

import json
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    PromptReference,
    Resource,
    ResourceTemplate,
    ResourceTemplateReference,
    TextContent,
)

from xianyu_mcp.logging import get_logger
from xianyu_mcp.mcp.tools.account_tools import check_login_status
from xianyu_mcp.mcp.tools.ai_tools import build_analysis_prompt
from xianyu_mcp.mcp.tools.goods_tools import (
    get_favorites,
    get_goods_detail,
    get_home_goods,
    search_goods,
)
from xianyu_mcp.mcp.tools.sale_tools import get_my_goods
from xianyu_mcp.mcp.tools.seller_tools import get_seller_profile

logger = get_logger("context_features")

RESOURCE_SCHEME = "xianyu"
PROMPT_ANALYZE_GOODS = "analyze_goods"

SORT_FIELDS = ["create", "modify", "credit", "reduce", "price"]
SORT_VALUES = ["asc", "desc", "credit_desc"]
MY_GOODS_STATUS = ["selling", "sold", "taken_down"]


def list_resources_definitions() -> list[Resource]:
    """Return static resources that are directly readable without arguments."""
    return [
        Resource(
            name="login_status",
            title="Login Status",
            uri="xianyu://account/login-status",
            description="当前账号登录状态。",
            mimeType="application/json",
        ),
        Resource(
            name="home_goods",
            title="Home Goods",
            uri="xianyu://goods/home?page_num=1&page_size=30",
            description="首页推荐商品（默认分页）。",
            mimeType="application/json",
        ),
        Resource(
            name="favorites",
            title="Favorite Goods",
            uri="xianyu://favorites?page_num=1&page_size=20",
            description="我的收藏（默认分页）。",
            mimeType="application/json",
        ),
        Resource(
            name="my_goods",
            title="My Goods",
            uri="xianyu://my-goods?page_num=1&page_size=20",
            description="我发布的商品（默认分页）。",
            mimeType="application/json",
        ),
    ]


def list_resource_template_definitions() -> list[ResourceTemplate]:
    """Return parameterized resource templates."""
    return [
        ResourceTemplate(
            name="goods_detail",
            title="Goods Detail",
            uriTemplate="xianyu://goods/detail/{item_id}",
            description="按商品 ID 读取商品详情。",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="goods_search",
            title="Goods Search",
            uriTemplate="xianyu://goods/search/{keyword}{?page_num,page_size,price_min,price_max,sort_field,sort_value,quick_filters}",
            description="按关键词搜索商品。",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="home_goods",
            title="Home Goods",
            uriTemplate="xianyu://goods/home{?page_num,page_size}",
            description="读取首页推荐商品。",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="favorites",
            title="Favorites",
            uriTemplate="xianyu://favorites{?page_num,page_size}",
            description="读取收藏列表。",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="seller_profile",
            title="Seller Profile",
            uriTemplate="xianyu://seller/{user_id}{?include_items,include_ratings}",
            description="读取卖家主页信息。",
            mimeType="application/json",
        ),
        ResourceTemplate(
            name="my_goods",
            title="My Goods",
            uriTemplate="xianyu://my-goods{?status,page_num,page_size}",
            description="读取我发布的商品列表。",
            mimeType="application/json",
        ),
    ]


def list_prompt_definitions() -> list[Prompt]:
    """Return prompt definitions."""
    return [
        Prompt(
            name=PROMPT_ANALYZE_GOODS,
            title="Analyze Goods",
            description="生成闲鱼商品风险与价格分析提示词。",
            arguments=[
                PromptArgument(
                    name="item_id",
                    description="商品 ID 或完整商品 URL。",
                    required=True,
                )
            ],
        )
    ]


def _to_json_resource(uri: str, payload: dict[str, Any]) -> list[ReadResourceContents]:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return [ReadResourceContents(content=text, mime_type="application/json")]


def _first_query_value(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    value = values[0].strip()
    return value if value else default


def _query_int(query: dict[str, list[str]], key: str, default: int, minimum: int | None = None) -> int:
    raw = _first_query_value(query, key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return minimum
    return value


def _query_float(query: dict[str, list[str]], key: str) -> float | None:
    raw = _first_query_value(query, key)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _query_bool(query: dict[str, list[str]], key: str, default: bool) -> bool:
    raw = _first_query_value(query, key)
    if raw is None:
        return default
    normalized = raw.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _query_list(query: dict[str, list[str]], key: str) -> list[str] | None:
    values = query.get(key)
    if not values:
        return None

    flattened: list[str] = []
    for value in values:
        for item in value.split(","):
            stripped = item.strip()
            if stripped:
                flattened.append(stripped)

    return flattened or None


async def read_resource_by_uri(uri: str) -> list[ReadResourceContents]:
    """Read dynamic resource content by URI."""
    logger.info(f"Resource read: {uri}")

    parsed = urlparse(uri)
    query = parse_qs(parsed.query)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]

    if scheme != RESOURCE_SCHEME:
        return _to_json_resource(uri, {"error": True, "message": f"Unsupported URI scheme: {scheme}"})

    try:
        if host == "account" and segments == ["login-status"]:
            result = await check_login_status()
            return _to_json_resource(uri, result)

        if host == "goods" and segments[:1] == ["home"]:
            result = await get_home_goods(
                page_num=_query_int(query, "page_num", default=1, minimum=1),
                page_size=_query_int(query, "page_size", default=30, minimum=1),
            )
            return _to_json_resource(uri, result)

        if host == "goods" and len(segments) >= 2 and segments[0] == "detail":
            result = await get_goods_detail(item_id=segments[1])
            return _to_json_resource(uri, result)

        if host == "goods" and len(segments) >= 2 and segments[0] == "search":
            result = await search_goods(
                keyword=segments[1],
                page_num=_query_int(query, "page_num", default=1, minimum=1),
                page_size=_query_int(query, "page_size", default=20, minimum=1),
                price_min=_query_float(query, "price_min"),
                price_max=_query_float(query, "price_max"),
                sort_field=_first_query_value(query, "sort_field"),
                sort_value=_first_query_value(query, "sort_value"),
                quick_filters=_query_list(query, "quick_filters"),
            )
            return _to_json_resource(uri, result)

        if host == "favorites":
            result = await get_favorites(
                page_num=_query_int(query, "page_num", default=1, minimum=1),
                page_size=_query_int(query, "page_size", default=20, minimum=1),
            )
            return _to_json_resource(uri, result)

        if host == "seller" and segments:
            result = await get_seller_profile(
                user_id=segments[0],
                include_items=_query_bool(query, "include_items", default=True),
                include_ratings=_query_bool(query, "include_ratings", default=True),
            )
            return _to_json_resource(uri, result)

        if host == "my-goods":
            result = await get_my_goods(
                status=_first_query_value(query, "status"),
                page_num=_query_int(query, "page_num", default=1, minimum=1),
                page_size=_query_int(query, "page_size", default=20, minimum=1),
            )
            return _to_json_resource(uri, result)

        return _to_json_resource(uri, {"error": True, "message": f"Unsupported resource URI: {uri}"})
    except Exception as e:
        logger.error(f"Error while reading resource {uri}: {e}", exc_info=True)
        return _to_json_resource(uri, {"error": True, "message": f"Error reading resource: {e}"})


async def get_prompt_by_name(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    """Build prompt output by prompt name."""
    if name != PROMPT_ANALYZE_GOODS:
        raise ValueError(f"Unknown prompt: {name}")

    item_id = (arguments or {}).get("item_id", "").strip()
    if not item_id:
        raise ValueError("Missing required prompt argument: item_id")

    result = await build_analysis_prompt(item_id=item_id)
    prompt_text = result.get("prompt")
    if not prompt_text:
        message = result.get("message", "Failed to build analysis prompt")
        prompt_text = (
            "商品分析提示词构建失败，请先检查商品 ID 和登录状态。\n"
            f"错误信息: {message}"
        )

    return GetPromptResult(
        description="闲鱼商品分析任务提示词。",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=prompt_text),
            )
        ],
    )


async def complete_argument(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None = None,
) -> Completion | None:
    """Provide basic argument completion for prompt and resource templates."""
    del context

    values: list[str] = []
    if isinstance(ref, PromptReference) and ref.name == PROMPT_ANALYZE_GOODS and argument.name == "item_id":
        values = []
    elif argument.name == "status":
        values = MY_GOODS_STATUS
    elif argument.name == "sort_field":
        values = SORT_FIELDS
    elif argument.name == "sort_value":
        values = SORT_VALUES
    elif argument.name in {"include_items", "include_ratings"}:
        values = ["true", "false"]

    prefix = argument.value.strip()
    if prefix:
        values = [value for value in values if value.startswith(prefix)]

    return Completion(
        values=values[:20],
        total=len(values),
        hasMore=len(values) > 20,
    )
