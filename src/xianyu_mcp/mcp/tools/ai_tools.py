"""AI analysis tools for Xianyu - Prompt template approach."""

from typing import Any

from xianyu_mcp.infrastructure.api import get_api_client
from xianyu_mcp.mcp.tools.goods_tools import extract_item_id
from xianyu_mcp.mcp.tools.seller_tools import get_seller_profile
from xianyu_mcp.logging import get_logger

logger = get_logger("ai_tools")


# Analysis prompt template — 修改分析框架请直接编辑此处
ANALYSIS_PROMPT = """你是一位专业的闲鱼二手交易顾问。请基于以下数据对商品进行深度分析：

---

## 商品基本信息
- **标题**：{title}
- **价格**：¥{price}（原价：¥{original_price}）
- **分类**：{category}
- **所在地**：{location}
- **发布时间**：{publish_time}
- **商品状态**：{status_desc}
- **浏览量**：{view_count} 次
- **想要人数**：{want_count} 人

### 商品描述
{description}

---

## 卖家档案
- **昵称**：{seller_nickname}
- **信用分数**：{seller_credit}
- **个性签名**：{seller_bio}
- **在售/已售商品数**：{seller_item_count}
- **收到的评价总数**：{seller_rate_count}

### 卖家信用等级
- 作为卖家：{seller_credit_level}
- 作为买家：{buyer_credit_level}

### 交易口碑
- **卖家好评率**：{seller_good_rate}（{seller_good_count}）
- **买家好评率**：{buyer_good_rate}（{buyer_good_count}）

### 卖家近期商品（样例）
{seller_recent_items}

### 卖家收到的评价（样例）
{seller_recent_ratings}

---

分析任务
1. 价格评估

当前价格是否合理？与原价相比折扣力度如何？

基于商品描述和品类，是否存在砍价空间？（给出理由）

建议入手价格区间（给区间，并说明区间依据：成色/热度/风险/卖家可信度）

输出要包含：

价格判断：合理 / 偏贵 / 偏低但可疑

折扣计算：折扣%（若原价缺失则写“无法计算”）

砍价空间：大/中/小 + 原因

建议入手区间：¥A-¥B

砍价策略要点：1-2条

2. 卖家可信度（权重最高）

你需要从“账号质量 + 交易行为 + 商品矩阵 + 评价样态”综合判断卖家可信度，并给出风险等级：低 / 中 / 高 / 极高。

重点检查：

信用分数是否达标？（建议 400+）

好评率是否健康？（建议 95%+，并结合评价总数）

从签名、商品列表、评价内容判断卖家类型：个人 / 职业商家 / 可能是倒爷

是否存在刷单/虚假评价迹象（如：评价内容高度一致、极短、集中时间段、与商品类目不相关、买卖双方画像异常等）

输出要包含：

卖家可信度结论：可信 / 一般 / 不可信

风险等级：低/中/高/极高

卖家类型判断：个人/职业商家/倒爷（给证据）

可疑点清单：按严重程度排序（没有也要写“未发现明显异常”但要说明依据）

建议采取的验证动作：至少 2 条（例如要补图、要录像、要订单截图、要序列号等）

3. 商品真实性

对“标题-描述-状态-价格”一致性做核验，并识别诈骗/引流/模糊话术。

检查点：

描述是否详细、真实？是否存在夸大或模糊（如“几乎全新/自用/懂得来”但无细节）

标题与描述是否一致？

是否包含常见骗局关键词/行为（如：急售、只走微信、仅限见面不走担保、低价秒出、先付定金、外地发货但不走平台等）

输出要包含：

真实性判断：高/中/低

一致性检查：一致 / 有矛盾（指出矛盾点）

风险关键词/可疑表述：列出原文片段（短引用即可）

需要补充的信息清单：至少 3 条（例如发票/序列号/瑕疵特写/功能视频/电池健康等，按品类合理推断）

4. 交易风险提示

基于平台交易常见风险给出“能不能买”的关键限制条件。

必须输出：

是否支持平台担保交易：支持/不明确/不支持（不明确要提示“务必确认”）

见面交易风险：低/中/高（并说明触发原因）

高危红线：列出任何一条出现就“❌不推荐”的条件

建议交易方式：优先级排序（如：平台担保 > 同城当面验货仍走担保 > 线下仅当面现金=不建议）

5. 综合建议

请给出最终结论，必须包含：

推荐指数：⭐1-⭐5（可半星）

是否推荐购买：✅ 推荐 / ⚠️ 谨慎 / ❌ 不推荐

核心理由：一句话总结（必须同时覆盖“卖家可信度 + 商品真实性/价格”至少两项）
"""


