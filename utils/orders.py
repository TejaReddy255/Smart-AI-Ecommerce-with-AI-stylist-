import os
import csv
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

# reportlab imports (you already had these)
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm

# ---------- config ----------
OUTPUT_DIR: str = "output"
ORDERS_FILE: str = os.path.join(OUTPUT_DIR, "orders.csv")
ENCODING: str = "utf-8"

# Legacy flat rates (kept for backward compat if you used these)
DISCOUNT_RATE_RETURNING: float = 0.10
DISCOUNT_RATE_NEW: float = 0.0

# Discount engine defaults (tweakable)
DEFAULT_RULES = {
    "loyalty_pct": 0.05,        # 5% loyalty
    "big_cart_threshold": 5000, # subtotal threshold
    "big_cart_pct": 0.05,       # 5% extra for big cart
    "category_bonuses": {       # extra % by masterCategory
        "Footwear": 0.05,
        "Apparel": 0.03,
    },
    "first_time_pct": 0.00,     # first time discount
    "max_total_pct": 0.20,      # cap percent discounts at 20%
    # "promo_fixed_amount": 100.0  # optional fixed promo
}

# ensure output dir
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------- helpers ----------
def _ensure_orders_csv():
    """Create orders CSV if missing (with header)."""
    if not os.path.exists(ORDERS_FILE):
        os.makedirs(os.path.dirname(ORDERS_FILE), exist_ok=True)
        with open(ORDERS_FILE, "w", newline="", encoding=ENCODING) as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "order_id",
                    "created_at",
                    "customer_name",
                    "email",
                    "address",
                    "subtotal",
                    "discount_amount",
                    "discount_breakdown",
                    "total",
                    "items",
                ],
            )
            writer.writeheader()

def _load_orders() -> List[Dict[str, Any]]:
    """Load saved orders and parse JSON columns."""
    if not os.path.exists(ORDERS_FILE):
        return []
    orders: List[Dict[str, Any]] = []
    with open(ORDERS_FILE, "r", encoding=ENCODING) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            # parse JSON columns
            try:
                row["discount_breakdown"] = json.loads(row.get("discount_breakdown") or "[]")
            except Exception:
                row["discount_breakdown"] = []
            try:
                row["items"] = json.loads(row.get("items") or "[]")
            except Exception:
                row["items"] = []
            # Convert numeric fields if needed
            try:
                row["subtotal"] = float(row.get("subtotal") or 0.0)
            except Exception:
                row["subtotal"] = 0.0
            try:
                row["discount_amount"] = float(row.get("discount_amount") or 0.0)
            except Exception:
                row["discount_amount"] = 0.0
            try:
                row["total"] = float(row.get("total") or 0.0)
            except Exception:
                row["total"] = 0.0
            orders.append(row)
    return orders

# ---------- returning customer ----------
def is_returning_customer(email: str) -> bool:
    """
    Return True if the email exists in previous orders.
    """
    if not email:
        return False
    orders = _load_orders()
    emails = {o.get("email", "").strip().casefold() for o in orders}
    return str(email).strip().casefold() in emails

# ---------- subtotal helper ----------
def _sum_subtotal(cart: List[Dict[str, Any]]) -> float:
    subtotal = 0.0
    for it in cart:
        # support both 'price' and legacy 'price_inr' keys
        price = it.get("price")
        if price is None:
            price = it.get("price_inr") or it.get("priceInr") or 0.0
        qty = it.get("qty") or it.get("quantity") or 1
        try:
            subtotal += float(price) * int(qty)
        except Exception:
            continue
    return round(subtotal, 2)


