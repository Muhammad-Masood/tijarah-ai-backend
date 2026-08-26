"""
Generate a Daraz create-product draft from a product image + category attributes.

Efficiency model (same principle as reviews_service):
  1. Deterministic partition in Python — never ask the LLM to decide which
     fields the seller must own (price, qty, SKU, package dims, ...).
  2. Auto-fill mandatory single-option enums in code (e.g. warranty_type
     with only "No Warranty") — zero tokens.
  3. ONE structured vision call over the remaining candidates, constrained
     to each attribute's option list when present.
  4. Post-validate enums in code so hallucinated option names never reach
     the draft the UI submits to create_new_product.

No LangGraph: there are no tools, no multi-turn state, and no map-reduce
scale problem — a second agent would only add latency and cost.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from neurocom_backend.models.daraz_model import CategoryAttribute
from neurocom_backend.models.product_listing_model import (
    FilledAttribute,
    GenerateListingRequest,
    GenerateListingResponse,
    ListingDraft,
    ListingSkuDraft,
)


# Seller-owned / ops fields: never inferred from a product photo.
_USER_OWNED_NAMES: frozenset[str] = frozenset({
    "SellerSku",
    "price",
    "quantity",
    "special_price",
    "special_from_date",
    "special_to_date",
    "package_length",
    "package_width",
    "package_height",
    "package_weight",
    "tax_class",
    "seller_promotion",
    "delivery_option_standard",
    "delivery_option_express",
    "delivery_option_economy",
    "warranty",
    "product_warranty",
    "product_warranty_en",
    "video",
    "__images__",
    "Size_Chart_Image",
    "color_thumbnail",
    "promotion_long_image",
    "promotion_whitebkg_image",
    "express_delivery",
    "campaign",
    "complementary_products",
    "Hazmat",
    # Inventory variants the seller chooses to stock — not visible as a
    # single definitive value on one product photo.
    "size",
})

_SKIP_INPUT_TYPES: frozenset[str] = frozenset({"img"})

# SKU-level fields that vision may fill into the draft Sku (sale props + box text).
_SKU_VISION_NAMES: frozenset[str] = frozenset({
    "color_family",
    "color",
    "package_content",
})


class _VisionFieldFill(BaseModel):
    name: str = Field(description="Exact attribute name from the candidate list")
    value: Optional[str] = Field(
        default=None,
        description="Filled value, or null when not clearly visible / not inferable",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0-1 confidence; use <0.5 when unsure",
    )


class _VisionFillResult(BaseModel):
    title: Optional[str] = Field(
        default=None,
        description="Product title suitable for Daraz listing (concise, searchable)",
    )
    fields: List[_VisionFieldFill] = Field(default_factory=list)


def _option_names(attr: CategoryAttribute) -> List[str]:
    if not attr.options:
        return []
    return [o.name for o in attr.options if o.name]


def partition_attributes(
    attributes: List[CategoryAttribute],
) -> Tuple[List[CategoryAttribute], List[CategoryAttribute], Dict[str, str]]:
    """Split attrs into (vision_candidates, user_owned, auto_filled).

    auto_filled maps attr name → the sole option value for mandatory
    single-option enums (no LLM needed).
    """
    vision: List[CategoryAttribute] = []
    user_owned: List[CategoryAttribute] = []
    auto_filled: Dict[str, str] = {}

    for attr in attributes:
        if attr.input_type in _SKIP_INPUT_TYPES or attr.name in _USER_OWNED_NAMES:
            user_owned.append(attr)
            continue

        options = _option_names(attr)
        if attr.is_mandatory == 1 and len(options) == 1:
            auto_filled[attr.name] = options[0]
            continue

        vision.append(attr)

    return vision, user_owned, auto_filled


def _candidate_prompt_block(attrs: List[CategoryAttribute]) -> str:
    lines: List[str] = []
    for attr in attrs:
        options = _option_names(attr)
        option_part = f" | options={options}" if options else " | free_text"
        lines.append(
            f"- name={attr.name!r} label={attr.label!r} "
            f"type={attr.input_type} scope={attr.attribute_type} "
            f"mandatory={bool(attr.is_mandatory)} sale_prop={bool(attr.is_sale_prop)}"
            f"{option_part}"
        )
    return "\n".join(lines)


def _match_option(value: str, options: List[str]) -> Optional[str]:
    """Return the canonical option name if value matches (case-insensitive)."""
    if not options:
        return value.strip() or None
    lowered = {o.lower(): o for o in options}
    return lowered.get(value.strip().lower())


def _run_vision_fill(
    image_urls: List[str],
    candidates: List[CategoryAttribute],
    title_hint: Optional[str],
    brand_hint: Optional[str],
) -> _VisionFillResult:
    if not candidates and not image_urls:
        return _VisionFillResult()

    llm = ChatOpenAI(temperature=0, model="gpt-4o")
    structured = llm.with_structured_output(_VisionFillResult)

    hints = []
    if title_hint:
        hints.append(f"Seller title hint: {title_hint}")
    if brand_hint:
        hints.append(f"Seller brand hint: {brand_hint}")
    hints_block = ("\n".join(hints) + "\n") if hints else ""

    system = SystemMessage(content=(
        "You are a Daraz marketplace listing assistant. Analyze the product "
        "image(s) and fill ONLY the candidate attributes listed. Rules:\n"
        "1. For attributes with an options list, value MUST be one of those "
        "exact option strings — never invent a new option.\n"
        "2. Leave value null when the image does not clearly support a value "
        "(do not guess price, size stocked, warranty policy, or seller SKU).\n"
        "3. Prefer null over low-confidence guesses (confidence < 0.5 → null).\n"
        "4. Write name / name_en / short_description* / description* as clear "
        "marketplace copy when the product is visible; descriptions may use "
        "simple HTML paragraphs.\n"
        "5. Return every candidate you attempt in fields[]; omit only if you "
        "have nothing to say — null values are fine and preferred when unsure."
    ))

    content: List[dict] = [
        {
            "type": "text",
            "text": (
                f"{hints_block}"
                "Candidate attributes to fill:\n"
                f"{_candidate_prompt_block(candidates)}\n\n"
                "Also propose a concise Title for the listing."
            ),
        }
    ]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    return structured.invoke([system, HumanMessage(content=content)])


def generate_product_listing(request: GenerateListingRequest) -> GenerateListingResponse:
    image_urls = [str(u) for u in request.image_urls]
    candidates, user_owned_attrs, auto_filled = partition_attributes(request.attributes)

    user_required_names = sorted({a.name for a in user_owned_attrs})
    attr_by_name: Dict[str, CategoryAttribute] = {a.name: a for a in request.attributes}
    candidate_names: Set[str] = {a.name for a in candidates}

    vision = _run_vision_fill(
        image_urls,
        candidates,
        request.title_hint,
        request.brand_hint,
    )

    product_attrs: Dict[str, Optional[str]] = {}
    sku_fields: Dict[str, Optional[str]] = {}
    filled: List[FilledAttribute] = []
    vision_skipped: List[str] = []
    seen_vision: Set[str] = set()

    for name, value in auto_filled.items():
        attr = attr_by_name.get(name)
        if attr and attr.attribute_type == "sku":
            sku_fields[name] = value
        else:
            product_attrs[name] = value
        filled.append(FilledAttribute(name=name, value=value, source="vision", confidence=1.0))

    for item in vision.fields:
        if item.name not in candidate_names:
            continue
        seen_vision.add(item.name)
        attr = attr_by_name[item.name]
        options = _option_names(attr)

        value: Optional[str] = None
        if item.value and item.confidence >= 0.5:
            value = _match_option(item.value, options)
            if options and value is None:
                # Model invented a non-option value — treat as skipped.
                vision_skipped.append(item.name)
                filled.append(FilledAttribute(
                    name=item.name, value=None, source="skipped", confidence=item.confidence,
                ))
                continue

        if value is None:
            vision_skipped.append(item.name)
            filled.append(FilledAttribute(
                name=item.name, value=None, source="skipped", confidence=item.confidence,
            ))
            continue

        if attr.attribute_type == "sku" or item.name in _SKU_VISION_NAMES:
            sku_fields[item.name] = value
        else:
            product_attrs[item.name] = value
        filled.append(FilledAttribute(
            name=item.name, value=value, source="vision", confidence=item.confidence,
        ))

    for name in candidate_names - seen_vision:
        if name not in auto_filled:
            vision_skipped.append(name)
            filled.append(FilledAttribute(name=name, value=None, source="skipped"))

    for attr in user_owned_attrs:
        if attr.attribute_type == "sku" or attr.name in _USER_OWNED_NAMES:
            # Keep product-level Attributes dict clean; SKU blanks live on Sku draft.
            if attr.attribute_type != "sku" and attr.name not in {
                "SellerSku", "price", "quantity",
                "package_length", "package_width", "package_height", "package_weight",
                "special_price", "special_from_date", "special_to_date",
                "tax_class", "seller_promotion", "__images__",
            }:
                product_attrs.setdefault(attr.name, None)
        filled.append(FilledAttribute(name=attr.name, value=None, source="user_required"))

    # Ensure vision product-level candidates appear in Attributes even when skipped
    # so the UI can render empty required inputs.
    for attr in candidates:
        if attr.attribute_type != "sku" and attr.name not in _SKU_VISION_NAMES:
            product_attrs.setdefault(attr.name, None)

    title = vision.title
    if request.title_hint and not title:
        title = request.title_hint
    # Prefer name_en / name from filled attrs if title missing.
    if not title:
        title = product_attrs.get("name_en") or product_attrs.get("name")

    if title:
        product_attrs.setdefault("name", title)
        product_attrs.setdefault("name_en", title)

    if request.brand_hint and not product_attrs.get("brand"):
        brand_attr = attr_by_name.get("brand")
        brand_options = _option_names(brand_attr) if brand_attr else []
        matched = _match_option(request.brand_hint, brand_options) if brand_options else request.brand_hint
        if matched:
            product_attrs["brand"] = matched

    sku = ListingSkuDraft(
        color_family=sku_fields.get("color_family"),
        size=None,  # always user-owned
        package_content=sku_fields.get("package_content"),
        Images=image_urls[:1],
    )

    draft = ListingDraft(
        Title=title,
        PrimaryCategory=request.primary_category_id,
        Images=image_urls,
        Attributes=product_attrs,
        Skus=[sku],
    )

    return GenerateListingResponse(
        draft=draft,
        filled=filled,
        user_required=user_required_names,
        vision_skipped=sorted(set(vision_skipped)),
    )