async def build_analysis_prompt(item_id: str) -> dict[str, Any]:
    """
    Fetch goods detail and seller profile, then build a filled analysis prompt
    for the LLM caller.

    Args:
        item_id: The item ID or item URL.

    Returns:
        dict with filled prompt text and raw data (goods + seller).
    """
    logger.info(f"Tool called: build_analysis_prompt (item_id: {item_id})")

    if not item_id:
        return {"item_id": None, "message": "Item ID is required"}

    # Extract item ID from URL if needed
    if item_id.startswith("http"):
        extracted = extract_item_id(item_id)
        if extracted:
            item_id = extracted

    try:
        # 1. Fetch goods detail via API
        api_client = get_api_client()
        goods_detail = await api_client.get_goods_detail(item_id)
        logger.info(f"Goods detail fetched: {goods_detail.get('title', 'No title')}")

        # 2. Fetch seller profile (currently browser-based, will be API after refactor)
        seller_id = goods_detail.get("seller_id")
        seller_profile: dict[str, Any] = {}
        if seller_id:
            try:
                seller_profile = await get_seller_profile(seller_id)
                logger.info(f"Seller profile fetched: {seller_profile.get('seller_name', 'Unknown')}")
            except Exception as e:
                logger.warning(f"Failed to fetch seller profile: {e}")

        # 3. Prepare template fields with fallbacks
        def _format_items_list(items: list, max_count: int = 5) -> str:
            """Format seller's recent items for display."""
            if not items:
                return "暂无数据"
            lines = []
            for i, item in enumerate(items[:max_count], 1):
                status = item.get("商品状态", "未知")
                price = item.get("商品价格", "未知")
                title = item.get("商品标题", "未知标题")[:30]
                lines.append(f"  {i}. [{status}] ¥{price} - {title}")
            return "\n".join(lines) if lines else "暂无数据"

        def _format_ratings_list(ratings: list, max_count: int = 5) -> str:
            """Format seller's recent ratings for display."""
            if not ratings:
                return "暂无数据"
            lines = []
            for i, rate in enumerate(ratings[:max_count], 1):
                rate_type = rate.get("评价类型", "未知")
                role = rate.get("评价来源角色", "未知角色")
                content = rate.get("评价内容", "无内容")[:50]
                time = rate.get("评价时间", "")
                lines.append(f"  {i}. [{rate_type}] {role}: \"{content}\" ({time})")
            return "\n".join(lines) if lines else "暂无数据"

        # 商品字段
        title = goods_detail.get("title", "未知")
        price = goods_detail.get("price", "未知")
        original_price = goods_detail.get("original_price") or "未知"
        description = goods_detail.get("description") or "暂无描述"
        if len(description) > 500:
            description = description[:500] + "..."

        fields = {
            # 商品基本信息
            "title": title,
            "price": price,
            "original_price": original_price,
            "description": description,
            "category": goods_detail.get("category") or "未知",
            "location": goods_detail.get("location") or "未知",
            "publish_time": goods_detail.get("publish_time") or "未知",
            "status_desc": goods_detail.get("status_desc") or goods_detail.get("status") or "未知",
            "view_count": goods_detail.get("view_count", 0),
            "want_count": goods_detail.get("want_count", 0),
            # 卖家基本信息
            "seller_nickname": goods_detail.get("seller_nickname") or seller_profile.get("卖家昵称", "未知"),
            "seller_credit": goods_detail.get("seller_credit", "未知"),
            "seller_bio": seller_profile.get("卖家个性签名") or "暂无签名",
            "seller_item_count": seller_profile.get("卖家在售/已售商品数", "未知"),
            "seller_rate_count": seller_profile.get("卖家收到的评价总数", "未知"),
            # 卖家信用等级
            "seller_credit_level": seller_profile.get("卖家信用等级", "未知"),
            "buyer_credit_level": seller_profile.get("买家信用等级", "未知"),
            # 卖家交易口碑
            "seller_good_rate": seller_profile.get("作为卖家的好评率", "未知"),
            "seller_good_count": seller_profile.get("作为卖家的好评数", "未知"),
            "buyer_good_rate": seller_profile.get("作为买家的好评率", "未知"),
            "buyer_good_count": seller_profile.get("作为买家的好评数", "未知"),
            # 卖家商品和评价样例
            "seller_recent_items": _format_items_list(seller_profile.get("卖家发布的商品列表", [])),
            "seller_recent_ratings": _format_ratings_list(seller_profile.get("卖家收到的评价列表", [])),
        }

        # 4. Fill prompt
        prompt = ANALYSIS_PROMPT.format(**fields)

        return {
            "item_id": item_id,
            "seller_id": seller_id,
            "prompt": prompt,
            "goods_data": goods_detail,
            "seller_data": seller_profile,
            "message": "Analysis prompt built successfully. LLM caller should use the prompt to perform analysis.",
        }

    except Exception as e:
        logger.error(f"Error in build_analysis_prompt: {e}")
        return {
            "item_id": item_id,
            "message": f"Error building analysis prompt: {e}",
            "error": str(e),
        }


# Tool definitions for MCP registration
AI_TOOLS = [
    {
        "name": "analyze_goods",
        "description": "对闲鱼商品进行深度风险与价格分析。返回分析提示词和商品数据，包含价格评估、卖家可信度、商品真实性、交易风险等维度。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "商品 ID 或商品链接",
                },
            },
            "required": ["item_id"],
        },
        "handler": build_analysis_prompt,
    },
]