# ---------- discount engine ----------
def compute_dynamic_discount(
    cart: List[Dict[str, Any]],
    is_returning: bool,
    rules: Optional[Dict[str, Any]] = None,
) -> Tuple[float, List[Dict[str, Any]]]:
    """
    Compute total discount amount and return a breakdown list.

    Returns: (discount_amount, breakdown_list)
    breakdown_list entries:
      {"name": "...", "type": "percentage"|"fixed", "value": 0.05, "amount": 250.0}
    """
    if rules is None:
        rules = DEFAULT_RULES

    subtotal = _sum_subtotal(cart)
    breakdown: List[Dict[str, Any]] = []
    total_pct = 0.0
    total_fixed = 0.0

    # Loyalty / first-time
    if is_returning:
        pct = float(rules.get("loyalty_pct", 0.0))
        if pct:
            amt = round(subtotal * pct, 2)
            breakdown.append({"name": "Loyalty discount", "type": "percentage", "value": pct, "amount": amt})
            total_pct += pct
    else:
        pct = float(rules.get("first_time_pct", 0.0))
        if pct:
            amt = round(subtotal * pct, 2)
            breakdown.append({"name": "Welcome discount", "type": "percentage", "value": pct, "amount": amt})
            total_pct += pct

    # Big-cart bonus
    big_thresh = float(rules.get("big_cart_threshold", 0.0))
    if subtotal >= big_thresh and float(rules.get("big_cart_pct", 0)):
        pct = float(rules.get("big_cart_pct", 0.0))
        amt = round(subtotal * pct, 2)
        breakdown.append({"name": f"Big-cart bonus (>= ₹{int(big_thresh):,})", "type": "percentage", "value": pct, "amount": amt})
        total_pct += pct

    # Category-based bonuses (masterCategory)
    category_bonuses = rules.get("category_bonuses", {}) or {}
    present_categories = set()
    for it in cart:
        mc = it.get("masterCategory") or it.get("category") or ""
        if mc:
            present_categories.add(str(mc).strip().casefold())

    if isinstance(category_bonuses, dict):
        for cat, pct in category_bonuses.items():
            if str(cat).strip().casefold() in present_categories:
                amt = round(subtotal * float(pct), 2)
                breakdown.append({"name": f"Category bonus: {cat}", "type": "percentage", "value": float(pct), "amount": amt})
                total_pct += float(pct)

    # Optional fixed promo
    if rules.get("promo_fixed_amount"):
        fixed = float(rules["promo_fixed_amount"])
        if fixed > 0:
            breakdown.append({"name": "Promotional discount", "type": "fixed", "value": fixed, "amount": round(fixed, 2)})
            total_fixed += fixed

    # Cap percentage discounts
    max_pct = float(rules.get("max_total_pct", 1.0))
    if total_pct > max_pct and total_pct > 0:
        scale = max_pct / total_pct
        new_breakdown: List[Dict[str, Any]] = []
        pct_so_far = 0.0
        for entry in breakdown:
            if entry["type"] == "percentage":
                old_pct = entry["value"]
                new_pct = old_pct * scale
                new_amt = round(subtotal * new_pct, 2)
                new_breakdown.append({"name": entry["name"], "type": "percentage", "value": round(new_pct, 6), "amount": new_amt})
                pct_so_far += new_pct
            else:
                new_breakdown.append(entry)
        breakdown = new_breakdown
        total_pct = pct_so_far

    discount_from_pct = round(subtotal * total_pct, 2)
    discount_fixed = round(total_fixed, 2)
    total_discount = round(discount_from_pct + discount_fixed, 2)

    return total_discount, breakdown

def compute_totals_with_discounts(cart: List[Dict[str, Any]], is_returning: bool, rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compute subtotal, discount breakdown, and final total.
    Returns dict with keys: subtotal, discount_amount, discount_breakdown, total
    """
    subtotal = _sum_subtotal(cart)
    discount_amount, breakdown = compute_dynamic_discount(cart, is_returning, rules=rules)
    total = max(0.0, round(subtotal - discount_amount, 2))
    return {
        "subtotal": round(subtotal, 2),
        "discount_amount": discount_amount,
        "discount_breakdown": breakdown,
        "total": total,
    }

# Backwards-compatible wrapper
def compute_totals(cart: List[Dict[str, Any]], returning: bool) -> Dict[str, Any]:
    """
    Kept for compatibility with older call sites.
    Returns: subtotal, discount_rate (approx), discount_amount, total
    """
    # compute dynamic totals and also return an approximate aggregate rate
    res = compute_totals_with_discounts(cart, is_returning=returning)
    subtotal = res["subtotal"]
    discount_amount = res["discount_amount"]
    approx_rate = (discount_amount / subtotal) if subtotal > 0 else 0.0
    return {
        "subtotal": res["subtotal"],
        "discount_rate": round(approx_rate, 4),
        "discount_amount": res["discount_amount"],
        "total": res["total"],
    }

# ---------- save order ----------
def save_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Persist an order to ORDERS_FILE (CSV). Adds order_id and created_at if missing.
    Serializes JSON fields (items, discount_breakdown).
    Returns the enriched order dict.
    """
    _ensure_orders_csv()

    # enrich the order
    if not order.get("order_id"):
        order["order_id"] = str(uuid.uuid4())
    if not order.get("created_at"):
        order["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Ensure items is a list
    items = order.get("items") or []
    if not isinstance(items, list):
        # If passed as JSON string, try to parse
        try:
            items = json.loads(items)
        except Exception:
            items = []

    if len(items) == 0:
        # do not save empty orders
        raise ValueError("Order has no items; refusing to save.")

    row: Dict[str, Any] = {
        "order_id": order["order_id"],
        "created_at": order["created_at"],
        "customer_name": order.get("customer_name", ""),
        "email": order.get("email", ""),
        "address": order.get("address", ""),
        "subtotal": float(order.get("subtotal") or 0.0),
        "discount_amount": float(order.get("discount_amount") or 0.0),
        "discount_breakdown": json.dumps(order.get("discount_breakdown") or []),
        "total": float(order.get("total") or 0.0),
        "items": json.dumps(items),
    }

    try:
        with open(ORDERS_FILE, mode="a", newline="", encoding=ENCODING) as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
            # header already created by _ensure_orders_csv
            writer.writerow(row)
        return order
    except (OSError, csv.Error, TypeError) as error:
        raise RuntimeError("failed to save order") from error

# ---------- invoice generation ----------
def generate_invoice(order: Dict[str, Any], output_file: str) -> str:
    """
    Generate a PDF invoice using reportlab. Returns path to file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, output_file)

    # Build document
    doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        "companyStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=1,
        textColor=colors.HexColor("#1a73e8"),
    )

    title_style = ParagraphStyle("titleStyle", parent=styles["Title"], fontSize=30, leading=36, alignment=1, textColor=colors.HexColor("#333333"))

    normal_style = ParagraphStyle("normalStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=12, spaceAfter=4)

    header_style = ParagraphStyle("headerStyle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=12, leading=14, spaceAfter=6, textColor=colors.HexColor("#333333"))

    elements: List[Any] = []

    # header
    elements.append(Paragraph("StyleScope AI Product Search", company_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Order Invoice", title_style))
    elements.append(Spacer(1, 24))

    # order & customer info
    info_data = [
        [Paragraph("<b>Order Id:</b> " + str(order.get("order_id", "")), normal_style), Paragraph("<b>Date:</b> " + str(order.get("created_at", "")), normal_style)],
        [Paragraph("<b>Customer Name:</b> " + str(order.get("customer_name", "")), normal_style), Paragraph("<b>Email:</b> " + str(order.get("email", "")), normal_style)],
        [Paragraph("<b>Address:</b> " + str(order.get("address", "")), normal_style), Paragraph("", normal_style)],
    ]

    info_table = Table(info_data, colWidths=[100 * mm, 90 * mm])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))

    # items table
    data = [["Product", "Size", "Qty", "Price(INR)", "Total(INR)"]]
    for item in order.get("items", []):
        # support both price keys
        price_val = item.get("price") if item.get("price") is not None else item.get("price_inr") or item.get("priceInr") or 0.0
        try:
            total_item = float(price_val) * int(item.get("qty", 0))
        except Exception:
            total_item = 0.0
        data.append([str(item.get("title", "") or item.get("name", "")), str(item.get("size", "")), str(item.get("qty", "")), f"Rs {float(price_val):.2f}", f"Rs {total_item:.2f}"])

    table = Table(data, hAlign="LEFT", colWidths=[100 * mm, 20 * mm, 20 * mm, 30 * mm, 30 * mm])

    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("TOPPADDING", (0, 0), (-1, 0), 12),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#cccccc")),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
            ("TOPPADDING", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )

    for i in range(1, len(data)):
        bg_color = colors.whitesmoke if i % 2 == 0 else colors.HexColor("#ffffff")
        table_style.add("BACKGROUND", (0, i), (-1, i), bg_color)
        table_style.add("LINEBELOW", (0, i), (-1, i), 0.5, colors.HexColor("#f0f0f0"))

    table.setStyle(table_style)
    elements.append(table)
    elements.append(Spacer(1, 12))

    # totals
    totals_data = [
        ["Subtotal:", f"Rs {order.get('subtotal', 0):.2f}"],
        ["Discount:", f"Rs {order.get('discount_amount', 0):.2f}"],
        ["Total Paid:", f"Rs {order.get('total', 0):.2f}"],
    ]
    totals_table = Table(totals_data, colWidths=[130 * mm, 60 * mm])
    totals_table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 12), ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    elements.append(Spacer(1, 6))
    elements.append(totals_table)
    elements.append(Spacer(1, 12))

    # discount breakdown (if present)
    if order.get("discount_breakdown"):
        elements.append(Paragraph("Discount breakdown:", header_style))
        elements.append(Spacer(1, 6))
        for d in order.get("discount_breakdown", []):
            amt = d.get("amount", 0)
            name = d.get("name", "")
            elements.append(Paragraph(f"- {name}: Rs {amt:.2f}", normal_style))
        elements.append(Spacer(1, 12))

    # footer
    elements.append(Paragraph("Thank you for shopping with us!", header_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("We hope you enjoy your purchase.", normal_style))

    doc.build(elements)
    return filepath